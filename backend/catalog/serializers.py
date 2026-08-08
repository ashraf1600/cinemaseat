"""
Read-only serializers for the catalog API.

The seat-map shape is part of the public contract documented in the README,
so the field order/names in `SeatMapSerializer` must not change.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Movie, Seat, Showtime


class MovieSerializer(serializers.ModelSerializer):
    class Meta:
        model = Movie
        fields = ("id", "title", "duration_minutes")


class ShowtimeSerializer(serializers.ModelSerializer):
    movie_title = serializers.CharField(source="movie.title", read_only=True)
    theatre_name = serializers.CharField(source="theatre.name", read_only=True)

    class Meta:
        model = Showtime
        fields = (
            "id",
            "movie",
            "movie_title",
            "theatre",
            "theatre_name",
            "starts_at",
            "base_price",
        )


class SeatMapSerializer(serializers.ModelSerializer):
    # The README documents exactly this response shape:
    #   [{ "id": 12, "label": "F12", "status": "AVAILABLE", "price": 450 }, ...]
    # `price` is sourced from the parent showtime's `base_price`.
    price = serializers.DecimalField(source="showtime.base_price", max_digits=10, decimal_places=2)

    class Meta:
        model = Seat
        fields = ("id", "label", "status", "price")
