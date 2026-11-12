import os
import random
import requests

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.device_security import validate_device_binding
from audit.services import log_security_event
from .models import ApprovalRequest
from .serializers import ApprovalRequestSerializer


def _reconcile_expired_approvals(payshield_user):
    """
    Reconciles any pending approvals whose timer has expired, informing the upstream bank.
    """
    now = timezone.now()
    expired_approvals = ApprovalRequest.objects.filter(
        user=payshield_user,
        status="PENDING",
        expires_at__lte=now,
    ).select_related("transaction")

    callback_url = (
        os.getenv("DUMMY_BANK_DECISION_URL")
        or "http://127.0.0.1:8001/api/transactions/decision/"
    )
    api_token = (
        os.getenv("DUMMY_BANK_API_TOKEN")
        or "payshield-dummy-bank-shared-secret-token"
    )

    for approval in expired_approvals:
        if not callback_url or not api_token:
            continue

        payload = {
            "source_transaction_id": approval.transaction.source_transaction_id,
            "decision": "EXPIRED",
        }

        try:
            bank_response = requests.post(
                callback_url,
                json=payload,
                headers={"X-PayShield-Token": api_token},
                timeout=5,
            )
        except requests.RequestException:
            continue

        if bank_response.ok:
            approval.status = "EXPIRED"
            approval.save(update_fields=["status"])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pending_approvals(request):
    """
    Returns pending approvals strictly owned by the authenticated PayShield user.
    Lazily reconciles any expired approvals for this user before returning the active list.
    """
    payshield_user = getattr(request.user, "payshield_user", None)
    if not payshield_user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Enforce device binding if user has registered an active device
    is_valid, err_resp = validate_device_binding(request, payshield_user)
    if not is_valid:
        return err_resp

    _reconcile_expired_approvals(payshield_user)

    # Fetch strictly this user's active pending approvals
    approvals = (
        ApprovalRequest.objects.filter(
            user=payshield_user,
            status="PENDING",
            expires_at__gt=timezone.now(),
        )
        .select_related("transaction")
        .order_by("-created_at")
    )

    serializer = ApprovalRequestSerializer(approvals, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def approval_history(request):
    """
    Returns the recent approval transaction history (APPROVED, DENIED, EXPIRED, PENDING)
    strictly for the authenticated PayShield user.
    """
    payshield_user = getattr(request.user, "payshield_user", None)
    if not payshield_user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    is_valid, err_resp = validate_device_binding(request, payshield_user)
    if not is_valid:
        return err_resp

    _reconcile_expired_approvals(payshield_user)

    approvals = (
        ApprovalRequest.objects.filter(user=payshield_user)
        .select_related("transaction")
        .order_by("-created_at")[:50]
    )

    serializer = ApprovalRequestSerializer(approvals, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def report_cyber_crime(request, approval_id):
    """
    Logs a cyber crime report / scam alert for a suspicious or denied transaction.
    Records tamper-evident audit evidence, assigns an official complaint tracking reference,
    and returns 1930 Helpline and portal assistance details for the victim.
    """
    payshield_user = getattr(request.user, "payshield_user", None)
    if not payshield_user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    is_valid, err_resp = validate_device_binding(request, payshield_user)
    if not is_valid:
        return err_resp

    try:
        approval = (
            ApprovalRequest.objects.select_related("transaction")
            .get(pk=approval_id)
        )
    except ApprovalRequest.DoesNotExist:
        return Response(
            {"error": "Approval request not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if approval.user_id != payshield_user.id:
        return Response(
            {"error": "You do not have permission to report this approval."},
            status=status.HTTP_403_FORBIDDEN,
        )

    scam_category = request.data.get("category", "SUSPICIOUS_UNAUTHORIZED")
    user_notes = request.data.get("notes", "")

    # If already reported, return existing reference
    if approval.is_reported_fraud and approval.fraud_report_id:
        return Response(
            {
                "message": "Transaction has already been reported to Cyber Crime authorities.",
                "complaint_ref": approval.fraud_report_id,
                "helpline": "1930",
                "portal_url": "https://cybercrime.gov.in",
                "approval_id": approval.id,
                "already_reported": True,
            },
            status=status.HTTP_200_OK,
        )

    # Generate official reference ID: NCR-<YEAR>-<6DIGITS>
    random_digits = random.randint(100000, 999999)
    complaint_ref = f"NCR-{timezone.now().year}-{random_digits}"

    approval.is_reported_fraud = True
    approval.fraud_report_id = complaint_ref
    approval.save(update_fields=["is_reported_fraud", "fraud_report_id"])

    # Log tamper-evident audit event
    tx = approval.transaction
    amount_str = str(tx.amount) if tx else ""
    recipient_name = tx.recipient_name if tx else ""
    recipient_account = tx.recipient_account_masked if tx else ""
    tx_ref = str(tx.transaction_ref) if tx else ""

    log_security_event(
        event_type="CYBER_CRIME_REPORTED",
        user=payshield_user,
        device_id=request.headers.get("X-Device-ID", ""),
        ip_address=request.META.get("REMOTE_ADDR", ""),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        details={
            "approval_id": approval.id,
            "complaint_ref": complaint_ref,
            "transaction_ref": tx_ref,
            "amount": amount_str,
            "recipient_name": recipient_name,
            "recipient_account": recipient_account,
            "scam_category": scam_category,
            "user_notes": user_notes[:500],
            "approval_status": approval.status,
            "helpline": "1930",
            "portal": "https://cybercrime.gov.in",
        },
    )

    return Response(
        {
            "message": "Incident report logged successfully. You can quote this reference number when contacting the National Cyber Crime Helpline (1930).",
            "complaint_ref": complaint_ref,
            "helpline": "1930",
            "portal_url": "https://cybercrime.gov.in",
            "approval_id": approval.id,
            "already_reported": False,
            "reported_at": timezone.now().isoformat(),
            "summary": {
                "amount": amount_str,
                "currency": tx.currency if tx else "INR",
                "recipient_name": recipient_name,
                "scam_category": scam_category,
            },
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def decide_approval(request, approval_id):
    """
    Processes an Approve or Deny decision for an approval request.
    Strictly verifies object-level ownership: only the user who owns the linked
    bank account can decide the approval.
    """
    decision = request.data.get("decision")

    if decision not in ["APPROVED", "DENIED"]:
        return Response(
            {"error": "Decision must be APPROVED or DENIED."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    payshield_user = getattr(request.user, "payshield_user", None)
    if not payshield_user:
        return Response(
            {"error": "Authenticated user is not registered as a PayShield customer."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Enforce device binding if user has registered an active device
    is_valid, err_resp = validate_device_binding(request, payshield_user)
    if not is_valid:
        return err_resp

    callback_url = (
        os.getenv("DUMMY_BANK_DECISION_URL")
        or "http://127.0.0.1:8001/api/transactions/decision/"
    )
    api_token = (
        os.getenv("DUMMY_BANK_API_TOKEN")
        or "payshield-dummy-bank-shared-secret-token"
    )

    if not callback_url or not api_token:
        return Response(
            {"error": "Dummy Bank integration is not configured."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    with transaction.atomic():
        try:
            approval = (
                ApprovalRequest.objects.select_for_update()
                .select_related("transaction")
                .get(pk=approval_id)
            )
        except ApprovalRequest.DoesNotExist:
            return Response(
                {"error": "Approval request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # STRICT OBJECT-LEVEL AUTHORIZATION CHECK
        if approval.user_id != payshield_user.id:
            return Response(
                {"error": "You do not have permission to access or decide this approval."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if approval.status != "PENDING":
            return Response(
                {
                    "error": "This approval is no longer pending.",
                    "current_status": approval.status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        if timezone.now() >= approval.expires_at:
            payload = {
                "source_transaction_id": approval.transaction.source_transaction_id,
                "decision": "EXPIRED",
            }

            try:
                bank_response = requests.post(
                    callback_url,
                    json=payload,
                    headers={"X-PayShield-Token": api_token},
                    timeout=5,
                )
            except requests.RequestException:
                return Response(
                    {"error": "Approval expired; Dummy Bank could not be reached."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            if not bank_response.ok:
                return Response(
                    {"error": "Dummy Bank did not confirm expiry cancellation."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            approval.status = "EXPIRED"
            approval.save(update_fields=["status"])

            return Response(
                {"error": "Approval request has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = {
            "source_transaction_id": approval.transaction.source_transaction_id,
            "decision": decision,
        }

        try:
            bank_response = requests.post(
                callback_url,
                json=payload,
                headers={"X-PayShield-Token": api_token},
                timeout=5,
            )
        except requests.RequestException:
            return Response(
                {
                    "error": "Could not contact Dummy Bank.",
                    "message": "Verify the bank transaction status before retrying.",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not bank_response.ok:
            bank_error_msg = ""
            try:
                b_json = bank_response.json()
                bank_error_msg = b_json.get("error") or b_json.get("detail") or ""
            except Exception:
                bank_error_msg = bank_response.text[:200]
            err_title = f"Dummy Bank rejected the decision: {bank_error_msg}" if bank_error_msg else "Dummy Bank rejected the decision."
            return Response(
                {
                    "error": err_title,
                    "bank_status_code": bank_response.status_code,
                    "bank_response": bank_response.text[:500],
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        approval.status = decision
        approval.decided_at = timezone.now()
        approval.save(update_fields=["status", "decided_at"])

    try:
        bank_result = bank_response.json()
    except ValueError:
        bank_result = {"message": "Dummy Bank accepted the decision."}

    return Response(
        {
            "message": f"Transaction {decision.lower()}.",
            "approval_id": approval_id,
            "decision": decision,
            "transaction_ref": str(approval.transaction.transaction_ref),
            "bank_response": bank_result,
        },
        status=status.HTTP_200_OK,
    )
