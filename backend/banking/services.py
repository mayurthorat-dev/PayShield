import os
import requests
from typing import Tuple, Dict, Any


def request_dummy_bank_account_verification(
    phone_number: str,
    account_number: str = None,
    account_id: int = None,
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Performs authenticated server-to-server request to Dummy Bank to verify account ownership.
    Returns:
        (success: bool, result_payload: dict, http_status_code: int)
    """
    verify_url = os.getenv(
        "DUMMY_BANK_VERIFY_URL",
        "http://127.0.0.1:8001/api/accounts/verify-link/",
    )
    api_token = os.getenv("DUMMY_BANK_API_TOKEN") or "payshield-dummy-bank-shared-secret-token"

    if not api_token:
        return (
            False,
            {"error": "Dummy Bank API token is not configured on PayShield."},
            503,
        )

    payload = {"phone_number": phone_number}
    if account_number:
        payload["account_number"] = str(account_number)
    if account_id:
        payload["account_id"] = account_id

    try:
        response = requests.post(
            verify_url,
            json=payload,
            headers={"X-PayShield-Token": api_token},
            timeout=5,
        )
    except requests.RequestException as exc:
        return (
            False,
            {
                "error": "Could not contact Dummy Bank verification service.",
                "details": str(exc),
            },
            502,
        )

    try:
        body = response.json()
    except ValueError:
        body = {"error": "Invalid response from Dummy Bank."}

    return (response.ok, body, response.status_code)


def discover_dummy_bank_accounts(phone_number: str) -> Tuple[bool, Dict[str, Any], int]:
    """
    Asks Dummy Bank for all active bank accounts registered under phone_number.
    """
    discover_url = os.getenv(
        "DUMMY_BANK_DISCOVER_URL",
        "http://127.0.0.1:8001/api/accounts/discover/",
    )
    api_token = os.getenv("DUMMY_BANK_API_TOKEN") or "payshield-dummy-bank-shared-secret-token"

    if not api_token:
        return (
            False,
            {"error": "Dummy Bank API token is not configured on PayShield."},
            503,
        )

    try:
        response = requests.post(
            discover_url,
            json={"phone_number": phone_number},
            headers={"X-PayShield-Token": api_token},
            timeout=5,
        )
    except requests.RequestException as exc:
        return (
            False,
            {
                "error": "Could not contact Dummy Bank discovery service.",
                "details": str(exc),
            },
            502,
        )

    try:
        body = response.json()
    except ValueError:
        body = {"error": "Invalid response from Dummy Bank."}

    return (response.ok, body, response.status_code)


