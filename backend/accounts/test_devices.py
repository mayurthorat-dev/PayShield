from datetime import timedelta
import os
import uuid
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import Device, LoginOTPChallenge, PayShieldUser
from audit.models import SecurityAuditEvent
from authorization.models import ApprovalRequest
from banking.models import LinkedBankAccount
from transactions.models import TransactionContext


class DeviceRegistrationAndBindingTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Customer 1: Rahul
        self.user_1 = PayShieldUser.create_user_with_phone("9000000001", is_phone_verified=True, full_name="Rahul Sharma")
        self.token_1 = Token.objects.create(user=self.user_1.user)

        # Customer 2: Priya
        self.user_2 = PayShieldUser.create_user_with_phone("9000000002", is_phone_verified=True, full_name="Priya Patel")
        self.token_2 = Token.objects.create(user=self.user_2.user)

        self.device_id_1 = uuid.uuid4()
        self.device_id_2 = uuid.uuid4()

    # 1. A user can register their first device
    def test_user_can_register_first_device(self):
        """User can register their initial device, which becomes ACTIVE."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_1.key}")
        res = self.client.post(
            "/api/devices/register/",
            {
                "device_id": str(self.device_id_1),
                "device_name": "Google Pixel 8",
                "platform": "ANDROID",
                "app_version": "1.0.0",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.json()["device"]["status"], "ACTIVE")
        self.assertEqual(res.json()["device"]["device_name"], "Google Pixel 8")

        # Verify DB state
        device = Device.objects.get(device_id=self.device_id_1)
        self.assertEqual(device.status, "ACTIVE")
        self.assertEqual(device.user, self.user_1)
        self.assertEqual(device.active_user, self.user_1)

        # Verify audit log
        audit = SecurityAuditEvent.objects.filter(
            user=self.user_1,
            event_type="DEVICE_REGISTERED",
            device_id=str(self.device_id_1),
        ).first()
        self.assertIsNotNone(audit)

    # 2. A user cannot register a second active device
    def test_user_cannot_register_second_active_device(self):
        """Registering a second device without replacement is rejected with HTTP 409 Conflict."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_1.key}")

        # Register first device
        self.client.post(
            "/api/devices/register/",
            {"device_id": str(self.device_id_1), "device_name": "Pixel 8", "platform": "ANDROID"},
            format="json",
        )

        # Attempt to register second device
        second_device_id = uuid.uuid4()
        res2 = self.client.post(
            "/api/devices/register/",
            {"device_id": str(second_device_id), "device_name": "iPhone 15", "platform": "IOS"},
            format="json",
        )
        self.assertEqual(res2.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res2.json()["code"], "DEVICE_REPLACEMENT_REQUIRED")
        self.assertIn("Another device is already registered", res2.json()["error"])

        # Check only 1 active device exists in DB
        self.assertEqual(Device.objects.filter(user=self.user_1, status="ACTIVE").count(), 1)

        # Verify audit log recorded rejection
        audit = SecurityAuditEvent.objects.filter(
            user=self.user_1,
            event_type="REGISTRATION_REJECTED",
            device_id=str(second_device_id),
        ).first()
        self.assertIsNotNone(audit)

    # 3. Different users cannot access each other's device records
    def test_different_users_cannot_access_each_others_device_records(self):
        """User A and User B only see their own device status."""
        Device.objects.create(
            user=self.user_1,
            active_user=self.user_1,
            device_id=self.device_id_1,
            device_name="Rahul Phone",
            status="ACTIVE",
        )

        Device.objects.create(
            user=self.user_2,
            active_user=self.user_2,
            device_id=self.device_id_2,
            device_name="Priya Phone",
            status="ACTIVE",
        )

        # User 2 queries device status
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_2.key}")
        res = self.client.get("/api/devices/status/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        data = res.json()
        self.assertTrue(data["has_active_device"])
        self.assertEqual(data["active_device"]["device_name"], "Priya Phone")
        self.assertNotEqual(data["active_device"]["device_id"], str(self.device_id_1))

    # 4. Revoked devices cannot access protected endpoints
    def test_revoked_device_cannot_access_protected_endpoints(self):
        """Protected requests carrying a revoked device ID are rejected with HTTP 403 Forbidden."""
        device = Device.objects.create(
            user=self.user_1,
            active_user=self.user_1,
            device_id=self.device_id_1,
            device_name="Rahul Phone",
            status="ACTIVE",
        )
        device.revoke(reason="SUSPECTED_COMPROMISE")

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.token_1.key}",
            HTTP_X_DEVICE_ID=str(self.device_id_1),
        )

        res = self.client.get("/api/approvals/")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.json()["code"], "DEVICE_REVOKED")

        # Verify audit log
        audit = SecurityAuditEvent.objects.filter(
            user=self.user_1,
            event_type="DEVICE_UNAUTHORIZED_REQUEST",
            device_id=str(self.device_id_1),
        ).first()
        self.assertIsNotNone(audit)

    # 5. Device replacement requires appropriate phone OTP verification
    @override_settings(DEBUG=True)
    def test_device_replacement_requires_phone_otp_verification(self):
        """Device replacement revokes previous device and activates new device only upon valid OTP."""
        # Initial active device
        old_dev = Device.objects.create(
            user=self.user_1,
            active_user=self.user_1,
            device_id=self.device_id_1,
            device_name="Old Pixel",
            status="ACTIVE",
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_1.key}")

        # Request replacement OTP
        otp_req_res = self.client.post("/api/devices/replace/request-otp/")
        self.assertEqual(otp_req_res.status_code, status.HTTP_201_CREATED)
        dev_otp = otp_req_res.json()["dev_otp"]

        # Attempt replacement with wrong OTP fails
        fail_res = self.client.post(
            "/api/devices/replace/",
            {
                "otp": "000000",
                "device_id": str(self.device_id_2),
                "device_name": "New Galaxy",
            },
            format="json",
        )
        self.assertEqual(fail_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(fail_res.json()["code"], "INVALID_OTP")

        # Submit with correct OTP
        success_res = self.client.post(
            "/api/devices/replace/",
            {
                "otp": dev_otp,
                "device_id": str(self.device_id_2),
                "device_name": "New Galaxy",
            },
            format="json",
        )
        self.assertEqual(success_res.status_code, status.HTTP_200_OK)
        self.assertIn("token", success_res.json())

        # Old device is REVOKED
        old_dev.refresh_from_db()
        self.assertEqual(old_dev.status, "REVOKED")
        self.assertIsNone(old_dev.active_user)
        self.assertEqual(old_dev.revocation_reason, "REPLACED_BY_USER")

        # New device is ACTIVE
        new_dev = Device.objects.get(device_id=self.device_id_2)
        self.assertEqual(new_dev.status, "ACTIVE")
        self.assertEqual(new_dev.active_user, self.user_1)

        # Audit log verified
        audit = SecurityAuditEvent.objects.filter(
            user=self.user_1,
            event_type="DEVICE_REPLACED",
            device_id=str(self.device_id_2),
        ).first()
        self.assertIsNotNone(audit)

    # 6. Revoked sessions cannot be reused
    @override_settings(DEBUG=True)
    def test_revoked_sessions_cannot_be_reused(self):
        """Tokens associated with revoked devices are deleted and cannot make subsequent requests."""
        Device.objects.create(
            user=self.user_1,
            active_user=self.user_1,
            device_id=self.device_id_1,
            device_name="Old Device",
            status="ACTIVE",
        )
        old_token_key = self.token_1.key
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {old_token_key}")

        # Request OTP and execute replacement
        otp_res = self.client.post("/api/devices/replace/request-otp/")
        dev_otp = otp_res.json()["dev_otp"]

        replace_res = self.client.post(
            "/api/devices/replace/",
            {
                "otp": dev_otp,
                "device_id": str(self.device_id_2),
                "device_name": "Replacement Device",
            },
            format="json",
        )
        self.assertEqual(replace_res.status_code, status.HTTP_200_OK)
        new_token_key = replace_res.json()["token"]
        self.assertNotEqual(old_token_key, new_token_key)

        # Old token cannot be reused
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {old_token_key}")
        check_res = self.client.get("/api/auth/me/")
        self.assertEqual(check_res.status_code, status.HTTP_401_UNAUTHORIZED)

        # New token works
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {new_token_key}",
            HTTP_X_DEVICE_ID=str(self.device_id_2),
        )
        new_check = self.client.get("/api/auth/me/")
        self.assertEqual(new_check.status_code, status.HTTP_200_OK)

    # 7. Concurrent registration attempts cannot create two active devices
    def test_concurrent_registration_attempts_cannot_create_two_active_devices(self):
        """Database unique constraint on active_user prevents two ACTIVE devices for the same user."""
        Device.objects.create(
            user=self.user_1,
            active_user=self.user_1,
            device_id=self.device_id_1,
            device_name="Active Device 1",
            status="ACTIVE",
        )

        # Attempt to insert a second active device for the same user directly
        with self.assertRaises(IntegrityError):
            Device.objects.create(
                user=self.user_1,
                active_user=self.user_1,
                device_id=uuid.uuid4(),
                device_name="Conflicting Active Device",
                status="ACTIVE",
            )

    # 8. Another user's device cannot be revoked
    def test_another_user_device_cannot_be_revoked(self):
        """User B cannot revoke User A's device (returns HTTP 403 Forbidden)."""
        dev_a = Device.objects.create(
            user=self.user_1,
            active_user=self.user_1,
            device_id=self.device_id_1,
            device_name="Rahul Phone",
            status="ACTIVE",
        )

        # User B attempts to revoke dev_a
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token_2.key}")
        res = self.client.post(
            "/api/devices/revoke/",
            {"device_id": str(self.device_id_1)},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.json()["code"], "PERMISSION_DENIED")

        # dev_a remains ACTIVE
        dev_a.refresh_from_db()
        self.assertEqual(dev_a.status, "ACTIVE")

    # 9. Existing transaction approval functionality continues working
    def test_existing_transaction_approval_functionality_with_device_binding(self):
        """Approved device can retrieve and decide payment requests successfully."""
        # Register device for user 1
        Device.objects.create(
            user=self.user_1,
            active_user=self.user_1,
            device_id=self.device_id_1,
            device_name="Authorized Phone",
            status="ACTIVE",
        )

        # Create linked account and transaction
        account = LinkedBankAccount.objects.create(
            user=self.user_1,
            bank_name="Test Bank",
            bank_customer_id=uuid.uuid4(),
            bank_account_id=201,
            account_number_masked="•••• 2001",
            is_verified=True,
            verification_status="VERIFIED",
        )
        tx = TransactionContext.objects.create(
            source_bank="Test Bank",
            source_transaction_id=str(uuid.uuid4()),
            transaction_type="UPI",
            sender_name="Rahul Sharma",
            recipient_name="Zomato India",
            amount="650.00",
            currency="INR",
            otp_verified=True,
            user=self.user_1,
            linked_account=account,
        )
        approval = ApprovalRequest.objects.create(
            transaction=tx,
            user=self.user_1,
            status="PENDING",
            expires_at=timezone.now() + timedelta(seconds=60),
        )

        # Mock dummy bank callback response
        with patch("requests.post") as mock_post:
            mock_post.return_value.ok = True
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"status": "SUCCESS", "message": "Funds transferred"}

            os.environ["DUMMY_BANK_API_TOKEN"] = "test-token"
            os.environ["DUMMY_BANK_DECISION_URL"] = "http://testbank/decision/"

            # Protected fetch with X-Device-ID
            self.client.credentials(
                HTTP_AUTHORIZATION=f"Token {self.token_1.key}",
                HTTP_X_DEVICE_ID=str(self.device_id_1),
            )

            feed_res = self.client.get("/api/approvals/")
            self.assertEqual(feed_res.status_code, status.HTTP_200_OK)
            self.assertEqual(len(feed_res.json()), 1)

            # Protected decision with X-Device-ID
            decide_res = self.client.post(
                f"/api/approvals/{approval.id}/decide/",
                {"decision": "APPROVED"},
                format="json",
            )
            self.assertEqual(decide_res.status_code, status.HTTP_200_OK)
            self.assertEqual(decide_res.json()["decision"], "APPROVED")

    # 10. Multiple linked bank accounts remain supported with single active device
    def test_multiple_linked_bank_accounts_remain_supported_with_single_device(self):
        """User can authorize payments from multiple bank accounts using their single registered device."""
        Device.objects.create(
            user=self.user_1,
            active_user=self.user_1,
            device_id=self.device_id_1,
            device_name="Single Registered Device",
            status="ACTIVE",
        )

        # Account A: HDFC Bank
        acc_a = LinkedBankAccount.objects.create(
            user=self.user_1,
            bank_name="HDFC Bank",
            bank_customer_id=uuid.uuid4(),
            bank_account_id=301,
            account_number_masked="•••• 3001",
            is_verified=True,
            verification_status="VERIFIED",
        )
        # Account B: ICICI Bank
        acc_b = LinkedBankAccount.objects.create(
            user=self.user_1,
            bank_name="ICICI Bank",
            bank_customer_id=uuid.uuid4(),
            bank_account_id=302,
            account_number_masked="•••• 3002",
            is_verified=True,
            verification_status="VERIFIED",
        )

        # User profile reports 2 linked accounts
        self.assertEqual(self.user_1.linked_bank_accounts.filter(is_active=True).count(), 2)

        # Create transactions on both accounts
        tx_a = TransactionContext.objects.create(
            source_bank="HDFC Bank",
            source_transaction_id=str(uuid.uuid4()),
            transaction_type="NEFT",
            sender_name="Rahul",
            recipient_name="Merchant A",
            amount="1000.00",
            currency="INR",
            otp_verified=True,
            user=self.user_1,
            linked_account=acc_a,
        )
        ApprovalRequest.objects.create(
            transaction=tx_a,
            user=self.user_1,
            status="PENDING",
            expires_at=timezone.now() + timedelta(seconds=60),
        )

        tx_b = TransactionContext.objects.create(
            source_bank="ICICI Bank",
            source_transaction_id=str(uuid.uuid4()),
            transaction_type="UPI",
            sender_name="Rahul",
            recipient_name="Merchant B",
            amount="2500.00",
            currency="INR",
            otp_verified=True,
            user=self.user_1,
            linked_account=acc_b,
        )
        ApprovalRequest.objects.create(
            transaction=tx_b,
            user=self.user_1,
            status="PENDING",
            expires_at=timezone.now() + timedelta(seconds=60),
        )

        # Both appear for the single registered device
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {self.token_1.key}",
            HTTP_X_DEVICE_ID=str(self.device_id_1),
        )
        feed_res = self.client.get("/api/approvals/")
        self.assertEqual(feed_res.status_code, status.HTTP_200_OK)
        items = feed_res.json()
        self.assertEqual(len(items), 2)
        banks = {item["source_bank"] for item in items}
        self.assertEqual(banks, {"HDFC Bank", "ICICI Bank"})
