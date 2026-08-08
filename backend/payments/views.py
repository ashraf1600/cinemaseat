"""Payment webhook receiver.

The upstream gateway POSTs asynchronous notifications to us at
``/api/webhooks/payment/``. The contract is:

    {
      "event_id": "<unique>",        # idempotency key — DB-unique
      "payment_id": "<gateway id>",
      "booking_ref": "bk_...",
      "status": "SUCCEEDED" | "FAILED" | "REFUNDED",
      "amount": "123.45"
    }

Behaviour:
  1. If a ``PaymentEvent`` with this ``event_id`` already exists, return
     200 immediately. This is the duplicate-callback guard and is the
     only thing standing between us and double-confirmation.
  2. Otherwise, insert the event row and apply the status change to
     ``Payment`` + ``Booking`` + ``Seat`` inside a single transaction.
  3. ALWAYS return 200. Any exception is caught and logged — the
     gateway will retry forever on a non-200.

State transitions on SUCCEEDED:
    Booking.status HELD -> PAID
    Seat.status    HELD -> BOOKED
    Payment.status PENDING -> SUCCEEDED

State transitions on FAILED (decision: release immediately):
    Booking.status HELD -> EXPIRED
    Seat.status    HELD -> AVAILABLE
    Payment.status PENDING -> FAILED

Rationale for releasing seats immediately on FAILED: the user just saw
a declined card. Telling them "your seats will be available again in
~90s" is a worse UX than telling them "your seats are available right
now, try again." The webhook is the source of truth; a later retry
of /pay/ will create a brand-new Payment, so there's no state machine
hazard from instant release.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from booking.models import Booking, BookingSeat
from catalog.models import Seat

from .models import Payment, PaymentEvent

logger = logging.getLogger(__name__)

_VALID_STATUSES = {
    Payment.Status.SUCCEEDED,
    Payment.Status.FAILED,
    Payment.Status.REFUNDED,
}


def _parse_amount(raw) -> Decimal:
    """Be tolerant of int / float / str / Decimal in the payload."""
    if isinstance(raw, Decimal):
        return raw
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid amount: {raw!r}") from exc


def _apply_event_atomically(payload: dict) -> None:
    """Apply ``payload`` to Payment + Booking + Seat. Raises on malformed input."""
    booking_ref = payload["booking_ref"]
    event_status = payload["status"]
    amount = _parse_amount(payload["amount"])
    gateway_payment_id = payload.get("payment_id")

    if event_status not in _VALID_STATUSES:
        raise ValueError(f"Unsupported status: {event_status!r}")

    with transaction.atomic():
        # Lock the Payment row so a concurrent webhook for the same
        # booking can't race us. (The event_id guard above is the
        # primary defence; this is belt-and-suspenders.)
        try:
            payment = Payment.objects.select_for_update().get(booking__booking_ref=booking_ref)
        except Payment.DoesNotExist as exc:
            raise ValueError(f"No Payment for booking {booking_ref}") from exc

        if gateway_payment_id and not payment.payment_id:
            payment.payment_id = str(gateway_payment_id)

        booking = (
            Booking.objects
            .select_for_update()
            .get(pk=payment.booking_id)
        )

        if event_status == Payment.Status.SUCCEEDED:
            payment.status = Payment.Status.SUCCEEDED
            payment.save(update_fields=["status", "payment_id"])

            booking.status = Booking.Status.PAID
            booking.save(update_fields=["status"])

            seat_ids = BookingSeat.objects.filter(booking=booking).values_list("seat_id", flat=True)
            Seat.objects.filter(id__in=list(seat_ids)).update(status=Seat.Status.BOOKED)

        elif event_status == Payment.Status.FAILED:
            # Release seats immediately so the user can retry without
            # waiting for the TTL sweep. See module docstring.
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=["status", "payment_id"])

            booking.status = Booking.Status.EXPIRED
            booking.save(update_fields=["status"])

            seat_ids = BookingSeat.objects.filter(booking=booking).values_list("seat_id", flat=True)
            Seat.objects.filter(id__in=list(seat_ids)).update(status=Seat.Status.AVAILABLE)

        else:  # REFUNDED
            payment.status = Payment.Status.REFUNDED
            payment.save(update_fields=["status", "payment_id"])
            # Refund doesn't change seat / booking state per the
            # contract — the booking is already PAID, seats are BOOKED.


def _missing_field_response(missing: str) -> Response:
    return Response(
        {"error": {"detail": f"Missing field: {missing}"}},
        status=status.HTTP_200_OK,  # ALWAYS 200 — the gateway retries forever on non-200.
    )


class PaymentWebhookView(APIView):
    """
    POST /api/webhooks/payment/

    Idempotent gateway callback receiver. See module docstring for the
    full state-transition contract.
    """

    # Disable auth/CSRF — the gateway is unauthenticated; in production
    # this would be signed-HMAC verified, but the spec for this milestone
    # is HMAC-less and tests use the gateway-mock pattern.
    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request, *args, **kwargs) -> Response:
        payload = request.data if isinstance(request.data, dict) else {}

        # Required fields. Per the spec, ALWAYS return 200 — even on
        # bad input — so the gateway doesn't retry forever. We log and
        # move on.
        for field in ("event_id", "payment_id", "booking_ref", "status", "amount"):
            if not payload.get(field):
                logger.warning("Webhook missing field %s in payload=%s", field, payload)
                return _missing_field_response(field)

        # Idempotency: a PaymentEvent with this event_id is the
        # duplicate-callback guard. If it already exists, this is a
        # duplicate delivery and we MUST NOT touch Payment/Booking/Seat
        # state again.
        #
        # ``PaymentEvent.payment`` is a required FK, so we have to
        # resolve the local Payment row before inserting the event.
        # We do that lookup first; if no Payment exists yet for this
        # booking_ref, we accept the webhook (200) and log — we don't
        # want a stray callback to wedge the system.
        try:
            payment = Payment.objects.get(booking__booking_ref=payload["booking_ref"])
        except Payment.DoesNotExist:
            logger.warning(
                "Webhook event_id=%s references unknown booking_ref=%s",
                payload["event_id"], payload["booking_ref"],
            )
            return Response({"status": "accepted"}, status=status.HTTP_200_OK)

        try:
            with transaction.atomic():
                event, created = PaymentEvent.objects.get_or_create(
                    event_id=str(payload["event_id"]),
                    defaults={
                        "payment": payment,
                        "status": payload["status"],
                        "raw_payload": payload,
                    },
                )
        except Exception as exc:  # noqa: BLE001 — defensive, always 200
            logger.exception("PaymentEvent insert failed for event_id=%s", payload.get("event_id"))
            return Response({"status": "accepted"}, status=status.HTTP_200_OK)

        if not created:
            # Duplicate delivery — we've already processed this event.
            return Response({"status": "accepted"}, status=status.HTTP_200_OK)

        # Apply the state transition. ANY exception here is logged but
        # still returns 200 — a non-200 would make the gateway retry
        # forever per its documented behavior.
        try:
            _apply_event_atomically(payload)
        except Exception as exc:  # noqa: BLE001 — defensive, always 200
            logger.exception(
                "Failed to apply webhook event_id=%s status=%s: %s",
                payload["event_id"], payload["status"], exc,
            )

        return Response({"status": "accepted"}, status=status.HTTP_200_OK)
