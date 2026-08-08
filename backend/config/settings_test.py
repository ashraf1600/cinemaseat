"""
Test settings: same as `config.settings` but uses a shared file-backed
sqlite and drops middleware that requires optional third-party packages.
Used automatically by `pytest.ini`.

The DB is a tempfile on disk (not `:memory:`) so worker threads on their
own connections can see writes made by the test's connection. An
in-memory DB is per-connection, which would silently break the
background-charge worker used by the /pay/ endpoint.
"""
import tempfile

from .settings import *  # noqa: F401,F403

# pytest-django will create/destroy this file per test session.
_TEST_DB_PATH = tempfile.NamedTemporaryFile(
    suffix=".sqlite3", delete=False
).name

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _TEST_DB_PATH,
    }
}

# Don't try to compress/serve static files during tests.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# Strip middleware whose backing packages may not be installed in CI.
MIDDLEWARE = [m for m in MIDDLEWARE if "whitenoise" not in m.lower()]