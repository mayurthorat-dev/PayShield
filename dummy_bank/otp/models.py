from django.db import models
from payments.models import BankTransaction


class OTPChallenge(models.Model):
    OTP_STATUS = [
        ("PENDING", "Pending"),
        ("VERIFIED", "Verified"),
        ("EXPIRED", "Expired"),
        ("LOCKED", "Locked"),
        ("INVALID", "Invalid"),
    ]

    challenge_id = models.BigAutoField(primary_key=True)

    transaction = models.ForeignKey(
        BankTransaction,
        on_delete=models.PROTECT,
        related_name="otp_challenges",
    )

    otp_hash = models.CharField(max_length=255)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)

    status = models.CharField(
        max_length=10,
        choices=OTP_STATUS,
        default="PENDING",
    )

    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"OTP Challenge {self.challenge_id} - {self.status}"