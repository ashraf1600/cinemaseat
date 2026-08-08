"""
Tests for the payments app — focused on the contract behaviors we
recently added on top of the webhook receiver:

  * HMAC ``X-Signature`` verification (enforced when ``GATEWAY_SECRET``
    is set, silently disabled when it's empty).
  * Lenient parser: ``event_id`` + ``booking_ref`` are the only fields
    we require; every extra is silently ignored so we can roll out
    gateway-side schema additions without redeploying.
  * Replay protection: a second POST with the same ``event_id`` returns
    200 without re-applying state.
  * ``OtpWebhookView`` mirror of the same contract: HMAC + replay +
    lenient parser + best-effort code stashing on ``OtpVerification``,
    always 200.
  * ``PayView`` mints a per-attempt ``Idempotency-Key`` and forwards it
    to ``gateway.charge``.

The /pay/ + charge tests for the existing payment flow live in
``booking/tests.py`` (shared fixtures + helpers live there).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from decimal import Decimal

import pytest
from django.conf import settings
from django.core.management import call_command
from rest_framework.test import APIClient

from booking import gateway
from booking.models import Booking, OtpVerification
from catalog.models import Seat, Showtime
from payments.models import OtpDeliveryEvent, Payment, PaymentEvent


# ---------------------------------------------------------------------------
# Shared fixtures (mirrored from booking/tests.py so this file is standalone)
# ---------------------------------------------------------------------------
@pytest.fixture
def seeded(db) -> Showtime:
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


def _seed_payment_row(booking: Booking) -> Payment:
    """Create a PENDING Payment row directly (bypassing /pay/)."""
    seat_count = booking.booking_seats.count()
    base_price = booking.booking_seats.first().seat.showtime.base_price
    return Payment.objects.create(
        booking=booking,
        amount=base_price * seat_count,
        status=Payment.Status.PENDING,
    )


def _sign(body: bytes, secret: str) -> str:
    """Compute the HMAC-SHA256 signature the gateway would send.

    Mirrors the one in ``payments/signature.py`` so tests can write
    a valid signature without exporting the production helper.
    """
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _post_signed(
    client: APIClient,
    path: str,
    payload: dict,
    *,
    secret: str | None = None,
    signature: str | None = None,
) -> "object":
    """POST ``payload`` (JSON) to ``path`` with the appropriate X-Signature.

    The helper does raw bytes so the HMAC matches the exact bytes the
    view sees (DRF's ``request.body`` is the unparsed bytestream).
    """
    body = json.dumps(payload).encode("utf-8")
    if signature is None:
        if secret is not None:
            signature = _sign(body, secret)
        else:
            signature = ""
    return client.generic(
        "POST",
        path,
        data=body,
        content_type="application/json",
        HTTP_X_SIGNATURE=signature,
    )


# ===========================================================================
# PaymentWebhookView — HMAC
# ===========================================================================
@pytest.mark.django_db
def test_payment_webhook_rejects_missing_signature_when_secret_set(
    client, held_booking, monkeypatch, settings
):
    """When ``GATEWAY_SECRET`` is set, a missing/bad X-Signature -> 401."""
    settings.GATEWAY_SECRET = "topsecret"
    _seed_payment_row(held_booking)

    response = client.post(
        "/api/webhooks/payment/",
        data={
            "event_id": "evt_001",
            "booking_ref": held_booking.booking_ref,
            "status": "SUCCEEDED",
            "amount": "150.00",
        },
        format="json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_payment_webhook_rejects_bad_signature_when_secret_set(
    client, held_booking, settings
):
    settings.GATEWAY_SECRET = "topsecret"
    _seed_payment_row(held_booking)

    body = json.dumps({
        "event_id": "evt_002",
        "booking_ref": held_booking.booking_ref,
        "status": "SUCCEEDED",
        "amount": "150.00",
    }).encode("utf-8")

    response = client.generic(
        "POST",
        "/api/webhooks/payment/",
        data=body,
        content_type="application/json",
        HTTP_X_SIGNATURE="deadbeef" * 8,  # wrong but well-formed
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_payment_webhook_accepts_valid_signature_when_secret_set(
    client, held_booking, settings
):
    settings.GATEWAY_SECRET = "topsecret"
    _seed_payment_row(held_booking)

    response = _post_signed(
        client,
        "/api/webhooks/payment/",
        {
            "event_id": "evt_003",
            "booking_ref": held_booking.booking_ref,
            "status": "SUCCEEDED",
            "amount": "150.00",
            "payment_id": "pay_signed",
        },
        secret="topsecret",
    )
    assert response.status_code == 200, response.content

    payment = Payment.objects.get(booking=held_booking)
    assert payment.status == Payment.Status.SUCCEEDED


@pytest.mark.django_db
def test_payment_webhook_disabled_when_secret_empty(client, held_booking, settings):
    """Empty GATEWAY_SECRET disables verification (back-compat for dev)."""
    settings.GATEWAY_SECRET = ""
    _seed_payment_row(held_booking)

    response = client.post(
        "/api/webhooks/payment/",
        data={
            "event_id": "evt_004",
            "booking_ref": held_booking.booking_ref,
            "status": "SUCCEEDED",
            "amount": "150.00",
        },
        format="json",
    )
    assert response.status_code == 200


# ===========================================================================
# PaymentWebhookView — lenient parser + replay protection
# ===========================================================================
@pytest.mark.django_db
def test_payment_webhook_ignores_extras_silently(client, held_booking):
    """Any field we don't recognise (currency, timestamp, phone, etc.)
    must be tolerated — it's the gateway's right to add fields."""
    _seed_payment_row(held_booking)
    response = client.post(
        "/api/webhooks/payment/",
        data={
            "event_id": "evt_extras",
            "booking_ref": held_booking.booking_ref,
            "status": "SUCCEEDED",
            "amount": "150.00",
            "currency": "BDT",
            "timestamp": "2024-01-01T00:00:00Z",
            "phone": "+15550001234",
            "metadata": {"foo": "bar"},
            "random_new_field": [1, 2, 3],
        },
        format="json",
    )
    assert response.status_code == 200

    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.PAID


@pytest.mark.django_db
def test_payment_webhook_duplicate_event_id_is_idempotent(client, held_booking):
    """Two deliveries with the same event_id must converge to the same
    end state — the second one is a no-op."""
    _seed_payment_row(held_booking)

    first = client.post(
        "/api/webhooks/payment/",
        data={
            "event_id": "evt_dup",
            "booking_ref": held_booking.booking_ref,
            "status": "SUCCEEDED",
            "amount": "150.00",
        },
        format="json",
    )
    assert first.status_code == 200
    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.PAID

    # Second delivery — even with a DIFFERENT status payload, the dedup
    # guard must prevent a state change.
    second = client.post(
        "/api/webhooks/payment/",
        data={
            "event_id": "evt_dup",
            "booking_ref": held_booking.booking_ref,
            "status": "FAILED",
            "amount": "150.00",
        },
        format="json",
    )
    assert second.status_code == 200

    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.PAID  # unchanged
    payment = Payment.objects.get(booking=held_booking)
    assert payment.status == Payment.Status.SUCCEEDED

    # Exactly one event row recorded.
    assert PaymentEvent.objects.filter(payment=payment).count() == 1


@pytest.mark.django_db
def test_payment_webhook_missing_event_id_returns_200_no_state_change(
    client, held_booking
):
    """Missing event_id -> 200 + log (no DB rows touched)."""
    _seed_payment_row(held_booking)
    response = client.post(
        "/api/webhooks/payment/",
        data={"booking_ref": held_booking.booking_ref, "status": "SUCCEEDED"},
        format="json",
    )
    assert response.status_code == 200

    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.HELD  # unchanged
    payment = Payment.objects.get(booking=held_booking)
    assert payment.status == Payment.Status.PENDING
    assert PaymentEvent.objects.count() == 0


@pytest.mark.django_db
def test_payment_webhook_missing_booking_ref_returns_200_no_state_change(
    client, held_booking
):
    """Missing booking_ref -> 200 + log (no DB rows touched)."""
    _seed_payment_row(held_booking)
    response = client.post(
        "/api/webhooks/payment/",
        data={"event_id": "evt_no_booking", "status": "SUCCEEDED"},
        format="json",
    )
    assert response.status_code == 200

    held_booking.refresh_from_db()
    assert held_booking.status == Booking.Status.HELD
    payment = Payment.objects.get(booking=held_booking)
    assert payment.status == Payment.Status.PENDING
    assert PaymentEvent.objects.count() == 0


@pytest.mark.django_db
def test_payment_webhook_unknown_booking_ref_returns_200_no_state_change(
    client, held_booking
):
    """Unknown booking_ref -> 200 + log (no DB rows touched)."""
    response = client.post(
        "/api/webhooks/payment/",
        data={
            "event_id": "evt_unknown_bk",
            "booking_ref": "bk_nope",
            "status": "SUCCEEDED",
            "amount": "150.00",
        },
        format="json",
    )
    assert response.status_code == 200
    assert PaymentEvent.objects.count() == 0


# ===========================================================================
# OtpWebhookView — HMAC + lenient parser + replay + best-effort code stash
# ===========================================================================
@pytest.mark.django_db
def test_otp_webhook_happy_path_stashes_code_on_otp_row(
    client, held_booking, monkeypatch
):
    """The gateway POSTs the delivered code -> we stash it on the
    matching OtpVerification so the client UI can render it."""
    send_stub = _OtpSendSpy()
    monkeypatch.setattr(gateway, "send_otp", send_stub)

    # Create the OTP row first (as /otp/send/ would).
    response = client.post(f"/api/bookings/{held_booking.booking_ref}/otp/send/")
    assert response.status_code == 202
    otp = OtpVerification.objects.get(booking=held_booking)
    _wait_for_calls(send_stub, expected=1)

    # Now the gateway POSTs the delivered code to our webhook.
    webhook = client.post(
        "/api/webhooks/otp/",
        data={
            "event_id": "otp_evt_001",
            "ref": otp.ref,
            "code": "654321",
            "phone": "+15550001234",
        },
        format="json",
    )
    assert webhook.status_code == 200

    otp.refresh_from_db()
    assert otp.last_delivered_code == "654321"
    assert otp.last_delivered_at is not None

    # The delivery event is recorded.
    event = OtpDeliveryEvent.objects.get(event_id="otp_evt_001")
    assert event.ref == otp.ref
    assert event.code == "654321"


@pytest.mark.django_db
def test_otp_webhook_replay_is_idempotent(client, held_booking, monkeypatch):
    """Same event_id delivered twice -> 200 both times, code stashed
    only once, only one event row."""
    monkeypatch.setattr(gateway, "send_otp", _OtpSendSpy())
    client.post(f"/api/bookings/{held_booking.booking_ref}/otp/send/")
    otp = OtpVerification.objects.get(booking=held_booking)

    payload = {"event_id": "otp_evt_replay", "ref": otp.ref, "code": "111111"}
    first = client.post("/api/webhooks/otp/", data=payload, format="json")
    second = client.post("/api/webhooks/otp/", data=payload, format="json")
    assert first.status_code == 200
    assert second.status_code == 200

    otp.refresh_from_db()
    assert otp.last_delivered_code == "111111"
    assert OtpDeliveryEvent.objects.filter(event_id="otp_evt_replay").count() == 1

    # Capture the first timestamp so we can confirm the second delivery
    # didn't overwrite it.
    first_at = otp.last_delivered_at

    # Third delivery would overwrite the code if it weren't idempotent.
    time.sleep(0.01)
    payload_third = {"event_id": "otp_evt_replay", "ref": otp.ref, "code": "999999"}
    third = client.post("/api/webhooks/otp/", data=payload_third, format="json")
    assert third.status_code == 200
    otp.refresh_from_db()
    assert otp.last_delivered_code == "111111"  # unchanged
    assert otp.last_delivered_at == first_at    # unchanged


@pytest.mark.django_db
def test_otp_webhook_missing_event_id_returns_200_no_event_row(client, held_booking):
    """Missing event_id -> 200 + log; no event row created."""
    response = client.post(
        "/api/webhooks/otp/",
        data={"ref": "otp_anything", "code": "123456"},
        format="json",
    )
    assert response.status_code == 200
    assert OtpDeliveryEvent.objects.count() == 0


@pytest.mark.django_db
def test_otp_webhook_unknown_ref_is_recorded_but_does_not_crash(client, held_booking):
    """An event for an unknown ref is still recorded (audit trail) but
    no OtpVerification row is modified — we'd rather have the event in
    the table than crash and lose it."""
    response = client.post(
        "/api/webhooks/otp/",
        data={
            "event_id": "otp_evt_unknown",
            "ref": "otp_nope",
            "code": "123456",
            "booking_ref": "bk_nope",
        },
        format="json",
    )
    assert response.status_code == 200

    assert OtpDeliveryEvent.objects.filter(event_id="otp_evt_unknown").exists()
    # No matching OtpVerification row was touched.
    assert OtpVerification.objects.count() == 0


@pytest.mark.django_db
def test_otp_webhook_ignores_extra_fields(client, held_booking, monkeypatch):
    """Extra fields in the payload are silently ignored."""
    monkeypatch.setattr(gateway, "send_otp", _OtpSendSpy())
    client.post(f"/api/bookings/{held_booking.booking_ref}/otp/send/")
    otp = OtpVerification.objects.get(booking=held_booking)

    response = client.post(
        "/api/webhooks/otp/",
        data={
            "event_id": "otp_evt_extras",
            "ref": otp.ref,
            "code": "222222",
            "delivered_at": "2024-01-01T00:00:00Z",
            "carrier": "grameenphone",
            "metadata": {"campaign": "spring"},
        },
        format="json",
    )
    assert response.status_code == 200
    otp.refresh_from_db()
    assert otp.last_delivered_code == "222222"


@pytest.mark.django_db
def test_otp_webhook_rejects_bad_signature_when_secret_set(
    client, held_booking, settings
):
    settings.GATEWAY_SECRET = "topsecret"
    response = client.post(
        "/api/webhooks/otp/",
        data={"event_id": "otp_evt_bad_sig", "ref": "otp_x", "code": "1"},
        format="json",
    )
    assert response.status_code == 401


@pytest.mark.django_db
def test_otp_webhook_accepts_valid_signature_when_secret_set(
    client, held_booking, monkeypatch, settings
):
    settings.GATEWAY_SECRET = "topsecret"
    monkeypatch.setattr(gateway, "send_otp", _OtpSendSpy())
    client.post(f"/api/bookings/{held_booking.booking_ref}/otp/send/")
    otp = OtpVerification.objects.get(booking=held_booking)

    response = _post_signed(
        client,
        "/api/webhooks/otp/",
        {
            "event_id": "otp_evt_signed",
            "ref": otp.ref,
            "code": "123456",
        },
        secret="topsecret",
    )
    assert response.status_code == 200
    otp.refresh_from_db()
    assert otp.last_delivered_code == "123456"


@pytest.mark.django_db
def test_otp_webhook_falls_back_to_booking_ref_match(
    client, held_booking, monkeypatch
):
    """If the gateway omits our ``ref`` but sends ``booking_ref``, we
    still match the latest OtpVerification for that booking."""
    monkeypatch.setattr(gateway, "send_otp", _OtpSendSpy())
    client.post(f"/api/bookings/{held_booking.booking_ref}/otp/send/")
    otp = OtpVerification.objects.get(booking=held_booking)

    response = client.post(
        "/api/webhooks/otp/",
        data={
            "event_id": "otp_evt_fallback",
            "booking_ref": held_booking.booking_ref,
            "code": "333333",
        },
        format="json",
    )
    assert response.status_code == 200
    otp.refresh_from_db()
    assert otp.last_delivered_code == "333333"


# ===========================================================================
# PayView — Idempotency-Key minting
# ===========================================================================
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
    """Spin until the /charge worker thread has called the stub ``expected`` times."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(stub.calls) >= expected:
            return
        threading.Event().wait(0.01)


class _OtpSendSpy:
    """Stand-in for ``gateway.send_otp`` that records calls and returns 200.

    Slightly different from ``_Call`` in ``booking/tests.py`` because we
    want this file to be standalone (no cross-imports).
    """

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return 200


def _wait_for_calls(stub: _OtpSendSpy, expected: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(stub.calls) >= expected:
            return
        threading.Event().wait(0.01)


@pytest.mark.django_db(transaction=True)
def test_pay_forwards_idempotency_key_to_gateway_charge(
    client, held_booking, monkeypatch
):
    """The /pay/ view must mint a per-attempt Idempotency-Key and
    forward it to ``gateway.charge``. The Payment row stores the same
    value for audit."""
    stub = _ChargeCall(return_value=(200, {"payment_id": "pay_xyz"}))
    monkeypatch.setattr(gateway, "charge", stub)

    response = client.post(f"/api/bookings/{held_booking.booking_ref}/pay/")
    assert response.status_code == 202, response.content

    _wait_for_charge_calls(stub, expected=1)
    kwargs = stub.calls[0]["kwargs"]
    assert "idempotency_key" in kwargs, kwargs
    assert kwargs["idempotency_key"].startswith(f"charge-{held_booking.booking_ref}-")

    # The same key is stored on the Payment row.
    payment = Payment.objects.get(booking=held_booking)
    assert payment.idempotency_key == kwargs["idempotency_key"]


@pytest.mark.django_db(transaction=True)
def test_pay_reuses_existing_idempotency_key_on_retry(
    client, held_booking, monkeypatch
):
    """If a Payment row already exists with an idempotency_key (e.g. a
    previous /pay/ that timed out before the user retried), the retry
    must reuse the same key — so the gateway continues to dedupe."""
    existing = _seed_payment_row(held_booking)
    existing.idempotency_key = f"charge-{held_booking.booking_ref}-abc123"
    existing.save(update_fields=["idempotency_key"])

    stub = _ChargeCall(return_value=(200, {"payment_id": "pay_retry"}))
    monkeypatch.setattr(gateway, "charge", stub)

    response = client.post(f"/api/bookings/{held_booking.booking_ref}/pay/")
    assert response.status_code == 202

    _wait_for_charge_calls(stub, expected=1)
    kwargs = stub.calls[0]["kwargs"]
    assert kwargs["idempotency_key"] == existing.idempotency_key

    # Still only one Payment row.
    assert Payment.objects.filter(booking=held_booking).count() == 1


@pytest.mark.django_db(transaction=True)
def test_pay_mints_new_idempotency_key_for_fresh_payment(
    client, held_booking, monkeypatch
):
    """A brand-new Payment (no prior key) gets a freshly-minted key."""
    stub = _ChargeCall(return_value=(200, {"payment_id": "pay_new"}))
    monkeypatch.setattr(gateway, "charge", stub)

    response = client.post(f"/api/bookings/{held_booking.booking_ref}/pay/")
    assert response.status_code == 202

    _wait_for_charge_calls(stub, expected=1)
    payment = Payment.objects.get(booking=held_booking)
    assert payment.idempotency_key is not None
    assert payment.idempotency_key.startswith(f"charge-{held_booking.booking_ref}-")
    # 12 hex chars after the last dash (secrets.token_hex(6)).
    suffix = payment.idempotency_key.rsplit("-", 1)[-1]
    assert len(suffix) == 12
    int(suffix, 16)  # raises if not hex
