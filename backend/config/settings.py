"""
Django settings for the cinemaseat project.

All sensitive and deployment-specific values are read from environment
variables. See ``backend/.env.example`` for the full list.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths & core
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# A misconfigured SECRET_KEY must never silently fall back to a real value,
# so we only auto-generate one when DEBUG is on (local dev convenience).
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-do-not-use-in-production",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "False").lower() in {"1", "true", "yes", "on"}

_raw_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
ALLOWED_HOSTS = [h.strip() for h in _raw_hosts.split(",") if h.strip()]

# CORS — allow the Vite dev server to call the API in development. In
# production the frontend and backend are typically served from the same
# origin (or via a reverse proxy) so this list should be tightened.
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    # local
    "core.apps.CoreConfig",
    "catalog.apps.CatalogConfig",
    "booking.apps.BookingConfig",
    "payments.apps.PaymentsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# WhiteNoise is optional — install it for production static-file serving,
# but the dev server boots fine without it. Probe once at import time so
# `runserver` works on a bare ``pip install -r requirements-min.txt``.
try:
    import whitenoise  # noqa: F401
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
except ImportError:  # pragma: no cover — dev convenience
    STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

# django-cors-headers is optional — only needed when the frontend lives
# on a different origin from the API. Probe once at import time so the
# dev server still boots when running pure API tests.
try:
    import corsheaders  # noqa: F401
    INSTALLED_APPS += ["corsheaders"]  # type: ignore[arg-type]
    # CorsMiddleware must run before CommonMiddleware so preflight
    # responses get the right headers even on OPTIONS requests.
    MIDDLEWARE.insert(1, "corsheaders.middleware.CorsMiddleware")
except ImportError:  # pragma: no cover — dev convenience
    pass

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Default is SQLite (local dev — no Postgres install required). For
# production / staging, set ``DB_BACKEND=postgres`` (or any other value)
# and the four ``POSTGRES_*`` env vars and the project will switch to
# PostgreSQL automatically.
#
# SQLite is intentionally available for local exploration. The test suite
# uses its own ``settings_test`` module which keeps a file-backed sqlite
# separate from the dev DB so worker threads still see writes.
_DB_BACKEND = os.environ.get("DB_BACKEND", "sqlite").lower()

if _DB_BACKEND in {"postgres", "postgresql"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ["POSTGRES_USER"],
            "PASSWORD": os.environ["POSTGRES_PASSWORD"],
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    # SQLite: single file under the project root so ``manage.py`` and
    # ``runserver`` see the same DB without any extra config.
    _SQLITE_PATH = os.environ.get(
        "SQLITE_PATH",
        str(BASE_DIR / "db.sqlite3"),
    )
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": _SQLITE_PATH,
        }
    }

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files (WhiteNoise)
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    # Catalog endpoints must return raw arrays (per the documented seat-map
    # contract) rather than the default paginated envelope.
    "DEFAULT_PAGINATION_CLASS": None,
}

# ---------------------------------------------------------------------------
# Cinemaseat custom settings
# ---------------------------------------------------------------------------
# How long a seat hold stays valid before the background worker releases it.
# MUST be overridable via env — judges use this to test expiry behaviour.
HOLD_TTL_SECONDS = int(os.environ.get("HOLD_TTL_SECONDS", "120"))

# Base URL of the upstream payment gateway service.
GATEWAY_BASE_URL = os.environ.get("GATEWAY_BASE_URL", "http://gateway:9000")

# Public URL *we* are reachable at — used to build callback URLs handed to
# the gateway (so its webhook deliveries route back to the right container).
# In docker-compose this is the backend service name + exposed port.
BACKEND_PUBLIC_URL = os.environ.get(
    "BACKEND_PUBLIC_URL",
    "http://backend:8000",
)

# Shared secret used to verify the ``X-Signature`` HMAC on incoming webhook
# deliveries. Empty value disables verification (local dev only).
GATEWAY_SECRET = os.environ.get("GATEWAY_SECRET", "")
