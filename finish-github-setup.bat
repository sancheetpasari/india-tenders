@echo off
REM Run this AFTER `gh auth login`. It does everything else:
REM   creates the public repo, pushes, turns on Pages, starts the first run.
setlocal
cd /d "%~dp0"
set GH="C:\Program Files\GitHub CLI\gh.exe"

%GH% auth status >nul 2>&1
if errorlevel 1 (
  echo Not logged in yet. Run this first:
  echo     "C:\Program Files\GitHub CLI\gh.exe" auth login
  exit /b 1
)

echo == creating public repo and pushing ==
%GH% repo create india-tenders --public --source=. --remote=origin --push || goto :err

echo.
echo == enabling GitHub Pages via Actions ==
for /f "delims=" %%u in ('%GH% api user --jq .login') do set OWNER=%%u
%GH% api -X POST "repos/%OWNER%/india-tenders/pages" -f build_type=workflow >nul 2>&1 ^
  || %GH% api -X PUT "repos/%OWNER%/india-tenders/pages" -f build_type=workflow >nul 2>&1

echo.
echo == starting the first refresh ==
%GH% workflow run "Refresh tenders" || goto :err

echo.
echo Done. Watch it with:   %GH% run watch
echo Your site will be:     https://%OWNER%.github.io/india-tenders/
exit /b 0

:err
echo.
echo Something failed above - the message should say what.
exit /b 1
