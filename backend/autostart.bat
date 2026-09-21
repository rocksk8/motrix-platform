@echo off
chcp 65001 >nul
set PYTHONUTF8=1

:: === 對外連線的兩個總開關（2026-09-22）=========================
:: 這兩個是【這台機器的設定】，不是產品的預設值。
:: 程式碼裡的出貨預設是【關】——那是對客戶的承諾：
::   一台裝好的機器不會在沒有人知道的情況下連到外面的網站。
:: 這裡打開，是因為這台是我們自己的正式機。
::
:: MOTRIX_TENDER_RADAR=1  每天在設定的時段連政府電子採購網抓標案公告
:: MOTRIX_GEO=1           把地址送到 OpenStreetMap 換成座標（算距離用）
::
:: 要關掉：把下面兩行加上 :: 註解掉，然後重新啟動【排程工作】
::   （不是重啟 uvicorn——見下面那段說明）
set MOTRIX_TENDER_RADAR=1
set MOTRIX_GEO=1
:: ===============================================================
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