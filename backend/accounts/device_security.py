from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from audit.services import log_security_event


def get_request_device_id(request) -> str:
    """
    Extracts the X-Device-ID header from the incoming HTTP request.
    Handles both standard WSGI HTTP_X_DEVICE_ID and ASGI / TestClient headers.
    """
    device_id = request.headers.get("X-Device-ID") or request.META.get("HTTP_X_DEVICE_ID", "")
    return str(device_id).strip()


def validate_device_binding(request, payshield_user) -> tuple[bool, Response | None]:
    """
    Validates device binding for mobile API requests:
    1. If the user has an active registered device, X-Device-ID is strictly required.
    2. The presented device ID must match the user's single ACTIVE registered device.
    3. Revoked devices or mismatched device IDs are rejected with HTTP 403 Forbidden.
    4. Rejections are recorded in the security audit log.
    """
    active_device = getattr(payshield_user, "active_device", None)
    if not active_device:
        active_device = payshield_user.devices.filter(status="ACTIVE").first()

    device_id_str = get_request_device_id(request)
    ip_addr = request.META.get("REMOTE_ADDR", "")
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    # User does not have an active registered device
    if not active_device:
        if device_id_str:
            # Check if this specific device was previously revoked
            revoked = payshield_user.devices.filter(device_id=device_id_str, status="REVOKED").first()
            if revoked:
                log_security_event(
                    event_type="DEVICE_UNAUTHORIZED_REQUEST",
                    user=payshield_user,
                    device_id=device_id_str,
                    ip_address=ip_addr,
                    user_agent=user_agent,
                    details={"reason": "Attempted access with revoked device."},
                )
                return False, Response(
                    {
                        "error": "This device has been revoked and cannot access PayShield services.",
                        "code": "DEVICE_REVOKED",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
        return True, None

    # User has an active device: X-Device-ID is mandatory
    if not device_id_str:
        log_security_event(
            event_type="DEVICE_UNAUTHORIZED_REQUEST",
            user=payshield_user,
            device_id="",
            ip_address=ip_addr,
            user_agent=user_agent,
            details={"reason": "X-Device-ID header missing for device-bound user."},
        )
        return False, Response(
            {
                "error": "Device identification header (X-Device-ID) is required for this account.",
                "code": "DEVICE_HEADER_MISSING",
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # Check match with active device
    if str(active_device.device_id) != device_id_str:
        # Check if the presented ID is a revoked device belonging to this user
        revoked = payshield_user.devices.filter(device_id=device_id_str, status="REVOKED").first()
        reason = "Device has been revoked." if revoked else "Unrecognized or mismatched device."
        code = "DEVICE_REVOKED" if revoked else "DEVICE_UNAUTHORIZED"

        log_security_event(
            event_type="DEVICE_UNAUTHORIZED_REQUEST",
            user=payshield_user,
            device_id=device_id_str,
            ip_address=ip_addr,
            user_agent=user_agent,
            details={"reason": reason, "active_device_id": str(active_device.device_id)},
        )
        return False, Response(
            {
                "error": f"Device authorization failed: {reason}",
                "code": code,
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # Active and matched! Update last_active_at
    active_device.last_active_at = timezone.now()
    active_device.save(update_fields=["last_active_at"])
    return True, None

