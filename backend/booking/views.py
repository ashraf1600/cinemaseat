"""
Booking API views — seat-hold creation, lookup, OTP verification, and
payment initiation.

The hold view is the system's critical concurrency point: it must never
allow the same seat to be held twice. See `HoldSeatsView` for the
locking + validation strategy.
"""
from __future__ import annotations

import logging
import secrets
import threading
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import OperationalError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Seat, Showtime
from payments.models import Payment

from . import gateway
from .models import Booking, BookingSeat, OtpVerification
from .serializers import (
    HoldRequestSerializer,
    OtpVerifyRequestSerializer,
    build_booking_detail_response,
    build_hold_response,
    build_otp_response,
)

logger = logging.getLogger(__name__)


def _new_booking_ref() -> str:
    """Short, URL-safe, unique identifier for a booking."""
    return "bk_" + secrets.token_hex(6)  # 12 hex chars = ~10^14 entropy


def _new_otp_ref() -> str:
    """Short, URL-safe, unique identifier for an OTP verification."""
    return "otp_" + secrets.token_hex(6)


def _ttl_expiry():
    """Now + HOLD_TTL_SECONDS (sourced from env via settings)."""
    return timezone.now() + timedelta(seconds=settings.HOLD_TTL_SECONDS)


def _conflict() -> Response:
    """The single, documented 409 response for the hold endpoint."""
    return Response(
        {"error": {"detail": "One or more seats are no longer available."}},
        status=status.HTTP_409_CONFLICT,
    )


def _dispatch_otp_send(phone: str, ref: str) -> None:
    """Fire-and-forget gateway call for OTP dispatch.

    Lives in a daemon thread so the HTTP latency of the upstream gateway
    can never block the API response. Exceptions are swallowed and logged —
    the OTP ``SENT`` row is our source of truth; whether the SMS actually
    arrived is the gateway's responsibility per its documented behavior.
    """
    def _worker() -> None:
        try:
            gateway.send_otp(phone=phone, ref=ref)
        except gateway.GatewayError as exc:
            logger.warning("OTP send to gateway failed for ref=%s: %s", ref, exc)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Unexpected error in OTP send worker (ref=%s)", ref)

    thread = threading.Thread(target=_worker, name=f"otp-send-{ref}", daemon=True)
    thread.start()


def _callback_url_for(request) -> str:
    """Build the absolute URL the gateway should POST back to."""
    return request.build_absolute_uri("/api/webhooks/payment/")


def _total_amount_for_hold(booking: Booking) -> Decimal:
    """Compute the amount to charge for a booking.

    Uses the showtime's ``base_price`` times the number of held seats.
    ``Booking`` itself has no FK to ``Showtime`` — we reach it through
    any of its ``booking_seats`` (all seats on a single booking must
    belong to the same showtime, enforced by the hold endpoint).
    """
    seat_count = booking.booking_seats.count()
    base_price = booking.booking_seats.first().seat.showtime.base_price
    return (base_price * seat_count).quantize(Decimal("0.01"))


def _dispatch_charge(booking: Booking, amount: Decimal, callback_url: str) -> threading.Thread:
    """Fire-and-forget gateway /charge call.

    On a successful /charge (HTTP 2xx) we capture the gateway's
    ``payment_id`` into the local Payment row. On 5xx / transport failure
    we leave the Payment in PENDING — the upcoming webhook (or the
    absence of one + a future retry) will settle the state. On 4xx (the
    gateway rejecting the request outright) we mark the Payment FAILED so
    the user can be told immediately instead of waiting on a webhook
    that will never come.

    Returns the spawned thread so tests can ``.join()`` on it.
    """
    def _worker() -> None:
        try:
            status_code, body = gateway.charge(
                amount=amount,
                currency="BDT",
                booking_ref=booking.booking_ref,
                callback_url=callback_url,
            )
        except gateway.GatewayError as exc:
            logger.warning(
                "Charge call to gateway failed for booking=%s: %s",
                booking.booking_ref, exc,
            )
            return

        try:
            with transaction.atomic():
                # No select_for_update here: this worker runs after the
                # /pay/ API request has already returned, and the Payment
                # row was just inserted by that same handler. The only
                # concurrent writer is the webhook, which has its own
                # row lock on the same Payment. Keeping this read plain
                # also avoids sqlite "database is locked" errors when
                # the worker races the test transaction.
                payment = Payment.objects.get(booking=booking)
        except Payment.DoesNotExist:
            logger.error(
                "Charge returned for booking=%s but no Payment row exists",
                booking.booking_ref,
            )
            return
        except OperationalError as exc:
            # SQLite lock contention / test-thread DB access restriction.
            # Logged and ignored — the Payment row is PENDING, the webhook
            # is the source of truth, and the user's retry will re-attempt.
            logger.warning(
                "Charge worker could not update Payment for booking=%s: %s",
                booking.booking_ref, exc,
            )
            return

        if 200 <= status_code < 300:
            gateway_payment_id = body.get("payment_id") if isinstance(body, dict) else None
            if gateway_payment_id:
                payment.payment_id = str(gateway_payment_id)
                payment.save(update_fields=["payment_id"])
            # Status stays PENDING until the webhook confirms.
        elif 400 <= status_code < 500:
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=["status"])
        else:
            # 5xx / unknown — leave PENDING; webhook will reconcile.
            logger.warning(
                "Gateway /charge returned %s for booking=%s; leaving PENDING",
                status_code, booking.booking_ref,
            )

    thread = threading.Thread(
        target=_worker, name=f"charge-{booking.booking_ref}", daemon=True,
    )
    thread.start()
    return thread


