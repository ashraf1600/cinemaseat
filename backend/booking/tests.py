"""
Tests for the booking app — focused on the hold endpoint's concurrency
guarantees (the seat-hold system must never oversell under contention).

The two tests covering 0-oversell verify the *check-then-act* logic.
True concurrent-thread testing (with two threads hammering the same seat
through separate DB connections) lives in Milestone 4's load test
script — these tests would not catch a real race in a single-connection
test client, so the comment in each test makes that explicit.
"""
from __future__ import annotations

import threading
import time
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient

from booking import gateway
from booking.models import Booking, BookingSeat, OtpVerification
from catalog.models import Seat, Showtime
from payments.models import Payment


@pytest.fixture
def seeded(db) -> Showtime:
    """Seed the demo dataset and return a single showtime for testing."""
    call_command("seed_demo_data", "--reset")
    return Showtime.objects.first()


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def held_booking(client, seeded) -> Booking:
    """Create a HELD booking on the seeded showtime and return it."""
    seats = list(Seat.objects.filter(showtime=seeded).order_by("id")[:2])
    response = client.post(
        "/api/bookings/hold/",
        data={
            "showtime_id": seeded.id,
            "seat_ids": [s.id for s in seats],
            "phone": "+15550001234",
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    return Booking.objects.get(booking_ref=response.json()["booking_id"])


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_hold_creates_held_booking_and_marks_seats(client, seeded) -> None:
    """A successful hold creates a HELD booking, flips seats to HELD,
    and returns the documented response shape."""
    seats = list(Seat.objects.filter(showtime=seeded).order_by("id")[:2])
    seat_ids = [s.id for s in seats]

    response = client.post(
        "/api/bookings/hold/",
        data={"showtime_id": seeded.id, "seat_ids": seat_ids, "phone": "+15551112222"},
        format="json",
    )

    assert response.status_code == 201, response.content
    body = response.json()

    # Documented response shape.
    assert set(body.keys()) == {"booking_id", "status", "expires_at", "seats"}
    assert body["status"] == "HELD"
    assert body["booking_id"].startswith("bk_")
    assert len(body["seats"]) == 2
    assert {s["id"] for s in body["seats"]} == set(seat_ids)
    assert {s["label"] for s in body["seats"]} == {s.label for s in seats}

    # expires_at must be ~HOLD_TTL_SECONDS in the future (default 120s).
    expires_at = timezone.datetime.fromisoformat(body["expires_at"])
    if expires_at.tzinfo is None:
        from django.utils.timezone import make_aware
        expires_at = make_aware(expires_at)
    delta = expires_at - timezone.now()
    assert timedelta(seconds=110) < delta < timedelta(seconds=130)

    # Side effects: seats HELD, booking + join rows created.
    for s in seats:
        s.refresh_from_db()
        assert s.status == Seat.Status.HELD

    booking = Booking.objects.get(booking_ref=body["booking_id"])
    assert booking.status == Booking.Status.HELD
    assert booking.phone == "+15551112222"
    assert BookingSeat.objects.filter(booking=booking).count() == 2


@pytest.mark.django_db
def test_get_booking_returns_status_and_seats(client, seeded) -> None:
    """GET /api/bookings/<ref>/ returns the held seats."""
    seats = list(Seat.objects.filter(showtime=seeded).order_by("id")[:3])
    seat_ids = [s.id for s in seats]

    hold = client.post(
        "/api/bookings/hold/",
        data={"showtime_id": seeded.id, "seat_ids": seat_ids, "phone": "+15553334444"},
        format="json",
    ).json()

    response = client.get(f"/api/bookings/{hold['booking_id']}/")
    assert response.status_code == 200
    body = response.json()
    assert body["booking_id"] == hold["booking_id"]
    assert body["status"] == "HELD"
    assert {s["id"] for s in body["seats"]} == set(seat_ids)


@pytest.mark.django_db
def test_get_booking_404_for_unknown_ref(client, seeded) -> None:
    response = client.get("/api/bookings/bk_does_not_exist/")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_hold_rejects_duplicate_seat_ids_in_request(client, seeded) -> None:
    """Duplicate ids in the request body must be rejected by the serializer."""
    seat_id = Seat.objects.filter(showtime=seeded).first().id
    response = client.post(
        "/api/bookings/hold/",
        data={"showtime_id": seeded.id, "seat_ids": [seat_id, seat_id], "phone": "+15550000000"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_hold_rejects_unknown_seat_id(client, seeded) -> None:
    response = client.post(
        "/api/bookings/hold/",
        data={"showtime_id": seeded.id, "seat_ids": [999_999], "phone": "+15550000000"},
        format="json",
    )
    assert response.status_code == 409
    assert response.json() == {"error": {"detail": "One or more seats are no longer available."}}
    assert Seat.objects.filter(showtime=seeded, status=Seat.Status.HELD).count() == 0


@pytest.mark.django_db
def test_hold_rejects_seat_from_wrong_showtime(client, seeded) -> None:
    """A seat id that exists but belongs to a different showtime must 409."""
    other_seat = Seat.objects.exclude(showtime=seeded).order_by("id").first()
    other_showtime = other_seat.showtime
    response = client.post(
        "/api/bookings/hold/",
        data={
            "showtime_id": seeded.id,  # claim it belongs to `seeded`
            "seat_ids": [other_seat.id],  # but it belongs to `other_showtime`
            "phone": "+15550000000",
        },
        format="json",
    )
    assert response.status_code == 409
    other_seat.refresh_from_db()
    assert other_seat.status == Seat.Status.AVAILABLE
    assert other_seat.showtime_id == other_showtime.id


# ---------------------------------------------------------------------------
# Zero-oversell guarantee (check-then-act)
# ---------------------------------------------------------------------------
#
# NOTE: These tests prove the check-then-act path against sequential
# calls. True concurrent-thread testing (two threads, two DB connections,
# hammering the same seat in parallel) happens in the Milestone 4 load
# test script, which reads/writes separate connections — pytest-django's
# `APIClient` shares a single connection per test transaction and would
# not catch a real race. The two tests below are the *contract* tests:
# once the lock is held, the second caller must see a non-AVAILABLE seat
# and roll back atomically.
#
@pytest.mark.django_db
def test_hold_last_seat_then_second_attempt_returns_409_and_db_is_consistent(
    client, seeded
) -> None:
    """Scenario: only one AVAILABLE seat remains. The first hold succeeds
    and flips it to HELD. A second hold for the same seat must 409, and
    the DB must never show the seat as BOOKED twice or go negative."""
    # Hold every seat except the last one to set up the "last available" scenario.
    all_seats = list(Seat.objects.filter(showtime=seeded).order_by("id"))
    last_seat = all_seats[-1]
    earlier_seats = all_seats[:-1]

    first_hold = client.post(
        "/api/bookings/hold/",
        data={
            "showtime_id": seeded.id,
            "seat_ids": [s.id for s in earlier_seats],
            "phone": "+15550000001",
        },
        format="json",
    )
    assert first_hold.status_code == 201, first_hold.content

    # Now request the last seat — should succeed.
    last_hold = client.post(
        "/api/bookings/hold/",
        data={
            "showtime_id": seeded.id,
            "seat_ids": [last_seat.id],
            "phone": "+15550000002",
        },
        format="json",
    )
    assert last_hold.status_code == 201

    # A second attempt to hold the SAME seat must fail with 409.
    second_attempt = client.post(
        "/api/bookings/hold/",
        data={
            "showtime_id": seeded.id,
            "seat_ids": [last_seat.id],
            "phone": "+15550000003",
        },
        format="json",
    )
    assert second_attempt.status_code == 409
    assert second_attempt.json() == {
        "error": {"detail": "One or more seats are no longer available."}
    }

    # DB state must be exactly consistent: the seat is HELD, exactly one
    # BookingSeat row references it, and we never produced a negative
    # count for any status.
    last_seat.refresh_from_db()
    assert last_seat.status == Seat.Status.HELD
    assert BookingSeat.objects.filter(seat=last_seat).count() == 1
    assert Booking.objects.count() == 2  # earlier + last holding
    assert Seat.objects.filter(showtime=seeded, status=Seat.Status.AVAILABLE).count() == 0
    assert Seat.objects.filter(showtime=seeded, status=Seat.Status.BOOKED).count() == 0
    # No HELD row should have been created by the failed attempt.
    held_count = Seat.objects.filter(showtime=seeded, status=Seat.Status.HELD).count()
    assert held_count == len(earlier_seats) + 1


@pytest.mark.django_db
def test_overlapping_multi_seat_hold_rolls_back_atomically(client, seeded) -> None:
    """Scenario: caller A holds {1,2,3}, caller B tries to hold {2,3,4}.
    B must 409 and NONE of {2,3,4} must end up HELD for B — the atomic
    transaction guarantees we never half-hold a set."""
    seats = list(Seat.objects.filter(showtime=seeded).order_by("id")[:4])
    a_ids = [seats[0].id, seats[1].id, seats[2].id]
    b_ids = [seats[1].id, seats[2].id, seats[3].id]

    # A grabs {1,2,3}
    a_response = client.post(
        "/api/bookings/hold/",
        data={"showtime_id": seeded.id, "seat_ids": a_ids, "phone": "+15550000001"},
        format="json",
    )
    assert a_response.status_code == 201

    # B's overlapping request must be rejected.
    b_response = client.post(
        "/api/bookings/hold/",
        data={"showtime_id": seeded.id, "seat_ids": b_ids, "phone": "+15550000002"},
        format="json",
    )
    assert b_response.status_code == 409

    # Seat 4 (not in A's hold) must still be AVAILABLE.
    seats[3].refresh_from_db()
    assert seats[3].status == Seat.Status.AVAILABLE

    # A's 3 seats must STILL be HELD by A — transaction atomicity means B's
    # failure didn't flip anything.
    for s in seats[:3]:
        s.refresh_from_db()
        assert s.status == Seat.Status.HELD

    # Exactly one booking must exist, with exactly A's 3 seats.
    assert Booking.objects.count() == 1
    assert BookingSeat.objects.count() == 3
    assert BookingSeat.objects.filter(seat__in=a_ids).count() == 3
    assert BookingSeat.objects.filter(seat=seats[3]).count() == 0


# ---------------------------------------------------------------------------
# OTP integration
# ---------------------------------------------------------------------------
#
# The OTP endpoints talk to an upstream gateway over HTTP. These tests
# monkeypatch `booking.gateway.send_otp` / `verify_otp` so we never hit
# the network — fast, deterministic, and independent of gateway state.
#
# `monkeypatch` is preferred over mocking libraries to keep the test
# file dependency-free.
class _Call:
    """Records each gateway call so tests can assert on them."""

    def __init__(self, return_value: int, raise_exc: Exception | None = None):
        self.return_value = return_value
        self.raise_exc = raise_exc
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.return_value


def _wait_for_send_calls(stub: _Call, expected: int, timeout: float = 2.0) -> None:
    """Spin until the OTP-send worker thread has called the stub `expected` times.

    The send view fires the gateway call in a daemon thread, so the test
    must yield to the scheduler before asserting on the stub. We poll for
    up to `timeout` seconds and fail loudly if nothing arrived.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(stub.calls) >= expected:
            return
        # Yield to the worker thread so it can finish its HTTP call.
        threading.Event().wait(0.01)
    raise AssertionError(
        f"Expected {expected} gateway send call(s), saw {len(stub.calls)}"
    )


@pytest.mark.django_db
def test_otp_send_returns_202_creates_sent_row_and_calls_gateway(client, held_booking, monkeypatch):
    """POST /api/bookings/<ref>/otp/send/ must:
      * return 202 immediately,
      * create an OtpVerification row in SENT status,
      * call the gateway in the background with {phone, ref}.
    """
    stub = _Call(return_value=200)
    monkeypatch.setattr(gateway, "send_otp", stub)

    response = client.post(f"/api/bookings/{held_booking.booking_ref}/otp/send/")

    assert response.status_code == 202, response.content
    body = response.json()
    assert body["booking_id"] == held_booking.booking_ref
    assert body["status"] == "SENT"
    assert body["otp_ref"].startswith("otp_")

    otp = OtpVerification.objects.get(booking=held_booking)
    assert otp.status == OtpVerification.Status.SENT
    assert otp.ref == body["otp_ref"]

    # The gateway call is dispatched in a daemon thread; wait for it.
    _wait_for_send_calls(stub, expected=1)
    # `callback_url` was added as an additional kwarg after this test was
    # written; assert the required fields are present without pinning the
    # whole dict (so future kwarg additions don't break the test).
    call_kwargs = stub.calls[0]["kwargs"]
    assert call_kwargs.get("phone") == held_booking.phone
    assert call_kwargs.get("ref") == otp.ref
    assert "callback_url" in call_kwargs  # /api/webhooks/otp/


@pytest.mark.django_db
def test_otp_send_returns_202_even_when_gateway_is_down(client, held_booking, monkeypatch):
    """The send endpoint MUST NOT block on the gateway. If the upstream
    is slow or unreachable, we still create the OTP row and return 202 —
    whether the SMS actually arrives is the gateway's responsibility."""
    stub = _Call(return_value=200, raise_exc=gateway.GatewayError("connection refused"))
    monkeypatch.setattr(gateway, "send_otp", stub)

    response = client.post(f"/api/bookings/{held_booking.booking_ref}/otp/send/")

    # 202 fires immediately, before the worker even gets a chance to fail.
    assert response.status_code == 202, response.content
    assert OtpVerification.objects.filter(
        booking=held_booking, status=OtpVerification.Status.SENT
    ).exists()

    _wait_for_send_calls(stub, expected=1)


@pytest.mark.django_db
def test_otp_send_404_for_unknown_booking(client, seeded):
    response = client.post("/api/bookings/bk_does_not_exist/otp/send/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_otp_verify_on_gateway_200_marks_verified_and_returns_200(
    client, held_booking, monkeypatch
):
    """Happy path: gateway returns 200 → OtpVerification.status = VERIFIED, response 200."""
    send_stub = _Call(return_value=200)
    monkeypatch.setattr(gateway, "send_otp", send_stub)

    # Set up an OTP row first.
    client.post(f"/api/bookings/{held_booking.booking_ref}/otp/send/")
    otp = OtpVerification.objects.get(booking=held_booking)

    # Now verify.
    verify_stub = _Call(return_value=200)
    monkeypatch.setattr(gateway, "verify_otp", verify_stub)

    response = client.post(
        f"/api/bookings/{held_booking.booking_ref}/otp/verify/",
        data={"code": "123456"},
        format="json",
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["booking_id"] == held_booking.booking_ref
    assert body["otp_ref"] == otp.ref
    assert body["status"] == "VERIFIED"

    otp.refresh_from_db()
    assert otp.status == OtpVerification.Status.VERIFIED

    assert len(verify_stub.calls) == 1
    assert verify_stub.calls[0]["kwargs"] == {"ref": otp.ref, "code": "123456"}


@pytest.mark.django_db
def test_otp_verify_on_gateway_400_returns_400_and_leaves_status_unchanged(
    client, held_booking, monkeypatch
):
    """Bad/expired code path: gateway returns 400 → 400 with documented body,
    OtpVerification.status stays at SENT."""
    monkeypatch.setattr(gateway, "send_otp", _Call(return_value=200))
    client.post(f"/api/bookings/{held_booking.booking_ref}/otp/send/")
    otp = OtpVerification.objects.get(booking=held_booking)
    assert otp.status == OtpVerification.Status.SENT

    verify_stub = _Call(return_value=400)
    monkeypatch.setattr(gateway, "verify_otp", verify_stub)

    response = client.post(
        f"/api/bookings/{held_booking.booking_ref}/otp/verify/",
        data={"code": "000000"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json() == {"error": {"detail": "Invalid or expired code."}}

    otp.refresh_from_db()
    assert otp.status == OtpVerification.Status.SENT  # not flipped to VERIFIED


@pytest.mark.django_db
def test_otp_verify_400_when_code_field_missing(client, held_booking):
    """The DRF serializer rejects malformed bodies before we touch the gateway."""
    response = client.post(
        f"/api/bookings/{held_booking.booking_ref}/otp/verify/",
        data={},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_otp_verify_404_for_unknown_booking(client, seeded):
    response = client.post(
        "/api/bookings/bk_does_not_exist/otp/verify/",
        data={"code": "123456"},
        format="json",
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_otp_verify_404_when_no_otp_was_sent(client, held_booking):
    """If the client never called /otp/send/, the verify endpoint has no
    ref to send to the gateway — return 404 rather than crashing."""
    response = client.post(
        f"/api/bookings/{held_booking.booking_ref}/otp/verify/",
        data={"code": "123456"},
        format="json",
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Payment initiation + idempotent webhook
# ---------------------------------------------------------------------------
#
# The /pay/ endpoint fires the gateway call in a daemon thread — tests
# must therefore wait for the worker to finish before asserting on the
# gateway stub. The webhook tests run synchronously with no thread.
#
# Webhook contract reminder (see payments/views.py docstring):
#   1. duplicate event_id  -> 200, no state change
#   2. SUCCEEDED            -> Booking PAID, seats BOOKED
#   3. FAILED               -> Booking EXPIRED, seats AVAILABLE (per design)
#   4. ANYTHING             -> 200 (so the gateway never retries forever)
#
class _ChargeCall:
    """Records /charge calls and returns a (status, body) tuple."""

    def __init__(self, return_value: tuple[int, dict], raise_exc: Exception | None = None):
        self.return_value = return_value
        self.raise_exc = raise_exc
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.return_value


def _wait_for_charge_calls(stub: _ChargeCall, expected: int, timeout: float = 2.0) -> None:
    """Spin until the /charge worker thread has called the stub `expected` times."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(stub.calls) >= expected:
            return
        threading.Event().wait(0.01)


def _wait_for_payment_id(payment_id_value: str, timeout: float = 5.0) -> None:
    """Spin until the latest Payment row has ``payment_id`` set to the expected value.

    The /charge worker writes back the gateway's ``payment_id`` from a
    separate thread on its own DB connection. We poll the test's
    connection until the row reflects the worker's commit.
    """
    deadline = time.monotonic() + timeout
    last_value = None
    while time.monotonic() < deadline:
        p = Payment.objects.order_by("-id").first()
        last_value = p.payment_id if p else None
        if last_value == payment_id_value:
            return
        threading.Event().wait(0.05)
    raise AssertionError(
        f"Timed out waiting for Payment.payment_id to become {payment_id_value!r} "
        f"(last seen: {last_value!r})"
    )
    raise AssertionError(
        f"Expected {expected} gateway /charge call(s), saw {len(stub.calls)}"
    )


def _seed_payment_row(held_booking: Booking) -> Payment:
    """Helper: create a PENDING Payment row directly (bypassing /pay/)."""
    seat_count = held_booking.booking_seats.count()
    base_price = held_booking.booking_seats.first().seat.showtime.base_price
    return Payment.objects.create(
        booking=held_booking,
        amount=base_price * seat_count,
        status=Payment.Status.PENDING,
    )


# ----- /pay/ -----------------------------------------------------------------
@pytest.mark.django_db(transaction=True)
def test_pay_returns_202_creates_pending_payment_and_calls_gateway(
    client, held_booking, monkeypatch
):
    """POST /api/bookings/<ref>/pay/ must:
      * return 202 immediately,
      * create a Payment row in PENDING with the right amount,
      * call the gateway /charge in the background with the documented payload.

    Uses ``transaction=True`` so the test's writes actually commit and
    release the row locks the in-thread worker is waiting on. Combined
    with the file-backed test DB (see settings_test.py) and the worker's
    retry-on-OperationalError loop, this gives the worker a clear shot
    at the table.
    """
    stub = _ChargeCall(return_value=(200, {"payment_id": "pay_xyz123"}))
    monkeypatch.setattr(gateway, "charge", stub)

    response = client.post(f"/api/bookings/{held_booking.booking_ref}/pay/")

    assert response.status_code == 202, response.content
    body = response.json()
    assert body["booking_id"] == held_booking.booking_ref
    assert body["status"] == "PENDING"
    # On the immediate response, payment_id may be None (the worker
    # backfills it after the gateway call). Accept either.
    assert body["payment_id"] in (None, "pay_xyz123")
    assert "amount" in body

    payment = Payment.objects.get(booking=held_booking)
    assert payment.status == Payment.Status.PENDING
    seat_count = held_booking.booking_seats.count()
    base_price = held_booking.booking_seats.first().seat.showtime.base_price
    assert payment.amount == base_price * seat_count

    _wait_for_charge_calls(stub, expected=1)
    kwargs = stub.calls[0]["kwargs"]
    assert kwargs["currency"] == "BDT"
    assert kwargs["booking_ref"] == held_booking.booking_ref
    assert kwargs["callback_url"].endswith("/api/webhooks/payment/")
    assert Decimal(kwargs["amount"]) == payment.amount

    # Wait for the worker to commit the back-filled payment_id.
    _wait_for_payment_id("pay_xyz123")
    payment.refresh_from_db()
    assert payment.payment_id == "pay_xyz123"


@pytest.mark.django_db
def test_pay_returns_202_even_when_gateway_times_out(client, held_booking, monkeypatch):
    """A GatewayError (timeout / refused) MUST NOT propagate to the caller.
    The Payment row stays PENDING; the webhook will settle it later."""
    stub = _ChargeCall(return_value=(0, {}), raise_exc=gateway.GatewayError("connection refused"))
    monkeypatch.setattr(gateway, "charge", stub)

    response = client.post(f"/api/bookings/{held_booking.booking_ref}/pay/")

    assert response.status_code == 202
    payment = Payment.objects.get(booking=held_booking)
    assert payment.status == Payment.Status.PENDING
    assert payment.payment_id is None

    _wait_for_charge_calls(stub, expected=1)


@pytest.mark.django_db
def test_pay_returns_202_when_gateway_5xx_then_payment_stays_pending(
    client, held_booking, monkeypatch
):
    """The documented 2% /charge failure rate returns 5xx. We leave the
    Payment PENDING and the webhook will reconcile."""
    stub = _ChargeCall(return_value=(503, {}))
    monkeypatch.setattr(gateway, "charge", stub)

    response = client.post(f"/api/bookings/{held_booking.booking_ref}/pay/")

    assert response.status_code == 202
    _wait_for_charge_calls(stub, expected=1)
    payment = Payment.objects.get(booking=held_booking)
    assert payment.status == Payment.Status.PENDING


@pytest.mark.django_db
def test_pay_409_on_booking_not_held(client, held_booking, monkeypatch):
    """If the booking is already PAID / EXPIRED / CANCELLED, /pay/ must 409."""
    held_booking.status = Booking.Status.PAID
    held_booking.save(update_fields=["status"])

    stub = _ChargeCall(return_value=(200, {"payment_id": "pay_x"}))
    monkeypatch.setattr(gateway, "charge", stub)

    response = client.post(f"/api/bookings/{held_booking.booking_ref}/pay/")
    assert response.status_code == 409
    assert "error" in response.json()
    assert stub.calls == []  # no gateway call was made


@pytest.mark.django_db
def test_pay_404_for_unknown_booking(client, seeded, monkeypatch):
    stub = _ChargeCall(return_value=(200, {}))
    monkeypatch.setattr(gateway, "charge", stub)
    response = client.post("/api/bookings/bk_does_not_exist/pay/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_pay_reuses_existing_payment_on_retry(client, held_booking, monkeypatch):
    """The user is allowed to retry /pay/ (e.g. after a 5xx). We don't
    create a second Payment row — we reuse the existing PENDING one
    and fire a fresh /charge call."""
    existing = _seed_payment_row(held_booking)
    stub = _ChargeCall(return_value=(200, {"payment_id": "pay_retry"}))
    monkeypatch.setattr(gateway, "charge", stub)

    response = client.post(f"/api/bookings/{held_booking.booking_ref}/pay/")
    assert response.status_code == 202
    assert Payment.objects.filter(booking=held_booking).count() == 1
    _wait_for_charge_calls(stub, expected=1)


# ----- Webhook (/api/webhooks/payment/) --------------------------------------
def _post_webhook(client, **overrides) -> Response:
    payload = {
        "event_id": "evt_test_001",
        "payment_id": "pay_xyz",
        "booking_ref": "bk_does_not_matter",
        "status": "SUCCEEDED",
        "amount": "150.00",
        **overrides,
    }
    return client.post("/api/webhooks/payment/", data=payload, format="json")


@pytest.mark.django_db
def test_webhook_succeeded_marks_booking_paid_and_seats_booked(client, held_booking):
    _seed_payment_row(held_booking)
    response = _post_webhook(client, booking_ref=held_booking.booking_ref)
    assert response.status_code == 200

    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.PAID

    payment = Payment.objects.get(booking=held_booking)
    assert payment.status == Payment.Status.SUCCEEDED
    assert payment.payment_id == "pay_xyz"

    seats = [bs.seat for bs in held_booking.booking_seats.all()]
    for seat in seats:
        seat.refresh_from_db()
        assert seat.status == Seat.Status.BOOKED

    # The event log row exists and is the only one.
    from payments.models import PaymentEvent
    events = PaymentEvent.objects.filter(payment=payment)
    assert events.count() == 1
    assert events.first().status == Payment.Status.SUCCEEDED


@pytest.mark.django_db
def test_webhook_duplicate_event_id_is_a_no_op(client, held_booking):
    """The gateway may deliver the same event twice. The second delivery
    must NOT touch Booking/Payment/Seat state — only the event log
    proves it arrived."""
    _seed_payment_row(held_booking)

    first = _post_webhook(client, booking_ref=held_booking.booking_ref)
    assert first.status_code == 200

    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.PAID
    first_seat_status = held_booking.booking_seats.first().seat.status
    Seat.objects.filter(id__in=held_booking.booking_seats.values_list("seat_id", flat=True)).update(
        status=Seat.Status.BOOKED
    )

    # Second delivery — flip the SUCCEEDED payload to FAILED in a way
    # that would normally corrupt state. The dedup must prevent it.
    second = _post_webhook(
        client,
        booking_ref=held_booking.booking_ref,
        status="FAILED",
        event_id="evt_test_001",  # SAME event_id
    )
    assert second.status_code == 200

    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.PAID  # unchanged
    payment = Payment.objects.get(booking=held_booking)
    assert payment.status == Payment.Status.SUCCEEDED  # unchanged

    # Seat count + statuses unchanged.
    held_seat_ids = list(held_booking.booking_seats.values_list("seat_id", flat=True))
    booked = Seat.objects.filter(id__in=held_seat_ids, status=Seat.Status.BOOKED).count()
    assert booked == len(held_seat_ids)

    # Exactly one event row, not two.
    from payments.models import PaymentEvent
    assert PaymentEvent.objects.filter(payment=payment).count() == 1


@pytest.mark.django_db
def test_webhook_failed_releases_seats_immediately_and_expires_booking(client, held_booking):
    """Design decision: FAILED webhook releases seats to AVAILABLE right
    away and flips the booking to EXPIRED. The user can retry /pay/
    immediately rather than waiting for the TTL sweep."""
    _seed_payment_row(held_booking)
    response = _post_webhook(
        client,
        booking_ref=held_booking.booking_ref,
        status="FAILED",
    )
    assert response.status_code == 200

    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.EXPIRED

    payment = Payment.objects.get(booking=held_booking)
    assert payment.status == Payment.Status.FAILED

    held_seat_ids = list(held_booking.booking_seats.values_list("seat_id", flat=True))
    available = Seat.objects.filter(id__in=held_seat_ids, status=Seat.Status.AVAILABLE).count()
    assert available == len(held_seat_ids)


@pytest.mark.django_db
def test_webhook_returns_200_even_when_booking_does_not_exist(client, seeded):
    """An unknown booking_ref MUST still return 200 — otherwise the
    gateway retries forever."""
    response = _post_webhook(client, booking_ref="bk_nope")
    assert response.status_code == 200


@pytest.mark.django_db
def test_webhook_returns_200_when_required_field_missing(client, held_booking):
    """Missing required fields -> 200 (logged but accepted). The gateway
    spec says non-200 makes it retry forever; we never want that."""
    response = client.post(
        "/api/webhooks/payment/",
        data={"event_id": "evt_test_002"},  # missing everything else
        format="json",
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_webhook_refunded_changes_payment_status_only(client, held_booking):
    """REFUNDED is a no-op on seat/booking state — the booking is
    already PAID, seats are already BOOKED. Only Payment.status moves."""
    _seed_payment_row(held_booking)
    # First, drive the booking to PAID via SUCCEEDED.
    _post_webhook(client, booking_ref=held_booking.booking_ref, event_id="evt_success_1")

    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.PAID

    response = _post_webhook(
        client,
        booking_ref=held_booking.booking_ref,
        status="REFUNDED",
        event_id="evt_refund_1",
    )
    assert response.status_code == 200

    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.PAID  # unchanged

    payment = Payment.objects.get(booking=held_booking)
    assert payment.status == Payment.Status.REFUNDED

    held_seat_ids = list(held_booking.booking_seats.values_list("seat_id", flat=True))
    booked = Seat.objects.filter(id__in=held_seat_ids, status=Seat.Status.BOOKED).count()
    assert booked == len(held_seat_ids)


# ---------------------------------------------------------------------------
# Hold expiry (check-on-read + management command)
# ---------------------------------------------------------------------------
#
# Two layers cooperate to keep HELD bookings from holding seats forever:
#
#   1. Check-on-read: every seat-map and booking-detail read runs
#      ``expire_overdue_holds()`` first.
#   2. Background sweep: ``manage.py expire_holds`` does the same sweep
#      independently so holds expire even without a read.
#
# The tests below create a booking with ``expires_at`` already in the past
# and verify both code paths.


def _backdate_hold(booking: Booking, *, seconds: int = 60) -> None:
    """Force ``booking.expires_at`` into the past and re-save."""
    booking.expires_at = timezone.now() - timedelta(seconds=seconds)
    booking.save(update_fields=["expires_at"])


@pytest.mark.django_db
def test_seat_map_endpoint_expires_overdue_hold(client, held_booking, seeded):
    """Hitting the seat-map endpoint must expire any HELD booking whose
    TTL has passed — seats go back to AVAILABLE and the booking flips
    to EXPIRED as a side effect of the read."""
    # Backdate the hold so it's clearly overdue.
    _backdate_hold(held_booking, seconds=120)

    held_seat_ids = list(held_booking.booking_seats.values_list("seat_id", flat=True))

    # Sanity check the starting state.
    assert Seat.objects.filter(id__in=held_seat_ids, status=Seat.Status.HELD).count() == len(held_seat_ids)

    # The endpoint runs the expiry sweep before returning data.
    response = client.get(f"/api/showtimes/{seeded.id}/seats/")

    assert response.status_code == 200, response.content
    seats_by_id = {s["id"]: s for s in response.json()}
    for seat_id in held_seat_ids:
        assert seats_by_id[seat_id]["status"] == "AVAILABLE"

    # Side effects: the booking is EXPIRED and the seats are AVAILABLE.
    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.EXPIRED
    assert Seat.objects.filter(id__in=held_seat_ids, status=Seat.Status.AVAILABLE).count() == len(held_seat_ids)


@pytest.mark.django_db
def test_booking_detail_endpoint_expires_overdue_hold(client, held_booking):
    """GET /api/bookings/<ref>/ must also expire the hold if it's overdue,
    so the caller observes the post-sweep EXPIRED status, not stale HELD."""
    _backdate_hold(held_booking, seconds=120)

    response = client.get(f"/api/bookings/{held_booking.booking_ref}/")

    assert response.status_code == 200
    assert response.json()["status"] == "EXPIRED"
    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.EXPIRED


@pytest.mark.django_db
def test_seat_map_does_not_expire_fresh_holds(client, held_booking, seeded):
    """A hold whose TTL hasn't passed must NOT be touched."""
    # `held_booking` was created seconds ago with the default 120s TTL.
    response = client.get(f"/api/showtimes/{seeded.id}/seats/")
    assert response.status_code == 200

    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.HELD


@pytest.mark.django_db
def test_expire_holds_command_is_idempotent(client, held_booking):
    """Running the management command twice in a row is a no-op the second time."""
    from django.core.management import call_command

    _backdate_hold(held_booking, seconds=120)
    held_seat_ids = list(held_booking.booking_seats.values_list("seat_id", flat=True))

    # First run expires the hold.
    call_command("expire_holds")
    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.EXPIRED
    assert Seat.objects.filter(id__in=held_seat_ids, status=Seat.Status.AVAILABLE).count() == len(held_seat_ids)

    # Second run is a no-op (no overdue rows match the filter).
    call_command("expire_holds")
    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.EXPIRED


@pytest.mark.django_db
def test_expire_holds_command_releases_seats_for_background_only(client, held_booking, seeded):
    """If no read has triggered expiry yet, the command alone must still
    release the seats — the background-sweep layer is independently correct."""
    from django.core.management import call_command

    _backdate_hold(held_booking, seconds=120)
    held_seat_ids = list(held_booking.booking_seats.values_list("seat_id", flat=True))

    # No endpoint hits; only the sweep runs.
    call_command("expire_holds")

    assert Seat.objects.filter(id__in=held_seat_ids, status=Seat.Status.AVAILABLE).count() == len(held_seat_ids)
    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.EXPIRED


@pytest.mark.django_db
def test_expire_holds_command_does_not_touch_unrelated_bookings(client, held_booking, seeded):
    """A fresh HELD booking must NOT be touched by the command."""
    from django.core.management import call_command

    call_command("expire_holds")  # nothing is overdue

    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.HELD


@pytest.mark.django_db
def test_expired_hold_seats_can_be_reheld_by_a_new_booking(client, held_booking, seeded):
    """After expiry, a fresh hold request for the same seats must succeed —
    this is the user-visible payoff of the expiry sweep."""
    _backdate_hold(held_booking, seconds=120)
    held_seat_ids = list(held_booking.booking_seats.values_list("seat_id", flat=True))

    # Reading the seat map (or running the command) flips them back.
    client.get(f"/api/showtimes/{seeded.id}/seats/")

    response = client.post(
        "/api/bookings/hold/",
        data={
            "showtime_id": seeded.id,
            "seat_ids": held_seat_ids,
            "phone": "+15550009999",
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    assert Seat.objects.filter(id__in=held_seat_ids, status=Seat.Status.HELD).count() == len(held_seat_ids)
