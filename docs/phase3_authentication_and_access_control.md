# PayShield — Phase 3: Authentication & Access Control

This document details the security architecture, token authentication system, object-level authorization enforcement, and mobile client integration implemented in Phase 3.

---

## 1. Authentication Architecture

PayShield uses an **Expiring Token Authentication** mechanism built on top of Django REST Framework's standard token system (`rest_framework.authtoken`).

### Key Properties:
- **Token Format**: Standard cryptographically secure 40-character hexadecimal token keys issued by Django (`Token.objects.create(user=...)`).
- **Lifetime**: Configurable via `PAYSHIELD_TOKEN_LIFETIME_HOURS` (defaults to 24 hours).
- **Enforcement Class**: `accounts.authentication.ExpiringTokenAuthentication`.
- **Validation**: On every authenticated request, the token's age (`now - token.created`) is checked. If the token is older than the configured lifetime, it is deleted from the database and an HTTP 401 Unauthorized (`Authentication token has expired. Please log in again.`) is returned.
- **Revocation**: Handled cleanly via `POST /api/auth/logout/` which deletes the active token record.

---

## 2. Distinction: User Authentication vs. Bank Transaction OTP

A core principle of PayShield's architecture is the strict separation of credentials:

| Attribute | PayShield Login Authentication | Dummy Bank Transaction OTP |
|---|---|---|
| **Purpose** | Authenticates the user to access their PayShield app session | Verifies the initial payment request inside the banking system |
| **Model** | `accounts.LoginOTPChallenge` | `otp.OTPChallenge` |
| **Issued By** | PayShield Backend (Port 8000) | Dummy Bank (Port 8001) |
| **Storage** | PBKDF2 hash on PayShield MySQL DB | PBKDF2 hash on Dummy Bank MySQL DB |
| **Attempts** | Max 3 attempts, locks on 3rd failure | Max 5 attempts, locks on 5th failure |
| **Expiry** | 5 minutes | 5 minutes |
| **Outcome** | Returns access token for PayShield APIs | Advances transaction to `OTP_VERIFIED` and pushes context |

> [!IMPORTANT]
> A user never enters their bank password, banking PIN, or bank transaction OTP into PayShield. PayShield login OTPs are generated and validated exclusively on the PayShield backend.

---

## 3. Object-Level Authorization Rules

Prior to Phase 3, any client could query all pending approvals and decide any approval by guessing an integer ID. Phase 3 enforces strict object-level authorization:

### A. Approval Listing (`GET /api/approvals/`)
- **Permission**: `IsAuthenticated`.
- **Enforcement**: Only approvals where `user == request.user.payshield_user` are queried.
- **Data Leakage Protection**: User A cannot see User B’s pending approvals or transaction amounts.

### B. Approval Decision (`POST /api/approvals/<id>/decide/`)
- **Permission**: `IsAuthenticated`.
- **Enforcement**:
  ```python
  if approval.user_id != payshield_user.id:
      return Response(
          {"error": "You do not have permission to access or decide this approval."},
          status=status.HTTP_403_FORBIDDEN,
      )
  ```
- **Integrity Protection**: Customer B cannot approve or deny Customer A's transactions.
- **Race Condition Protection**: `select_for_update()` inside `transaction.atomic()` prevents concurrent duplicate approvals from executing twice.

### C. Server-to-Server Boundaries
- `POST /api/integration/transaction-context/`: Protected by `X-Dummy-Bank-Token` (validated via constant-time `secrets.compare_digest`). Mobile clients cannot call or spoof this endpoint.
- `POST /api/transactions/payshield-decision/` (Dummy Bank): Protected by `X-PayShield-Token`.

---

## 4. API Endpoints

### Authentication Endpoints (`backend/`)

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| `POST` | `/api/auth/request-otp/` | None | Issues a 6-digit login OTP for a registered mobile number. Rate-limited to 5 requests per 15 minutes. |
| `POST` | `/api/auth/verify-otp/` | None | Verifies the OTP, provisions `PayShieldUser`, and issues an expiring `Token`. |
| `GET` | `/api/auth/me/` | Token | Returns profile details and linked accounts count for the authenticated user. |
| `POST` | `/api/auth/logout/` | Token | Revokes and deletes the current access token. |

