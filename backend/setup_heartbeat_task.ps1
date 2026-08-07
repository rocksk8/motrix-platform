# MOTRIX ERP — Windows 工作排程器「心跳監控」設定
# 執行：powershell -ExecutionPolicy Bypass -File setup_heartbeat_task.ps1（需系統管理員權限，
#       因為要用 SYSTEM 帳號註冊工作）
#
# 重建紀錄（2026-08-08）：同 setup_autostart_task.ps1，這支腳本原本只存在正式機、
# 開發機 git repo 一直沒有備份（QUICK.md §0 已知落差第 2 筆、DR-SOP.md §3 第 1 點）。
# 依 QUICK.md §1.2 記載的行為規格重建：獨立於登入狀態、每 5 分鐘執行一次
# heartbeat_job.py（同目錄，本身不 import app，ERP 服務掛了也照跑）。下次接觸
# 正式機時務必跟實際在跑的版本 diff 一次。
#
# ⚠️ 不要在非正式機上執行這支腳本並允許它註冊——heartbeat_config.json 裡設定的
# ping_url 若剛好是正式機在用的 healthchecks.io 監控端點，在別台機器上重複打卡
# 會混淆「正式機是否還活著」的判斷，本機服務沒開著時甚至會誤觸發 /fail 告警。

$TaskName   = "MOTRIX ERP Heartbeat"
$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProdRoot   = "C:\Users\Motrix\Desktop\V9.0"
$Script     = Join-Path $BackendDir "heartbeat_job.py"

if ($BackendDir -ne (Join-Path $ProdRoot "backend")) {
    Write-Error "此腳本只應在正式機（$ProdRoot）執行；目前路徑為 $BackendDir。中止，未做任何變更。"
    exit 1
}

if (-not (Test-Path $Script)) { Write-Error "Script not found: $Script"; exit 1 }

# 不寫死使用者帳號路徑——動態找目前這台機器實際在用的 python.exe（同
# setup_backup_task.ps1 的做法）。
$Python = $null
$cmd = Get-Command python -ErrorAction SilentlyContinue
if ($cmd) { $Python = $cmd.Source }
if (-not $Python) {
    $candidates = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue
    if ($candidates) { $Python = ($candidates | Select-Object -First 1).FullName }
}
if (-not $Python -or -not (Test-Path $Python)) { Write-Error "Python not found (checked PATH and $env:LOCALAPPDATA\Programs\Python\Python3*\python.exe)"; exit 1 }

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed old task: $TaskName"
}

$action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Script`"" -WorkingDirectory $BackendDir

# 註冊後立即開始，每 5 分鐘重複，不綁定登入狀態（見 QUICK.md §1.2）——
# heartbeat_job.py 本身不 import main app，即使沒有人登入、ERP 服務本身掛了，
# 這支心跳仍要能獨立運作並回報。
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration ([TimeSpan]::MaxValue)

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

# SYSTEM 帳號、ServiceAccount 登入類型：不需要存密碼，且不依賴任何使用者是否登入。
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force `
    -Description "MOTRIX ERP: 每 5 分鐘心跳檢查（heartbeat_job.py，獨立於登入狀態與 ERP 服務本身）" | Out-Null

Write-Host ""
Write-Host "=== Scheduled task registered ===" -ForegroundColor Green
Write-Host "Task    : $TaskName"
Write-Host "Trigger : 立即開始，每 5 分鐘重複（不綁登入，SYSTEM 帳號）"
Write-Host "Python  : $Python"
Write-Host "Script  : $Script"
Write-Host ""
Write-Host "Test run:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Get-Content backend\logs\heartbeat_job.log -Tail 20"
