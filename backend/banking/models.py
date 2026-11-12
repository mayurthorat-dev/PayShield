from django.db import models
from django.utils import timezone
from accounts.models import PayShieldUser


class LinkedBankAccount(models.Model):
    """
    Represents an external bank account linked to a PayShield user.
    Maintains a trusted reference to the bank customer UUID and account identifier
    without storing sensitive credentials, PINs, or raw balances.
    """

    VERIFICATION_STATUS = [
        ("UNVERIFIED", "Unverified"),
        ("VERIFIED", "Verified"),
        ("FAILED", "Failed"),
        ("REVOKED", "Revoked"),
    ]

    link_id = models.BigAutoField(primary_key=True)

    user = models.ForeignKey(
        PayShieldUser,
        on_delete=models.CASCADE,
        related_name="linked_bank_accounts",
    )

    bank_name = models.CharField(
        max_length=100,
        default="PayShield Demo Bank",
    )

    # Trusted identifiers originating from the issuing bank (e.g. Dummy Bank)
    bank_customer_id = models.UUIDField(
        db_index=True,
        help_text="BankCustomer UUID from the issuing bank",
    )
    bank_account_id = models.BigIntegerField(
        db_index=True,
        help_text="BankAccount primary key from the issuing bank",
    )

    # Privacy-preserving display information
    account_number_masked = models.CharField(
        max_length=30,
        help_text="Masked account representation, e.g. ********0001",
    )
    account_type = models.CharField(
        max_length=20,
        default="SAVINGS",
    )

    # Verification lifecycle (Rule 8: New links begin unverified)
    is_verified = models.BooleanField(
        default=False,
        help_text="Must be verified via trusted bank verification flow",
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS,
        default="UNVERIFIED",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Whether this link is active or disabled by the user",
    )

    linked_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Linked Bank Account"
        verbose_name_plural = "Linked Bank Accounts"
        constraints = [
            models.UniqueConstraint(
                fields=["bank_name", "bank_account_id"],
                name="unique_bank_account_link",
            )
        ]

    def mark_verified(self):
        self.is_verified = True
        self.verification_status = "VERIFIED"
        self.verified_at = timezone.now()
        self.save(update_fields=["is_verified", "verification_status", "verified_at"])

    def mark_failed(self):
        self.is_verified = False
        self.verification_status = "FAILED"
        self.save(update_fields=["is_verified", "verification_status"])

    def revoke(self):
        self.is_active = False
        self.verification_status = "REVOKED"
        self.save(update_fields=["is_active", "verification_status"])

    def __str__(self):
        return f"{self.bank_name} ({self.account_number_masked}) - {self.verification_status} ({self.user.phone_number})"
