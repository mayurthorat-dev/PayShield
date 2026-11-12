from datetime import timedelta
import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import LoginOTPChallenge, PayShieldUser
from .serializers import (
    RegisterInputSerializer,
    RequestOTPInputSerializer,
    UserProfileSerializer,
    VerifyOTPInputSerializer,
)


def _issue_otp_challenge(phone_number: str):
    """
    Internal helper to rate-limit, invalidate old pending challenges,
    and generate a fresh hashed 6-digit challenge.
    Returns (otp_code, error_message).
    """
    fifteen_mins_ago = timezone.now() - timedelta(minutes=15)
    recent_requests_count = LoginOTPChallenge.objects.filter(
        phone_number=phone_number,
        created_at__gte=fifteen_mins_ago,
    ).count()

    if recent_requests_count >= 5:
        return None, "Too many verification requests. Please wait a few minutes before trying again."

    LoginOTPChallenge.objects.filter(
        phone_number=phone_number,
        status="PENDING",
    ).update(status="EXPIRED")

    otp_code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = timezone.now() + timedelta(minutes=5)

    LoginOTPChallenge.objects.create(
        phone_number=phone_number,
        otp_hash=make_password(otp_code),
        expires_at=expires_at,
        max_attempts=3,
        status="PENDING",
    )
    return otp_code, None


