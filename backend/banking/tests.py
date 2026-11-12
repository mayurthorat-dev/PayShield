import os
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import PayShieldUser, LoginOTPChallenge
from authorization.models import ApprovalRequest
from banking.models import LinkedBankAccount
from transactions.models import TransactionContext


class CustomerIdentityAndAccountLinkingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.dummy_bank_token = "mock-bank-token"
        os.environ["DUMMY_BANK_API_TOKEN"] = self.dummy_bank_token

        # User 1: Rahul
        self.user1 = PayShieldUser.create_user_with_phone(
            phone_number="9000000001",
            is_phone_verified=True,
        )
        # User 2: Priya
        self.user2 = PayShieldUser.create_user_with_phone(
            phone_number="9000000002",
            is_phone_verified=True,
        )

        self.customer1_uuid = uuid.uuid4()
        self.customer2_uuid = uuid.uuid4()

    # 1. Multiple linked accounts for one user
    def test_user_can_have_multiple_linked_bank_accounts(self):
        """A PayShield user can have multiple linked bank accounts."""
        acc1 = LinkedBankAccount.objects.create(
            user=self.user1,
            bank_name="PayShield Demo Bank",
            bank_customer_id=self.customer1_uuid,
            bank_account_id=101,
            account_number_masked="********0101",
            account_type="SAVINGS",
            is_verified=True,
            verification_status="VERIFIED",
        )
        acc2 = LinkedBankAccount.objects.create(
            user=self.user1,
            bank_name="Another Partner Bank",
            bank_customer_id=self.customer1_uuid,
            bank_account_id=202,
            account_number_masked="********0202",
            account_type="CURRENT",
            is_verified=True,
            verification_status="VERIFIED",
        )

        user1_accounts = self.user1.linked_bank_accounts.all()
        self.assertEqual(user1_accounts.count(), 2)
        self.assertIn(acc1, user1_accounts)
        self.assertIn(acc2, user1_accounts)

    # 2. New linked account is unverified by default
    @patch("banking.views.request_dummy_bank_account_verification")
    def test_new_linked_account_is_unverified_by_default(self, mock_verify):
        """When an account link is initiated, it begins in UNVERIFIED state."""
        self.client.force_authenticate(user=self.user1.user)
        mock_verify.return_value = (
            True,
            {
                "verified": True,
                "bank_name": "PayShield Demo Bank",
                "bank_customer_id": str(self.customer1_uuid),
                "bank_account_id": 101,
                "account_number_masked": "********0101",
                "account_type": "SAVINGS",
            },
            200,
        )

        response = self.client.post(
            "/api/banking/accounts/initiate/",
            {
                "account_number": "100000000101",
                "bank_name": "PayShield Demo Bank",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()["link"]
        self.assertFalse(data["is_verified"])
        self.assertEqual(data["verification_status"], "UNVERIFIED")

        link_record = LinkedBankAccount.objects.get(link_id=data["link_id"])
        self.assertFalse(link_record.is_verified)
        self.assertEqual(link_record.verification_status, "UNVERIFIED")

    # 3. Duplicate external account links rejected
    def test_duplicate_external_account_links_rejected(self):
        """Attempting to link an already linked bank account is rejected."""
        LinkedBankAccount.objects.create(
            user=self.user1,
            bank_name="PayShield Demo Bank",
            bank_customer_id=self.customer1_uuid,
            bank_account_id=101,
            account_number_masked="********0101",
            account_type="SAVINGS",
            is_verified=True,
            verification_status="VERIFIED",
        )

        with patch("banking.views.request_dummy_bank_account_verification") as mock_verify:
            mock_verify.return_value = (
                True,
                {
                    "verified": True,
                    "bank_name": "PayShield Demo Bank",
                    "bank_customer_id": str(self.customer1_uuid),
                    "bank_account_id": 101,
                    "account_number_masked": "********0101",
                    "account_type": "SAVINGS",
                },
                200,
            )

            # User 2 tries to link User 1's account
            self.client.force_authenticate(user=self.user2.user)
            response = self.client.post(
                "/api/banking/accounts/link-and-verify/",
                {
                    "account_number": "100000000101",
                    "bank_name": "PayShield Demo Bank",
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
            self.assertIn("already linked", response.json()["error"])

    # 4. Customer cannot link another customer's bank account
    @patch("banking.views.request_dummy_bank_account_verification")
    def test_customer_cannot_link_another_customers_account(self, mock_verify):
        """If Dummy Bank returns identity mismatch (403), linking is rejected."""
        self.client.force_authenticate(user=self.user1.user)
        mock_verify.return_value = (
            False,
            {
                "verified": False,
                "error": "Customer identity mismatch. This bank account is registered to a different mobile number.",
            },
            403,
        )

        response = self.client.post(
            "/api/banking/accounts/link-and-verify/",
            {
                "account_number": "100000000002",
                "bank_name": "PayShield Demo Bank",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(LinkedBankAccount.objects.count(), 0)

    # 5. Unauthenticated or invalid service requests cannot establish verified links
    @patch("banking.views.request_dummy_bank_account_verification")
    def test_unauthenticated_or_invalid_service_requests_cannot_establish_verified_links(
        self, mock_verify
    ):
        """If the service-to-service call fails authentication (401), link is not verified."""
        self.client.force_authenticate(user=self.user1.user)
        mock_verify.return_value = (
            False,
            {"error": "Unauthorized PayShield service."},
            401,
        )

        response = self.client.post(
            "/api/banking/accounts/link-and-verify/",
            {
                "account_number": "100000000101",
            },
            format="json",
        )
        self.assertNotEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(LinkedBankAccount.objects.filter(is_verified=True).count(), 0)

    # 6. Invalid or unknown customer references rejected
    @patch("banking.views.request_dummy_bank_account_verification")
    def test_invalid_or_unknown_customer_references_rejected(self, mock_verify):
        """If bank returns 404 for unknown account, request fails appropriately."""
        self.client.force_authenticate(user=self.user1.user)
        mock_verify.return_value = (
            False,
            {"verified": False, "error": "Bank account not found."},
            404,
        )

        response = self.client.post(
            "/api/banking/accounts/link-and-verify/",
            {
                "account_number": "999999999999",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # 7. Transaction associated only with correct verified account and user
    def test_transaction_associated_only_with_correct_verified_account_and_user(self):
        """Incoming transaction context is securely linked to the correct PayShield user."""
        self.client.credentials()  # Unauthenticated client calling server-to-server endpoint
        linked_acc = LinkedBankAccount.objects.create(
            user=self.user1,
            bank_name="PayShield Demo Bank",
            bank_customer_id=self.customer1_uuid,
            bank_account_id=101,
            account_number_masked="********0101",
            account_type="SAVINGS",
            is_verified=True,
            verification_status="VERIFIED",
        )

        payload = {
            "source_bank": "PayShield Demo Bank",
            "source_transaction_id": str(uuid.uuid4()),
            "transaction_type": "BANK_TRANSFER",
            "sender_name": "Rahul Sharma",
            "sender_account_masked": "********0101",
            "bank_customer_id": str(self.customer1_uuid),
            "bank_account_id": 101,
            "recipient_name": "Priya Patil",
            "recipient_account_masked": "********0202",
            "amount": "1500.00",
            "currency": "INR",
            "description": "Dinner split",
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

        context = TransactionContext.objects.get(
            source_transaction_id=payload["source_transaction_id"]
        )
        self.assertEqual(context.linked_account, linked_acc)
        self.assertEqual(context.user, self.user1)

        approval = ApprovalRequest.objects.get(transaction=context)
        self.assertEqual(approval.user, self.user1)

    # 8. Unknown or unverified transaction ownership is handled safely
    def test_unknown_or_unverified_transaction_ownership_handled_safely(self):
        """A transaction from an unlinked or unverified account is recorded safely without silent misattribution."""
        self.client.credentials()
        payload = {
            "source_bank": "PayShield Demo Bank",
            "source_transaction_id": str(uuid.uuid4()),
            "transaction_type": "BANK_TRANSFER",
            "sender_name": "Unknown Person",
            "sender_account_masked": "********9999",
            "bank_customer_id": str(uuid.uuid4()),
            "bank_account_id": 999,
            "recipient_name": "Priya Patil",
            "recipient_account_masked": "********0202",
            "amount": "2000.00",
            "currency": "INR",
            "description": "Unlinked transfer",
            "otp_verified": True,
        }

        response = self.client.post(
            "/api/integration/transaction-context/",
            payload,
            HTTP_X_DUMMY_BANK_TOKEN=self.dummy_bank_token,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.json()["is_customer_linked"])
        self.assertIn("warning", response.json())

        context = TransactionContext.objects.get(
            source_transaction_id=payload["source_transaction_id"]
        )
        self.assertIsNone(context.linked_account)
        self.assertIsNone(context.user)

        approval = ApprovalRequest.objects.get(transaction=context)
        self.assertIsNone(approval.user)

    # 9. Existing transaction-context and approval compatibility
    def test_existing_transaction_context_and_approval_compatibility(self):
        """Legacy transaction context payloads without bank_customer_id still succeed."""
        self.client.credentials()
        payload = {
            "source_bank": "PayShield Demo Bank",
            "source_transaction_id": str(uuid.uuid4()),
            "transaction_type": "BANK_TRANSFER",
            "sender_name": "Rahul Sharma",
            "recipient_name": "Priya Patil",
            "recipient_account_masked": "********0202",
            "amount": "500.00",
            "currency": "INR",
            "description": "Legacy format payload",
            "otp_verified": True,
        }

        response = self.client.post(
            "/api/integration/transaction-context/",
            payload,
            HTTP_X_DUMMY_BANK_TOKEN=self.dummy_bank_token,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.json()["is_customer_linked"])

    # 10. LoginOTPChallenge model logic
    def test_login_otp_challenge_model(self):
        """Dedicated PayShield login OTP model behaves as expected."""
        challenge = LoginOTPChallenge.objects.create(
            phone_number="9000000001",
            otp_hash="pbkdf2_sha256$mockhash",
            expires_at=timezone.now() + timedelta(minutes=5),
            max_attempts=3,
        )
        self.assertTrue(challenge.can_attempt())
        self.assertFalse(challenge.is_expired())

        # Expiration test
        challenge.expires_at = timezone.now() - timedelta(seconds=1)
        self.assertTrue(challenge.is_expired())
        self.assertFalse(challenge.can_attempt())
