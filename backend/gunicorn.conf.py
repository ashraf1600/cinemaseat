"""
Gunicorn configuration.

Kept as a separate file (rather than command-line flags in the
Dockerfile) so settings can be tuned by environment variables without
re-building the image.
"""
from __future__ import annotations

import multiprocessing
import os


bind = os.environ.get("GUNICORN_BIND", f"0.0.0.0:{os.environ.get('PORT', '8000')}")
workers = int(os.environ.get("GUNICORN_WORKERS", str(min(4, multiprocessing.cpu_count() * 2 + 1))))
worker_class = os.environ.get("GUNICORN_WORKER_CLASS", "sync")
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", "5"))
loglevel = os.environ.get("LOG_LEVEL", "info").lower()

# Use /dev/shm for the worker heartbeat directory — it's tmpfs, so the
# filesystem writes never hit disk and can't be a bottleneck.
worker_tmp_dir = "/dev/shm"

accesslog = os.environ.get("GUNICORN_ACCESS_LOG", "-")
errorlog = os.environ.get("GUNICORN_ERROR_LOG", "-")

# Sensible proc_name so `docker top` shows something readable.
proc_name = "cinemaseat"
