@echo off
title Accu-Chek Auto-Sync Monitor
echo ===================================================
echo     Accu-Chek Instant - Bluetooth Automation Hub
echo ===================================================
echo.

:: 1. Check if venv exists and activate it
if exist venv\Scripts\activate (
    echo [1/3] Activating Virtual Environment...
    call venv\Scripts\activate
) else (
    echo [1/3] Checking Global Python...
    python --version >nul 2>&1
)

:: 2. Install/Update Libraries
echo [2/3] Verifying Libraries (Flask & Bleak)...
pip install flask bleak >nul 2>&1

:: 3. Run Server
echo [3/3] Starting System...
echo ---------------------------------------------------
echo  * Waiting for Accu-Chek readings...
echo ---------------------------------------------------
python server.py

pause