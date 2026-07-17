@echo off
cd /d "C:\Users\hichan\Desktop\MOTRIX-ERP\backend"
if not exist "C:\Users\hichan\Desktop\MOTRIX-ERP\backend\logs" mkdir "C:\Users\hichan\Desktop\MOTRIX-ERP\backend\logs"
echo [%date% %time%] MOTRIX ERP starting... >> "C:\Users\hichan\Desktop\MOTRIX-ERP\backend\logs\server.log"
"C:\Users\hichan\AppData\Local\Programs\Python\Python313\Scripts\uvicorn.exe" main:app --port 666 --host 0.0.0.0 --log-level info >> "C:\Users\hichan\Desktop\MOTRIX-ERP\backend\logs\server.log" 2>&1
echo [%date% %time%] MOTRIX ERP stopped. >> "C:\Users\hichan\Desktop\MOTRIX-ERP\backend\logs\server.log"
