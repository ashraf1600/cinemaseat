from django.urls import path

from .views import (
    BookingDetailView,
    HoldSeatsView,
    OtpSendView,
    OtpVerifyView,
    PayView,
)

urlpatterns = [
    path("hold/", HoldSeatsView.as_view(), name="booking-hold"),
    path("<str:booking_ref>/", BookingDetailView.as_view(), name="booking-detail"),
    path(
        "<str:booking_ref>/otp/send/",
        OtpSendView.as_view(),
        name="booking-otp-send",
    ),
    path(
        "<str:booking_ref>/otp/verify/",
        OtpVerifyView.as_view(),
        name="booking-otp-verify",
    ),
    path(
        "<str:booking_ref>/pay/",
        PayView.as_view(),
        name="booking-pay",
    ),
]
