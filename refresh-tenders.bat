@echo off
rem Tender refresh - run by Windows Task Scheduler at 00:00 and 12:00
cd /d "%~dp0"
python scraper.py --window 14 --deadline 900 >> refresh-history.log 2>&1
python build_artifact.py >> refresh-history.log 2>&1
rem send GeM / AP / Chhattisgarh / Gujarat up so the cloud page can use them
python push_to_cloud.py >> refresh-history.log 2>&1
