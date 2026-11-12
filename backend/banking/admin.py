from django.contrib import admin
from .models import LinkedBankAccount

@admin.register(LinkedBankAccount)
class LinkedBankAccountAdmin(admin.ModelAdmin):
    list_display = (
        "link_id",
        "user",
        "bank_name",
        "account_number_masked",
        "verification_status",
        "is_verified",
        "is_active",
        "linked_at",
    )
    search_fields = ("account_number_masked", "user__phone_number", "bank_name")
    list_filter = ("verification_status", "is_verified", "is_active", "bank_name")
