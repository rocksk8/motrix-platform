@echo off
chcp 65001 >nul
echo ======================================
echo   MOTRIX ERP  —  starting on :666
echo ======================================
cd /d "%~dp0"
pip install -r requirements.txt -q

:: 顯示本機 IP
for /f "tokens=2 delims=[]" %%a in ('ping -n 1 -4 "%COMPUTERNAME%" ^| findstr "["') do set MY_IP=%%a
if defined MY_IP (
    echo   本機：  http://localhost:666
    echo   區網：  http://%MY_IP%:666
) else (
    echo   http://localhost:666
)
echo ======================================
echo   （防火牆未開？請先執行 firewall_setup.bat）
echo ======================================
echo.
uvicorn main:app --reload --port 666 --host 0.0.0.0
pause
