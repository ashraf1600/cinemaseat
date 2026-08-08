"""
OTP delivery webhook receiver.

The upstream gateway POSTs OTP-delivery callbacks to us at
``/api/webhooks/otp/``. The contract is:

    {
      "event_id": "<unique>",        # idempotency key — DB-unique
      "ref": "otp_...",              # the OtpVerification.ref we generated
      "code": "123456",              # the OTP code, for debug/UI display
      "phone": "+8801...",           # optional
      ...                            # any other fields are silently ignored
    }

Behaviour:
  1. If an ``OtpDeliveryEvent`` with this ``event_id`` already exists,
     return 200 immediately. Duplicate-delivery guard.
  2. Otherwise, insert the event row, and (if we can match it) stash
     the delivered code on the matching ``OtpVerification`` row.
  3. ALWAYS return 200. Any exception is caught and logged — the
     gateway will retry forever on a non-200.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from booking.models import Booking, OtpVerification

from .models import OtpDeliveryEvent
from .signature import verify_signature

logger = logging.getLogger(__name__)


class OtpWebhookView(APIView):
    """
    POST /api/webhooks/otp/

    Idempotent OTP-delivery callback receiver. See module docstring.
    """

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request, *args, **kwargs) -> Response:
        # HMAC verification (only enforced when GATEWAY_SECRET is set).
        if not verify_signature(
            request.body,
            request.META.get("HTTP_X_SIGNATURE", ""),
        ):
            logger.warning("OTP webhook rejected: invalid X-Signature")
            return Response(
                {"error": {"detail": "Invalid signature."}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        payload = request.data if isinstance(request.data, dict) else {}

        # event_id is the only field we cannot work without.
        event_id = payload.get("event_id")
        if not event_id:
            logger.warning("OTP webhook payload missing event_id; ignoring. payload=%s", payload)
            return Response({"status": "accepted"}, status=status.HTTP_200_OK)

        ref = payload.get("ref", "")
        code = payload.get("code", "")
        booking_ref = payload.get("booking_ref", "")

        # Best-effort: match this delivery to an existing OtpVerification
        # so we can stash the code on it. The matching is by ``ref`` (our
        # own identifier) first, then ``booking_ref`` as a fallback.
        # We tolerate unknown refs gracefully — we still record the event.
        otp = None
        if ref:
            otp = OtpVerification.objects.filter(ref=ref).first()
        if otp is None and booking_ref:
            otp = (
                OtpVerification.objects
                .filter(booking__booking_ref=booking_ref)
                .order_by("-id")
                .first()
            )

        try:
            with transaction.atomic():
                event, created = OtpDeliveryEvent.objects.get_or_create(
                    event_id=str(event_id),
                    defaults={
                        "booking_ref": booking_ref,
                        "ref": ref,
                        "code": code,
                        "raw_payload": payload,
                    },
                )
        except Exception as exc:  # noqa: BLE001 — defensive, always 200
            logger.exception("OtpDeliveryEvent insert failed for event_id=%s", event_id)
            return Response({"status": "accepted"}, status=status.HTTP_200_OK)

        if not created:
            # Duplicate delivery — already processed.
            return Response({"status": "accepted"}, status=status.HTTP_200_OK)

        # Stash the delivered code on the matching OtpVerification row.
        # We do this OUTSIDE the event-creation transaction so a bad
        # match (or no match) doesn't poison the idempotency guarantee.
        if otp is not None and code:
            try:
                otp.last_delivered_code = str(code)
                otp.last_delivered_at = timezone.now()
                otp.save(update_fields=["last_delivered_code", "last_delivered_at"])
            except Exception:  # noqa: BLE001 — defensive
                logger.exception(
                    "Failed to stash delivered OTP code on otp_ref=%s", otp.ref,
                )

        if otp is None:
            logger.warning(
                "OTP webhook event_id=%s could not match any OtpVerification "
                "(ref=%s booking_ref=%s); recorded the event only",
                event_id, ref, booking_ref,
            )

        # Reference booking_ref is only used for the fallback match.
        # Silence the "unused" warning without removing the variable.
        _ = booking_ref

        return Response({"status": "accepted"}, status=status.HTTP_200_OK)
