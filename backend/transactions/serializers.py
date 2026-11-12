from rest_framework import serializers
from .models import TransactionContext


class TransactionContextSerializer(serializers.ModelSerializer):
    bank_customer_id = serializers.UUIDField(required=False, allow_null=True)
    bank_account_id = serializers.IntegerField(required=False, allow_null=True)
    sender_account_masked = serializers.CharField(
        max_length=30, required=False, allow_blank=True
    )
    linked_account_id = serializers.PrimaryKeyRelatedField(
        source="linked_account", read_only=True
    )
    user_id = serializers.PrimaryKeyRelatedField(
        source="user.id", read_only=True
    )

    class Meta:
        model = TransactionContext
        fields = [
            "transaction_ref",
            "source_bank",
            "source_transaction_id",
            "transaction_type",
            "sender_name",
            "sender_account_masked",
            "bank_customer_id",
            "bank_account_id",
            "linked_account_id",
            "user_id",
            "recipient_name",
            "recipient_account_masked",
            "amount",
            "currency",
            "description",
            "otp_verified",
            "received_at",
        ]
        read_only_fields = ["transaction_ref", "received_at", "linked_account_id", "user_id"]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Amount must be greater than zero."
            )
        return value

    def validate_otp_verified(self, value):
        if value is not True:
            raise serializers.ValidationError(
                "Only OTP-verified transactions can be submitted."
            )
        return value
