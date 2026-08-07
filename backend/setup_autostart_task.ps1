# MOTRIX ERP — 開機（登入）自動啟動設定
# 執行：powershell -ExecutionPolicy Bypass -File setup_autostart_task.ps1
#
# 2026-08-08：已跟正式機上實際版本 diff 過並校正一致（見 DR-SOP.md §3 第 1 點、
# MOTRIX-ERP-QUICK.md §0）。唯一刻意保留的差異是下面這段「只能在正式機路徑
# 執行」的身分守門——正式機原始版本沒有這段，是這次重建過程中額外補上的防呆，
# 純粹避免在其他機器誤跑導致誤判，不影響正式機上的實際行為。

$TaskName = "MOTRIX ERP Server Autostart"
$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProdRoot = "C:\Users\Motrix\Desktop\V9.0"

# 正式機原始版本沒有這段；autostart_hidden.vbs 內部路徑寫死 Motrix 帳號，在
# 其他機器註冊這個排程工作沒有意義，擋在這裡總比悄悄註冊一個不會正常運作的
# 工作好。
if ($BackendDir -ne (Join-Path $ProdRoot "backend")) {
    Write-Error "此腳本只應在正式機（$ProdRoot）執行；目前路徑為 $BackendDir。中止，未做任何變更。"
    exit 1
}

$Wscript = "$env:WINDIR\System32\wscript.exe"
$Script = Join-Path $BackendDir "autostart_hidden.vbs"

if (-not (Test-Path $Script)) { Write-Error "Script not found: $Script"; exit 1 }

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed old task: $TaskName"
}

$actionParams = @{
    Execute          = $Wscript
    Argument         = """$Script"""
    WorkingDirectory = $BackendDir
}
$action = New-ScheduledTaskAction @actionParams

$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:COMPUTERNAME\$env:USERNAME"
# 延遲 90 秒再啟動：避免與 GoogleDriveFS（同樣設定登入時啟動）搶跑，
# 讓 H: 雲端硬碟掛載完成後 ERP 才啟動備份健康檢查，避免每次開機都誤報 BACKUP_ALERT
$trigger.Delay = "PT90S"

$settingsParams = @{
    ExecutionTimeLimit         = (New-TimeSpan -Hours 0)  # 0 = no time limit（伺服器需常駐）
    StartWhenAvailable         = $true
    RunOnlyIfNetworkAvailable  = $false
    AllowStartIfOnBatteries    = $true
    DontStopIfGoingOnBatteries = $true
}
$settings = New-ScheduledTaskSettingsSet @settingsParams

$taskParams = @{
    TaskName    = $TaskName
    Action      = $action
    Trigger     = $trigger
    Settings    = $settings
    Description = "MOTRIX ERP server auto-start on user logon (uvicorn :666, background hidden window)"
    RunLevel    = "Limited"
    Force       = $true
}
Register-ScheduledTask @taskParams -ErrorAction Stop | Out-Null

Write-Host ""
Write-Host "=== Scheduled task registered ===" -ForegroundColor Green
Write-Host "Task    : $TaskName"
Write-Host "Trigger : At logon of $env:USERNAME"
Write-Host "Action  : $Wscript $Script"
Write-Host ""
Write-Host "Test run:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Get-ScheduledTaskInfo -TaskName '$TaskName'"
