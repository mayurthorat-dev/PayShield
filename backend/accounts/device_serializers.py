from rest_framework import serializers
from .models import Device


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = [
            "id",
            "device_id",
            "device_name",
            "platform",
            "app_version",
            "status",
            "registered_at",
            "last_active_at",
            "revoked_at",
            "revocation_reason",
        ]
        read_only_fields = fields


class DeviceRegisterInputSerializer(serializers.Serializer):
    device_id = serializers.UUIDField(required=True)
    device_name = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    platform = serializers.ChoiceField(choices=Device.PLATFORM_CHOICES, default="ANDROID")
    app_version = serializers.CharField(max_length=30, required=False, allow_blank=True, default="1.0.0")


class DeviceReplaceInputSerializer(serializers.Serializer):
    otp = serializers.CharField(max_length=6, min_length=6, required=True)
    device_id = serializers.UUIDField(required=True)
    device_name = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    platform = serializers.ChoiceField(choices=Device.PLATFORM_CHOICES, default="ANDROID")
    app_version = serializers.CharField(max_length=30, required=False, allow_blank=True, default="1.0.0")

    def validate_otp(self, value):
        cleaned = value.strip()
        if not cleaned.isdigit() or len(cleaned) != 6:
            raise serializers.ValidationError("Verification OTP must be 6 numeric digits.")
        return cleaned


class DeviceRevokeInputSerializer(serializers.Serializer):
    device_id = serializers.UUIDField(required=False)
    reason = serializers.CharField(max_length=120, required=False, default="MANUAL_REVOCATION")

