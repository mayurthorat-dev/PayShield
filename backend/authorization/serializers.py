from rest_framework import serializers
from .models import ApprovalRequest


class ApprovalRequestSerializer(serializers.ModelSerializer):
    transaction_ref = serializers.UUIDField(
        source="transaction.transaction_ref",
        read_only=True,
    )
    transaction_type = serializers.CharField(
        source="transaction.transaction_type",
        read_only=True,
    )
    amount = serializers.DecimalField(
        source="transaction.amount",
        max_digits=14,
        decimal_places=2,
        read_only=True,
    )
    currency = serializers.CharField(
        source="transaction.currency",
        read_only=True,
    )
    source_bank = serializers.CharField(
        source="transaction.source_bank",
        read_only=True,
    )
    sender_name = serializers.CharField(
        source="transaction.sender_name",
        read_only=True,
    )
    sender_account_masked = serializers.CharField(
        source="transaction.sender_account_masked",
        read_only=True,
    )
    recipient_name = serializers.CharField(
        source="transaction.recipient_name",
        read_only=True,
    )
    recipient_account_masked = serializers.CharField(
        source="transaction.recipient_account_masked",
        read_only=True,
    )
    description = serializers.CharField(
        source="transaction.description",
        read_only=True,
    )

    class Meta:
        model = ApprovalRequest
        fields = [
            "id",
            "transaction_ref",
            "transaction_type",
            "amount",
            "currency",
            "source_bank",
            "sender_name",
            "sender_account_masked",
            "recipient_name",
            "recipient_account_masked",
            "description",
            "status",
            "is_reported_fraud",
            "fraud_report_id",
            "expires_at",
            "created_at",
        ]
