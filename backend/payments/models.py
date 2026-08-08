"""
Payment models: the payment itself, the gateway↔system event log, and
the JSON payload needed for replay/debugging.
"""
from __future__ import annotations

from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"

    booking = models.OneToOneField(
        "booking.Booking",
        on_delete=models.PROTECT,
        related_name="payment",
    )
    # `payment_id` is the gateway's identifier — we only know it once the
    # upstream call succeeds, so it's nullable. Unique when present.
    payment_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Payment(booking={self.booking_id}, {self.status}, {self.amount})"


class PaymentEvent(models.Model):
    """
    Append-only log of every webhook/event from the payment gateway.
    `event_id` is the idempotency key — duplicates are rejected at the DB.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"

    event_id = models.CharField(max_length=128, unique=True)
    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="events",
    )
    status = models.CharField(max_length=16, choices=Status.choices)
    received_at = models.DateTimeField(auto_now_add=True)
    # Full JSON body for debugging / replay.
    raw_payload = models.JSONField()

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["payment", "received_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"PaymentEvent({self.event_id}, {self.status})"
