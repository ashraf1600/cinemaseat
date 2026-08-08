from django.urls import path

from .otp_webhook import OtpWebhookView
from .views import PaymentWebhookView

urlpatterns = [
    path("payment/", PaymentWebhookView.as_view(), name="payment-webhook"),
    path("otp/", OtpWebhookView.as_view(), name="otp-webhook"),
]
