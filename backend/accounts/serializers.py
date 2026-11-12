import re
from rest_framework import serializers
from .models import PayShieldUser


def clean_and_validate_phone(phone_number: str) -> str:
    cleaned = str(phone_number).strip().replace(" ", "").replace("-", "")
    if cleaned.startswith("+"):
        digits = cleaned[1:]
    else:
        digits = cleaned

    if not digits.isdigit() or len(digits) < 10 or len(digits) > 15:
        raise serializers.ValidationError(
            "Enter a valid mobile number (10 to 15 digits)."
        )
    return digits


class RequestOTPInputSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)

    def validate_phone_number(self, value):
        return clean_and_validate_phone(value)


class RegisterInputSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=120, required=True, allow_blank=False)
    phone_number = serializers.CharField(max_length=20, required=True)

    def validate_full_name(self, value):
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise serializers.ValidationError("Full name must be at least 2 characters long.")
        return cleaned

    def validate_phone_number(self, value):
        return clean_and_validate_phone(value)


class VerifyOTPInputSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    otp = serializers.CharField(max_length=6, min_length=6)

    def validate_phone_number(self, value):
        return clean_and_validate_phone(value)

    def validate_otp(self, value):
        cleaned = value.strip()
        if not cleaned.isdigit() or len(cleaned) != 6:
            raise serializers.ValidationError("OTP must be a 6-digit numeric code.")
        return cleaned


class PayShieldUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayShieldUser
        fields = [
            "id",
            "full_name",
            "phone_number",
            "is_phone_verified",
            "is_active",
            "created_at",
        ]
        read_only_fields = fields


class UserProfileSerializer(serializers.ModelSerializer):
    linked_accounts_count = serializers.SerializerMethodField()
    has_active_device = serializers.SerializerMethodField()

    class Meta:
        model = PayShieldUser
        fields = [
            "id",
            "full_name",
            "phone_number",
            "is_phone_verified",
            "is_active",
            "has_active_device",
            "linked_accounts_count",
            "created_at",
        ]
        read_only_fields = fields

    def get_linked_accounts_count(self, obj) -> int:
        return obj.linked_bank_accounts.filter(is_active=True).count()

    def get_has_active_device(self, obj) -> bool:
        return obj.devices.filter(status="ACTIVE").exists()

