@echo off
chcp 65001 >nul
title MOTRIX ERP - Restart
cd /d "%~dp0"

echo ======================================
echo   MOTRIX ERP - Restart Server
echo ======================================
echo.

echo [1/4] Killing all Python processes on port 666...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":666 "') do (
    echo   Kill PID %%p
    taskkill /F /PID %%p >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo [2/4] Force-kill any remaining uvicorn / python holding port 666...
taskkill /F /IM uvicorn.exe >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":666 "') do (
    taskkill /F /PID %%p >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo [3/4] Verify port 666 is free...
netstat -ano | findstr ":666 " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   WARNING: port 666 still occupied, waiting extra 3s...
    timeout /t 3 /nobreak >nul
) else (
    echo   Port 666 is free.
)

echo.
echo [4/4] Starting new server (port 666)...
for /f "tokens=2 delims=[]" %%a in ('ping -n 1 -4 "%COMPUTERNAME%" ^| findstr "["') do set MY_IP=%%a
if defined MY_IP (
    echo   Local:  http://localhost:666
    echo   LAN:    http://%MY_IP%:666
) else (
    echo   http://localhost:666
)
echo.
echo   Ctrl+C to stop
echo ======================================
echo.

if not exist "logs" mkdir "logs"
echo [%date% %time%] Manual restart >> "logs\server.log"

uvicorn main:app --port 666 --host 0.0.0.0 --log-level info
pause
