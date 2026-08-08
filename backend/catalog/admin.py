from django.contrib import admin

from .models import Movie, Seat, Showtime, Theatre


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "duration_minutes")
    search_fields = ("title",)
    ordering = ("title",)


@admin.register(Theatre)
class TheatreAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "location")
    search_fields = ("name", "location")
    ordering = ("name",)


class SeatInline(admin.TabularInline):
    model = Seat
    extra = 0
    fields = ("label", "status")
    show_change_link = True


@admin.register(Showtime)
class ShowtimeAdmin(admin.ModelAdmin):
    list_display = ("id", "movie", "theatre", "starts_at", "base_price")
    list_filter = ("theatre", "movie")
    search_fields = ("movie__title", "theatre__name")
    autocomplete_fields = ("movie", "theatre")
    inlines = [SeatInline]


@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ("id", "showtime", "label", "status")
    list_filter = ("status", "showtime__theatre", "showtime__movie")
    search_fields = ("label",)