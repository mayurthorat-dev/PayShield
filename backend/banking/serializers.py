from rest_framework import serializers
from .models import LinkedBankAccount


class LinkedBankAccountSerializer(serializers.ModelSerializer):
    user_phone = serializers.CharField(source="user.phone_number", read_only=True)

    class Meta:
        model = LinkedBankAccount
        fields = [
            "link_id",
            "user_phone",
            "bank_name",
            "bank_customer_id",
            "bank_account_id",
            "account_number_masked",
            "account_type",
            "is_verified",
            "verification_status",
            "is_active",
            "linked_at",
            "verified_at",
        ]
        read_only_fields = [
            "link_id",
            "user_phone",
            "bank_customer_id",
            "bank_account_id",
            "account_number_masked",
            "account_type",
            "is_verified",
            "verification_status",
            "linked_at",
            "verified_at",
        ]


class InitiateAccountLinkSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15, required=False)
    account_number = serializers.CharField(max_length=30, required=True)
    bank_name = serializers.CharField(
        max_length=100, default="PayShield Demo Bank", required=False
    )

    def validate_account_number(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Account number cannot be empty.")
        return cleaned


class LinkAndVerifyAccountSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15, required=False)
    account_number = serializers.CharField(max_length=30, required=True)
    bank_name = serializers.CharField(
        max_length=100, default="PayShield Demo Bank", required=False
    )

    def validate_account_number(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Account number cannot be empty.")
        return cleaned

