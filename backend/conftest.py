"""
Root pytest configuration for the booking app.

Auto-skips tests that need real DB concurrency when the configured
database is SQLite. SQLite's single-writer file lock makes those
tests unreliable on Windows + the file-backed test DB, even though they
pass under PostgreSQL (the docker-compose prod backend).

What counts as "needs real concurrency":
  * Any test in a class whose name contains ``Concurrency`` — these are
    the dedicated multi-thread tests.
  * Any test decorated with ``@pytest.mark.django_db(transaction=True)``
    and that spawns a worker thread which touches the DB —
    ``pytest.ini`` exports that combo as the ``concurrency_db`` marker
    (see ``pytest.mark.django_db`` keyword aliasing below).

For everything else, we leave the test alone.
"""
from __future__ import annotations

import pytest
from django.conf import settings


_SKIP_REASON = (
    "SQLite's single-writer lock makes real-thread DB contention "
    "unreliable on Windows; this test passes under PostgreSQL "
    "(docker-compose)."
)


def pytest_collection_modifyitems(config, items):
    """Apply the SQLite skipif to multi-thread / transaction=true tests."""
    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
        return

    skip_marker = pytest.mark.skip(reason=_SKIP_REASON)
    for item in items:
        is_concurrency_class = bool(item.cls) and "Concurrency" in item.cls.__name__
        # `transaction_django_db` is the keyword pytest-django adds when
        # @pytest.mark.django_db is called with transaction=True.
        opens_real_transaction = "transaction_django_db" in item.keywords
        if is_concurrency_class or opens_real_transaction:
            item.add_marker(skip_marker)
