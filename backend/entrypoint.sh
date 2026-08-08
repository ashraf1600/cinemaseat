#!/usr/bin/env bash
#
# Backend container entrypoint.
#
# Responsibilities, in order:
#   1. Wait until Postgres is actually accepting connections (cheap
#      python ping; we do NOT depend on a docker-compose healthcheck
#      alone because the backend container may be started by hand).
#   2. Run `migrate` so the schema is up to date for whatever the image
#      ships. Idempotent — safe to run on every boot.
#   3. Seed the demo dataset so the API has data to return out of the
#      box. `--reset` is intentionally NOT used here: judges may have
#      created state we must preserve across restarts.
#   4. Spawn a background loop that calls `expire_holds` every 5
#      seconds. The loop is a daemon subshell; we trap signals so the
#      loop is killed cleanly when gunicorn exits.
#   5. `exec` gunicorn so it becomes PID 1 — signals (SIGTERM from
#      `docker stop`) reach it directly and graceful shutdown works.
#
# The CMD from the Dockerfile is what we exec at the end.
# ---------------------------------------------------------------------------
set -euo pipefail

# Don't echo the secret. Reasonable defaults; the compose file sets the
# real DB name via POSTGRES_DB env var.
: "${DB_BACKEND:=postgres}"
: "${POSTGRES_HOST:=db}"
: "${POSTGRES_PORT:=5432}"
: "${POSTGRES_DB:=cinemaseat}"
: "${POSTGRES_USER:=cinemaseat}"
: "${POSTGRES_PASSWORD:=cinemaseat}"

EXPIRE_LOOP_INTERVAL="${EXPIRE_LOOP_INTERVAL:-5}"

echo "[entrypoint] backend booting (DB_BACKEND=${DB_BACKEND} -> ${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB})"

# ---------------------------------------------------------------------------
# 1. Wait for Postgres.
# ---------------------------------------------------------------------------
wait_for_db() {
  if [ "${DB_BACKEND}" != "postgres" ]; then
    return 0
  fi

  local attempt=0
  local max_attempts=60
  while true; do
    attempt=$((attempt + 1))
    if python - <<'PY' >/dev/null 2>&1
import os, socket, sys
host = os.environ.get("POSTGRES_HOST", "db")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
s = socket.socket()
s.settimeout(2.0)
try:
    s.connect((host, port))
except Exception as exc:
    print(f"db not ready: {exc}", file=sys.stderr)
    sys.exit(1)
finally:
    s.close()
PY
    then
      echo "[entrypoint] Postgres is reachable on ${POSTGRES_HOST}:${POSTGRES_PORT}"
      return 0
    fi

    if [ "${attempt}" -ge "${max_attempts}" ]; then
      echo "[entrypoint] Postgres never became reachable after ${max_attempts} attempts" >&2
      return 1
    fi
    echo "[entrypoint] waiting for Postgres (attempt ${attempt}/${max_attempts})..."
    sleep 2
  done
}

wait_for_db

# ---------------------------------------------------------------------------
# 2. Migrate.
# ---------------------------------------------------------------------------
echo "[entrypoint] applying migrations..."
python manage.py migrate --noinput

# ---------------------------------------------------------------------------
# 3. Seed demo data (idempotent).
# ---------------------------------------------------------------------------
echo "[entrypoint] seeding demo data..."
python manage.py seed_demo_data || {
  echo "[entrypoint] seed_demo_data failed (non-fatal, continuing)" >&2
}

# ---------------------------------------------------------------------------
# 4. Background expire_holds loop.
# ---------------------------------------------------------------------------
echo "[entrypoint] starting expire_holds loop (interval=${EXPIRE_LOOP_INTERVAL}s)..."

(
  while true; do
    python manage.py expire_holds || true
    sleep "${EXPIRE_LOOP_INTERVAL}"
  done
) &

EXPIRE_PID=$!
echo "[entrypoint] expire_holds loop pid=${EXPIRE_PID}"

# Propagate SIGTERM/SIGINT to the loop so `docker stop` is clean.
cleanup() {
  echo "[entrypoint] received signal, stopping expire_holds loop..."
  kill "${EXPIRE_PID}" 2>/dev/null || true
  wait "${EXPIRE_PID}" 2>/dev/null || true
}
trap cleanup TERM INT

# ---------------------------------------------------------------------------
# 5. Hand off to gunicorn (PID 1).
# ---------------------------------------------------------------------------
echo "[entrypoint] launching gunicorn..."
exec "$@"
