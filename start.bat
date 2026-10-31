@echo off
title Fundamental Trading Intelligence
rem Starts the whole app (API + dashboard) on http://127.0.0.1:8000
rem and opens it in the default browser once the server has had a moment to boot.
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (
  echo Backend virtualenv not found. See README.md, section "First-time setup".
  pause
  exit /b 1
)
if not exist "..\frontend\dist\index.html" (
  echo Frontend build not found ^(frontend\dist^). The API will run, but the dashboard needs a build - see README.md.
)
echo Starting Fundamental Trading Intelligence on http://127.0.0.1:8000
echo Close this window to stop the app.
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
