from django.contrib import admin

from .models import Payment, PaymentEvent


class PaymentEventInline(admin.TabularInline):
    model = PaymentEvent
    extra = 0
    readonly_fields = ("event_id", "status", "received_at", "raw_payload")
    fields = ("event_id", "status", "received_at", "raw_payload")
    can_delete = False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "booking", "payment_id", "status", "amount")
    list_filter = ("status",)
    search_fields = ("payment_id", "booking__booking_ref")
    raw_id_fields = ("booking",)
    inlines = [PaymentEventInline]


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ("id", "event_id", "payment", "status", "received_at")
    list_filter = ("status",)
    search_fields = ("event_id", "payment__payment_id", "payment__booking__booking_ref")
    readonly_fields = ("received_at", "raw_payload")