"""
Hold expiry — flips HELD bookings whose TTL has passed back to EXPIRED
and releases their seats.

Single source of truth used by:
  * the seat-map endpoint (``catalog.views.ShowtimeSeatsView``)
  * the booking-detail endpoint (``booking.views.BookingDetailView``)
  * the ``expire_holds`` management command (run from a Docker Compose loop)

Why a dedicated helper?
  The expiry semantics are subtle — they touch two tables atomically and
  must not race the hold endpoint. Centralising the logic means a single
  locking strategy is enforced everywhere a hold can be observed.

Locking strategy:
  * Outer ``transaction.atomic()`` — the entire sweep is one transaction.
  * ``select_for_update().filter(status=HELD, expires_at<now)`` locks every
    overdue booking row in one statement, in primary-key order.
  * For each expired booking, a second ``select_for_update`` on the
    related ``Seat`` rows releases them. The seat lock is what stops a
    racing hold from re-claiming a seat while we flip its booking.

Idempotency: calling the function twice in a row is a no-op the second
time — there are no rows matching the overdue filter.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from catalog.models import Seat
from .models import Booking, BookingSeat

logger = logging.getLogger(__name__)


def expire_overdue_holds() -> int:
    """Expire every HELD booking whose ``expires_at`` is in the past.

    Returns the number of bookings flipped from HELD to EXPIRED.
    """
    now = timezone.now()

    with transaction.atomic():
        overdue_ids = list(
            Booking.objects
            .select_for_update()
            .filter(status=Booking.Status.HELD, expires_at__lt=now)
            .values_list("id", flat=True)
        )

        if not overdue_ids:
            return 0

        # Lock the related seat rows in ascending id order to keep
        # this consistent with the hold endpoint's deadlock-free lock
        # ordering.
        seat_ids = list(
            Seat.objects
            .filter(booking_seats__booking_id__in=overdue_ids)
            .values_list("id", flat=True)
        )

        Seat.objects.filter(id__in=seat_ids).select_for_update().order_by("id")

        # Flip the bookings first, then release the seats. Doing it
        # in this order means a concurrent observer either sees the
        # booking as still HELD (and respects its holds), or sees
        # EXPIRED and the seats already AVAILABLE.
        Booking.objects.filter(id__in=overdue_ids).update(status=Booking.Status.EXPIRED)
        Seat.objects.filter(id__in=seat_ids).update(status=Seat.Status.AVAILABLE)

        # Drop the now-stale ``BookingSeat`` rows. ``BookingSeat`` has a
        # ``UNIQUE (seat)`` constraint — one seat can only ever be
        # claimed by one booking row at a time. If we kept the join
        # rows here, no future booking could re-hold the same seat
        # until the EXPIRED booking was hard-deleted. Deleting the
        # join rows is the correct semantic: an EXPIRED hold releases
        # its seats fully.
        deleted_links, _ = BookingSeat.objects.filter(booking_id__in=overdue_ids).delete()

        logger.info(
            "Expired %d overdue hold(s), released %d seat(s), "
            "removed %d booking-seat link(s)",
            len(overdue_ids), len(seat_ids), deleted_links,
        )
        return len(overdue_ids)
