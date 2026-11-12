from rest_framework import serializers


class OTPVerifySerializer(serializers.Serializer):
    transaction_id = serializers.UUIDField()
    otp = serializers.RegexField(
        regex=r"^\d{6}$",
        error_messages={
            "invalid": "OTP must contain exactly six digits."
        }
    )