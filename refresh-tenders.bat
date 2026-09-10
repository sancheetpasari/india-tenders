@echo off
rem Local tender refresh - run by Windows Task Scheduler at 10:00 and 16:00.
rem
rem This machine does NOT scrape all 43 sources. It cannot: Modern Standby puts
rem the laptop to sleep after a few idle minutes and kills the run, at any hour
rem and whatever the schedule. Every scheduled full scrape since 8 September
rem died that way, usually with no more than a hex code to show for it.
rem
rem Instead: take the cloud's published dataset, which already has the 39
rem sources GitHub can reach, and scrape only the four that refuse its runners.
rem That is about fourteen minutes, which does fit in a waking window.
cd /d "%~dp0"
python pull_cloud.py >> refresh-history.log 2>&1
python scraper.py --states GeM Gujarat "Andhra Pradesh" Chhattisgarh --deadline 900 >> refresh-history.log 2>&1
python build_artifact.py >> refresh-history.log 2>&1
python push_to_cloud.py >> refresh-history.log 2>&1
if errorlevel 1 goto :eof
set "GH=gh"
where gh >nul 2>&1 || set "GH=C:\Program Files\GitHub CLI\gh.exe"
"%GH%" workflow run refresh.yml >> refresh-history.log 2>&1
