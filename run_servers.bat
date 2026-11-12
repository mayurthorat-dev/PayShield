@echo off
title PayShield All Services Launcher
echo ========================================================
echo   Starting PayShield Ecosystem with IP: 192.168.1.13
echo ========================================================
echo.

set DUMMY_BANK_API_TOKEN=payshield-dummy-bank-shared-secret-token
set PAYSHIELD_API_TOKEN=payshield-dummy-bank-shared-secret-token
set PAYSHIELD_TRANSACTION_CONTEXT_URL=http://127.0.0.1:8000/api/integration/transaction-context/
set DUMMY_BANK_DECISION_URL=http://127.0.0.1:8001/api/transactions/decision/
set DUMMY_BANK_VERIFY_URL=http://127.0.0.1:8001/api/accounts/verify-link/
set DUMMY_BANK_DISCOVER_URL=http://127.0.0.1:8001/api/accounts/discover/

echo 1. Launching Dummy Bank Core Banking Web on Port 8001...
start "Dummy Bank [Port 8001]" cmd /k "cd /d "%~dp0dummy_bank" && set DUMMY_BANK_API_TOKEN=payshield-dummy-bank-shared-secret-token && set PAYSHIELD_API_TOKEN=payshield-dummy-bank-shared-secret-token && set PAYSHIELD_TRANSACTION_CONTEXT_URL=http://127.0.0.1:8000/api/integration/transaction-context/ && .venv\Scripts\python.exe manage.py runserver 0.0.0.0:8001"

echo 2. Launching PayShield Backend API on Port 8000...
start "PayShield Backend [Port 8000]" cmd /k "cd /d "%~dp0backend" && set DUMMY_BANK_API_TOKEN=payshield-dummy-bank-shared-secret-token && set PAYSHIELD_API_TOKEN=payshield-dummy-bank-shared-secret-token && set DUMMY_BANK_DECISION_URL=http://127.0.0.1:8001/api/transactions/decision/ && .venv\Scripts\python.exe manage.py runserver 0.0.0.0:8000"

echo 3. Launching Mobile Expo Dev Server on Port 8081...
start "PayShield Mobile [Expo]" cmd /k "cd /d "%~dp0mobile" && npx expo start"

echo.
echo ========================================================
echo   All 3 services launched in separate windows!
echo   - Web Banking Portal: http://127.0.0.1:8001/
echo   - Backend API:        http://192.168.1.13:8000/
echo   - Expo App:           Scan the QR code from the Expo window
echo ========================================================
echo.
pause
