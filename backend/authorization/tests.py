from datetime import timedelta
import os
import uuid
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import PayShieldUser, LoginOTPChallenge
from audit.models import SecurityAuditEvent
from authorization.models import ApprovalRequest
from banking.models import LinkedBankAccount
from transactions.models import TransactionContext


class AuthorizationSecurityTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dummy_bank_token = "valid-dummy-bank-token"
        os.environ["DUMMY_BANK_API_TOKEN"] = self.dummy_bank_token
        os.environ["DUMMY_BANK_DECISION_URL"] = "http://127.0.0.1:8001/api/transactions/payshield-decision/"

        # Customer A: Rahul
        self.user_a = PayShieldUser.create_user_with_phone("9000000001", is_phone_verified=True)
        self.token_a = Token.objects.create(user=self.user_a.user)

        # Customer B: Priya
        self.user_b = PayShieldUser.create_user_with_phone("9000000002", is_phone_verified=True)
        self.token_b = Token.objects.create(user=self.user_b.user)

        # User A's linked account and transaction
        self.account_a = LinkedBankAccount.objects.create(
            user=self.user_a,
            bank_name="PayShield Demo Bank",
            bank_customer_id=uuid.uuid4(),
            bank_account_id=101,
            account_number_masked="********0101",
            is_verified=True,
            verification_status="VERIFIED",
        )
        self.tx_a = TransactionContext.objects.create(
            source_bank="PayShield Demo Bank",
            source_transaction_id=str(uuid.uuid4()),
            transaction_type="BANK_TRANSFER",
            sender_name="Rahul Sharma",
            recipient_name="Merchant X",
            amount="500.00",
            currency="INR",
            otp_verified=True,
            user=self.user_a,
            linked_account=self.account_a,
        )
        self.approval_a = ApprovalRequest.objects.create(
            transaction=self.tx_a,
            user=self.user_a,
            status="PENDING",
            expires_at=timezone.now() + timedelta(seconds=60),
        )

        # User B's linked account and transaction
        self.account_b = LinkedBankAccount.objects.create(
            user=self.user_b,
            bank_name="PayShield Demo Bank",
            bank_customer_id=uuid.uuid4(),
            bank_account_id=102,
            account_number_masked="********0102",
            is_verified=True,
            verification_status="VERIFIED",
        )
        self.tx_b = TransactionContext.objects.create(
            source_bank="PayShield Demo Bank",
            source_transaction_id=str(uuid.uuid4()),
            transaction_type="BANK_TRANSFER",
            sender_name="Priya Patil",
            recipient_name="Merchant Y",
            amount="1200.00",
            currency="INR",
            otp_verified=True,
            user=self.user_b,
            linked_account=self.account_b,
        )
        self.approval_b = ApprovalRequest.objects.create(
            transaction=self.tx_b,
            user=self.user_b,
            status="PENDING",
            expires_at=timezone.now() + timedelta(seconds=60),
        )

    # 1. Unauthenticated users cannot access protected approval endpoints
    def test_unauthenticated_users_cannot_access_approvals(self):
        """Unauthenticated GET and POST requests are rejected with HTTP 401."""
        self.client.credentials()  # No token
        get_res = self.client.get("/api/approvals/")
        self.assertEqual(get_res.status_code, status.HTTP_401_UNAUTHORIZED)

        post_res = self.client.post(
            f"/api/approvals/{self.approval_a.id}/decide/",
            {"decision": "APPROVED"},
            format="json",
        )
        self.assertEqual(post_res.status_code, status.HTTP_401_UNAUTHORIZED)

    # 2. Authenticated user can list their own approvals
    def test_authenticated_user_can_list_own_approvals(self):
        """Authenticated user Rahul can view only Rahul's approvals."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_a.key}")
        response = self.client.get("/api/approvals/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], self.approval_a.id)
        self.assertEqual(data[0]["sender_name"], "Rahul Sharma")

    # 3. User cannot see another user's approvals (Cross-user isolation)
    def test_user_cannot_see_another_users_approvals(self):
        """Authenticated user Priya only sees Priya's approval, never Rahul's."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_b.key}")
        response = self.client.get("/api/approvals/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], self.approval_b.id)
        # Approval A must NOT be in the list
        ids = [item["id"] for item in data]
        self.assertNotIn(self.approval_a.id, ids)

    # 4. User cannot approve or deny another user's approval by ID
    def test_user_cannot_decide_another_users_approval(self):
        """User B (Priya) attempting to decide User A's (Rahul) approval is blocked with 403."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_b.key}")

        response = self.client.post(
            f"/api/approvals/{self.approval_a.id}/decide/",
            {"decision": "APPROVED"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("permission", response.json()["error"].lower())

        # Verify Approval A was NOT changed
        self.approval_a.refresh_from_db()
        self.assertEqual(self.approval_a.status, "PENDING")

    # 5. Missing or invalid service credentials rejected on server-to-server endpoint
    def test_invalid_service_token_rejected_on_transaction_intake(self):
        """Server-to-server transaction-context endpoint rejects invalid X-Dummy-Bank-Token."""
        payload = {
            "source_bank": "PayShield Demo Bank",
            "source_transaction_id": str(uuid.uuid4()),
            "transaction_type": "BANK_TRANSFER",
            "sender_name": "Test",
            "amount": "100.00",
            "otp_verified": True,
        }
        # Missing token
        res_missing = self.client.post(
            "/api/integration/transaction-context/",
            payload,
            format="json",
        )
        self.assertEqual(res_missing.status_code, status.HTTP_401_UNAUTHORIZED)

        # Invalid token
        res_invalid = self.client.post(
            "/api/integration/transaction-context/",
            payload,
            HTTP_X_DUMMY_BANK_TOKEN="bad-token",
            format="json",
        )
        self.assertEqual(res_invalid.status_code, status.HTTP_401_UNAUTHORIZED)

    # 6. Valid server-to-server integration continues working
    def test_valid_service_token_accepts_transaction_context(self):
        """Valid server-to-server transaction context succeeds and creates approval."""
        tx_id = str(uuid.uuid4())
        payload = {
            "source_bank": "PayShield Demo Bank",
            "source_transaction_id": tx_id,
            "transaction_type": "BANK_TRANSFER",
            "sender_name": "Rahul Sharma",
            "sender_account_masked": "********0101",
            "bank_customer_id": str(self.account_a.bank_customer_id),
            "bank_account_id": self.account_a.bank_account_id,
            "recipient_name": "Test Beneficiary",
            "amount": "250.00",
            "currency": "INR",
            "otp_verified": True,
        }
        response = self.client.post(
            "/api/integration/transaction-context/",
            payload,
            HTTP_X_DUMMY_BANK_TOKEN=self.dummy_bank_token,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.json()["is_customer_linked"])

        context = TransactionContext.objects.get(source_transaction_id=tx_id)
        self.assertEqual(context.user, self.user_a)

    # 7. Expired approvals cannot be approved
    @patch("requests.post")
    def test_expired_approvals_cannot_be_approved(self, mock_post):
        """An expired approval cannot be approved; notifies bank of expiry."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        self.approval_a.expires_at = timezone.now() - timedelta(seconds=10)
        self.approval_a.save()

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_a.key}")
        response = self.client.post(
            f"/api/approvals/{self.approval_a.id}/decide/",
            {"decision": "APPROVED"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expired", response.json()["error"].lower())

        self.approval_a.refresh_from_db()
        self.assertEqual(self.approval_a.status, "EXPIRED")

    # 8. Duplicate decisions do not execute a transaction twice
    @patch("requests.post")
    def test_duplicate_decisions_rejected(self, mock_post):
        """Once approved or denied, attempting a second decision is rejected with 409 Conflict."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"message": "Success"}
        mock_post.return_value = mock_resp

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_a.key}")

        # First decision
        first_res = self.client.post(
            f"/api/approvals/{self.approval_a.id}/decide/",
            {"decision": "APPROVED"},
            format="json",
        )
        self.assertEqual(first_res.status_code, status.HTTP_200_OK)

        # Duplicate decision
        dup_res = self.client.post(
            f"/api/approvals/{self.approval_a.id}/decide/",
            {"decision": "APPROVED"},
            format="json",
        )
        self.assertEqual(dup_res.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("no longer pending", dup_res.json()["error"].lower())

    # 9. Existing approval and transaction records remain usable
    def test_existing_records_remain_usable(self):
        """Records created without a user can exist without breaking queries."""
        legacy_tx = TransactionContext.objects.create(
            source_bank="PayShield Demo Bank",
            source_transaction_id="legacy-tx-001",
            transaction_type="BANK_TRANSFER",
            sender_name="Legacy Customer",
            amount="999.00",
            currency="INR",
            otp_verified=True,
            user=None,
            linked_account=None,
        )
        legacy_approval = ApprovalRequest.objects.create(
            transaction=legacy_tx,
            user=None,
            status="PENDING",
            expires_at=timezone.now() + timedelta(seconds=60),
        )
        self.assertIsNotNone(legacy_approval.id)
        self.assertIsNone(legacy_approval.user)

    # 10. Dummy Bank transaction OTP verification remains separate from PayShield login authentication
    def test_transaction_otp_separate_from_login_auth(self):
        """PayShield login OTP model is completely distinct from transaction context."""
        login_otp = LoginOTPChallenge.objects.create(
            phone_number="9000000001",
            otp_hash="hash123",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.assertEqual(login_otp.phone_number, "9000000001")
        # Ensure login OTP has no transaction foreign key or bank association
        self.assertFalse(hasattr(login_otp, "transaction"))

    # 11. Transaction History returns only the authenticated user's records
    def test_approval_history_returns_user_approvals_only(self):
        """History endpoint returns all approvals for the requesting user, excluding others."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_a.key}")
        res = self.client.get("/api/approvals/history/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], self.approval_a.id)

    # 12. Reporting scam generates a complaint ticket and audit log
    def test_report_cyber_crime_success(self):
        """Reporting fraud on an approval creates a complaint reference and logs security audit."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_a.key}")
        payload = {
            "category": "PHISHING_FAKE_LINK",
            "notes": "Suspicious SMS claiming electricity bill overdue.",
        }
        res = self.client.post(
            f"/api/approvals/{self.approval_a.id}/report-fraud/",
            payload,
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.json()
        self.assertTrue(data["complaint_ref"].startswith("NCR-2026-"))
        self.assertEqual(data["helpline"], "1930")
        self.assertEqual(data["portal_url"], "https://cybercrime.gov.in")

        # Verify DB update
        self.approval_a.refresh_from_db()
        self.assertTrue(self.approval_a.is_reported_fraud)
        self.assertEqual(self.approval_a.fraud_report_id, data["complaint_ref"])

        # Verify audit log entry
        audit_event = SecurityAuditEvent.objects.filter(
            event_type="CYBER_CRIME_REPORTED",
            user=self.user_a,
        ).first()
        self.assertIsNotNone(audit_event)
        self.assertEqual(audit_event.details["complaint_ref"], data["complaint_ref"])

    # 13. Cross-user scam reporting is forbidden
    def test_report_cyber_crime_cross_user_denied(self):
        """User B cannot report User A's transaction as fraud."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_b.key}")
        res = self.client.post(
            f"/api/approvals/{self.approval_a.id}/report-fraud/",
            {"category": "IMPERSONATION"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

