from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from accounts.models import LoginOTPChallenge, PayShieldUser


class AuthenticationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.phone = "9000000001"
        self.user = PayShieldUser.create_user_with_phone(
            phone_number=self.phone,
            is_phone_verified=True,
            full_name="Rahul Sharma",
        )

    @override_settings(DEBUG=True)
    def test_request_login_otp_success(self):
        """Requesting login OTP generates challenge with expiration and dev_otp in DEBUG."""
        response = self.client.post(
            "/api/auth/request-otp/",
            {"phone_number": self.phone},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["phone_number"], self.phone)
        self.assertIn("expires_in_seconds", data)
        self.assertIn("dev_otp", data)

        challenge = LoginOTPChallenge.objects.filter(phone_number=self.phone).first()
        self.assertIsNotNone(challenge)
        self.assertEqual(challenge.status, "PENDING")
        self.assertEqual(challenge.attempts, 0)
        self.assertFalse(challenge.is_expired())

    @override_settings(DEBUG=False)
    def test_request_login_otp_never_exposes_dev_otp_in_production(self):
        """When DEBUG=False, dev_otp is strictly excluded from response."""
        response = self.client.post(
            "/api/auth/request-otp/",
            {"phone_number": self.phone},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertNotIn("dev_otp", data)

    def test_request_login_otp_rate_limiting(self):
        """Exceeding 5 requests in 15 minutes triggers rate limiting (HTTP 429)."""
        for _ in range(5):
            LoginOTPChallenge.objects.create(
                phone_number=self.phone,
                otp_hash="hash",
                expires_at=timezone.now() + timedelta(minutes=5),
            )

        response = self.client.post(
            "/api/auth/request-otp/",
            {"phone_number": self.phone},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("Too many verification requests", response.json()["error"])

    @override_settings(DEBUG=True)
    def test_verify_login_otp_success_and_token_generation(self):
        """Submitting correct OTP provisions PayShieldUser and issues expiring Token."""
        req_res = self.client.post(
            "/api/auth/request-otp/",
            {"phone_number": self.phone},
            format="json",
        )
        dev_otp = req_res.json()["dev_otp"]

        verify_res = self.client.post(
            "/api/auth/verify-otp/",
            {"phone_number": self.phone, "otp": dev_otp},
            format="json",
        )
        self.assertEqual(verify_res.status_code, status.HTTP_200_OK)
        data = verify_res.json()
        self.assertIn("token", data)
        self.assertEqual(data["user"]["phone_number"], self.phone)
        self.assertTrue(data["user"]["is_phone_verified"])

        token = Token.objects.get(key=data["token"])
        self.assertEqual(token.user.payshield_user.phone_number, self.phone)

    def test_verify_login_otp_wrong_code(self):
        """Submitting wrong code increments attempts and does not issue token."""
        self.client.post(
            "/api/auth/request-otp/",
            {"phone_number": self.phone},
            format="json",
        )

        verify_res = self.client.post(
            "/api/auth/verify-otp/",
            {"phone_number": self.phone, "otp": "000000"},
            format="json",
        )
        self.assertEqual(verify_res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid verification code", verify_res.json()["error"])
        self.assertEqual(verify_res.json()["attempts_remaining"], 2)

    def test_verify_login_otp_locks_after_max_attempts(self):
        """Locked challenge after 3 wrong attempts returns 429."""
        self.client.post(
            "/api/auth/request-otp/",
            {"phone_number": self.phone},
            format="json",
        )

        for _ in range(3):
            self.client.post(
                "/api/auth/verify-otp/",
                {"phone_number": self.phone, "otp": "000000"},
                format="json",
            )

        # 4th attempt should return 429 Locked
        locked_res = self.client.post(
            "/api/auth/verify-otp/",
            {"phone_number": self.phone, "otp": "000000"},
            format="json",
        )
        self.assertEqual(locked_res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_auth_me_protected_endpoint(self):
        """GET /api/auth/me/ requires authentication token."""
        # Unauthenticated
        unauth_res = self.client.get("/api/auth/me/")
        self.assertEqual(unauth_res.status_code, status.HTTP_401_UNAUTHORIZED)

        # Authenticated
        user = PayShieldUser.create_user_with_phone("9000000001", is_phone_verified=True)
        token = Token.objects.create(user=user.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        auth_res = self.client.get("/api/auth/me/")
        self.assertEqual(auth_res.status_code, status.HTTP_200_OK)
        self.assertEqual(auth_res.json()["phone_number"], "9000000001")

    def test_logout_revokes_token(self):
        """Logging out deletes the token from database."""
        user = PayShieldUser.create_user_with_phone("9000000001", is_phone_verified=True)
        token = Token.objects.create(user=user.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        logout_res = self.client.post("/api/auth/logout/")
        self.assertEqual(logout_res.status_code, status.HTTP_200_OK)
        self.assertFalse(Token.objects.filter(key=token.key).exists())

        # Calling again should now be 401
        check_res = self.client.get("/api/auth/me/")
        self.assertEqual(check_res.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(DEBUG=True)
    def test_register_user_success_and_otp_issued(self):
        """Registering with valid full_name and phone creates unverified user and issues OTP."""
        res = self.client.post(
            "/api/auth/register/",
            {"full_name": "Vikram Malhotra", "phone_number": "9111222333"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        data = res.json()
        self.assertEqual(data["full_name"], "Vikram Malhotra")
        self.assertEqual(data["phone_number"], "9111222333")
        self.assertIn("dev_otp", data)

        # Check DB state: user is created but NOT yet verified
        user = PayShieldUser.objects.filter(phone_number="9111222333").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.full_name, "Vikram Malhotra")
        self.assertFalse(user.is_phone_verified)

    @override_settings(DEBUG=True)
    def test_register_and_verify_flow(self):
        """End-to-end registration: register -> receive OTP -> verify OTP -> verified user + token."""
        reg_res = self.client.post(
            "/api/auth/register/",
            {"full_name": "Priya Sharma", "phone_number": "9222333444"},
            format="json",
        )
        self.assertEqual(reg_res.status_code, status.HTTP_201_CREATED)
        otp = reg_res.json()["dev_otp"]

        verify_res = self.client.post(
            "/api/auth/verify-otp/",
            {"phone_number": "9222333444", "otp": otp},
            format="json",
        )
        self.assertEqual(verify_res.status_code, status.HTTP_200_OK)
        vdata = verify_res.json()
        self.assertIn("token", vdata)
        self.assertEqual(vdata["user"]["full_name"], "Priya Sharma")
        self.assertEqual(vdata["user"]["phone_number"], "9222333444")
        self.assertTrue(vdata["user"]["is_phone_verified"])

        # Check profile endpoint with token
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {vdata['token']}")
        me_res = self.client.get("/api/auth/me/")
        self.assertEqual(me_res.status_code, status.HTTP_200_OK)
        self.assertEqual(me_res.json()["full_name"], "Priya Sharma")
        self.assertEqual(me_res.json()["phone_number"], "9222333444")

    def test_register_already_verified_user_fails(self):
        """Attempting to register with an already verified phone number returns 400."""
        PayShieldUser.create_user_with_phone("9333444555", is_phone_verified=True, full_name="Existing User")
        res = self.client.post(
            "/api/auth/register/",
            {"full_name": "New Imposter", "phone_number": "9333444555"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json().get("code"), "ACCOUNT_EXISTS")

    def test_register_validation_errors(self):
        """Invalid phone or short full_name triggers validation error."""
        # Short name
        res = self.client.post(
            "/api/auth/register/",
            {"full_name": "A", "phone_number": "9000000001"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        # Invalid phone
        res2 = self.client.post(
            "/api/auth/register/",
            {"full_name": "Valid Name", "phone_number": "123"},
            format="json",
        )
        self.assertEqual(res2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_request_login_otp_unregistered_user_fails(self):
        """Requesting login OTP for an unregistered number returns 404 with USER_NOT_FOUND."""
        res = self.client.post(
            "/api/auth/request-otp/",
            {"phone_number": "9999999999"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.json().get("code"), "USER_NOT_FOUND")

    def test_verify_login_otp_unregistered_user_fails(self):
        """Verifying OTP for an unregistered number returns 404 with USER_NOT_FOUND."""
        LoginOTPChallenge.objects.create(
            phone_number="9999999999",
            otp_hash="pbkdf2_sha256$260000$dummy$hash",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        res = self.client.post(
            "/api/auth/verify-otp/",
            {"phone_number": "9999999999", "otp": "123456"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.json().get("code"), "USER_NOT_FOUND")
