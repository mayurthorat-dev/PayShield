from django.contrib import admin
from .models import Device, LoginOTPChallenge, PayShieldUser

@admin.register(PayShieldUser)
class PayShieldUserAdmin(admin.ModelAdmin):
    list_display = ("phone_number", "full_name", "user", "is_phone_verified", "is_active", "created_at")
    search_fields = ("phone_number", "full_name", "user__username")
    list_filter = ("is_phone_verified", "is_active")

@admin.register(LoginOTPChallenge)
class LoginOTPChallengeAdmin(admin.ModelAdmin):
    list_display = ("challenge_id", "phone_number", "status", "attempts", "max_attempts", "expires_at", "created_at")
    search_fields = ("phone_number",)
    list_filter = ("status",)

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("device_id", "device_name", "user", "platform", "status", "push_token", "registered_at", "last_active_at")
    search_fields = ("device_id", "device_name", "user__phone_number", "push_token")
    list_filter = ("status", "platform")
    readonly_fields = ("registered_at",)
