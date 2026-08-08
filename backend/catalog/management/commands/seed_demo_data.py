"""
Seed the database with a small, deterministic demo dataset so the API has
something to return out of the box.

Usage:
    python manage.py seed_demo_data            # idempotent, safe to re-run
    python manage.py seed_demo_data --reset    # wipe catalog tables first

Creates:
    * 3 movies
    * 2 theatres
    * 8 showtimes (each theatre x each of 4 days, mixed movies)
    * 40 seats per showtime (rows A-D, seats 1-10)
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from catalog.models import Movie, Seat, Showtime, Theatre


SEED_MOVIES = [
    {"title": "The Last Reel", "duration_minutes": 124},
    {"title": "Neon Skyline", "duration_minutes": 108},
    {"title": "Echoes of Tomorrow", "duration_minutes": 142},
]

SEED_THEATRES = [
    {"name": "CinemaStar Downtown", "location": "123 Main St"},
    {"name": "CinemaStar Riverside", "location": "47 River Rd"},
]

# A 4-letter row x 10-seat grid -> 40 seats per showtime.
ROW_LETTERS = ["A", "B", "C", "D"]
SEAT_NUMBERS = range(1, 11)  # 1..10 inclusive


class Command(BaseCommand):
    help = "Populate the catalog with a small, deterministic demo dataset."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing movies/theatres/showtimes/seats before seeding.",
        )

    def handle(self, *args, **options) -> None:
        with transaction.atomic():
            if options["reset"]:
                self.stdout.write("Wiping existing catalog data…")
                Seat.objects.all().delete()
                Showtime.objects.all().delete()
                Theatre.objects.all().delete()
                Movie.objects.all().delete()

            movies = [Movie.objects.get_or_create(**m)[0] for m in SEED_MOVIES]
            theatres = [Theatre.objects.get_or_create(**t)[0] for t in SEED_THEATRES]

            base = timezone.now().replace(hour=19, minute=0, second=0, microsecond=0) + timedelta(days=1)
            created_showtimes = 0
            created_seats = 0

            for day_offset in range(4):
                starts_at = base + timedelta(days=day_offset)
                for theatre in theatres:
                    # Alternate which movie plays at each slot so listings have variety.
                    movie = movies[(day_offset + theatres.index(theatre)) % len(movies)]
                    showtime, was_new = Showtime.objects.get_or_create(
                        movie=movie,
                        theatre=theatre,
                        starts_at=starts_at,
                        defaults={"base_price": "450.00"},
                    )
                    if was_new:
                        created_showtimes += 1
                        # 4 rows x 10 seats = 40 per showtime
                        seats = [
                            Seat(
                                showtime=showtime,
                                label=f"{row}{num}",
                                status=Seat.Status.AVAILABLE,
                            )
                            for row in ROW_LETTERS
                            for num in SEAT_NUMBERS
                        ]
                        Seat.objects.bulk_create(seats)
                        created_seats += len(seats)

        self.stdout.write(self.style.SUCCESS(
            f"Seed complete: {len(movies)} movies, {len(theatres)} theatres, "
            f"{created_showtimes} new showtimes, {created_seats} new seats."
        ))