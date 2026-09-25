<#
  _prod_health_facts.ps1 — 部署前健康檢查要的「事實」（CORE-SPEC §9e D1），完全唯讀、不做判斷。
  由 _dashboard_remote.ps1 -Action health 以 Invoke-Command -FilePath 在正式機執行；
  抽成獨立檔是為了在開發機對假的安裝根目錄直接跑測試（tests/platform/test_deploy_dashboard_health_facts.py）。
  判斷規則在 deploy_insights.evaluate_health()。
#>
# 讀檔一律 -Encoding UTF8：PS 5.1 預設用系統字碼頁（cp950／cp932），Python 寫的 UTF-8 告警會變亂碼（測試抓到）
param([Parameter(Mandatory = $true)][string]$Root, [int]$Port = 666)
# 唯讀收集事實：任何一項失敗都不可以讓整支中斷（中斷＝畫面只剩「連線失敗」，2026-09-25 使用者實跑）。
# 錯誤收進 factErrors 一起回傳，判斷交給 evaluate_health。
$ErrorActionPreference = "Continue"
$Error.Clear()
# 稽核 A-3：輸出固定 UTF-8，結果不可以取決於執行者主控台的字碼頁（cp932／cp950 會把中文告警變亂碼）。
# ⚠ 遠端工作階段（wsmprovhost）沒有主控台，設定可能丟例外 ⇒ 包 try；-FilePath 的回傳走 Remoting 序列化，不經主控台編碼
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Error.Clear()
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
if (Test-Path $dm) { $deployed = [IO.File]::ReadAllText($dm, [Text.Encoding]::UTF8) }

