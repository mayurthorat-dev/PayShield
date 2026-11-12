import os
import secrets
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction as db_transaction
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
import requests

from bank_audit.models import BankTransactionEvent
from payments.models import BankTransaction

from .models import OTPChallenge
from .serializers import OTPGenerateSerializer
from .verify_serializers import OTPVerifySerializer


@api_view(["POST"])
def generate_otp(request):
    serializer = OTPGenerateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    transaction_id = serializer.validated_data["transaction_id"]

    try:
        transaction = BankTransaction.objects.get(transaction_id=transaction_id)
    except BankTransaction.DoesNotExist:
        return Response(
            {"error": "Transaction not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if transaction.status != "CREATED":
        return Response(
            {"error": "OTP can only be generated for a CREATED transaction."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    otp = f"{secrets.randbelow(1_000_000):06d}"

    OTPChallenge.objects.create(
        transaction=transaction,
        otp_hash=make_password(otp),
        expires_at=timezone.now() + timedelta(minutes=5),
    )

    transaction.status = "OTP_PENDING"
    transaction.save(update_fields=["status", "updated_at"])

    BankTransactionEvent.objects.create(
        transaction=transaction,
        event_type="OTP_GENERATED",
        description="OTP generated for local prototype testing.",
    )

    return Response(
        {
            "message": "OTP generated successfully.",
            "transaction_id": str(transaction.transaction_id),
            "expires_in_seconds": 300,
            "dev_otp": otp,
            "warning": "Development only. Never return OTPs in production.",
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
def verify_otp(request):
    serializer = OTPVerifySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    transaction_id = serializer.validated_data["transaction_id"]
    submitted_otp = serializer.validated_data["otp"]

    with db_transaction.atomic():
        try:
            bank_tx = BankTransaction.objects.select_for_update().get(
                transaction_id=transaction_id
            )
        except BankTransaction.DoesNotExist:
            return Response(
                {"error": "Transaction not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if bank_tx.status != "OTP_PENDING":
            return Response(
                {"error": "Transaction is not awaiting OTP verification."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        challenge = (
            OTPChallenge.objects.select_for_update()
            .filter(transaction=bank_tx, status="PENDING")
            .order_by("-created_at")
            .first()
        )

        if challenge is None:
            return Response(
                {"error": "No pending OTP challenge found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if timezone.now() >= challenge.expires_at:
            challenge.status = "EXPIRED"
            challenge.save(update_fields=["status"])
            bank_tx.status = "FAILED"
            bank_tx.save(update_fields=["status", "updated_at"])

            BankTransactionEvent.objects.create(
                transaction=bank_tx,
                event_type="OTP_EXPIRED",
                description="OTP expired before verification.",
            )

            return Response(
                {"error": "OTP has expired. Start a new transaction."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if challenge.attempts >= challenge.max_attempts:
            challenge.status = "LOCKED"
            challenge.save(update_fields=["status"])
            bank_tx.status = "FAILED"
            bank_tx.save(update_fields=["status", "updated_at"])

            return Response(
                {"error": "Maximum OTP attempts reached."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        challenge.attempts += 1

        if not check_password(submitted_otp, challenge.otp_hash):
            if challenge.attempts >= challenge.max_attempts:
                challenge.status = "LOCKED"
                bank_tx.status = "FAILED"
                bank_tx.save(update_fields=["status", "updated_at"])

            challenge.save(update_fields=["attempts", "status"])

            BankTransactionEvent.objects.create(
                transaction=bank_tx,
                event_type="OTP_INVALID",
                description="Incorrect OTP submitted.",
            )

            return Response(
                {
                    "error": "Incorrect OTP.",
                    "attempts_remaining": max(
                        challenge.max_attempts - challenge.attempts, 0
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        challenge.status = "VERIFIED"
        challenge.verified_at = timezone.now()
        challenge.save(update_fields=["attempts", "status", "verified_at"])

        bank_tx.status = "OTP_VERIFIED"
        bank_tx.save(update_fields=["status", "updated_at"])

        BankTransactionEvent.objects.create(
            transaction=bank_tx,
            event_type="OTP_VERIFIED",
            description="OTP successfully verified.",
        )

    # Send verified transaction context to PayShield outside atomic block
    callback_url = os.getenv(
        "PAYSHIELD_TRANSACTION_CONTEXT_URL"
    ) or "http://127.0.0.1:8000/api/integration/transaction-context/"

    if not callback_url:
        return Response(
            {
                "error": "PayShield integration URL is not configured.",
                "transaction_id": str(bank_tx.transaction_id),
                "transaction_status": bank_tx.status,
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    recipient_name = ""
    recipient_account_masked = ""

    if bank_tx.beneficiary:
        recipient_name = bank_tx.beneficiary.recipient_name
        recipient_number = bank_tx.beneficiary.recipient_account_number
        recipient_account_masked = (
            "*" * max(len(recipient_number) - 4, 0) + recipient_number[-4:]
        )

    sender_number = bank_tx.sender_account.account_number
    sender_account_masked = (
        "*" * max(len(sender_number) - 4, 0) + sender_number[-4:]
    )

    payload = {
        "source_bank": bank_tx.sender_account.bank_name,
        "source_transaction_id": str(bank_tx.transaction_id),
        "transaction_type": bank_tx.transaction_type,
        "sender_name": bank_tx.sender_account.customer.full_name,
        "sender_account_masked": sender_account_masked,
        "bank_customer_id": str(bank_tx.sender_account.customer.customer_id),
        "bank_account_id": bank_tx.sender_account.account_id,
        "recipient_name": recipient_name,
        "recipient_account_masked": recipient_account_masked,
        "amount": str(bank_tx.amount),
        "currency": bank_tx.currency,
        "description": bank_tx.description,
        "otp_verified": True,
    }

    api_token = os.getenv("PAYSHIELD_API_TOKEN") or "payshield-dummy-bank-shared-secret-token"

    if not api_token:
        return Response(
            {"error": "PayShield service token is not configured."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        payshield_response = requests.post(
            callback_url,
            json=payload,
            headers={"X-Dummy-Bank-Token": api_token},
            timeout=5,
        )
    except requests.RequestException:
        return Response(
            {
                "error": "OTP verified, but PayShield could not be reached.",
                "transaction_id": str(bank_tx.transaction_id),
                "transaction_status": bank_tx.status,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if not payshield_response.ok:
        return Response(
            {
                "error": "OTP verified, but PayShield rejected the context.",
                "transaction_id": str(bank_tx.transaction_id),
                "transaction_status": bank_tx.status,
                "payshield_status": payshield_response.status_code,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    try:
        payshield_result = payshield_response.json()
    except ValueError:
        return Response(
            {"error": "PayShield returned an invalid response."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    expires_at_value = payshield_result.get("expires_at")

    if not isinstance(expires_at_value, str):
        return Response(
            {"error": "PayShield did not return an approval expiry."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    expires_at = parse_datetime(expires_at_value)

    if expires_at is None or timezone.is_naive(expires_at):
        return Response(
            {"error": "PayShield returned an invalid approval expiry."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # Save the deadline and update the transaction status.
    with db_transaction.atomic():
        bank_tx = (
            BankTransaction.objects.select_for_update()
            .get(transaction_id=transaction_id)
        )

        if bank_tx.status != "OTP_VERIFIED":
            return Response(
                {"error": "Transaction status changed unexpectedly."},
                status=status.HTTP_409_CONFLICT,
            )

        bank_tx.payshield_expires_at = expires_at
        bank_tx.status = "AWAITING_APPROVAL"
        bank_tx.save(
            update_fields=[
                "payshield_expires_at",
                "status",
                "updated_at",
            ]
        )

        BankTransactionEvent.objects.create(
            transaction=bank_tx,
            event_type="PAYSHIELD_CONTEXT_RECEIVED",
            description="PayShield approval deadline saved.",
        )

    return Response(
        {
            "message": "OTP verified and transaction sent to PayShield.",
            "transaction_id": str(bank_tx.transaction_id),
            "transaction_status": bank_tx.status,
            "payshield": payshield_result,
        },
        status=status.HTTP_200_OK,
    )
