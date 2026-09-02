@echo off
rem Serve the dashboard. Data refreshes nightly at 00:00 via Windows Task Scheduler.
cd /d "%~dp0"
python live.py --serve-only
