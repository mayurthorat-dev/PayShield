from django.contrib import admin
from .models import Beneficiary, BankTransaction

admin.site.register(Beneficiary)
@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    # Add your existing configurations here (like list_display, etc.)
    
    # This line sorts by the specified field in descending order (-)
    ordering = ['-created_at'] 