@echo off
chcp 65001 >nul
:: 檢查是否以系統管理員身份執行
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo 需要系統管理員權限，自動提升中...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ====================================
echo   MOTRIX ERP — 防火牆設定
echo ====================================

:: 刪除舊規則（如有）
netsh advfirewall firewall delete rule name="MOTRIX ERP Port 666" >nul 2>&1

:: 新增入站規則
netsh advfirewall firewall add rule ^
    name="MOTRIX ERP Port 666" ^
    dir=in ^
    action=allow ^
    protocol=TCP ^
    localport=666 ^
    description="MOTRIX ERP Web Application"

if %errorLevel% equ 0 (
    echo.
    echo [OK] 防火牆規則已建立
    echo [OK] Port 666 已開放
    echo.
    echo 其他使用者請使用以下網址連線：
    for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
        set ip=%%a
        setlocal enabledelayedexpansion
        set ip=!ip: =!
        echo     http://!ip!:666
        endlocal
    )
) else (
    echo [錯誤] 防火牆設定失敗
)

echo.
pause
