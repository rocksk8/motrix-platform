# MOTRIX ERP - Heartbeat scheduled task setup (independent of uvicorn)
# Run: powershell -ExecutionPolicy Bypass -File setup_heartbeat_task.ps1
#
# 2026-08-08：已跟正式機上實際版本 diff 過並校正一致（見 DR-SOP.md §3 第 1 點、
# MOTRIX-ERP-QUICK.md §0）。唯一刻意保留的差異是下面這段「只能在正式機路徑
# 執行」的身分守門——正式機原始版本沒有這段，是這次重建過程中額外補上的防呆，
# 純粹避免在其他機器誤跑導致誤判（例如 heartbeat_config.json 的 ping_url 若剛好
# 指到正式機在用的 healthchecks.io 端點，在別台機器上重複打卡會混淆判斷），
# 不影響正式機上的實際行為。

$TaskName   = "MOTRIX ERP Heartbeat"
$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProdRoot   = "C:\Users\Motrix\Desktop\V9.0"

# 正式機原始版本沒有這段，見檔頭說明。
if ($BackendDir -ne (Join-Path $ProdRoot "backend")) {
    Write-Error "此腳本只應在正式機（$ProdRoot）執行；目前路徑為 $BackendDir。中止，未做任何變更。"
    exit 1
}

$Python     = "C:\Users\Motrix\AppData\Local\Programs\Python\Python312\pythonw.exe"
$Script     = Join-Path $BackendDir "heartbeat_job.py"

if (-not (Test-Path $Script)) { Write-Error "Script not found: $Script"; exit 1 }
if (-not (Test-Path $Python)) { Write-Error "Python not found: $Python"; exit 1 }

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed old task: $TaskName"
}

$actionParams = @{
    Execute          = $Python
    Argument         = """$Script"""
    WorkingDirectory = $BackendDir
}
$action = New-ScheduledTaskAction @actionParams

# Starts immediately on registration, repeats every 5 minutes for 10 years (effectively indefinite);
# not tied to any logon event, so it keeps running across logon/logoff.
$triggerParams = @{
    Once               = $true
    At                 = (Get-Date)
    RepetitionInterval = (New-TimeSpan -Minutes 5)
    RepetitionDuration  = (New-TimeSpan -Days 3650)
}
$trigger = New-ScheduledTaskTrigger @triggerParams

$settingsParams = @{
    ExecutionTimeLimit         = (New-TimeSpan -Minutes 3)
    StartWhenAvailable         = $true
    RunOnlyIfNetworkAvailable  = $false
    AllowStartIfOnBatteries    = $true
    DontStopIfGoingOnBatteries = $true
    MultipleInstances          = "IgnoreNew"
}
$settings = New-ScheduledTaskSettingsSet @settingsParams

$taskParams = @{
    TaskName    = $TaskName
    Action      = $action
    Trigger     = $trigger
    Settings    = $settings
    Description = "MOTRIX ERP heartbeat: checks local /api/ping every 5 min, pings healthchecks.io on success; if this host or the ERP service goes down the ping stops and healthchecks.io emails the admin after the grace period."
    RunLevel    = "Limited"
    Force       = $true
}
Register-ScheduledTask @taskParams -ErrorAction Stop | Out-Null

Write-Host ""
Write-Host "=== Scheduled task registered ===" -ForegroundColor Green
Write-Host "Task    : $TaskName"
Write-Host "Trigger : Starts now, repeat every 5min for 10 years (not tied to logon)"
Write-Host "Action  : $Python $Script"
Write-Host ""
Write-Host "Test run:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Host "  Get-Content ..\backend\logs\heartbeat_job.log -Tail 20"
