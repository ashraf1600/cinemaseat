"""
Health-check endpoint.

GET /api/health/

Contract:
  * Always returns well under 1 second.
  * Verifies the database is reachable with a single ``SELECT 1`` round-trip.
  * NEVER calls the upstream payment/OTP gateway — the gateway being down
    must not affect this endpoint. (Per the rulebook: a healthy service
    is one that can answer its own health check independently of any
    upstream it integrates with.)
  * Never touches business tables; the worst case is a single DB ping.
"""
from __future__ import annotations

import logging

from django.db import connection
from django.db.utils import OperationalError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class HealthView(APIView):
    """
    Lightweight liveness + readiness probe.

    - 200 OK    — process is up AND the database answered a ping.
    - 503       — process is up but the database is unreachable.
    """

    # The endpoint is intentionally unauthenticated and has no
    # permission requirements — load balancers and orchestrators hit
    # it directly without credentials.
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request, *args, **kwargs) -> Response:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except OperationalError as exc:
            logger.warning("Health check DB ping failed: %s", exc)
            return Response(
                {
                    "status": "unhealthy",
                    "checks": {"database": "down"},
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.exception("Health check failed unexpectedly: %s", exc)
            return Response(
                {
                    "status": "unhealthy",
                    "checks": {"database": "error"},
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "status": "ok",
                "checks": {"database": "up"},
            },
            status=status.HTTP_200_OK,
        )
