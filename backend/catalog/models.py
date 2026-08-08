"""
Catalog domain models: movies, theatres, showtimes, seats.
"""
from __future__ import annotations

from django.db import models


class Movie(models.Model):
    title = models.CharField(max_length=255)
    duration_minutes = models.PositiveIntegerField()

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.title} ({self.duration_minutes}m)"


class Theatre(models.Model):
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Theatres"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} — {self.location}"


class Showtime(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.PROTECT, related_name="showtimes")
    theatre = models.ForeignKey(Theatre, on_delete=models.PROTECT, related_name="showtimes")
    starts_at = models.DateTimeField()
    # Stored as decimal so we never lose precision on currency math.
    base_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["starts_at"]
        indexes = [
            models.Index(fields=["movie", "starts_at"]),
            models.Index(fields=["theatre", "starts_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.movie.title} @ {self.theatre.name} — {self.starts_at:%Y-%m-%d %H:%M}"


class Seat(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        HELD = "HELD", "Held"
        BOOKED = "BOOKED", "Booked"

    showtime = models.ForeignKey(Showtime, on_delete=models.CASCADE, related_name="seats")
    label = models.CharField(max_length=16)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )

    class Meta:
        ordering = ["showtime", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["showtime", "label"],
                name="uniq_seat_per_showtime",
            ),
        ]
        indexes = [
            models.Index(fields=["showtime", "status"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.showtime_id}/{self.label}"
