import os
import secrets
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import BankAccount


@api_view(["POST"])
def verify_account_link(request):
    """
    Server-to-server endpoint for PayShield to verify ownership of a bank account.
    Validates X-PayShield-Token, verifies that the target account is active,
    and proves that the customer's registered bank phone number matches the PayShield user's phone number.

    PROTOTYPE NOTE: In a production banking environment, this would involve Open Banking APIs
    or an Account Aggregator consent framework.
    """
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

    phone_number = request.data.get("phone_number")
    account_number = request.data.get("account_number")
    account_id = request.data.get("account_id")

    if not phone_number:
        return Response(
            {"error": "phone_number is required for ownership verification."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not account_number and not account_id:
        return Response(
            {"error": "account_number or account_id is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Clean phone number for reliable matching
    cleaned_phone = str(phone_number).strip().replace(" ", "").replace("-", "")

    # Look up account
    try:
        if account_number:
            account = BankAccount.objects.select_related("customer").get(
                account_number=str(account_number).strip()
            )
        else:
            account = BankAccount.objects.select_related("customer").get(
                account_id=account_id
            )
    except BankAccount.DoesNotExist:
        return Response(
            {
                "verified": False,
                "error": "Bank account not found.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    if account.status != "ACTIVE":
        return Response(
            {
                "verified": False,
                "error": f"Bank account is {account.status.lower()} and cannot be linked.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    customer = account.customer
    if not customer.is_active:
        return Response(
            {
                "verified": False,
                "error": "Customer bank profile is inactive.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    bank_phone = str(customer.phone_number).strip().replace(" ", "").replace("-", "")

    # Enforce phone number ownership match
    if bank_phone != cleaned_phone:
        return Response(
            {
                "verified": False,
                "error": "Customer identity mismatch. This bank account is registered to a different mobile number.",
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    # Success: Return trusted bank reference without exposing balance, PIN, or full account secrets
    account_raw = account.account_number
    masked = "*" * max(len(account_raw) - 4, 0) + account_raw[-4:]

    return Response(
        {
            "verified": True,
            "bank_name": account.bank_name,
            "bank_customer_id": str(customer.customer_id),
            "bank_account_id": account.account_id,
            "account_number_masked": masked,
            "account_type": account.account_type,
            "customer_name": customer.full_name,
            "simulation_note": "Simulated Dummy Bank verification for prototype.",
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
def discover_accounts_by_phone(request):
    """
    UPI / NetBanking discovery endpoint (like PhonePe, BHIM, Paytm).
    Finds all active bank accounts registered under the customer's verified mobile number.
    """
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

    phone_number = request.data.get("phone_number")
    if not phone_number:
        return Response(
            {"error": "phone_number is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    cleaned_phone = str(phone_number).strip().replace(" ", "").replace("-", "")
    if cleaned_phone.startswith("+91"):
        cleaned_phone = cleaned_phone[3:]
    elif cleaned_phone.startswith("91") and len(cleaned_phone) == 12:
        cleaned_phone = cleaned_phone[2:]

    accounts = (
        BankAccount.objects.filter(
            customer__phone_number=cleaned_phone,
            customer__is_active=True,
            status="ACTIVE",
        )
        .select_related("customer")
        .order_by("account_id")
    )

    discovered = []
    customer_name = ""
    for acc in accounts:
        customer_name = acc.customer.full_name
        acc_raw = acc.account_number
        masked = "•••• " + acc_raw[-4:]
        discovered.append({
            "bank_account_id": acc.account_id,
            "bank_customer_id": str(acc.customer.customer_id),
            "bank_name": acc.bank_name,
            "account_number": acc.account_number,
            "account_number_masked": masked,
            "account_type": acc.account_type,
            "ifsc_code": acc.ifsc_code,
            "balance": str(acc.balance),
            "currency": acc.currency,
            "customer_name": acc.customer.full_name,
        })

    return Response({
        "phone_number": cleaned_phone,
        "customer_name": customer_name,
        "accounts_count": len(discovered),
        "accounts": discovered,
    }, status=status.HTTP_200_OK)