@api_view(["POST"])
@permission_classes([AllowAny])
def register_user(request):
    """
    Initiates customer registration by storing the unverified PayShieldUser profile
    and issuing a 6-digit phone verification OTP.
    """
    serializer = RegisterInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    phone_number = serializer.validated_data["phone_number"]
    full_name = serializer.validated_data["full_name"]

    # Check if user already exists and is verified
    existing_user = PayShieldUser.objects.filter(phone_number=phone_number).first()
    if existing_user and existing_user.is_phone_verified:
        return Response(
            {
                "error": "An account with this phone number already exists. Please sign in instead.",
                "code": "ACCOUNT_EXISTS",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Provision or update unverified PayShieldUser profile
    PayShieldUser.create_user_with_phone(
        phone_number=phone_number,
        is_phone_verified=False,
        full_name=full_name,
    )

    otp_code, error = _issue_otp_challenge(phone_number)
    if error:
        return Response({"error": error}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    response_data = {
        "message": "Registration initiated. Verification code sent successfully.",
        "phone_number": phone_number,
        "full_name": full_name,
        "expires_in_seconds": 300,
    }

    if settings.DEBUG:
        response_data["dev_otp"] = otp_code
        response_data["warning"] = "Development only: never exposed in production."

    return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([AllowAny])
def request_login_otp(request):
    """
    Generates and issues a 6-digit PayShield login OTP for phone number verification.
    Applies rate-limiting, expires prior pending codes, and hashes the code before storage.
    """
    serializer = RequestOTPInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    phone_number = serializer.validated_data["phone_number"]

    # Verify that an account exists for this mobile number
    payshield_user = PayShieldUser.objects.filter(phone_number=phone_number).first()
    if not payshield_user or not payshield_user.is_phone_verified:
        return Response(
            {
                "error": "No registered account found with this mobile number. Please create an account first.",
                "code": "USER_NOT_FOUND",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    if not payshield_user.is_active:
        return Response(
            {
                "error": "This account is inactive. Please contact customer support.",
                "code": "ACCOUNT_INACTIVE",
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    otp_code, error = _issue_otp_challenge(phone_number)
    if error:
        return Response({"error": error}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    response_data = {
        "message": "Verification code sent successfully.",
        "phone_number": phone_number,
        "expires_in_seconds": 300,
    }

    # Development-only exposure for testing without SMS gateway
    if settings.DEBUG:
        response_data["dev_otp"] = otp_code
        response_data["warning"] = "Development only: never exposed in production."

    return Response(response_data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([AllowAny])
def verify_login_otp(request):
    """
    Verifies the PayShield login OTP, authenticates or provisions the PayShieldUser,
    and issues an expiring authentication token.
    """
    serializer = VerifyOTPInputSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    phone_number = serializer.validated_data["phone_number"]
    submitted_otp = serializer.validated_data["otp"]

    payshield_user = PayShieldUser.objects.filter(phone_number=phone_number).first()
    if not payshield_user:
        return Response(
            {
                "error": "No registered account found with this mobile number. Please create an account first.",
                "code": "USER_NOT_FOUND",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    with transaction.atomic():
        challenge = (
            LoginOTPChallenge.objects.select_for_update()
            .filter(phone_number=phone_number)
            .exclude(status="EXPIRED")
            .order_by("-created_at")
            .first()
        )

        if not challenge:
            return Response(
                {
                    "error": "No active verification request found. Please request a new code."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if challenge.status == "LOCKED" or challenge.attempts >= challenge.max_attempts:
            if challenge.status != "LOCKED":
                challenge.status = "LOCKED"
                challenge.save(update_fields=["status"])
            return Response(
                {
                    "error": "Maximum verification attempts exceeded. Please request a new code."
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        if challenge.is_expired():
            challenge.status = "EXPIRED"
            challenge.save(update_fields=["status"])
            return Response(
                {
                    "error": "Verification code has expired. Please request a new code."
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
                    "error": "Invalid verification code.",
                    "attempts_remaining": max(
                        challenge.max_attempts - challenge.attempts, 0
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        challenge.status = "VERIFIED"
        challenge.verified_at = timezone.now()
        challenge.save(update_fields=["attempts", "status", "verified_at"])

        # Mark phone as verified if completing registration
        if not payshield_user.is_phone_verified:
            payshield_user.is_phone_verified = True
            payshield_user.save(update_fields=["is_phone_verified", "updated_at"])

        # Token lifecycle management
        lifetime_hours = getattr(settings, "PAYSHIELD_TOKEN_LIFETIME_HOURS", 24)
        existing_token = Token.objects.filter(user=payshield_user.user).first()

        if existing_token:
            token_age = timezone.now() - existing_token.created
            if token_age > timedelta(hours=lifetime_hours):
                existing_token.delete()
                token = Token.objects.create(user=payshield_user.user)
            else:
                token = existing_token
        else:
            token = Token.objects.create(user=payshield_user.user)

    return Response(
        {
            "message": "Login successful.",
            "token": token.key,
            "expires_in_hours": lifetime_hours,
            "user": {
                "id": payshield_user.id,
                "full_name": payshield_user.full_name,
                "phone_number": payshield_user.phone_number,
                "is_phone_verified": payshield_user.is_phone_verified,
                "has_active_device": payshield_user.devices.filter(status="ACTIVE").exists(),
                "linked_accounts_count": payshield_user.linked_bank_accounts.filter(
                    is_active=True
                ).count(),
            },
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_current_user_profile(request):
    """
    Returns the authenticated user's profile and count of linked accounts.
    """
    payshield_user = getattr(request.user, "payshield_user", None)
    if not payshield_user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = UserProfileSerializer(payshield_user)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_user(request):
    """
    Revokes the current authentication token and unbinds the push token from the active device
    so no future transaction notifications are delivered to a signed-out device.
    """
    payshield_user = getattr(request.user, "payshield_user", None)
    if payshield_user:
        calling_device_id = request.headers.get("X-Device-ID") or request.META.get("HTTP_X_DEVICE_ID")
        devices_to_clear = payshield_user.devices.filter(status="ACTIVE")
        if calling_device_id:
            specific_dev = devices_to_clear.filter(device_id=calling_device_id).first()
            if specific_dev:
                specific_dev.push_token = ""
                specific_dev.save(update_fields=["push_token"])
            else:
                devices_to_clear.update(push_token="")
        else:
            devices_to_clear.update(push_token="")

    if hasattr(request, "auth") and isinstance(request.auth, Token):
        request.auth.delete()

    return Response(
        {"message": "Logged out successfully."},
        status=status.HTTP_200_OK,
    )
