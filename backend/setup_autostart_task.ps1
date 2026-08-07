# MOTRIX ERP — Windows 工作排程器「開機自動啟動」設定
# 執行：powershell -ExecutionPolicy Bypass -File setup_autostart_task.ps1
#
# 重建紀錄（2026-08-08）：這支腳本原本只存在正式機，開發機 git repo 一直沒有
# 備份（MOTRIX-ERP-QUICK.md §0 已知落差第 2 筆、DR-SOP.md §3 第 1 點）。這份是
# 依照 QUICK.md §1.1 記載的行為規格、比照 setup_backup_task.ps1 的既有寫法重建，
# 並補上 apply_update.ps1 已有的「只能在正式機路徑執行」身分守門。下次真的接觸
# 到正式機時，務必跟正式機上實際在跑的版本 diff 一次，確認行為一致再視情況取代
# 這份重建版。

$TaskName   = "MOTRIX ERP Server Autostart"
$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProdRoot   = "C:\Users\Motrix\Desktop\V9.0"

# autostart.bat / autostart_hidden.vbs 內部路徑都寫死 Motrix 帳號（見該兩檔），
# 在其他機器註冊這個排程工作沒有意義，只會指向不存在的路徑——擋在這裡而不是
# 讓它悄悄註冊一個永遠不會正常運作的工作。
if ($BackendDir -ne (Join-Path $ProdRoot "backend")) {
    Write-Error "此腳本只應在正式機（$ProdRoot）執行；目前路徑為 $BackendDir。中止，未做任何變更。"
    exit 1
}

$VbsPath = Join-Path $BackendDir "autostart_hidden.vbs"
if (-not (Test-Path $VbsPath)) { Write-Error "找不到 $VbsPath"; exit 1 }

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed old task: $TaskName"
}

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$VbsPath`""

# 登入後延遲 90 秒才啟動：避開 GoogleDriveFS（同樣登入時啟動）掛載 H: 的搶跑窗口
# ——見 QUICK.md §1.1。GoogleDriveFS 還沒掛好時就啟動，_daily_backup() 等雲端備份
# 路徑檢查（archive.py _archive_ok()）會誤判成「H: 未掛載」，白白多寫一次警示。
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT90S"

# autostart.bat 自己內建 crash-restart 迴圈（uvicorn 意外中止 5 秒後自動重啟，
# 見該檔），Task Scheduler 這邊只負責「登入時啟動一次」，不需要也不應該再疊加一層
# 重試機制（RestartCount 預設 0 = 不重試，故意不設定）；伺服器要一路跑到登出/
# 關機，執行時間不設上限。
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description "MOTRIX ERP: 開機自動啟動 uvicorn（autostart.bat 內建 crash-restart 迴圈，見 backend/autostart.bat）" | Out-Null

Write-Host ""
Write-Host "=== Scheduled task registered ===" -ForegroundColor Green
Write-Host "Task    : $TaskName"
Write-Host "Trigger : At logon ($env:USERNAME) + 90s delay"
Write-Host "Action  : wscript.exe `"$VbsPath`""
Write-Host ""
Write-Host "Test run:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Get-Content backend\logs\server.log -Tail 20"
