from django.contrib import admin

from .models import Booking, BookingSeat, OtpVerification


class BookingSeatInline(admin.TabularInline):
    model = BookingSeat
    extra = 0
    autocomplete_fields = ("seat",)
    raw_id_fields = ("seat",)


class OtpInline(admin.StackedInline):
    model = OtpVerification
    extra = 0
    max_num = 1
    can_delete = False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "booking_ref", "phone", "status", "expires_at", "created_at")
    list_filter = ("status",)
    search_fields = ("booking_ref", "phone")
    readonly_fields = ("created_at",)
    inlines = [BookingSeatInline, OtpInline]


@admin.register(BookingSeat)
class BookingSeatAdmin(admin.ModelAdmin):
    list_display = ("id", "booking", "seat")
    list_filter = ("booking__status",)
    raw_id_fields = ("booking", "seat")


@admin.register(OtpVerification)
class OtpVerificationAdmin(admin.ModelAdmin):
    list_display = ("id", "booking", "ref", "status")
    list_filter = ("status",)
    search_fields = ("ref", "booking__booking_ref")