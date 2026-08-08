"""Tests for the OTP-delivery surfacing in the booking detail response.

The gateway pushes a delivery receipt to ``/api/webhooks/otp/`` after it
has actually delivered the SMS. That receipt writes ``last_delivered_code``
and ``last_delivered_at`` onto the ``OtpVerification`` row.

The frontend polls ``GET /api/bookings/<ref>/`` to autofill the code in
the OTP input, so the serializer MUST expose those two fields.

These tests do not depend on the ``held_booking`` / ``seeded`` fixtures
from ``tests.py`` because fixtures defined in a sibling test module are
not visible to this file. We build the booking inline using the same
model helpers.
"""

from __future__ import annotations

import json

import pytest
from django.utils import timezone

from booking.models import Booking, OtpVerification
from catalog.models import Movie, Seat, Showtime, Theatre


def _make_held_booking(client):
    """Create a HELD booking by going through the real POST /bookings/hold/.

    Going through the public endpoint exercises the same code path
    the rest of the suite uses, so we don't have to second-guess
    model defaults like `booking_ref` generation.
    """
    # Seed the catalog via the public endpoint as well.
    resp = client.get("/api/showtimes/")
    if resp.status_code == 200 and resp.json():
        showtimes = resp.json()
        showtime_id = showtimes[0]["id"]
    else:
        # No showtimes — create one and list its seats.
        movie = Movie.objects.create(title="Test Movie", duration_minutes=120)
        theatre = Theatre.objects.create(name="Theatre 1", location="Dhaka")
        showtime = Showtime.objects.create(
            movie=movie, theatre=theatre, starts_at=timezone.now(), base_price=100
        )
        Seat.objects.create(showtime=showtime, label="A1")
        showtime_id = showtime.id

    seats = client.get(f"/api/showtimes/{showtime_id}/seats/").json()
    held_response = client.post(
        "/api/bookings/hold/",
        data=json.dumps(
            {"showtime_id": showtime_id, "seat_ids": [seats[0]["id"]], "phone": "+8801700000000"}
        ),
        content_type="application/json",
    )
    assert held_response.status_code == 201, held_response.content
    return Booking.objects.get(booking_ref=held_response.json()["booking_id"])


@pytest.mark.django_db
def test_booking_detail_exposes_empty_otp_fields_when_no_otp_sent(client):
    """Before /otp/send/ runs, the detail returns empty strings/nulls."""
    booking = _make_held_booking(client)

    response = client.get(f"/api/bookings/{booking.booking_ref}/")

    assert response.status_code == 200
    body = response.json()
    assert body["last_delivered_code"] == ""
    assert body["last_delivered_at"] is None


@pytest.mark.django_db
def test_booking_detail_exposes_last_delivered_code_after_webhook(client):
    """After /api/webhooks/otp/ pushes a delivery receipt, the field is filled."""
    booking = _make_held_booking(client)

    # /otp/send/ would normally create the OtpVerification row. We
    # simulate that here so we can then post the delivery webhook.
    OtpVerification.objects.create(booking=booking, ref="otp_test_123")

    delivery_payload = {
        "event_id": "evt_test_1",
        "ref": "otp_test_123",
        "status": "DELIVERED",
        "code": "9876",
    }
    webhook = client.post(
        "/api/webhooks/otp/",
        data=json.dumps(delivery_payload),
        content_type="application/json",
    )
    assert webhook.status_code == 200, webhook.content

    response = client.get(f"/api/bookings/{booking.booking_ref}/")
    assert response.status_code == 200
    body = response.json()
    assert body["last_delivered_code"] == "9876"
    assert body["last_delivered_at"] is not None


@pytest.mark.django_db
def test_booking_detail_code_overwrites_on_subsequent_delivery(client):
    """Resending an OTP produces a new code; the surface reflects the latest."""
    booking = _make_held_booking(client)
    otp = OtpVerification.objects.create(booking=booking, ref="otp_resend")

    client.post(
        "/api/webhooks/otp/",
        data=json.dumps(
            {
                "event_id": "evt_resend_1",
                "ref": "otp_resend",
                "status": "DELIVERED",
                "code": "1111",
            }
        ),
        content_type="application/json",
    )
    client.post(
        "/api/webhooks/otp/",
        data=json.dumps(
            {
                "event_id": "evt_resend_2",
                "ref": "otp_resend",
                "status": "DELIVERED",
                "code": "2222",
            }
        ),
        content_type="application/json",
    )

    otp.refresh_from_db()
    assert otp.last_delivered_code == "2222"

    body = client.get(f"/api/bookings/{booking.booking_ref}/").json()
    assert body["last_delivered_code"] == "2222"
