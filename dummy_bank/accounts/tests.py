import os
import uuid
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from customers.models import BankCustomer
from accounts.models import BankAccount


class AccountLinkVerificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.test_token = "test-secret-token"
        os.environ["PAYSHIELD_API_TOKEN"] = self.test_token

        self.customer1 = BankCustomer.objects.create(
            customer_id=uuid.uuid4(),
            full_name="Rahul Sharma",
            email="rahul@example.com",
            phone_number="9000000001",
            is_active=True,
        )
        self.customer2 = BankCustomer.objects.create(
            customer_id=uuid.uuid4(),
            full_name="Priya Patil",
            email="priya@example.com",
            phone_number="9000000002",
            is_active=True,
        )

        self.account1 = BankAccount.objects.create(
            customer=self.customer1,
            account_number="100000000001",
            bank_name="PayShield Demo Bank",
            ifsc_code="DEMO0001",
            account_type="SAVINGS",
            balance=50000.00,
            status="ACTIVE",
        )
        self.account2 = BankAccount.objects.create(
            customer=self.customer2,
            account_number="100000000002",
            bank_name="PayShield Demo Bank",
            ifsc_code="DEMO0001",
            account_type="SAVINGS",
            balance=25000.00,
            status="ACTIVE",
        )

    def test_unauthenticated_request_rejected(self):
        """Calling without X-PayShield-Token returns 401."""
        response = self.client.post(
            "/api/accounts/verify-link/",
            {"phone_number": "9000000001", "account_number": "100000000001"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_service_token_rejected(self):
        """Calling with invalid X-PayShield-Token returns 401."""
        response = self.client.post(
            "/api/accounts/verify-link/",
            {"phone_number": "9000000001", "account_number": "100000000001"},
            HTTP_X_PAYSHIELD_TOKEN="wrong-token",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_matching_customer_and_phone_verified_successfully(self):
        """When phone number matches account owner, returns verified=True and metadata."""
        response = self.client.post(
            "/api/accounts/verify-link/",
            {"phone_number": "9000000001", "account_number": "100000000001"},
            HTTP_X_PAYSHIELD_TOKEN=self.test_token,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data.get("verified"))
        self.assertEqual(data.get("bank_customer_id"), str(self.customer1.customer_id))
        self.assertEqual(data.get("bank_account_id"), self.account1.account_id)
        self.assertEqual(data.get("account_number_masked"), "********0001")
        self.assertEqual(data.get("customer_name"), "Rahul Sharma")

    def test_customer_cannot_link_another_customers_account(self):
        """When phone number does not match account owner, returns 403 Forbidden."""
        # Rahul attempts to link Priya's account
        response = self.client.post(
            "/api/accounts/verify-link/",
            {"phone_number": "9000000001", "account_number": "100000000002"},
            HTTP_X_PAYSHIELD_TOKEN=self.test_token,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        data = response.json()
        self.assertFalse(data.get("verified"))
        self.assertIn("Customer identity mismatch", data.get("error"))

    def test_unknown_bank_account_returns_404(self):
        """Nonexistent bank account returns 404."""
        response = self.client.post(
            "/api/accounts/verify-link/",
            {"phone_number": "9000000001", "account_number": "999999999999"},
            HTTP_X_PAYSHIELD_TOKEN=self.test_token,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.json().get("verified"))