### Protected Banking & Approvals Endpoints (`backend/`)

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| `GET` | `/api/approvals/` | Token | Lists active pending payment approvals belonging exclusively to the authenticated user. |
| `POST` | `/api/approvals/<id>/decide/` | Token | Approves or denies an approval request. Checks strict object-level ownership. |
| `GET` | `/api/banking/accounts/` | Token | Lists linked bank accounts owned by the authenticated user. |
| `POST` | `/api/banking/accounts/initiate/` | Token | Initiates linking of an external account in `UNVERIFIED` state. |
| `POST` | `/api/banking/accounts/<id>/verify/` | Token | Confirms verification with Dummy Bank and marks status `VERIFIED`. |
| `POST` | `/api/banking/accounts/link-and-verify/` | Token | Convenience atomic link and verification for the authenticated user. |

---

## 5. Mobile App Integration

- **API Base URL**: Centralized in [`mobile/config.ts`](file:///c:/Users/Lenovo/OneDrive/Desktop/PayShield/mobile/config.ts).
- **Session & Token Storage**: Managed via [`mobile/authStorage.ts`](file:///c:/Users/Lenovo/OneDrive/Desktop/PayShield/mobile/authStorage.ts).
- **API Client**: Implemented in [`mobile/api.ts`](file:///c:/Users/Lenovo/OneDrive/Desktop/PayShield/mobile/api.ts) with automatic `Authorization: Token <key>` header injection.
- **Session Expiry Handling**: An HTTP 401 response from any protected API automatically triggers `authStorage.notifyAuthExpired()`, returning the user to the login screen with an alert.
- **Login Screen**: Built directly into [`mobile/App.tsx`](file:///c:/Users/Lenovo/OneDrive/Desktop/PayShield/mobile/App.tsx), allowing mobile sign-in via phone number and verification OTP.

---

## 6. Environment Variables

| Variable | Service | Description |
|---|---|---|
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Both | MySQL connection credentials |
| `DUMMY_BANK_API_TOKEN` | PayShield Backend | Shared secret used to authenticate Dummy Bank calls |
| `PAYSHIELD_API_TOKEN` | Dummy Bank | Shared secret used to authenticate PayShield calls |
| `DUMMY_BANK_DECISION_URL` | PayShield Backend | URL to forward approval decisions to Dummy Bank |
| `PAYSHIELD_TRANSACTION_CONTEXT_URL` | Dummy Bank | URL to send verified transaction context to PayShield |
| `DUMMY_BANK_VERIFY_URL` | PayShield Backend | URL for server-to-server bank account ownership verification |
| `PAYSHIELD_TOKEN_LIFETIME_HOURS` | PayShield Backend | Access token expiration period (default: `24`) |

---

## 7. Migration and Test Commands

### Running Migrations
```powershell
cd c:\Users\Lenovo\OneDrive\Desktop\PayShield\backend
.\.venv\Scripts\python.exe manage.py migrate
```

### Running Backend Security & Access Control Tests
```powershell
cd c:\Users\Lenovo\OneDrive\Desktop\PayShield\backend
.\.venv\Scripts\python.exe manage.py test accounts authorization banking
```

### Running Dummy Bank Tests
```powershell
cd c:\Users\Lenovo\OneDrive\Desktop\PayShield\dummy_bank
.\.venv\Scripts\python.exe manage.py test accounts
```

---

## 8. Known Limitations & Phase 4/5 Roadmap

1. **Device Binding (Phase 5)**: User sessions are currently tied to tokens. Hardware-based single-device binding and session revocation upon device transfer will be added in Phase 5.
2. **Push Notifications (Phase 5)**: Approval retrieval currently uses active polling/refresh in the mobile app. Firebase Cloud Messaging (FCM) notifications will be added in Phase 5.
3. **SMS Gateway**: In local development (`DEBUG = True`), `dev_otp` is provided in the API response for testing. In production, an external SMS provider (e.g. Twilio, AWS SNS) will deliver the login OTP out-of-band.

