<#
  _prod_health_facts.ps1 — 部署前健康檢查要的「事實」（CORE-SPEC §9e D1），完全唯讀、不做判斷。
  由 _dashboard_remote.ps1 -Action health 以 Invoke-Command -FilePath 在正式機執行；
  抽成獨立檔是為了在開發機對假的安裝根目錄直接跑測試（tests/platform/test_deploy_dashboard_health_facts.py）。
  判斷規則在 deploy_insights.evaluate_health()。
#>
# 讀檔一律 -Encoding UTF8：PS 5.1 預設用系統字碼頁（cp950／cp932），Python 寫的 UTF-8 告警會變亂碼（測試抓到）
param([Parameter(Mandatory = $true)][string]$Root, [int]$Port = 666)
$b = Join-Path $Root "backend"
$alertFile = Join-Path $Root "backup_alerts\BACKUP_ALERT.txt"
$alertText = ""
if (Test-Path $alertFile) { $alertText = ((Get-Content $alertFile -TotalCount 5 -Encoding UTF8) -join "`n") }
# S-P02（2026-09-25 C 稽核）：只認每日快照 db_backups\YYYY-MM-DD\.done。
# 原本取 db_backups 底下「任何檔案」的最新時間 ⇒ 每次部署建的 pre_update_* 就能讓它變綠。
$latestBackup = $null
$bdir = Join-Path $b "db_backups"
if (Test-Path $bdir) {
    $d = Get-ChildItem $bdir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}$' -and (Test-Path (Join-Path $_.FullName ".done")) } |
        Sort-Object Name -Descending | Select-Object -First 1
    if ($d) {
        $done = Get-Item (Join-Path $d.FullName ".done")
        $latestBackup = @{ name = $d.Name; at = $done.LastWriteTime.ToString("s") }
    }
}
$disks = @()
foreach ($d in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
    if ($d.Free -ne $null) { $disks += @{ name = $d.Name; freeGB = [math]::Round($d.Free / 1GB, 1) } }
}
$listen = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).Count
$pii = @()
foreach ($d in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
    foreach ($sub in @("我的雲端硬碟\系統存檔_個資", "My Drive\系統存檔_個資")) {
        $p = Join-Path $d.Root $sub
        if (Test-Path -LiteralPath $p) { $pii += $p }
    }
}
$deployed = $null
$dm = Join-Path $b ".deployed_commit.json"
if (Test-Path $dm) { $deployed = (Get-Content $dm -Raw -Encoding UTF8) }
@{
    checkedAt      = (Get-Date).ToString("s")
    alertActive    = (Test-Path $alertFile)
    alertText      = $alertText
    latestDbBackup = $latestBackup
    disks          = $disks
    port666Listen  = $listen
    devMarkers     = @(@(".no_email_send", ".no_cloud_archive") | Where-Object { Test-Path (Join-Path $Root $_) })
    piiFolders     = $pii
    deployedRaw    = $deployed
} | ConvertTo-Json -Depth 5 -Compress
