import os
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import PayShieldUser
from .models import LinkedBankAccount
from .serializers import (
    InitiateAccountLinkSerializer,
    LinkAndVerifyAccountSerializer,
    LinkedBankAccountSerializer,
)
from .services import (
    discover_dummy_bank_accounts,
    request_dummy_bank_account_verification,
)


def _get_target_user(request):
    """
    Resolves the PayShieldUser from authenticated request session or token.
    """
    if request.user and request.user.is_authenticated:
        return getattr(request.user, "payshield_user", None)
    return None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_linked_accounts(request):
    """
    Retrieves all linked bank accounts belonging to the authenticated user.
    """
    user = _get_target_user(request)
    if not user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    accounts = LinkedBankAccount.objects.filter(
        user=user,
        is_active=True,
    ).order_by("-linked_at")

    serializer = LinkedBankAccountSerializer(accounts, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def initiate_link_account(request):
    """
    Initiates linking of a bank account for the authenticated user.
    RULE 8: New bank-account links MUST begin unverified (is_verified=False, status='UNVERIFIED').
    Proves connectivity with the bank simulator without immediately granting verification.
    """
    user = _get_target_user(request)
    if not user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = InitiateAccountLinkSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    account_number = serializer.validated_data["account_number"]
    bank_name = serializer.validated_data.get("bank_name", "PayShield Demo Bank")

    # Authoritative ownership validation with Dummy Bank using authenticated user's registered phone
    success, bank_data, status_code = request_dummy_bank_account_verification(
        phone_number=user.phone_number,
        account_number=account_number,
    )

    if not success:
        return Response(
            {
                "error": bank_data.get("error", "Bank account verification failed."),
                "bank_status_code": status_code,
            },
            status=status_code if status_code in [400, 403, 404] else status.HTTP_502_BAD_GATEWAY,
        )

    bank_account_id = bank_data["bank_account_id"]
    bank_customer_id = bank_data["bank_customer_id"]

    # Check for duplicate active links
    existing_link = LinkedBankAccount.objects.filter(
        bank_name=bank_name,
        bank_account_id=bank_account_id,
        is_active=True,
    ).first()

    if existing_link:
        if existing_link.user != user:
            return Response(
                {"error": "This bank account is already linked to another PayShield user."},
                status=status.HTTP_409_CONFLICT,
            )
        if existing_link.is_verified:
            return Response(
                {"error": "This bank account is already linked and verified."},
                status=status.HTTP_409_CONFLICT,
            )
        link = existing_link
    else:
        # Create unverified link per Rule 8
        link = LinkedBankAccount.objects.create(
            user=user,
            bank_name=bank_name,
            bank_customer_id=bank_customer_id,
            bank_account_id=bank_account_id,
            account_number_masked=bank_data["account_number_masked"],
            account_type=bank_data.get("account_type", "SAVINGS"),
            is_verified=False,
            verification_status="UNVERIFIED",
        )

    serializer = LinkedBankAccountSerializer(link)
    return Response(
        {
            "message": "Bank account link initiated. Verification required.",
            "link": serializer.data,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def verify_link_account(request, link_id):
    """
    Transitions an unverified bank account link to VERIFIED after executing
    authoritative server-to-server validation with Dummy Bank.
    """
    user = _get_target_user(request)
    if not user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        link = LinkedBankAccount.objects.get(link_id=link_id, user=user)
    except LinkedBankAccount.DoesNotExist:
        return Response(
            {"error": "Linked bank account not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if link.is_verified:
        return Response(
            {
                "message": "Account is already verified.",
                "link": LinkedBankAccountSerializer(link).data,
            },
            status=status.HTTP_200_OK,
        )

    # Re-verify against Dummy Bank
    success, bank_data, status_code = request_dummy_bank_account_verification(
        phone_number=link.user.phone_number,
        account_id=link.bank_account_id,
    )

    if not success:
        link.mark_failed()
        return Response(
            {
                "error": bank_data.get("error", "Bank rejected verification."),
                "bank_status_code": status_code,
            },
            status=status_code if status_code in [400, 403, 404] else status.HTTP_502_BAD_GATEWAY,
        )

    link.mark_verified()
    return Response(
        {
            "message": "Bank account successfully verified.",
            "link": LinkedBankAccountSerializer(link).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def link_and_verify_account(request):
    """
    Convenience endpoint: Initiates and completes account linking and verification
    for the authenticated user in a single atomic flow.
    """
    user = _get_target_user(request)
    if not user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = LinkAndVerifyAccountSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    account_number = serializer.validated_data["account_number"]
    bank_name = serializer.validated_data.get("bank_name", "PayShield Demo Bank")

    # Authoritative verification with Dummy Bank
    success, bank_data, status_code = request_dummy_bank_account_verification(
        phone_number=user.phone_number,
        account_number=account_number,
    )

    if not success:
        return Response(
            {
                "error": bank_data.get("error", "Bank account verification failed."),
                "bank_status_code": status_code,
            },
            status=status_code if status_code in [400, 403, 404] else status.HTTP_502_BAD_GATEWAY,
        )

    bank_account_id = bank_data["bank_account_id"]
    bank_customer_id = bank_data["bank_customer_id"]

    # Check duplicate link constraints
    existing_link = LinkedBankAccount.objects.filter(
        bank_name=bank_name,
        bank_account_id=bank_account_id,
        is_active=True,
    ).first()

    if existing_link:
        if existing_link.user != user:
            return Response(
                {"error": "This bank account is already linked to another PayShield user."},
                status=status.HTTP_409_CONFLICT,
            )
        existing_link.mark_verified()
        return Response(
            {
                "message": "Bank account verified and updated.",
                "link": LinkedBankAccountSerializer(existing_link).data,
            },
            status=status.HTTP_200_OK,
        )

    link = LinkedBankAccount.objects.create(
        user=user,
        bank_name=bank_name,
        bank_customer_id=bank_customer_id,
        bank_account_id=bank_account_id,
        account_number_masked=bank_data["account_number_masked"],
        account_type=bank_data.get("account_type", "SAVINGS"),
        is_verified=True,
        verification_status="VERIFIED",
    )
    link.mark_verified()

    return Response(
        {
            "message": "Bank account linked and verified successfully.",
            "link": LinkedBankAccountSerializer(link).data,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def discover_bank_accounts(request):
    """
    UPI-style discovery (PhonePe, Paytm, BHIM).
    Queries Dummy Bank for all accounts registered under the authenticated user's mobile number.
    Marks which accounts are already linked in PayShield.
    """
    user = _get_target_user(request)
    if not user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    success, bank_data, status_code = discover_dummy_bank_accounts(user.phone_number)
    if not success:
        return Response(
            {
                "error": bank_data.get("error", "Failed to discover bank accounts."),
                "bank_status_code": status_code,
            },
            status=status_code if status_code in [400, 403, 404] else status.HTTP_502_BAD_GATEWAY,
        )

    # Get already linked account IDs for this user
    already_linked_ids = set(
        LinkedBankAccount.objects.filter(
            user=user,
            is_active=True,
        ).values_list("bank_account_id", flat=True)
    )

    discovered_list = bank_data.get("accounts", [])
    for acc in discovered_list:
        acc["is_already_linked"] = acc["bank_account_id"] in already_linked_ids

    return Response({
        "phone_number": user.phone_number,
        "customer_name": bank_data.get("customer_name", ""),
        "accounts_count": len(discovered_list),
        "accounts": discovered_list,
    }, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def link_discovered_account(request):
    """
    1-Tap UPI-style Bank Account Linking.
    Takes bank_account_id or account_number from discovered list,
    verifies ownership with Dummy Bank, and links it immediately.
    """
    user = _get_target_user(request)
    if not user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    account_number = request.data.get("account_number")
    bank_account_id = request.data.get("bank_account_id")
    bank_name = request.data.get("bank_name", "PayShield Demo Bank")

    if not account_number and not bank_account_id:
        return Response(
            {"error": "account_number or bank_account_id is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    success, bank_data, status_code = request_dummy_bank_account_verification(
        phone_number=user.phone_number,
        account_number=account_number,
        account_id=bank_account_id,
    )

    if not success:
        return Response(
            {
                "error": bank_data.get("error", "Bank account verification failed."),
                "bank_status_code": status_code,
            },
            status=status_code if status_code in [400, 403, 404] else status.HTTP_502_BAD_GATEWAY,
        )

    bank_acc_id = bank_data["bank_account_id"]
    bank_cust_id = bank_data["bank_customer_id"]

    existing_link = LinkedBankAccount.objects.filter(
        bank_name=bank_name,
        bank_account_id=bank_acc_id,
        is_active=True,
    ).first()

    if existing_link:
        if existing_link.user != user:
            return Response(
                {"error": "This bank account is already linked to another PayShield user."},
                status=status.HTTP_409_CONFLICT,
            )
        if not existing_link.is_verified:
            existing_link.mark_verified()
        return Response(
            {
                "message": "Bank account already linked and verified.",
                "link": LinkedBankAccountSerializer(existing_link).data,
            },
            status=status.HTTP_200_OK,
        )

    link = LinkedBankAccount.objects.create(
        user=user,
        bank_name=bank_name,
        bank_customer_id=bank_cust_id,
        bank_account_id=bank_acc_id,
        account_number_masked=bank_data["account_number_masked"],
        account_type=bank_data.get("account_type", "SAVINGS"),
        is_verified=True,
        verification_status="VERIFIED",
    )
    link.mark_verified()

    return Response(
        {
            "message": "Bank account linked successfully via UPI phone discovery.",
            "link": LinkedBankAccountSerializer(link).data,
        },
        status=status.HTTP_201_CREATED,
    )

