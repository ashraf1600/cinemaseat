"""
Read-only catalog API views.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import generics

from booking.expiry import expire_overdue_holds

from .models import Movie, Seat, Showtime
from .serializers import MovieSerializer, SeatMapSerializer, ShowtimeSerializer


class MovieListView(generics.ListAPIView):
    """GET /api/movies/ — list every movie."""

    queryset = Movie.objects.all().order_by("title")
    serializer_class = MovieSerializer


class ShowtimeListView(generics.ListAPIView):
    """
    GET /api/showtimes/?movie_id=<id>

    Returns all showtimes, optionally filtered by `movie_id`.
    """

    serializer_class = ShowtimeSerializer

    def get_queryset(self):
        qs = Showtime.objects.select_related("movie", "theatre").order_by("starts_at")
        movie_id = self.request.query_params.get("movie_id")
        if movie_id:
            qs = qs.filter(movie_id=movie_id)
        return qs


class ShowtimeSeatsView(generics.ListAPIView):
    """
    GET /api/showtimes/{id}/seats/

    Returns the documented seat-map shape:
        [{ "id": 12, "label": "F12", "status": "AVAILABLE", "price": 450 }, ...]

    Before returning data, runs the expiry sweep so any HELD booking whose
    TTL has passed is flipped to EXPIRED and its seats are released — the
    caller sees an up-to-the-millisecond seat map.
    """

    serializer_class = SeatMapSerializer

    def get_queryset(self):
        # Expire anything stale for *every* showtime so a single seat-map
        # read also cleans up holds on unrelated showtimes the caller is
        # implicitly aware of. Cheap on the index (status, expires_at).
        expire_overdue_holds()
        showtime = get_object_or_404(Showtime, pk=self.kwargs["pk"])
        return Seat.objects.filter(showtime=showtime).order_by("label")