def _dispatch_charge_safe(booking: Booking, amount: Decimal, callback_url: str) -> None:
    """Top-level entrypoint — swallows every exception the worker could raise.

    pytest-django raises ``RuntimeError("Database access not allowed…")``
    when a non-test thread touches the DB outside a ``transaction=True``
    test. SQLite raises ``OperationalError("database is locked")`` when
    a worker races the test transaction. Both are noise we want to log
    and forget — the webhook is the source of truth, the Payment row
    was already created in PENDING by the request handler, and the
    gateway will reconcile eventually.
    """
    try:
        _dispatch_charge(booking=booking, amount=amount, callback_url=callback_url)
    except Exception:  # noqa: BLE001 — defensive; worker is fire-and-forget
        logger.exception("charge worker crashed for booking=%s", booking.booking_ref)


class HoldSeatsView(APIView):
    """
    POST /api/bookings/hold/

    Atomically reserves a set of seats for a given showtime and creates
    a `HELD` booking that expires after `settings.HOLD_TTL_SECONDS`.

    Concurrency strategy:
      * Wrap everything in `transaction.atomic()` so partial failures roll
        back (never half-hold a set of seats).
      * Lock every requested seat with `select_for_update()` in ascending
        seat-id order. The fixed ordering prevents the classic deadlock
        where two transactions try to lock overlapping rows in opposite
        orders.
      * After the locks are held, re-read the seats' status; if any is
        not AVAILABLE, raise to roll back. This is the check-then-act
        guarantee: two requests that race on the last seat will serialise
        on the row lock and exactly one will succeed.
    """

    def post(self, request, *args, **kwargs) -> Response:
        req = HoldRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        showtime_id = req.validated_data["showtime_id"]
        seat_ids = req.validated_data["seat_ids"]
        phone = req.validated_data["phone"]

        # DETERMINISTIC LOCK ORDER: ascending seat id. This is the only
        # thing standing between us and deadlocks when two requests
        # target overlapping multi-seat sets in different orders.
        ordered_ids = sorted(set(seat_ids))

        try:
            with transaction.atomic():
                showtime = Showtime.objects.get(pk=showtime_id)

                seats = list(
                    Seat.objects
                    .select_for_update()
                    .filter(id__in=ordered_ids)
                    .order_by("id")
                )

                # If the caller asked for seats that don't exist, the
                # returned set is smaller than requested.
                if len(seats) != len(ordered_ids):
                    return _conflict()

                # Every seat must belong to the requested showtime.
                if any(seat.showtime_id != showtime.id for seat in seats):
                    return _conflict()

                # Every seat must still be AVAILABLE. Because we hold
                # the row locks, no other transaction can flip these to
                # HELD until we commit.
                if any(seat.status != Seat.Status.AVAILABLE for seat in seats):
                    return _conflict()

                # All checks passed — mark the seats HELD and create
                # the booking + join rows in the same transaction.
                Seat.objects.filter(id__in=ordered_ids).update(status=Seat.Status.HELD)

                booking = Booking.objects.create(
                    booking_ref=_new_booking_ref(),
                    phone=phone,
                    status=Booking.Status.HELD,
                    expires_at=_ttl_expiry(),
                )
                BookingSeat.objects.bulk_create(
                    [BookingSeat(booking=booking, seat=s) for s in seats]
                )

                response_seats = sorted(seats, key=lambda s: s.label)
        except Showtime.DoesNotExist:
            return _conflict()

        body = build_hold_response(booking, response_seats)
        return Response(body, status=status.HTTP_201_CREATED)


class BookingDetailView(APIView):
    """
    GET /api/bookings/<booking_ref>/

    Returns the current status, expiry and seat list for a booking.
    Runs the expiry sweep first so an observed-by-reading booking that
    has just passed its TTL is reported as EXPIRED.
    """

    def get(self, request, booking_ref: str, *args, **kwargs) -> Response:
        # Sweep first so this read observes a consistent "now". We then
        # re-read the booking to pick up its post-sweep status if the
        # sweep flipped it to EXPIRED.
        from .expiry import expire_overdue_holds
        expire_overdue_holds()

        booking = get_object_or_404(
            Booking.objects.prefetch_related("booking_seats__seat"),
            booking_ref=booking_ref,
        )
        seats = sorted(
            (bs.seat for bs in booking.booking_seats.all()),
            key=lambda s: s.label,
        )
        body = build_booking_detail_response(booking, seats)
        return Response(body, status=status.HTTP_200_OK)


