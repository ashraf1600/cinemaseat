"""HTTP client for the mock OTP/payment gateway.

The gateway is an upstream service reachable at ``settings.GATEWAY_BASE_URL``.
We use only ``urllib.request`` from the stdlib so the booking app has no extra
runtime dependencies.

The send endpoint is called from a background thread inside the view (so the
HTTP latency never blocks the caller); verify is synchronous because the
client needs the answer to proceed.

Every public function returns the gateway's HTTP status code as an ``int``.
``GatewayError`` is raised only for transport-level failures (DNS, refused
connection, timeout) — HTTP errors are returned as their numeric status so
the caller can branch on 200/400/etc.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    """Raised when the gateway cannot be reached at all (network/timeout)."""


def _post_json(path: str, payload: dict, timeout: float = 5.0) -> int:
    """POST ``payload`` (JSON) to ``path`` under ``settings.GATEWAY_BASE_URL``.

    Returns the HTTP status code on any HTTP response (success *or* error).
    Raises ``GatewayError`` for transport failures.
    """
    url = settings.GATEWAY_BASE_URL.rstrip("/") + path
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        # HTTPError is still an HTTP response — surface its status code.
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GatewayError(str(exc)) from exc


def _post_json_with_body(path: str, payload: dict, timeout: float = 5.0) -> tuple[int, dict]:
    """Like ``_post_json`` but also returns the parsed JSON body on 2xx.

    On non-2xx the body dict is empty — the caller only branches on status.
    Raises ``GatewayError`` for transport failures (same as ``_post_json``).
    """
    url = settings.GATEWAY_BASE_URL.rstrip("/") + path
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {}
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GatewayError(str(exc)) from exc


def send_otp(phone: str, ref: str, timeout: float = 5.0) -> int:
    """Call ``POST /otp/send`` on the gateway. Returns HTTP status code."""
    return _post_json("/otp/send", {"phone": phone, "ref": ref}, timeout=timeout)


def verify_otp(ref: str, code: str, timeout: float = 5.0) -> int:
    """Call ``POST /otp/verify`` on the gateway. Returns HTTP status code."""
    return _post_json("/otp/verify", {"ref": ref, "code": code}, timeout=timeout)


class ChargeError(Exception):
    """Raised when the gateway refuses a /charge call with an explicit error body.

    The HTTP status was 4xx and the body parses as ``{"error": "..."}``.
    The caller can decide whether to surface the failure to the user
    immediately (vs. falling back to PENDING and waiting on the webhook).
    """


def charge(
    *,
    amount,
    currency: str,
    booking_ref: str,
    callback_url: str,
    timeout: float = 5.0,
) -> tuple[int, dict]:
    """Call ``POST /charge`` on the gateway. Returns ``(status_code, body)``.

    The gateway is documented to fail ~2% of the time; callers must
    tolerate 5xx by leaving the local Payment in PENDING and letting the
    eventual webhook (or its absence + a future retry) settle the state.

    Raises ``GatewayError`` only for transport-level failures (DNS / refused
    / timeout). HTTP responses — even 5xx — come back as status codes.
    """
    return _post_json_with_body(
        "/charge",
        {
            "amount": str(amount),
            "currency": currency,
            "booking_ref": booking_ref,
            "callback_url": callback_url,
        },
        timeout=timeout,
    )
