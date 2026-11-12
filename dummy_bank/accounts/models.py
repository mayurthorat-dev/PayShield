from django.db import models
from customers.models import BankCustomer


class BankAccount(models.Model):

    ACCOUNT_TYPES = [
        ("SAVINGS", "Savings"),
        ("CURRENT", "Current"),
    ]

    ACCOUNT_STATUS = [
        ("ACTIVE", "Active"),
        ("FROZEN", "Frozen"),
        ("CLOSED", "Closed"),
    ]

    account_id = models.BigAutoField(primary_key=True)

    customer = models.ForeignKey(
        BankCustomer,
        on_delete=models.PROTECT,
        related_name="bank_accounts"
    )

    account_number = models.CharField(
        max_length=20,
        unique=True
    )

    bank_name = models.CharField(max_length=100)
    ifsc_code = models.CharField(max_length=11)

    account_type = models.CharField(
        max_length=10,
        choices=ACCOUNT_TYPES,
        default="SAVINGS"
    )

    balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0
    )

    currency = models.CharField(max_length=3, default="INR")

    status = models.CharField(
        max_length=10,
        choices=ACCOUNT_STATUS,
        default="ACTIVE"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.bank_name} - {self.account_number}"