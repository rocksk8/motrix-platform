# MOTRIX ERP — Windows 工作排程器每日備份設定
# 執行：powershell -ExecutionPolicy Bypass -File setup_backup_task.ps1

$TaskName = "MOTRIX ERP Daily Backup"
$BackendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\hichan\AppData\Local\Programs\Python\Python313\python.exe"
$Script = Join-Path $BackendDir "backup_job.py"

if (-not (Test-Path $Python)) { Write-Error "Python not found: $Python"; exit 1 }
if (-not (Test-Path $Script)) { Write-Error "Script not found: $Script"; exit 1 }

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

$trigger = New-ScheduledTaskTrigger -Daily -At "02:00"

$settingsParams = @{
    ExecutionTimeLimit         = (New-TimeSpan -Hours 1)
    RestartCount               = 2
    RestartInterval            = (New-TimeSpan -Minutes 10)
    StartWhenAvailable         = $true
    RunOnlyIfNetworkAvailable  = $false
}
$settings = New-ScheduledTaskSettingsSet @settingsParams

$taskParams = @{
    TaskName    = $TaskName
    Action      = $action
    Trigger     = $trigger
    Settings    = $settings
    Description = "MOTRIX ERP daily SQLite snapshot + cloud JSON backup (independent of ERP server)"
    RunLevel    = "Limited"
    Force       = $true
}
Register-ScheduledTask @taskParams | Out-Null

Write-Host ""
Write-Host "=== Scheduled task registered ===" -ForegroundColor Green
Write-Host "Task    : $TaskName"
Write-Host "Time    : Daily 02:00"
Write-Host "Python  : $Python"
Write-Host "Script  : $Script"
Write-Host ""
Write-Host "Test run:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Get-ScheduledTaskInfo -TaskName '$TaskName'"
