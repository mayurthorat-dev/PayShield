from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone

from accounts.models import Device, PayShieldUser
from transactions.models import TransactionContext
from authorization.models import ApprovalRequest
from notifications.services import send_push_notification, notify_user_of_approval


class PushNotificationTests(TestCase):
    def setUp(self):
        self.user = PayShieldUser.create_user_with_phone("9000000001", is_phone_verified=True, full_name="Rahul Sharma")
        self.device = Device.objects.create(
            user=self.user,
            active_user=self.user,
            device_name="Test Phone",
            platform="ANDROID",
            status="ACTIVE",
            push_token="ExponentPushToken[mock_token_12345]",
        )
        self.tx = TransactionContext.objects.create(
            source_bank="PayShield Demo Bank",
            source_transaction_id="tx-notif-100",
            transaction_type="BANK_TRANSFER",
            sender_name="Rahul Sharma",
            recipient_name="Priya Patil",
            amount=Decimal("1500.00"),
            currency="INR",
            otp_verified=True,
            user=self.user,
        )
        self.approval = ApprovalRequest.objects.create(
            transaction=self.tx,
            user=self.user,
            expires_at=timezone.now() + timezone.timedelta(seconds=60),
        )

    @patch("requests.post")
    def test_send_expo_push_notification_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        success = send_push_notification(
            device=self.device,
            title="Test Alert",
            body="Test Body",
            data={"test_key": "val"},
        )
        self.assertTrue(success)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://exp.host/--/api/v2/push/send")
        self.assertEqual(kwargs["json"]["to"], "ExponentPushToken[mock_token_12345]")
        self.assertEqual(kwargs["json"]["title"], "Test Alert")

    @patch("requests.post")
    def test_notify_user_of_approval_integration(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        success = notify_user_of_approval(self.approval)
        self.assertTrue(success)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertIn("₹1500.00", kwargs["json"]["title"])
        self.assertIn("Priya Patil", kwargs["json"]["body"])
        self.assertEqual(kwargs["json"]["data"]["approval_id"], str(self.approval.id))

    def test_send_notification_inactive_device_fails(self):
        self.device.status = "REVOKED"
        self.device.save()
        success = send_push_notification(self.device, "Title", "Body")
        self.assertFalse(success)

