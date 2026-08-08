"""
Booking models: the reservation lifecycle, the seat↔booking join table,
and OTP verification.
"""
from __future__ import annotations

from django.db import models


class Booking(models.Model):
    class Status(models.TextChoices):
        HELD = "HELD", "Held"
        PAID = "PAID", "Paid"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    booking_ref = models.CharField(max_length=64, unique=True)
    phone = models.CharField(max_length=32)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.HELD,
    )
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "expires_at"]),
            models.Index(fields=["phone"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.booking_ref} ({self.status})"


class BookingSeat(models.Model):
    """Many-to-many join between a booking and the seats it covers."""

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="booking_seats")
    seat = models.ForeignKey("catalog.Seat", on_delete=models.PROTECT, related_name="booking_seats")

    class Meta:
        constraints = [
            # One seat can only be claimed by one active booking row.
            models.UniqueConstraint(fields=["seat"], name="uniq_seat_in_booking"),
            models.UniqueConstraint(fields=["booking", "seat"], name="uniq_booking_seat"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"booking={self.booking_id} seat={self.seat_id}"


class OtpVerification(models.Model):
    class Status(models.TextChoices):
        SENT = "SENT", "Sent"
        VERIFIED = "VERIFIED", "Verified"
        EXPIRED = "EXPIRED", "Expired"

    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name="otp")
    ref = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.SENT,
    )

    class Meta:
        ordering = ["-id"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"OTP {self.ref} ({self.status})"
