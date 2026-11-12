from rest_framework import serializers
from .models import BankTransaction


class TransactionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankTransaction
        fields = [
            "transaction_id",
            "sender_account",
            "beneficiary",
            "transaction_type",
            "amount",
            "currency",
            "description",
            "status",
            "created_at",
        ]
        read_only_fields = [
            "transaction_id",
            "currency",
            "status",
            "created_at",
        ]

    def to_internal_value(self, data):
        data = data.copy() if hasattr(data, "copy") else dict(data)
        raw_type = data.get("transaction_type")
        if raw_type in ["UPI", "IMPS", "NEFT", "RTGS", "BANK_TRANSFER"]:
            data["transaction_type"] = "BANK_TRANSFER"
            if raw_type != "BANK_TRANSFER":
                current_desc = data.get("description", "") or ""
                if f"[{raw_type}]" not in current_desc:
                    data["description"] = f"[{raw_type}] {current_desc}".strip()
        return super().to_internal_value(data)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Amount must be greater than zero."
            )
        return value
