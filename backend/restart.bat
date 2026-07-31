@echo off
chcp 65001 >nul
title MOTRIX ERP - Restart
cd /d "%~dp0"

echo ======================================
echo   MOTRIX ERP - Restart Server
echo ======================================
echo.

echo [1/4] Stopping server on port 666...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$conn = Get-NetTCPConnection -LocalPort 666 -State Listen -ErrorAction SilentlyContinue; if ($conn) { $p = $conn.OwningProcess; Write-Host '  Kill PID' $p '(listening)'; Stop-Process -Id $p -Force -ErrorAction SilentlyContinue; $wmi = Get-WmiObject Win32_Process -Filter ('ProcessId=' + $p) -ErrorAction SilentlyContinue; if ($wmi -and $wmi.ParentProcessId -gt 4) { Write-Host '  Kill parent PID' $wmi.ParentProcessId; Stop-Process -Id $wmi.ParentProcessId -Force -ErrorAction SilentlyContinue } } else { Write-Host '  Port 666 not in use.' }"

echo [2/4] Kill remaining uvicorn / multiprocessing workers...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like '*uvicorn*main:app*' -or $_.CommandLine -like '*spawn_main*parent_pid*' } | ForEach-Object { Write-Host '  Kill PID' $_.ProcessId; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul

echo [3/4] Verify port 666 is free...
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 666 -State Listen -ErrorAction SilentlyContinue) { Write-Host '  WARNING: port still occupied, waiting 3s...'; Start-Sleep 3 } else { Write-Host '  Port 666 is free.' }"

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

uvicorn main:app --port 666 --host 0.0.0.0 --log-level info
pause
