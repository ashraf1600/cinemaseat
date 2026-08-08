"""
``manage.py expire_holds`` — release any HELD bookings whose TTL has
passed. Designed to be run in a tight loop from Docker Compose:

    while true; do python manage.py expire_holds; sleep 1; done

Idempotent: calling twice in a row is a no-op the second time.
Exit code is always 0; the loop should never crash. Any unexpected
exception is logged and swallowed so a transient DB blip can't take
the sweep down.
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from booking.expiry import expire_overdue_holds

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Expire HELD bookings whose TTL has passed and release their seats."

    def handle(self, *args, **options) -> None:
        try:
            count = expire_overdue_holds()
        except Exception:  # noqa: BLE001 — defensive; the sweeper must never die
            logger.exception("expire_holds sweep crashed")
            return

        if count:
            self.stdout.write(self.style.SUCCESS(f"Expired {count} overdue hold(s)."))
        else:
            self.stdout.write("No overdue holds.")
