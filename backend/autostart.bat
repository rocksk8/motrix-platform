@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "C:\Users\Motrix\Desktop\V9.0\backend"
if not exist "C:\Users\Motrix\Desktop\V9.0\backend\logs" mkdir "C:\Users\Motrix\Desktop\V9.0\backend\logs"

:loop
echo [%date% %time%] MOTRIX ERP starting... >> "C:\Users\Motrix\Desktop\V9.0\backend\logs\server.log"

:: 2026-08-27：憑證存在就自動改用 HTTPS（見 https_setup.ps1），沒有憑證
:: 就維持原本明文 HTTP；每次迴圈重新判斷一次，管理員在服務運作中補產生
:: 憑證的話，下次崩潰/重啟就會自動切換成 HTTPS，不需要額外手動介入
set SSL_ARGS=
if exist "certs\cert.pem" if exist "certs\key.pem" set SSL_ARGS=--ssl-keyfile=certs\key.pem --ssl-certfile=certs\cert.pem

"C:\Users\Motrix\AppData\Local\Programs\Python\Python312\Scripts\uvicorn.exe" main:app --port 666 --host 0.0.0.0 --log-level info %SSL_ARGS% >> "C:\Users\Motrix\Desktop\V9.0\backend\logs\server.log" 2>&1
echo [%date% %time%] MOTRIX ERP stopped (exit code %errorlevel%). restart in 5s... >> "C:\Users\Motrix\Desktop\V9.0\backend\logs\server.log"
timeout /t 5 /nobreak >nul
goto loop