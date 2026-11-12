import os
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from audit.services import log_security_event
from .device_security import get_request_device_id
from .device_serializers import (
    DeviceRegisterInputSerializer,
    DeviceReplaceInputSerializer,
    DeviceRevokeInputSerializer,
    DeviceSerializer,
)
from .models import Device, LoginOTPChallenge, PayShieldUser
from .views import _issue_otp_challenge


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_device_status(request):
    """
    Returns the device binding status for the authenticated user.
    Checks whether this specific calling device is registered, active, or revoked.
    """
    payshield_user = getattr(request.user, "payshield_user", None)
    if not payshield_user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    active_device = getattr(payshield_user, "active_device", None)
    if not active_device:
        active_device = payshield_user.devices.filter(status="ACTIVE").first()

    calling_device_id = get_request_device_id(request)
    calling_device_status = "UNREGISTERED"

    if calling_device_id:
        matching_dev = payshield_user.devices.filter(device_id=calling_device_id).first()
        if matching_dev:
            calling_device_status = matching_dev.status

    is_current_active = bool(
        active_device and calling_device_id and str(active_device.device_id) == calling_device_id
    )

    return Response(
        {
            "has_active_device": active_device is not None,
            "active_device": DeviceSerializer(active_device).data if active_device else None,
            "is_current_device_registered": is_current_active,
            "current_device_status": calling_device_status,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def register_device(request):
    """
    Registers a new mobile device for the authenticated user.
    Enforces the single active device policy:
    - If no device is active: registers this device as ACTIVE.
    - If the same device re-registers: updates last_active_at and metadata.
    - If another active device exists: rejects with HTTP 409 Conflict (DEVICE_REPLACEMENT_REQUIRED).
    """
    payshield_user = getattr(request.user, "payshield_user", None)
    if not payshield_user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = DeviceRegisterInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    device_id = serializer.validated_data["device_id"]
    device_name = serializer.validated_data.get("device_name", "")
    platform = serializer.validated_data.get("platform", "ANDROID")
    app_version = serializer.validated_data.get("app_version", "1.0.0")

    ip_addr = request.META.get("REMOTE_ADDR", "")
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    with transaction.atomic():
        # Lock user record to prevent concurrent double-registration race conditions
        user_lock = PayShieldUser.objects.select_for_update().get(id=payshield_user.id)
        active_device = user_lock.devices.filter(status="ACTIVE").first()

        if active_device:
            # Check if this is the exact same device re-registering
            if str(active_device.device_id) == str(device_id):
                active_device.device_name = device_name or active_device.device_name
                active_device.platform = platform
                active_device.app_version = app_version
                active_device.last_active_at = timezone.now()
                active_device.save(update_fields=["device_name", "platform", "app_version", "last_active_at"])

                return Response(
                    {
                        "message": "Device re-authenticated successfully.",
                        "device": DeviceSerializer(active_device).data,
                    },
                    status=status.HTTP_200_OK,
                )

            # Different device attempted registration while another device is already active
            log_security_event(
                event_type="REGISTRATION_REJECTED",
                user=payshield_user,
                device_id=str(device_id),
                ip_address=ip_addr,
                user_agent=user_agent,
                details={
                    "reason": "Attempted to register additional active device without replacement.",
                    "existing_device_id": str(active_device.device_id),
                    "existing_device_name": active_device.device_name,
                },
            )

            return Response(
                {
                    "error": "Another device is already registered to this PayShield account. Device replacement is required to switch devices.",
                    "code": "DEVICE_REPLACEMENT_REQUIRED",
                    "registered_device": {
                        "device_name": active_device.device_name or "Registered Mobile Phone",
                        "platform": active_device.platform,
                        "registered_at": active_device.registered_at,
                    },
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Check if this physical device already exists in the database under this user or any previous user
        existing_hardware = Device.objects.filter(device_id=device_id).first()
        if existing_hardware:
            # If previously owned by another user on this phone, cleanly transfer hardware binding
            if existing_hardware.user != user_lock:
                log_security_event(
                    event_type="DEVICE_REBOUND",
                    user=user_lock,
                    device_id=str(device_id),
                    ip_address=ip_addr,
                    user_agent=user_agent,
                    details={
                        "previous_user_id": existing_hardware.user.id,
                        "previous_phone": existing_hardware.user.phone_number,
                    },
                )
                # Clear previous user's active device link and push token
                if existing_hardware.active_user and existing_hardware.active_user != user_lock:
                    existing_hardware.active_user = None
                    existing_hardware.push_token = ""

                existing_hardware.user = user_lock

            existing_hardware.status = "ACTIVE"
            existing_hardware.active_user = user_lock
            existing_hardware.device_name = device_name or existing_hardware.device_name
            existing_hardware.platform = platform
            existing_hardware.app_version = app_version
            existing_hardware.revoked_at = None
            existing_hardware.revocation_reason = ""
            existing_hardware.last_active_at = timezone.now()
            existing_hardware.save()
            device = existing_hardware
        else:
            # Create fresh active device
            device = Device.objects.create(
                user=user_lock,
                active_user=user_lock,
                device_id=device_id,
                device_name=device_name,
                platform=platform,
                app_version=app_version,
                status="ACTIVE",
            )

        log_security_event(
            event_type="DEVICE_REGISTERED",
            user=payshield_user,
            device_id=str(device.device_id),
            ip_address=ip_addr,
            user_agent=user_agent,
            details={"device_name": device.device_name, "platform": device.platform},
        )

    return Response(
        {
            "message": "Device registered successfully.",
            "device": DeviceSerializer(device).data,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def request_replacement_otp(request):
    """
    Issues a fresh 6-digit verification code to the user's verified phone number
    specifically to authorize a secure device replacement.
    """
    payshield_user = getattr(request.user, "payshield_user", None)
    if not payshield_user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    otp_code, error = _issue_otp_challenge(payshield_user.phone_number)
    if error:
        return Response({"error": error}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    response_data = {
        "message": "Verification code sent to registered mobile number for device replacement.",
        "phone_number": payshield_user.phone_number,
        "expires_in_seconds": 300,
    }

    allow_dev_otp = getattr(settings, "ALLOW_DEV_OTP", True) or settings.DEBUG
    if allow_dev_otp:
        response_data["dev_otp"] = otp_code
        response_data["warning"] = "Development only: never exposed in production."

    return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def replace_device(request):
    """
    Executes secure device replacement:
    1. Verifies phone ownership via fresh OTP challenge.
    2. Atomically revokes previously active device(s).
    3. Invalidates previous session tokens associated with the revoked device.
    4. Registers and activates the new device.
    5. Issues a fresh device-bound token.
    6. Logs the security audit event.
    """
    payshield_user = getattr(request.user, "payshield_user", None)
    if not payshield_user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = DeviceReplaceInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    submitted_otp = serializer.validated_data["otp"]
    new_device_id = serializer.validated_data["device_id"]
    device_name = serializer.validated_data.get("device_name", "")
    platform = serializer.validated_data.get("platform", "ANDROID")
    app_version = serializer.validated_data.get("app_version", "1.0.0")

    ip_addr = request.META.get("REMOTE_ADDR", "")
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    with transaction.atomic():
        # Verify phone ownership via latest active challenge
        challenge = (
            LoginOTPChallenge.objects.select_for_update()
            .filter(phone_number=payshield_user.phone_number)
            .exclude(status="EXPIRED")
            .order_by("-created_at")
            .first()
        )

        if not challenge:
            return Response(
                {
                    "error": "No active verification code found for device replacement. Please request a new code.",
                    "code": "OTP_REQUIRED",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if challenge.status == "LOCKED" or challenge.attempts >= challenge.max_attempts:
            if challenge.status != "LOCKED":
                challenge.status = "LOCKED"
                challenge.save(update_fields=["status"])
            return Response(
                {
                    "error": "Maximum verification attempts exceeded. Please request a new code.",
                    "code": "OTP_LOCKED",
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        if challenge.is_expired():
            challenge.status = "EXPIRED"
            challenge.save(update_fields=["status"])
            return Response(
                {
                    "error": "Verification code has expired. Please request a new code.",
                    "code": "OTP_EXPIRED",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        challenge.attempts += 1

        if not check_password(submitted_otp, challenge.otp_hash):
            if challenge.attempts >= challenge.max_attempts:
                challenge.status = "LOCKED"
            challenge.save(update_fields=["attempts", "status"])
            return Response(
                {
                    "error": "Invalid verification code for device replacement.",
                    "attempts_remaining": max(challenge.max_attempts - challenge.attempts, 0),
                    "code": "INVALID_OTP",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Mark challenge verified
        challenge.status = "VERIFIED"
        challenge.verified_at = timezone.now()
        challenge.save(update_fields=["attempts", "status", "verified_at"])

        # Lock user record and revoke any previous active device
        user_lock = PayShieldUser.objects.select_for_update().get(id=payshield_user.id)
        previous_devices = user_lock.devices.select_for_update().filter(status="ACTIVE")

        revoked_ids = []
        for prev_dev in previous_devices:
            revoked_ids.append(str(prev_dev.device_id))
            prev_dev.revoke(reason="REPLACED_BY_USER")

        # Invalidate previous token sessions associated with the revoked device
        Token.objects.filter(user=user_lock.user).delete()
        new_token = Token.objects.create(user=user_lock.user)

        # Activate the replacement device
        existing_new_dev = Device.objects.filter(device_id=new_device_id).first()
        if existing_new_dev:
            if existing_new_dev.user != user_lock:
                if existing_new_dev.active_user and existing_new_dev.active_user != user_lock:
                    existing_new_dev.active_user = None
                    existing_new_dev.push_token = ""
                existing_new_dev.user = user_lock

            existing_new_dev.status = "ACTIVE"
            existing_new_dev.active_user = user_lock
            existing_new_dev.device_name = device_name or existing_new_dev.device_name
            existing_new_dev.platform = platform
            existing_new_dev.app_version = app_version
            existing_new_dev.revoked_at = None
            existing_new_dev.revocation_reason = ""
            existing_new_dev.last_active_at = timezone.now()
            existing_new_dev.save()
            new_device = existing_new_dev
        else:
            new_device = Device.objects.create(
                user=user_lock,
                active_user=user_lock,
                device_id=new_device_id,
                device_name=device_name,
                platform=platform,
                app_version=app_version,
                status="ACTIVE",
            )

        # Record device replacement audit event
        log_security_event(
            event_type="DEVICE_REPLACED",
            user=payshield_user,
            device_id=str(new_device.device_id),
            ip_address=ip_addr,
            user_agent=user_agent,
            details={
                "revoked_device_ids": revoked_ids,
                "new_device_name": new_device.device_name,
                "platform": new_device.platform,
            },
        )

    return Response(
        {
            "message": "Device replaced successfully. Previous device sessions have been revoked.",
            "device": DeviceSerializer(new_device).data,
            "token": new_token.key,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def revoke_device(request):
    """
    Revokes the user's active device.
    Strictly prevents revoking another user's device.
    Invalidates the current session token to lock out revoked hardware.
    """
    payshield_user = getattr(request.user, "payshield_user", None)
    if not payshield_user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = DeviceRevokeInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    target_device_id = serializer.validated_data.get("device_id")
    reason = serializer.validated_data.get("reason", "MANUAL_REVOCATION")

    ip_addr = request.META.get("REMOTE_ADDR", "")
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    with transaction.atomic():
        user_lock = PayShieldUser.objects.select_for_update().get(id=payshield_user.id)

        # Ensure a client cannot revoke another user's device
        if target_device_id:
            # Check if this device belongs to someone else
            foreign_device = Device.objects.filter(device_id=target_device_id).exclude(user=user_lock).first()
            if foreign_device:
                log_security_event(
                    event_type="DEVICE_UNAUTHORIZED_REQUEST",
                    user=payshield_user,
                    device_id=str(target_device_id),
                    ip_address=ip_addr,
                    user_agent=user_agent,
                    details={"reason": "Attempted to revoke another customer's device."},
                )
                return Response(
                    {"error": "You do not have permission to revoke this device.", "code": "PERMISSION_DENIED"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            device_to_revoke = user_lock.devices.filter(device_id=target_device_id, status="ACTIVE").first()
        else:
            device_to_revoke = user_lock.devices.filter(status="ACTIVE").first()

        if not device_to_revoke:
            return Response(
                {"error": "No active device found to revoke.", "code": "NO_ACTIVE_DEVICE"},
                status=status.HTTP_404_NOT_FOUND,
            )

        device_to_revoke.revoke(reason=reason)

        # Invalidate current session token so revoked device cannot continue making API requests
        Token.objects.filter(user=user_lock.user).delete()

        log_security_event(
            event_type="DEVICE_REVOKED",
            user=payshield_user,
            device_id=str(device_to_revoke.device_id),
            ip_address=ip_addr,
            user_agent=user_agent,
            details={"reason": reason},
        )

    return Response(
        {"message": "Device revoked successfully. Associated session has been invalidated."},
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_push_token(request):
    """
    Associates or updates the FCM/Expo push token for the authenticated user's active device.
    """
    payshield_user = getattr(request.user, "payshield_user", None)
    if not payshield_user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    push_token = request.data.get("push_token", "").strip()
    if not push_token:
        return Response(
            {"error": "push_token is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    calling_device_id = get_request_device_id(request)
    device = None

    if calling_device_id:
        device = payshield_user.devices.filter(device_id=calling_device_id, status="ACTIVE").first()

    if not device:
        device = getattr(payshield_user, "active_device", None)
        if not device or device.status != "ACTIVE":
            device = payshield_user.devices.filter(status="ACTIVE").first()

    if not device:
        return Response(
            {"error": "No active registered device found for this account. Register device first."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Clear this push_token from any other device to guarantee single-recipient routing
    Device.objects.filter(push_token=push_token).exclude(id=device.id).update(push_token="")

    device.push_token = push_token
    device.save(update_fields=["push_token"])

    return Response({
        "message": "Push token registered successfully.",
        "device_id": str(device.device_id),
        "platform": device.platform,
    }, status=status.HTTP_200_OK)

