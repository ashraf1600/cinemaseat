from django.urls import path

from .views import MovieListView, ShowtimeListView, ShowtimeSeatsView

urlpatterns = [
    path("movies/", MovieListView.as_view(), name="movie-list"),
    path("showtimes/", ShowtimeListView.as_view(), name="showtime-list"),
    path(
        "showtimes/<int:pk>/seats/",
        ShowtimeSeatsView.as_view(),
        name="showtime-seats",
    ),
]