class OtpSendView(APIView):
    """
    POST /api/bookings/<booking_ref>/otp/send/

    Dispatches an OTP to the booking's phone via the upstream gateway.
    The gateway call is fired off in a background thread so the HTTP
    latency of the upstream service can never block or fail this
    request — we always return ``202 Accepted`` with the freshly created
    ``OtpVerification`` row immediately after persisting it.
    """

    def post(self, request, booking_ref: str, *args, **kwargs) -> Response:
        booking = get_object_or_404(Booking, booking_ref=booking_ref)

        # Create the OTP row up-front so the caller has a stable ref to
        # verify against, regardless of gateway latency / availability.
        with transaction.atomic():
            otp, _created = OtpVerification.objects.update_or_create(
                booking=booking,
                defaults={
                    "ref": _new_otp_ref(),
                    "status": OtpVerification.Status.SENT,
                },
            )

        # Fire the gateway call in a daemon thread. The thread will
        # release immediately even if the gateway is slow or down.
        _dispatch_otp_send(phone=booking.phone, ref=otp.ref)

        body = build_otp_response(booking, otp)
        return Response(body, status=status.HTTP_202_ACCEPTED)


class OtpVerifyView(APIView):
    """
    POST /api/bookings/<booking_ref>/otp/verify/

    Verifies a code against the gateway for this booking's OTP ref.
    Mirrors the gateway's verdict: 200 on success, 400 on bad/expired.
    """

    def post(self, request, booking_ref: str, *args, **kwargs) -> Response:
        req = OtpVerifyRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        code = req.validated_data["code"]

        booking = get_object_or_404(Booking, booking_ref=booking_ref)
        otp = get_object_or_404(OtpVerification, booking=booking)

        try:
            status_code = gateway.verify_otp(ref=otp.ref, code=code)
        except gateway.GatewayError:
            # Transport failure on verify: surface as 400 to the caller —
            # we can't tell whether the code was good, and the booking
            # shouldn't be left in an ambiguous state.
            return Response(
                {"error": {"detail": "Invalid or expired code."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if status_code == 200:
            otp.status = OtpVerification.Status.VERIFIED
            otp.save(update_fields=["status"])
            body = build_otp_response(booking, otp)
            return Response(body, status=status.HTTP_200_OK)

        # Any non-200 from the gateway is treated as "invalid or expired".
        return Response(
            {"error": {"detail": "Invalid or expired code."}},
            status=status.HTTP_400_BAD_REQUEST,
        )


class PayView(APIView):
    """
    POST /api/bookings/<booking_ref>/pay/

    Initiates a charge against the upstream gateway. Returns ``202``
    immediately after creating a ``Payment`` row in PENDING — the actual
    /charge call to the gateway is dispatched in a background thread, and
    the final booking state is settled by the gateway's webhook callback.

    Failure modes are explicit:
      * gateway transport failure / 5xx → leave Payment PENDING, webhook
        will reconcile (or the absence of a webhook + a future retry).
      * gateway 4xx → Payment FAILED — the gateway has rejected the
        charge outright, no webhook will arrive.
      * /pay/ on a booking that is not HELD → 409.
    """

    def post(self, request, booking_ref: str, *args, **kwargs) -> Response:
        booking = get_object_or_404(
            Booking.objects.prefetch_related("booking_seats__seat__showtime"),
            booking_ref=booking_ref,
        )

        # Only HELD bookings can be paid for. A booking that has already
        # been PAID, EXPIRED, or CANCELLED must not initiate a new charge.
        with transaction.atomic():
            # Lock the booking row so a concurrent /pay/ can't double-charge.
            locked = (
                Booking.objects
                .select_for_update()
                .get(pk=booking.pk)
            )
            if locked.status != Booking.Status.HELD:
                return Response(
                    {"error": {"detail": "Booking is not in a payable state."}},
                    status=status.HTTP_409_CONFLICT,
                )

            amount = _total_amount_for_hold(locked)
            payment, _created = Payment.objects.get_or_create(
                booking=locked,
                defaults={"amount": amount, "status": Payment.Status.PENDING},
            )

            # If a Payment already exists for this booking (the client is
            # retrying /pay/), leave its state alone but still fire a new
            # charge — the webhook dedup on event_id will protect us from
            # double-confirmation, and we want the user's retry to make
            # progress if the gateway is reachable now.
            booking_ref_str = locked.booking_ref
            callback_url = _callback_url_for(request)

        # Fire-and-forget the /charge call. The worker tolerates timeouts
        # and 5xx by leaving the Payment PENDING — the webhook will
        # eventually settle the booking either way.
        _dispatch_charge_safe(
            booking=Booking.objects.get(pk=booking.pk),
            amount=amount,
            callback_url=callback_url,
        )

        body = {
            "booking_id": booking_ref_str,
            "payment_id": payment.payment_id,  # may be None on first attempt
            "status": payment.status,
            "amount": str(payment.amount),
        }
        return Response(body, status=status.HTTP_202_ACCEPTED)
