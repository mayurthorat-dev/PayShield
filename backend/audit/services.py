from .models import SecurityAuditEvent


def log_security_event(
    event_type: str,
    user=None,
    device_id: str = "",
    ip_address: str = "",
    user_agent: str = "",
    details: dict = None,
) -> SecurityAuditEvent:
    """
    Records a security event in the audit log.
    Strictly purges sensitive parameters (passwords, tokens, OTPs, secret keys).
    """
    sanitized = details.copy() if details else {}

    # Sensitive key pattern filtering
    sensitive_keywords = ["password", "otp", "token", "secret", "hash", "key", "auth"]
    for key in list(sanitized.keys()):
        for keyword in sensitive_keywords:
            if keyword in key.lower():
                sanitized.pop(key, None)
                break

    return SecurityAuditEvent.objects.create(
        event_type=event_type,
        user=user,
        device_id=str(device_id) if device_id else "",
        ip_address=ip_address or "",
        user_agent=(user_agent or "")[:255],
        details=sanitized,
    )

