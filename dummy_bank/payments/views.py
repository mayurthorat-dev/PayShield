import os
import secrets
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from django.utils import timezone
from django.db import transaction as db_transaction
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.models import BankAccount
from bank_audit.models import BankTransactionEvent

from .models import BankTransaction, Beneficiary
from .serializers import TransactionCreateSerializer


class TransactionCreateView(generics.CreateAPIView):
    queryset = BankTransaction.objects.all()
    serializer_class = TransactionCreateSerializer
    permission_classes = [AllowAny]
    authentication_classes = []


@api_view(["POST"])
def receive_payshield_decision(request):
    expected_token = os.getenv("PAYSHIELD_API_TOKEN") or "payshield-dummy-bank-shared-secret-token"
    provided_token = request.headers.get("X-PayShield-Token", "")

    if (
        not expected_token
        or not provided_token
        or not secrets.compare_digest(provided_token, expected_token)
    ):
        return Response(
            {"error": "Unauthorized PayShield service."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    source_transaction_id = request.data.get("source_transaction_id")
    decision = request.data.get("decision")

    if not source_transaction_id:
        return Response(
            {"error": "source_transaction_id is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if decision not in ["APPROVED", "DENIED", "EXPIRED"]:
        return Response(
            {"error": "Decision must be APPROVED, DENIED, or EXPIRED."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with db_transaction.atomic():
        try:
            bank_tx = BankTransaction.objects.select_for_update().get(
                transaction_id=source_transaction_id
            )
        except (BankTransaction.DoesNotExist, ValueError):
            return Response(
                {"error": "Transaction not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if bank_tx.status not in ["OTP_VERIFIED", "AWAITING_APPROVAL"]:
            return Response(
                {
                    "error": "Transaction is not awaiting a decision.",
                    "current_status": bank_tx.status,
                },
                status=status.HTTP_409_CONFLICT,
            )
            
        if bank_tx.payshield_expires_at is None:
            return Response(
                {"error": "PayShield approval expiry is missing."},
                status=status.HTTP_409_CONFLICT,
            )
            
        # Handle explicitly passed EXPIRED decision or time-based expiration check
        if decision == "EXPIRED" or timezone.now() >= bank_tx.payshield_expires_at:
            bank_tx.status = "CANCELLED"
            bank_tx.save(update_fields=["status", "updated_at"])

            event_type = "PAYSHIELD_APPROVAL_EXPIRED"
            description = (
                "PayShield approval expired; transaction cancelled."
                if decision == "EXPIRED"
                else "Late PayShield decision rejected; transaction cancelled."
            )

            BankTransactionEvent.objects.create(
                transaction=bank_tx,
                event_type=event_type,
                description=description,
            )

            error_msg = (
                "Expired transaction cancelled."
                if decision == "EXPIRED"
                else "PayShield approval has expired. Transaction cancelled."
            )
            
            return Response(
                {
                    "error" if decision != "EXPIRED" else "message": error_msg,
                    "transaction_id": str(bank_tx.transaction_id),
                    "status": bank_tx.status,
                },
                status=status.HTTP_409_CONFLICT if decision != "EXPIRED" else status.HTTP_200_OK,
            )
        
        if decision == "DENIED":
            bank_tx.status = "CANCELLED"
            bank_tx.save(update_fields=["status", "updated_at"])

            BankTransactionEvent.objects.create(
                transaction=bank_tx,
                event_type="PAYSHIELD_DENIED",
                description="PayShield denied the transaction.",
            )

            return Response({
                "message": "Transaction cancelled.",
                "transaction_id": str(bank_tx.transaction_id),
                "status": bank_tx.status,
            })

        sender = BankAccount.objects.select_for_update().get(
            account_id=bank_tx.sender_account_id
        )

        if sender.status != "ACTIVE":
            return Response(
                {"error": "Sender account is not active."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if sender.balance < bank_tx.amount:
            bank_tx.status = "FAILED"
            bank_tx.save(update_fields=["status", "updated_at"])
            return Response(
                {"error": "Insufficient balance."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        recipient = None

        if bank_tx.transaction_type == "BANK_TRANSFER":
            if bank_tx.beneficiary is None:
                return Response(
                    {"error": "A beneficiary is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Intra-bank transfer check (if recipient holds account at Dummy Bank)
            recipient = (
                BankAccount.objects.select_for_update()
                .filter(account_number=bank_tx.beneficiary.recipient_account_number)
                .first()
            )

            # If recipient has an internal account at Dummy Bank, verify it is active
            if recipient is not None and recipient.status != "ACTIVE":
                return Response(
                    {"error": "Recipient account is not active."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        sender.balance -= bank_tx.amount
        sender.save(update_fields=["balance"])

        if recipient is not None:
            recipient.balance += bank_tx.amount
            recipient.save(update_fields=["balance"])

        bank_tx.status = "COMPLETED"
        
        bank_tx.save(update_fields=["status", "updated_at"])

        BankTransactionEvent.objects.create(
            transaction=bank_tx,
            event_type="PAYSHIELD_APPROVED",
            description="PayShield approved the transaction; payment completed.",
        )

        return Response({
            "message": "Transaction completed successfully.",
            "transaction_id": str(bank_tx.transaction_id),
            "status": bank_tx.status,
        }, status=status.HTTP_200_OK)



@ensure_csrf_cookie
def portal_view(request):
    """
    Renders the modern Core Banking Web Portal for Dummy Bank.
    """
    return render(request, "portal.html")


@api_view(["GET"])
def portal_data_api(request):
    """
    Supplies account and beneficiary lists for the Dummy Bank portal UI.
    """
    accounts = (
        BankAccount.objects.filter(status="ACTIVE")
        .select_related("customer")
        .order_by("account_id")[:102]
    )

    acc_list = []
    for a in accounts:
        acc_list.append({
            "account_id": a.account_id,
            "account_number": a.account_number,
            "account_number_masked": "•••• " + a.account_number[-4:],
            "customer_name": a.customer.full_name,
            "customer_phone": a.customer.phone_number,
            "bank_name": a.bank_name,
            "account_type": a.account_type,
            "balance": str(a.balance),
            "currency": a.currency,
        })

    beneficiaries = (
        Beneficiary.objects.filter(is_active=True)
        .order_by("recipient_name")
    )
    b_list = []
    seen = set()
    for b in beneficiaries:
        key = (b.recipient_name, b.recipient_account_number)
        if key not in seen:
            seen.add(key)
            b_list.append({
                "beneficiary_id": b.beneficiary_id,
                "owner_account_id": b.owner_account_id,
                "recipient_name": b.recipient_name,
                "recipient_bank_name": b.recipient_bank_name,
                "recipient_account_number": b.recipient_account_number,
                "recipient_ifsc": b.recipient_ifsc,
            })

    return Response({
        "accounts": acc_list,
        "beneficiaries": b_list,
    }, status=status.HTTP_200_OK)


@api_view(["GET"])
def transaction_status_api(request, transaction_id):
    """
    Allows the Web Portal to poll the live status of an initiated transaction.
    Reflects when PayShield approves, denies, or lets the transaction expire.
    """
    try:
        tx = BankTransaction.objects.select_related(
            "sender_account__customer",
            "beneficiary"
        ).get(transaction_id=transaction_id)
    except BankTransaction.DoesNotExist:
        return Response({"error": "Transaction not found."}, status=status.HTTP_404_NOT_FOUND)

    recipient_name = tx.beneficiary.recipient_name if tx.beneficiary else "Merchant"
    recipient_acc = tx.beneficiary.recipient_account_number if tx.beneficiary else "N/A"

    return Response({
        "transaction_id": str(tx.transaction_id),
        "status": tx.status,
        "amount": str(tx.amount),
        "currency": tx.currency,
        "transaction_type": tx.transaction_type,
        "sender_name": tx.sender_account.customer.full_name,
        "sender_account": tx.sender_account.account_number,
        "sender_balance": str(tx.sender_account.balance),
        "recipient_name": recipient_name,
        "recipient_account": recipient_acc,
        "description": tx.description,
        "payshield_expires_at": tx.payshield_expires_at,
        "updated_at": tx.updated_at,
    }, status=status.HTTP_200_OK)
