@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "C:\Users\Motrix\Desktop\V9.0\backend"
if not exist "C:\Users\Motrix\Desktop\V9.0\backend\logs" mkdir "C:\Users\Motrix\Desktop\V9.0\backend\logs"

:loop
echo [%date% %time%] MOTRIX ERP starting... >> "C:\Users\Motrix\Desktop\V9.0\backend\logs\server.log"
"C:\Users\Motrix\AppData\Local\Programs\Python\Python312\Scripts\uvicorn.exe" main:app --port 666 --host 0.0.0.0 --log-level info >> "C:\Users\Motrix\Desktop\V9.0\backend\logs\server.log" 2>&1
echo [%date% %time%] MOTRIX ERP stopped (exit code %errorlevel%). restart in 5s... >> "C:\Users\Motrix\Desktop\V9.0\backend\logs\server.log"
timeout /t 5 /nobreak >nul
goto loop