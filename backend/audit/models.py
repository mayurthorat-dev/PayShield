from django.db import models


class SecurityAuditEvent(models.Model):
    """
    Audit log for security-critical actions and events in PayShield.
    Captures device lifecycle, authorization decisions, and access control rejections.
    Never logs passwords, OTP codes, auth tokens, or bank secrets.
    """

    EVENT_TYPES = [
        ("DEVICE_REGISTERED", "Device Registered"),
        ("REGISTRATION_REJECTED", "Registration Rejected"),
        ("DEVICE_REPLACED", "Device Replaced"),
        ("DEVICE_REVOKED", "Device Revoked"),
        ("DEVICE_UNAUTHORIZED_REQUEST", "Device Unauthorized Request"),
        ("LOGIN_SUCCESS", "Login Success"),
        ("LOGIN_FAILED", "Login Failed"),
        ("APPROVAL_DECISION", "Approval Decision"),
        ("CYBER_CRIME_REPORTED", "Cyber Crime Reported"),
    ]

    event_id = models.BigAutoField(primary_key=True)
    event_type = models.CharField(max_length=40, choices=EVENT_TYPES, db_index=True)
    user = models.ForeignKey(
        "accounts.PayShieldUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="security_audit_events",
    )
    device_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    ip_address = models.CharField(max_length=45, blank=True, default="")
    user_agent = models.CharField(max_length=255, blank=True, default="")
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Security Audit Event"
        verbose_name_plural = "Security Audit Events"
        ordering = ["-created_at"]

    def __str__(self):
        user_str = self.user.phone_number if self.user else "Anonymous"
        return f"[{self.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {self.event_type} - {user_str}"
