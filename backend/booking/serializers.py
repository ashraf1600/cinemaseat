"""
Booking serializers — request validation and response shapes for the
hold and booking-detail endpoints.
"""
from __future__ import annotations

from rest_framework import serializers

from catalog.models import Seat

from .models import OtpVerification


class HoldRequestSerializer(serializers.Serializer):
    """Request body for `POST /api/bookings/hold/`."""

    showtime_id = serializers.IntegerField(min_value=1)
    seat_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
    )
    phone = serializers.CharField(max_length=32, trim_whitespace=True)

    def validate_seat_ids(self, value: list[int]) -> list[int]:
        # Reject duplicates up-front so the DB layer doesn't have to.
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate seat ids in request.")
        return value


class OtpVerifyRequestSerializer(serializers.Serializer):
    """Request body for `POST /api/bookings/<ref>/otp/verify/`."""

    code = serializers.CharField(min_length=1, max_length=32, trim_whitespace=True)


def build_hold_response(booking, seats: list[Seat]) -> dict:
    """Construct the documented hold response payload."""
    return {
        "booking_id": booking.booking_ref,
        "status": booking.status,
        "expires_at": booking.expires_at,
        "seats": [{"id": s.id, "label": s.label} for s in seats],
    }


def build_booking_detail_response(booking, seats: list[Seat]) -> dict:
    """Construct the documented GET /api/bookings/<ref>/ payload."""
    return {
        "booking_id": booking.booking_ref,
        "status": booking.status,
        "expires_at": booking.expires_at,
        "seats": [{"id": s.id, "label": s.label} for s in seats],
    }


def build_otp_response(booking, otp: OtpVerification) -> dict:
    """Construct the documented OTP send/verify response payload."""
    return {
        "booking_id": booking.booking_ref,
        "otp_ref": otp.ref,
        "status": otp.status,
    }
