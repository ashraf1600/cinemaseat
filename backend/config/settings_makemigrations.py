"""
Throwaway settings module used ONLY for `makemigrations`.

Production / migrate commands keep using `config.settings`. This file
swaps the database engine to sqlite so Django can import models without
psycopg2 installed. The generated migration files are engine-agnostic
and run unchanged against PostgreSQL.
"""
from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
