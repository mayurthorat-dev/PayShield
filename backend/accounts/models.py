import secrets
import uuid
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.utils import timezone


class PayShieldUser(models.Model):
    """
    PayShield Customer Identity model.
    Securely links the primary registered mobile number to Django's auth User.
    Each PayShield account has exactly one registered mobile number.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payshield_user",
    )
    full_name = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="Customer full legal or display name",
    )
    phone_number = models.CharField(
        max_length=15,
        unique=True,
        db_index=True,
        help_text="Registered primary mobile number (E.164 or digit format)",
    )
    is_phone_verified = models.BooleanField(
        default=False,
        help_text="Whether this mobile number has been verified via PayShield login OTP",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Account active status for PayShield services",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "PayShield User"
        verbose_name_plural = "PayShield Users"

    def __str__(self):
        name_str = f" - {self.full_name}" if self.full_name else ""
        return f"{self.phone_number}{name_str} ({'Verified' if self.is_phone_verified else 'Unverified'})"

    @classmethod
    def create_user_with_phone(
        cls,
        phone_number: str,
        password: str = None,
        is_phone_verified: bool = False,
        full_name: str = "",
    ):
        """
        Atomically provisions a standard Django auth User and PayShieldUser profile.
        """
        User = get_user_model()
        cleaned_phone = phone_number.strip().replace(" ", "").replace("-", "")

        with transaction.atomic():
            username = f"ps_{cleaned_phone}"
            django_user, _ = User.objects.get_or_create(
                username=username,
                defaults={"is_active": True},
            )
            if password:
                django_user.set_password(password)
                django_user.save(update_fields=["password"])
            elif not django_user.password:
                django_user.set_password(secrets.token_urlsafe(24))
                django_user.save(update_fields=["password"])

            payshield_user, created = cls.objects.get_or_create(
                user=django_user,
                defaults={
                    "phone_number": cleaned_phone,
                    "full_name": full_name.strip() if full_name else "",
                    "is_phone_verified": is_phone_verified,
                    "is_active": True,
                },
            )
            update_fields = []
            if not created and is_phone_verified and not payshield_user.is_phone_verified:
                payshield_user.is_phone_verified = True
                update_fields.append("is_phone_verified")
            if full_name and payshield_user.full_name != full_name.strip():
                payshield_user.full_name = full_name.strip()
                update_fields.append("full_name")

            if update_fields:
                update_fields.append("updated_at")
                payshield_user.save(update_fields=update_fields)

            return payshield_user


class LoginOTPChallenge(models.Model):
    """
    Dedicated OTP challenge model for PayShield login verification.
    Completely separate from Dummy Bank's transaction OTP (OTPChallenge).
    """

    OTP_STATUS = [
        ("PENDING", "Pending"),
        ("VERIFIED", "Verified"),
        ("EXPIRED", "Expired"),
        ("LOCKED", "Locked"),
        ("INVALID", "Invalid"),
    ]

    challenge_id = models.BigAutoField(primary_key=True)
    phone_number = models.CharField(max_length=15, db_index=True)
    otp_hash = models.CharField(max_length=255)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)

    status = models.CharField(
        max_length=10,
        choices=OTP_STATUS,
        default="PENDING",
    )

    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Login OTP Challenge"
        verbose_name_plural = "Login OTP Challenges"
        ordering = ["-created_at"]

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def can_attempt(self) -> bool:
        return self.status == "PENDING" and self.attempts < self.max_attempts and not self.is_expired()

    def __str__(self):
        return f"LoginOTP({self.phone_number} - {self.status} - {self.attempts}/{self.max_attempts})"


class Device(models.Model):
    """
    Device Registration & Binding Model.
    Enforces the single active device per PayShield account policy.
    Maintains revocation history for security audits.
    """

    PLATFORM_CHOICES = [
        ("ANDROID", "Android"),
        ("IOS", "iOS"),
        ("WEB", "Web"),
        ("OTHER", "Other"),
    ]

    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("REVOKED", "Revoked"),
    ]

    id = models.BigAutoField(primary_key=True)
    device_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    user = models.ForeignKey(
        PayShieldUser,
        on_delete=models.CASCADE,
        related_name="devices",
        db_index=True,
    )
    # One-to-one pointer to active user. Exactly one ACTIVE device can point to user at a time.
    # When revoked, active_user is set to NULL, which MySQL uniquely permits in multiple rows.
    active_user = models.OneToOneField(
        PayShieldUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_device",
    )
    device_name = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text="User device name or model (e.g. Pixel 8, iPhone 15)",
    )
    platform = models.CharField(
        max_length=20,
        choices=PLATFORM_CHOICES,
        default="ANDROID",
    )
    app_version = models.CharField(
        max_length=30,
        blank=True,
        default="1.0.0",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="ACTIVE",
        db_index=True,
    )
    registered_at = models.DateTimeField(auto_now_add=True)
    last_active_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.CharField(
        max_length=120,
        blank=True,
        default="",
    )
    push_token = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="FCM device registration token or Expo push token",
    )

    class Meta:
        verbose_name = "Device"
        verbose_name_plural = "Devices"
        ordering = ["-registered_at"]

    def __str__(self):
        return f"{self.device_name or str(self.device_id)[:8]} ({self.platform}) - {self.status} [{self.user.phone_number}]"

    def is_active(self) -> bool:
        return self.status == "ACTIVE"

    def revoke(self, reason: str = "MANUAL_REVOCATION"):
        """
        Marks this device as REVOKED, releases the active_user slot, and updates revocation metadata.
        """
        self.status = "REVOKED"
        self.active_user = None
        self.push_token = ""
        self.revoked_at = timezone.now()
        self.revocation_reason = reason
        self.save(update_fields=["status", "active_user", "push_token", "revoked_at", "revocation_reason"])

