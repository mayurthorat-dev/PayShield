from django.db import models
from accounts.models import BankAccount
import uuid


class Beneficiary(models.Model):

    beneficiary_id = models.BigAutoField(primary_key=True)

    owner_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="beneficiaries"
    )

    recipient_name = models.CharField(max_length=100)
    recipient_bank_name = models.CharField(max_length=100)
    recipient_account_number = models.CharField(max_length=20)
    recipient_ifsc = models.CharField(max_length=11)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.recipient_name


class BankTransaction(models.Model):

    TRANSACTION_TYPES = [
        ("BANK_TRANSFER", "Bank Transfer"),
        ("GIFT_CARD", "Gift Card Purchase"),
    ]

    TRANSACTION_STATUS = [
        ("CREATED", "Created"),
        ("OTP_PENDING", "OTP Pending"),
        ("OTP_VERIFIED", "OTP Verified"),
        ("AWAITING_APPROVAL", "Awaiting PayShield Approval"),
        ("COMPLETED", "Completed"),
        ("CANCELLED", "Cancelled"),
        ("FAILED", "Failed"),
    ]

    
    transaction_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    sender_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="sent_transactions"
    )

    beneficiary = models.ForeignKey(
        Beneficiary,
        on_delete=models.PROTECT,
        related_name="transactions",
        null=True,
        blank=True
    )

    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPES,
        default="BANK_TRANSFER"
    )

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    description = models.CharField(max_length=200, blank=True)

    status = models.CharField(
        max_length=25,
        choices=TRANSACTION_STATUS,
        default="CREATED"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    
    payshield_expires_at = models.DateTimeField(
        null=True,
        blank=True
    )


    def __str__(self):
        return f"{self.transaction_id} - {self.status}"