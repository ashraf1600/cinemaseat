"""
Tests for the catalog API endpoints and the `seed_demo_data` command.

These run under `pytest` against an in-memory sqlite database
(see `backend/config/settings_test.py` and `backend/pytest.ini`).
"""
from __future__ import annotations

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient


@pytest.fixture
def seeded_client(db) -> APIClient:
    """Seed the demo dataset and return a DRF APIClient."""
    call_command("seed_demo_data", "--reset")
    return APIClient()


@pytest.mark.django_db
def test_seed_demo_data_is_idempotent(db) -> None:
    """Re-running the seeder must not duplicate data."""
    call_command("seed_demo_data")
    call_command("seed_demo_data")

    from catalog.models import Movie, Seat, Showtime, Theatre

    assert Movie.objects.count() == 3
    assert Theatre.objects.count() == 2
    # 4 days x 2 theatres = 8 showtimes
    assert Showtime.objects.count() == 8
    # 40 seats x 8 showtimes
    assert Seat.objects.count() == 40 * 8


@pytest.mark.django_db
def test_showtime_seats_returns_documented_shape(seeded_client) -> None:
    """GET /api/showtimes/<id>/seats/ must return the exact documented shape."""
    from catalog.models import Showtime

    showtime = Showtime.objects.first()
    assert showtime is not None  # seed should have created at least one

    response = seeded_client.get(f"/api/showtimes/{showtime.id}/seats/")
    assert response.status_code == 200
    payload = response.json()

    # Documented contract: a raw list, not a paginated envelope.
    assert isinstance(payload, list)
    assert len(payload) == 40  # rows A-D x seats 1-10

    # Every element must have exactly these four keys, in this order.
    sample = payload[0]
    assert list(sample.keys()) == ["id", "label", "status", "price"]
    assert isinstance(sample["id"], int)
    assert isinstance(sample["label"], str)
    assert sample["status"] == "AVAILABLE"
    # `price` must come from the parent showtime's `base_price` (450.00 in the seeder).
    assert float(sample["price"]) == 450.00

    # Labels should cover all 40 expected combinations.
    labels = {seat["label"] for seat in payload}
    expected = {f"{row}{num}" for row in "ABCD" for num in range(1, 11)}
    assert labels == expected


@pytest.mark.django_db
def test_showtime_list_filters_by_movie_id(seeded_client) -> None:
    """`?movie_id=` should narrow the result set correctly."""
    from catalog.models import Movie, Showtime

    first_movie = Movie.objects.first()
    response = seeded_client.get(f"/api/showtimes/?movie_id={first_movie.id}")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)

    # Every returned showtime must belong to the requested movie.
    assert payload, "expected at least one showtime for the first movie"
    for entry in payload:
        assert entry["movie"] == first_movie.id

    # Sanity check vs. the unfiltered count.
    unfiltered = seeded_client.get("/api/showtimes/").json()
    assert len(unfiltered) == Showtime.objects.count()
    assert len(payload) <= len(unfiltered)


@pytest.mark.django_db
def test_movie_list_returns_all_movies(seeded_client) -> None:
    """GET /api/movies/ should return every seeded movie."""
    response = seeded_client.get("/api/movies/")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 3
    titles = {m["title"] for m in payload}
    assert titles == {"The Last Reel", "Neon Skyline", "Echoes of Tomorrow"}


@pytest.mark.django_db
def test_showtime_seats_404_for_unknown_id(seeded_client) -> None:
    """Unknown showtime id must return 404, not an empty list."""
    response = seeded_client.get("/api/showtimes/999999/seats/")
    assert response.status_code == 404