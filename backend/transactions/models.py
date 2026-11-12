import uuid
from django.db import models


class TransactionContext(models.Model):
    TRANSACTION_TYPES = [
        ("BANK_TRANSFER", "Bank Transfer"),
        ("GIFT_CARD", "Gift Card Purchase"),
    ]

    transaction_ref = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    source_bank = models.CharField(max_length=100)
    source_transaction_id = models.CharField(
        max_length=100,
        unique=True,
    )

    transaction_type = models.CharField(
        max_length=20,
        choices=TRANSACTION_TYPES,
    )

    sender_name = models.CharField(max_length=100)
    sender_account_masked = models.CharField(max_length=30, blank=True)

    # Trusted identifiers from the issuing bank
    bank_customer_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="BankCustomer UUID passed by Dummy Bank",
    )
    bank_account_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Sender BankAccount primary key passed by Dummy Bank",
    )

    # Secure linkages to PayShield domain entities
    linked_account = models.ForeignKey(
        "banking.LinkedBankAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        help_text="The verified linked bank account record on PayShield",
    )
    user = models.ForeignKey(
        "accounts.PayShieldUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        help_text="The PayShield user owning the transaction",
    )

    recipient_name = models.CharField(max_length=100, blank=True)
    recipient_account_masked = models.CharField(
        max_length=30,
        blank=True,
    )

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    description = models.CharField(max_length=200, blank=True)

    otp_verified = models.BooleanField(default=False)

    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.source_transaction_id} - {self.amount} {self.currency}"
