"""
Webhook signature verification.

The gateway may sign webhook deliveries with HMAC-SHA256 over the **raw
request body** (before JSON parsing). When ``settings.GATEWAY_SECRET`` is
set, every incoming webhook must carry an ``X-Signature`` header whose
value matches ``HMAC-SHA256(GATEWAY_SECRET, body)``.

When the secret is empty (local dev / tests), verification is **disabled**
and we accept every request — these are integration tests written against
the gateway mock, not signed calls.
"""
from __future__ import annotations

import hashlib
import hmac

from django.conf import settings


def verify_signature(raw_body: bytes, provided_signature: str) -> bool:
    """Return True if the signature matches, or if verification is disabled.

    Empty ``GATEWAY_SECRET`` ⇒ disabled, returns True.
    Mismatched signature ⇒ returns False (caller must respond 401).
    """
    secret = getattr(settings, "GATEWAY_SECRET", "") or ""
    if not secret:
        return True

    if not provided_signature:
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, provided_signature)
