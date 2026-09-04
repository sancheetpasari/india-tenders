@echo off
rem Tender refresh - run by Windows Task Scheduler at 00:00 and 12:00
cd /d "%~dp0"
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
