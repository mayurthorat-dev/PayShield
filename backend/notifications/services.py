import logging
import os
import requests
from pathlib import Path
from typing import Any, Dict, Optional

from django.conf import settings
from accounts.models import Device

logger = logging.getLogger(__name__)

# Firebase Admin SDK Lazy Initialization
_firebase_initialized = False

def get_firebase_app():
    global _firebase_initialized
    if _firebase_initialized:
        return True

    try:
        import firebase_admin
        from firebase_admin import credentials

        if firebase_admin._apps:
            _firebase_initialized = True
            return True

        firebase_json_env = os.getenv("FIREBASE_CREDENTIALS_JSON")
        if firebase_json_env:
            import json
            cred_dict = json.loads(firebase_json_env)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            _firebase_initialized = True
            logger.info("Firebase Admin SDK initialized successfully from environment variable.")
            return True

        cert_path = getattr(
            settings,
            "FIREBASE_SERVICE_ACCOUNT_KEY",
            settings.BASE_DIR / "firebase_service_account.json",
        )

        if Path(cert_path).is_file():
            cred = credentials.Certificate(str(cert_path))
            firebase_admin.initialize_app(cred)
            _firebase_initialized = True
            logger.info("Firebase Admin SDK initialized successfully.")
            return True
        else:
            logger.warning(
                f"Firebase service account file not found at: {cert_path}. "
                "Raw FCM dispatch disabled (Expo push dispatch remains active)."
            )
            return False
    except Exception as e:
        logger.error(f"Failed to initialize Firebase Admin SDK: {e}")
        return False


def send_push_notification(
    device: Device,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Dispatches a high-priority push notification to the user's active device.
    Supports both Expo Push Tokens (for Expo Go testing) and raw FCM tokens.
    """
    if not device or not device.is_active():
        logger.warning("Attempted to send push notification to inactive or missing device.")
        return False

    push_token = getattr(device, "push_token", "").strip()
    if not push_token:
        logger.info(f"No push token registered for device {device.device_id}.")
        return False

    data_payload = {str(k): str(v) for k, v in (data or {}).items()}

    # 1. Expo Push Notification Dispatch (Used by Expo Go on physical phones)
    if push_token.startswith("ExponentPushToken[") or push_token.startswith("ExpoPushToken["):
        try:
            expo_payload = {
                "to": push_token,
                "title": title,
                "body": body,
                "data": data_payload,
                "sound": "default",
                "priority": "high",
                "channelId": "payshield-approvals",
            }
            res = requests.post(
                "https://exp.host/--/api/v2/push/send",
                json=expo_payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=5,
            )
            if res.ok:
                resp_json = res.json()
                data_obj = resp_json.get("data", {})
                if isinstance(data_obj, dict) and data_obj.get("status") == "error":
                    logger.error(f"Expo push service returned error: {data_obj.get('message')}")
                    return False
                logger.info(f"Expo push notification sent successfully to {device.device_id}.")
                return True
            else:
                logger.error(f"Expo push service returned {res.status_code}: {res.text}")
                return False
        except Exception as e:
            logger.error(f"Error sending Expo push notification: {e}")
            return False

    # 2. Raw FCM Dispatch via Firebase Admin SDK
    if get_firebase_app():
        try:
            from firebase_admin import messaging

            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=data_payload,
                token=push_token,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        sound="default",
                        channel_id="payshield-approvals",
                    ),
                ),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(sound="default", content_available=True)
                    )
                ),
            )
            msg_id = messaging.send(message)
            logger.info(f"FCM notification sent successfully: {msg_id}")
            return True
        except Exception as e:
            logger.error(f"Error sending FCM notification: {e}")
            return False

    logger.warning("No suitable push dispatch method available for token.")
    return False


def notify_user_of_approval(approval) -> bool:
    """
    Pushes an immediate high-priority approval notification to the user's active device.
    """
    user = getattr(approval, "user", None)
    if not user:
        return False

    # Retrieve user's active device
    device = user.devices.filter(status="ACTIVE").first()
    if not device:
        logger.info(f"User {user.phone_number} has no active device registered for push notifications.")
        return False

    tx = approval.transaction
    amount_str = f"₹{tx.amount}"
    recipient = tx.recipient_name or "Merchant"

    title = f"🛡️ PayShield Alert: {amount_str}"
    body = f"Approve transfer of {amount_str} to {recipient}? 60s remaining."

    payload = {
        "type": "PAYMENT_APPROVAL",
        "approval_id": str(approval.id),
        "transaction_ref": str(tx.transaction_ref),
        "amount": str(tx.amount),
        "recipient_name": str(recipient),
        "source_bank": str(tx.source_bank),
        "expires_at": approval.expires_at.isoformat(),
    }

    return send_push_notification(device=device, title=title, body=body, data=payload)

