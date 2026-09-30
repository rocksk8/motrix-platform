@echo off
chcp 65001 >nul
set PYTHONUTF8=1

:: ===================================================================
:: MOTRIX ERP server loop (customer template). This file lives in <install dir>\backend
:: and is NOT overwritten by updates (it is per-install configuration).
::
:: Outbound features are OFF by default. To turn one on, remove the leading "::" of its line
:: and then restart the loop (Task Scheduler: "MOTRIX ERP Server Autostart" -> End -> Run, or reboot).
:: Restarting only uvicorn is NOT enough: this loop must be restarted to read the new values.
::   :: set MOTRIX_TENDER_RADAR=1      tender radar: fetches public tenders on the schedule
::   :: set MOTRIX_GEO=1               address geocoding through OpenStreetMap
:: Python: "python" must be on PATH for the account that runs this task
:: (or replace "python" below with the full path of python.exe).
:: Port: put a number in backend\.install_port to change the default 666.
:: ===================================================================
cd /d "%~dp0"
if not exist "%~dp0logs" mkdir "%~dp0logs"

set PORT=666
if exist "%~dp0.install_port" set /p PORT=<"%~dp0.install_port"

:loop
echo [%date% %time%] MOTRIX ERP starting... >> "%~dp0logs\server.log"

:: HTTPS is used automatically when certs\cert.pem and certs\key.pem exist (see https_setup.ps1).
set SSL_ARGS=
if exist "certs\cert.pem" if exist "certs\key.pem" set SSL_ARGS=--ssl-keyfile=certs\key.pem --ssl-certfile=certs\cert.pem

python -m uvicorn main:app --port %PORT% --host 0.0.0.0 --log-level info %SSL_ARGS% >> "%~dp0logs\server.log" 2>&1
echo [%date% %time%] MOTRIX ERP stopped (exit code %errorlevel%). restart in 5s... >> "%~dp0logs\server.log"
timeout /t 5 /nobreak >nul
goto loop
