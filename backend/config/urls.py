"""Root URL configuration for the cinemaseat project."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Health endpoint — must be reachable before any other /api/ route
    # so load balancers and orchestrators can probe it directly.
    path("api/health/", include("core.urls")),
    # Catalog endpoints are mounted at /api/ per the README contract
    # (/api/movies/, /api/showtimes/, /api/showtimes/<id>/seats/).
    path("api/", include("catalog.urls")),
    path("api/catalog/", include("catalog.urls")),
    # Booking endpoints are mounted at /api/bookings/ (plural) per the
    # documented contract: /api/bookings/hold/, /api/bookings/<ref>/.
    path("api/bookings/", include("booking.urls")),
    # Payment webhook — declared at the root so the gateway's callback
    # URL is /api/webhooks/payment/ regardless of any future nesting.
    path("api/webhooks/", include("payments.urls")),
    path("api/payments/", include("payments.urls")),
]
