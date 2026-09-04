@echo off
rem Double-click this to store the Gmail App Password for reminder emails.
rem It opens a console, prompts once, and saves to Windows Credential Manager.
rem You only need to do this again if you revoke the app password in Google.
cd /d "%~dp0"
python store_password.py
echo.
pause