# §9e D5：正式機的模組狀態（唯讀）——已安裝的模組與版本、包內的 modules.lock.json、
# 管理者停用清單（DB 以唯讀模式讀）、最近一次啟動時的模組載入紀錄。
$installed = @()
$modDir = Join-Path $b "modules"
if (Test-Path $modDir) {
    foreach ($md in (Get-ChildItem $modDir -Directory -ErrorAction SilentlyContinue)) {
        $mj = Join-Path $md.FullName "module.json"
        if (Test-Path $mj) {
            try { $m = Get-Content $mj -Raw -Encoding UTF8 | ConvertFrom-Json; $installed += @{ key = $m.key; version = $m.version } }
            catch { $installed += @{ key = $md.Name; version = $null; error = "module.json 讀不懂" } }
        }
    }
}
$lockRaw = $null
foreach ($lp in @((Join-Path $Root "modules.lock.json"), (Join-Path $b "modules.lock.json"))) {
    if (Test-Path $lp) { $lockRaw = [IO.File]::ReadAllText($lp, [Text.Encoding]::UTF8); break }
}
# 服務實際用的 python：取自 autostart.bat 的 uvicorn.exe 路徑（Scripts 的上一層）。
# ⚠ 不可用 PATH 上的 python：WinRM 工作階段拿不到使用者層 PATH（2026-09-25 實測：版本讀不到、prod_env.json 靜默未寫）；
#   而且 PATH 上那支不一定是服務在用的那支（稽核 AUDIT-C-host-D3D5 C-1）。
$pyExe = $null
$pySource = $null
$autostart = Join-Path $b "autostart.bat"
if (Test-Path $autostart) {
    $m = [regex]::Match([IO.File]::ReadAllText($autostart, [Text.Encoding]::UTF8), '"([^"]+?)\\Scripts\\uvicorn\.exe"', 'IgnoreCase')
    if ($m.Success) {
        $cand = Join-Path $m.Groups[1].Value "python.exe"
        if (Test-Path -LiteralPath $cand) { $pyExe = $cand; $pySource = "autostart.bat" }
    }
}
if (-not $pyExe) {
    $gc = Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($gc) { $pyExe = $gc.Source; $pySource = "PATH" }
}
$disabledRaw = $null
$disabledError = $null
$dbFile = Join-Path $b "motrix_erp.db"
$dbMissing = -not (Test-Path $dbFile)
if (-not $pyExe) { $disabledError = "找不到 python（autostart.bat 與 PATH 都沒有）" }
elseif (Test-Path $dbFile) {
    # ⚠ 整檔讀取一律用 [IO.File]::ReadAllText：Get-Content -Raw 的字串帶 PSPath 等附加屬性，ConvertTo-Json 會把它序列化成物件（測試抓到）
    # ⚠ 程式碼走 stdin（python -），不走 -c 參數：PS 5.1 傳參數給原生程式時會吃掉內嵌的雙引號
    #   （測試抓到：查詢靜默失敗、停用清單變成空的）。程式碼只用 ASCII，避開 $OutputEncoding。
    $py = @'
import sqlite3, sys, pathlib
conn = sqlite3.connect(pathlib.Path(sys.argv[1]).as_uri() + "?mode=ro", uri=True)
row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (sys.argv[2],)).fetchone()
print(row[0] if row else "")
'@
    $out = $py | & $pyExe - $dbFile "modules_disabled" 2>&1
    if ($LASTEXITCODE -eq 0) { $disabledRaw = ($out | Out-String).Trim() }
    else {
        $disabledError = ($out | Out-String).Trim()
        # 稽核 D-6：非 0 結束卻沒有輸出（例如 Store 別名殼 exit 49）也要留下痕跡
        if (-not $disabledError) { $disabledError = "python exit $LASTEXITCODE，沒有輸出" }
    }
}
$modLog = @()
$serverLog = Join-Path $b "logs\server.log"
if (Test-Path $serverLog) {
    $modLog = @(Get-Content $serverLog -Tail 3000 -Encoding UTF8 | Where-Object { $_ -match '模組 \S+ (\S+ )?(已載入|未載入)' } | Select-Object -Last 40 | ForEach-Object { [string]$_ })
}
# 正式機的 Python 版本與套件（唯讀）：開發機的專案 venv 要對齊它，「在正式機的環境裡驗證過」才成立
$pyVersion = $null
$pipFreeze = $null
$pyError = $null
if ($pyExe) {
    try { $pyVersion = ((& $pyExe --version 2>&1) | Out-String).Trim() } catch { $pyError = "python --version 失敗：" + $_.Exception.Message }
    # 稽核 D-5：只保留「名稱==版本」；帶 URL（可能含帳密）或 -e 的行只留名稱
    try {
        $pipFreeze = @((& $pyExe -m pip freeze --disable-pip-version-check 2>$null) | ForEach-Object {
            $l = [string]$_
            if ($l -match '^([A-Za-z0-9_.\-]+)==') { $l } elseif ($l -match '^([A-Za-z0-9_.\-]+)\s*@') { $Matches[1] + " @ <url 已移除>" } else { $null }
        } | Where-Object { $_ })
    } catch { $pyError = "pip freeze 失敗：" + $_.Exception.Message }
} else { $pyError = "找不到 python（autostart.bat 與 PATH 都沒有）" }
@{
    checkedAt      = (Get-Date).ToString("s")
    pythonVersion  = $pyVersion
    pythonPath     = $pyExe
    pythonSource   = $pySource
    pythonError    = $pyError
    pipFreeze      = @($pipFreeze)
    alertActive    = (Test-Path $alertFile)
    alertText      = $alertText
    latestDbBackup = $latestBackup
    disks          = $disks
    port666Listen  = $listen
    installDrive   = (Split-Path -Path $Root -Qualifier).TrimEnd(':')
    devMarkers     = @(@(".no_email_send", ".no_cloud_archive") | Where-Object { Test-Path (Join-Path $Root $_) })
    piiFolders     = $pii
    deployedRaw    = $deployed
    factErrors     = @($Error | Select-Object -First 20 | ForEach-Object { [string]$_ })
    modules        = @{ installed = $installed; lockRaw = $lockRaw; disabledRaw = $disabledRaw; disabledError = $disabledError; dbMissing = $dbMissing; logLines = $modLog }
} | ConvertTo-Json -Depth 6 -Compress
