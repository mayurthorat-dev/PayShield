"""
PayShield - Simulated Transaction Generator
Simulates a customer initiating a bank transfer on Dummy Bank,
generating & verifying the transaction OTP, and forwarding the
context to PayShield for out-of-band mobile authorization.
"""

import sys
import requests

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

DUMMY_BANK_URL = "http://127.0.0.1:8001"

def simulate_payment(amount: str = "2499.00", description: str = "Online Shopping - Amazon India"):
    print("=" * 60)
    print(f"🚀 Initiating Payment of ₹{amount} from Dummy Bank...")
    print(f"   Sender: Rahul Sharma (Account #100000000001)")
    print(f"   Recipient: Priya Patil")
    print(f"   Description: {description}")
    print("=" * 60)

    # 1. Create transaction in Dummy Bank
    create_url = f"{DUMMY_BANK_URL}/api/transactions/create/"
    tx_payload = {
        "sender_account": 1,
        "beneficiary": 1,
        "transaction_type": "BANK_TRANSFER",
        "amount": amount,
        "description": description,
    }

    try:
        res = requests.post(create_url, json=tx_payload, timeout=5)
    except requests.RequestException as e:
        print(f"❌ Error connecting to Dummy Bank at {DUMMY_BANK_URL}: {e}")
        print("   Make sure Dummy Bank is running: cd dummy_bank && python manage.py runserver 0.0.0.0:8001")
        return

    if res.status_code != 201:
        print(f"❌ Failed to create transaction: {res.status_code} - {res.text}")
        return

    tx_data = res.json()
    tx_id = tx_data["transaction_id"]
    print(f"✓ Step 1: Transaction created in Dummy Bank (ID: {tx_id[:8]}...)")

    # 2. Generate Bank Transaction OTP
    otp_gen_url = f"{DUMMY_BANK_URL}/api/otp/generate/"
    res_otp = requests.post(otp_gen_url, json={"transaction_id": tx_id}, timeout=5)
    if res_otp.status_code != 201:
        print(f"❌ Failed to generate OTP: {res_otp.status_code} - {res_otp.text}")
        return

    otp_data = res_otp.json()
    otp_code = otp_data["dev_otp"]
    print(f"✓ Step 2: Dummy Bank generated transaction OTP: {otp_code}")

    # 3. Verify OTP & Forward Context to PayShield
    otp_verify_url = f"{DUMMY_BANK_URL}/api/otp/verify/"
    res_verify = requests.post(otp_verify_url, json={"transaction_id": tx_id, "otp": otp_code}, timeout=5)
    if res_verify.status_code != 200:
        print(f"❌ Failed to verify OTP: {res_verify.status_code} - {res_verify.text}")
        return

    verify_data = res_verify.json()
    payshield_info = verify_data.get("payshield", {})
    
    print(f"✓ Step 3: Bank OTP verified! Forwarded to PayShield.")
    print("-" * 60)
    print(f"🎉 SUCCESS! Payment is now waiting for PayShield Mobile Approval:")
    print(f"   Approval ID: {payshield_info.get('approval_id')}")
    print(f"   Status: {payshield_info.get('approval_status')}")
    print(f"   Window: 60 Seconds before auto-cancellation")
    print("-" * 60)
    print("👉 Now open your Expo Go app on your phone (or tap 'Refresh ↻') to see the alert and approve/deny!")

if __name__ == "__main__":
    amt = sys.argv[1] if len(sys.argv) > 1 else "2499.00"
    desc = sys.argv[2] if len(sys.argv) > 2 else "Electronics Purchase - Flipkart"
    simulate_payment(amount=amt, description=desc)
