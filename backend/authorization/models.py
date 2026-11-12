from django.db import models
from transactions.models import TransactionContext


class ApprovalRequest(models.Model):
    APPROVAL_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("DENIED", "Denied"),
        ("EXPIRED", "Expired"),
    ]

    transaction = models.OneToOneField(
        TransactionContext,
        on_delete=models.PROTECT,
        related_name="approval",
    )

    user = models.ForeignKey(
        "accounts.PayShieldUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approvals",
        help_text="The PayShield user authorized to decide this request",
    )

    status = models.CharField(
        max_length=10,
        choices=APPROVAL_CHOICES,
        default="PENDING",
    )

    is_reported_fraud = models.BooleanField(
        default=False,
        help_text="Flagged by user as a cyber crime / fraudulent transaction attempt",
    )
    fraud_report_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Official Cyber Crime Incident Reference ID (e.g. NCR-2026-XXXXXX)",
    )

    expires_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.transaction.source_transaction_id} - {self.status}"
