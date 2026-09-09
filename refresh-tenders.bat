@echo off
rem Tender refresh - run by Windows Task Scheduler at 00:00 and 12:00
cd /d "%~dp0"

rem Keep Chromium off C:. Gujarat and Bihar kept failing with "BrowserType.launch:
rem Executable doesn't exist" on scheduled runs while the same command worked in an
rem interactive shell. C: sits near-full and Storage Sense reclaims %LOCALAPPDATA%
rem caches under disk pressure, so the default ms-playwright cache there is not a
rem safe place for it. D: has room. Set here as well as in the user environment:
rem a task started from an existing logon inherits that logon's environment block,
rem so a newly-set user variable would not reach this run.
set "PLAYWRIGHT_BROWSERS_PATH=D:\playwright-browsers"

rem what this context resolves -- see probe_env.py
python probe_env.py >> refresh-history.log 2>&1
python scraper.py --window 14 --deadline 900 >> refresh-history.log 2>&1
python build_artifact.py >> refresh-history.log 2>&1
rem send GeM / AP / Chhattisgarh / Gujarat up so the cloud page can use them
python push_to_cloud.py >> refresh-history.log 2>&1

rem GitHub drops free-tier scheduled runs often enough that the cloud page can
rem sit half a day behind its own 00:00/12:00 cron, so start the workflow here
rem rather than trust it. Only after a successful upload: if nothing went up,
rem the cloud has nothing new to merge and its cron can handle it.
if errorlevel 1 goto :eof
set "GH=gh"
where gh >nul 2>&1 || set "GH=C:\Program Files\GitHub CLI\gh.exe"
"%GH%" workflow run refresh.yml >> refresh-history.log 2>&1
