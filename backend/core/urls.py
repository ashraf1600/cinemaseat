"""URL routes for the core app (health endpoint lives here)."""
from __future__ import annotations

from django.urls import path

from .views import HealthView

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
]
