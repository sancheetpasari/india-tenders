@echo off
rem Daily tender reminder - run by Windows Task Scheduler at 08:00 IST.
rem
rem The laptop sends this rather than GitHub Actions: Actions' scheduler runs
rem this repository's crons hours late and sometimes skips them, which is no
rem use for a morning digest. The workflow stays on as a fallback at 11:00 for
rem days this machine is off, and --announce tells it to stand down when we
rem have already sent.
rem
rem The app password is NOT here. It lives in Windows Credential Manager; see
rem smtp_password() in send_reminders.py for the one-off command that sets it.
cd /d "%~dp0"
set SMTP_USER=sancheet.pasari@gmail.com
set MAIL_TO=sancheet.pasari@gmail.com
python send_reminders.py --announce >> reminder-history.log 2>&1
