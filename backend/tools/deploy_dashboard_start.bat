@echo off
rem Starts the local deploy dashboard (deploy_dashboard.py) in the background.
rem Double-click this file. See MOTRIX-ERP-QUICK.md section 14.3c.
rem NOTE: keep this file plain ASCII only (no Chinese) - see
rem feedback_windows_locale_encoding_pitfall: cmd.exe misparses multi-byte
rem UTF-8 bytes in .bat files under this machine's default codepage.

cd /d "%~dp0\.."

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
    echo [Notice] Deploy dashboard already appears to be running - port 8765 is in use.
    echo To restart it, run deploy_dashboard_stop.bat first, then run this again.
    start "" http://127.0.0.1:8765
    pause
    exit /b 0
)

echo Starting deploy dashboard...
start /min "MOTRIX Deploy Dashboard" cmd /c "python tools\deploy_dashboard.py >> tools\deploy_dashboard_run.log 2>&1"

timeout /t 2 /nobreak >nul

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if errorlevel 1 (
    echo [Failed] Deploy dashboard did not start. Check tools\deploy_dashboard_run.log for details.
    pause
    exit /b 1
)

echo Deploy dashboard started: http://127.0.0.1:8765
start "" http://127.0.0.1:8765
