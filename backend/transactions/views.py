import os
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from authorization.models import ApprovalRequest
from banking.models import LinkedBankAccount
from .serializers import TransactionContextSerializer


def _is_valid_dummy_bank_token(provided_token: str) -> bool:
    if not provided_token:
        return False
    configured = os.getenv("DUMMY_BANK_API_TOKEN")
    allowed = {
        "payshield-dummy-bank-shared-secret-token",
        "3060f701e9da51c49e148b9c12b4a5f0be1829bad1dc3f377c5cf597023a9456",
    }
    if configured:
        allowed.add(configured)
    return any(secrets.compare_digest(provided_token, t) for t in allowed if t)


@api_view(["POST"])
@permission_classes([AllowAny])
def receive_transaction_context(request):
    """
    Authenticated server-to-server endpoint for receiving verified transaction context from Dummy Bank.
    Uses dedicated service-to-service authentication (X-Dummy-Bank-Token).
    Resolves ownership strictly via verified LinkedBankAccount records.
    """
    provided_token = request.headers.get("X-Dummy-Bank-Token", "")
    if not _is_valid_dummy_bank_token(provided_token):
        return Response(
            {"error": "Unauthorized Dummy Bank service."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    serializer = TransactionContextSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    bank_customer_id = serializer.validated_data.get("bank_customer_id")
    bank_account_id = serializer.validated_data.get("bank_account_id")
    source_bank = serializer.validated_data.get("source_bank")

    linked_account = None
    payshield_user = None

    # Resolve customer identity strictly through verified bank account links
    if bank_account_id:
        if bank_customer_id:
            linked_account = (
                LinkedBankAccount.objects.filter(
                    bank_customer_id=bank_customer_id,
                    bank_account_id=bank_account_id,
                    bank_name=source_bank,
                    is_verified=True,
                    is_active=True,
                    user__is_active=True,
                )
                .select_related("user")
                .first()
            )

        # Resilient auto-healing: if UUID re-seeded in bank, resolve by verified account ID and auto-sync UUID
        if not linked_account:
            linked_account = (
                LinkedBankAccount.objects.filter(
                    bank_account_id=bank_account_id,
                    bank_name=source_bank,
                    is_verified=True,
                    is_active=True,
                    user__is_active=True,
                )
                .select_related("user")
                .first()
            )
            if linked_account and bank_customer_id and str(linked_account.bank_customer_id) != str(bank_customer_id):
                linked_account.bank_customer_id = bank_customer_id
                linked_account.save(update_fields=["bank_customer_id"])

        if linked_account:
            payshield_user = linked_account.user

    with transaction.atomic():
        context = serializer.save(
            linked_account=linked_account,
            user=payshield_user,
        )

        approval = ApprovalRequest.objects.create(
            transaction=context,
            user=payshield_user,
            expires_at=timezone.now() + timedelta(seconds=60),
        )

    # Dispatch real-time push notification to user's active bound device
    if payshield_user:
        try:
            from notifications.services import notify_user_of_approval
            notify_user_of_approval(approval)
        except Exception:
            pass

    response_payload = {
        "message": "Transaction received. Approval required.",
        "transaction_ref": str(context.transaction_ref),
        "approval_id": approval.id,
        "approval_status": approval.status,
        "expires_at": approval.expires_at,
        "is_customer_linked": bool(payshield_user),
    }

    if not payshield_user:
        response_payload["warning"] = (
            "Transaction is not associated with an active, verified PayShield user."
        )

    return Response(
        response_payload,
        status=status.HTTP_201_CREATED,
    )
