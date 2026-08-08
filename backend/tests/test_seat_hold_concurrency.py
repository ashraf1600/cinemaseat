import threading

from django.db import connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from catalog.models import Movie, Theatre, Showtime, Seat
from booking.models import Booking

# SQLite has a single-writer lock at the file level: 100 threads fighting
# over one row produces spurious "database is locked" failures that have
# nothing to do with our row-level locking. The fix is hardware, not code —
# run the suite against PostgreSQL (docker-compose) and only there does
# this test actually exercise the row-lock guarantee.
# The skipif is applied centrally in backend/conftest.py — both this
# class (matches the "Concurrency" suffix) and any test using
# ``@pytest.mark.django_db(transaction=True)`` (which spawns a worker
# thread that touches the DB) are skipped when the configured engine
# is SQLite.
class SeatHoldConcurrencyTest(TransactionTestCase):
    """
    আসল threads দিয়ে একই সিটে একসাথে অনেকগুলো hold রিকোয়েস্ট পাঠায় —
    এটা প্রমাণ করে select_for_update() সত্যিই real contention এর নিচে
    কাজ করছে, শুধু sequential logic না। TransactionTestCase দরকার
    (normal TestCase না) কারণ আমাদের প্রতিটা thread এর নিজের DB
    connection লাগবে, একটা shared wrapped transaction না।
    """

    def setUp(self):
        movie = Movie.objects.create(title="Brand New Day", duration_minutes=140)
        theatre = Theatre.objects.create(name="CUET Cineplex", location="Chattogram")
        self.showtime = Showtime.objects.create(
            movie=movie, theatre=theatre, starts_at="2026-08-08T20:00:00Z", base_price=450
        )
        self.seat = Seat.objects.create(showtime=self.showtime, label="F12", status="AVAILABLE")

    def _fire_hold(self, results, index):
        client = APIClient()
        try:
            response = client.post(
                "/api/bookings/hold/",
                {
                    "showtime_id": self.showtime.id,
                    "seat_ids": [self.seat.id],
                    "phone": f"+8801700000{index:03d}",
                },
                format="json",
            )
            results[index] = response.status_code
        finally:
            # প্রতিটা thread এর connection বন্ধ করে দিতে হবে, নাহলে
            # ১০০টা thread ১০০টা DB connection leak করবে
            connections.close_all()

    def test_100_concurrent_holds_exactly_one_succeeds(self):
        N = 100
        results = [None] * N
        threads = [threading.Thread(target=self._fire_hold, args=(results, i)) for i in range(N)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        success_count = results.count(201)
        rejected_count = results.count(409)

        assert success_count == 1, f"Expected exactly 1 success, got {success_count}: {results}"
        assert rejected_count == N - 1, f"Expected {N - 1} rejections, got {rejected_count}"

        self.seat.refresh_from_db()
        assert self.seat.status == "HELD"
        assert Booking.objects.filter(bookingseat__seat=self.seat).count() == 1