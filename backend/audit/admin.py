from django.contrib import admin
from .models import SecurityAuditEvent


@admin.register(SecurityAuditEvent)
class SecurityAuditEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "event_type", "user", "device_id", "ip_address", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("device_id", "user__phone_number", "ip_address")
    readonly_fields = ("event_id", "event_type", "user", "device_id", "ip_address", "user_agent", "details", "created_at")
