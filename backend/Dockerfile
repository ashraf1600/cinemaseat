# syntax=docker/dockerfile:1.7
#
# CinemaSeat backend image.
#
# Base: python:3.11-slim (Debian Bookworm, glibc). Slim is small but still
# gives us the system libs psycopg2-binary needs at runtime, so we do not
# have to install libpq or gcc.
#
# Layout:
#   * builder stage  -> installs Python deps into a venv we can copy
#   * runtime stage  -> non-root user, copies the venv + project, runs
#                       entrypoint.sh which migrate/seed/loop/exec gunicorn
#
# Why two stages: keeps the final image small (no pip cache, no compilers)
# and keeps secrets out of the final layer.
# ---------------------------------------------------------------------------

ARG PYTHON_VERSION=3.11
ARG PORT=8000

FROM python:${PYTHON_VERSION}-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build deps first so they cache in their own layer.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# Create a venv we can copy wholesale into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
 && pip install -r /app/requirements.txt \
 && pip install "gunicorn>=21.2"

# ---------------------------------------------------------------------------

FROM python:${PYTHON_VERSION}-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DJANGO_SETTINGS_MODULE=config.settings \
    PATH="/opt/venv/bin:${PATH}"

# Runtime libs only: libpq for psycopg2-binary.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

# Non-root user. UID 10001 matches common k8s runAsUser conventions.
RUN groupadd --system --gid 10001 cinemaseat \
 && useradd  --system --uid 10001 --gid cinemaseat --home /app --shell /bin/bash cinemaseat

WORKDIR /app

# Bring the venv across from the builder.
COPY --from=builder /opt/venv /opt/venv

# Project files. Copy entrypoint first so we can chmod it before switching user.
COPY --chown=cinemaseat:cinemaseat entrypoint.sh /app/entrypoint.sh
COPY --chown=cinemaseat:cinemaseat . /app

RUN chmod +x /app/entrypoint.sh

USER cinemaseat

EXPOSE 8000

# Healthcheck uses curl (installed above) — never calls the gateway.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/health/ || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--threads", "2", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
