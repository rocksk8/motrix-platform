<#
  apply_update.ps1 — 在「正式機」執行

  用途：把 build_deploy_package.ps1 在開發機打包好、手動複製過來的部署包，
  套用到正式機。只換程式碼／schema，絕不覆蓋 db / uploads / PDF / logs / 設定檔。

  安全機制：
    - 身分守門：只能在正式機路徑下執行
    - 套用前：版本比對（避免重複/退版套用）+ 健康檢查記錄 + db 快照 + 程式碼快照（回滾用）
    - 套用中：安全停服（讓既有 autostart crash-restart 迴圈接手重啟，不自己搶 port）+ 只複製，不做 /MIR 鏡像刪除
    - 套用後：輪詢 /api/ping + 檢查 server.log 有無新錯誤；失敗就自動回滾並重啟

  用法：
    powershell -ExecutionPolicy Bypass -File apply_update.ps1 -PackagePath D:\deploy\20260801_120000_abcd123
    powershell -ExecutionPolicy Bypass -File apply_update.ps1 -PackagePath ... -Force   # 版本比對沒過也強制套用
    powershell -ExecutionPolicy Bypass -File apply_update.ps1 -PackagePath ... -Yes     # 跳過互動確認（僅供自動化測試用）
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackagePath,

    [switch]$Force,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"

$ProdRoot = "C:\Users\Motrix\Desktop\V9.0"
$BackendDir = Join-Path $ProdRoot "backend"
$FrontendDir = Join-Path $ProdRoot "frontend"
$PingUrl = "http://127.0.0.1:666/api/ping"

function Fail($msg) {
    Write-Host "`n[FAIL] $msg" -ForegroundColor Red
    exit 1
}
function Info($msg)  { Write-Host $msg }
function Warn($msg)  { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Ok($msg)    { Write-Host "[OK] $msg" -ForegroundColor Green }

Write-Host "======================================"
Write-Host "  MOTRIX ERP - Apply Update"
Write-Host "======================================"

# ============================================================
# Step 0: 身分守門 —— 只能在正式機執行
# ============================================================
$scriptRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
if ($scriptRoot -ne $ProdRoot) {
    Fail "偵測到執行路徑為 '$scriptRoot'，不是正式機路徑 '$ProdRoot'。本腳本只允許在正式機執行，中止。"
}
Info "身分確認：正式機（$ProdRoot）`n"

if (-not (Test-Path $PackagePath)) {
    Fail "找不到部署包路徑：$PackagePath"
}
$manifestPath = Join-Path $PackagePath "deploy_manifest.json"
if (-not (Test-Path $manifestPath)) {
    Fail "部署包內找不到 deploy_manifest.json（$PackagePath），不是合法的部署包。"
}
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json

# ============================================================
# Step 1: 套用前檢查
# ============================================================
Info "[1/5] 套用前檢查..."

$deployedMarkerPath = Join-Path $BackendDir ".deployed_commit.json"
$prevDeployed = $null
if (Test-Path $deployedMarkerPath) {
    try { $prevDeployed = Get-Content $deployedMarkerPath -Raw | ConvertFrom-Json } catch {}
}

if ($prevDeployed -and $prevDeployed.commit -eq $manifest.commit) {
    if (-not $Force) {
        Fail "這個部署包（commit $($manifest.commit_short)）跟正式機目前已套用的版本相同，看起來是重複套用。如果確定要強制重套，請加 -Force。"
    } else {
        Warn "版本相同，但因為 -Force 強制繼續套用。"
    }
}

Info "  目前正式機版本：$(if ($prevDeployed) { $prevDeployed.commit_short + ' / ' + $prevDeployed.applied_at } else { '（未知，本次視為基準）' })"
Info "  部署包版本：     $($manifest.commit_short) / $($manifest.built_at) / branch=$($manifest.branch)"
if ($manifest.version_manifest_latest) {
    Info "  version_manifest 最新一筆：$($manifest.version_manifest_latest.module) $($manifest.version_manifest_latest.version)"
}

# 套用前健康檢查（僅記錄，不作為中止條件）
$preHealthy = $false
try {
    $resp = Invoke-WebRequest -Uri $PingUrl -UseBasicParsing -TimeoutSec 3
    if ($resp.StatusCode -eq 200) { $preHealthy = $true }
} catch {}
Info "  套用前伺服器健康狀態：$(if ($preHealthy) { '正常' } else { '無回應（可能已停機，仍會繼續套用）' })"

# --- 備份（不管等一下順不順利，都先留退路）---
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

$dbBackupDir = Join-Path $BackendDir "db_backups\pre_update_$timestamp"
New-Item -ItemType Directory -Force -Path $dbBackupDir | Out-Null
$dbPath = Join-Path $BackendDir "motrix_erp.db"
if (Test-Path $dbPath) {
    Copy-Item $dbPath (Join-Path $dbBackupDir "motrix_erp.db") -Force
    Ok "  db 快照：$dbBackupDir\motrix_erp.db"
} else {
    Warn "  找不到 motrix_erp.db，略過 db 快照。"
}

# ============================================================
# Migration 乾跑驗證 —— 新版 db.py 只在 db 快照的「副本」上跑一次，
# 正式庫完全不碰。失敗就在這裡直接中止，不停服、不碰正式庫、
# 不留回滾快照，把「正式庫是第一個試跑新 migration 的地方」的風險
# 移到這一步先擋下來。
# ============================================================
if (Test-Path $dbPath) {
    Info "  Migration 乾跑驗證..."
    $dryRunDb = Join-Path $env:TEMP "motrix_erp_dryrun_$timestamp.db"
    Copy-Item (Join-Path $dbBackupDir "motrix_erp.db") $dryRunDb -Force

    $dryRunPy = Join-Path $env:TEMP "motrix_dryrun_$timestamp.py"
    @"
import sys
sys.path.insert(0, r'$(Join-Path $PackagePath "backend")')
import db
db.init_db(r'$dryRunDb')
print('DRYRUN_OK')
"@ | Set-Content -Path $dryRunPy -Encoding UTF8

    $dryRunOutput = & python $dryRunPy 2>&1
    $dryRunExit = $LASTEXITCODE
    Remove-Item $dryRunDb, $dryRunPy -Force -ErrorAction SilentlyContinue

    if ($dryRunExit -ne 0 -or ($dryRunOutput -notmatch "DRYRUN_OK")) {
        Write-Host ""
        Write-Host "======================================" -ForegroundColor Red
        Write-Host "  Migration 乾跑驗證失敗，中止套用（正式庫完全未被觸碰）" -ForegroundColor Red
        Write-Host "======================================" -ForegroundColor Red
        Write-Host ($dryRunOutput | Out-String)
        Fail "新版本的 migration 在 db 快照副本上乾跑失敗，套用到正式庫時很可能也會出錯。請檢查上面的錯誤訊息、修好新版 db.py 的 migration 後重新打包，再重新套用。"
    }
    Ok "  Migration 乾跑驗證通過（新版 db.py 對照正式庫目前的 schema 乾跑一輪，未發現錯誤）。"
} else {
    Warn "  找不到正式庫 motrix_erp.db，略過 migration 乾跑驗證（視為全新安裝）。"
}

$rollbackRoot = Join-Path $BackendDir "rollback_snapshots"
$rollbackDir = Join-Path $rollbackRoot $timestamp
New-Item -ItemType Directory -Force -Path $rollbackDir | Out-Null
Info "  建立程式碼回滾快照：$rollbackDir"
robocopy $BackendDir (Join-Path $rollbackDir "backend") /E /XD db_backups rollback_snapshots logs /XF motrix_erp.db motrix_erp.db-wal motrix_erp.db-shm motrix_erp_demo.db motrix_erp_demo.db-wal motrix_erp_demo.db-shm heartbeat_config.json .deployed_commit.json server.log | Out-Null
robocopy $FrontendDir (Join-Path $rollbackDir "frontend") /E | Out-Null
Ok "  回滾快照完成。"

# 只保留最新 5 份回滾快照
$oldSnapshots = Get-ChildItem $rollbackRoot -Directory | Sort-Object Name -Descending | Select-Object -Skip 5
foreach ($s in $oldSnapshots) {
    Remove-Item $s.FullName -Recurse -Force
    Info "  清除舊回滾快照：$($s.Name)"
}

if (-not $Yes) {
    Write-Host ""
    $answer = Read-Host "確認要套用這個更新嗎？(y/N)"
    if ($answer -ne "y" -and $answer -ne "Y") {
        Fail "使用者取消，未做任何套用動作（備份已保留，可直接刪除或留著沒差）。"
    }
}

# ============================================================
# Step 2: 停止伺服器（讓 autostart 迴圈接手重啟，不自己搶 port）
# ============================================================
Info "`n[2/5] 停止伺服器..."
$conn = Get-NetTCPConnection -LocalPort 666 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    $p = $conn.OwningProcess
    Info "  Kill PID $p (listening on 666)"
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
} else {
    Info "  Port 666 目前無人監聽。"
}
Get-WmiObject Win32_Process | Where-Object {
    $_.CommandLine -like "*uvicorn*main:app*" -or $_.CommandLine -like "*spawn_main*parent_pid*"
} | ForEach-Object {
    Info "  Kill PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
Ok "  伺服器已停止，等待 autostart crash-restart 迴圈接手（見 §1.1，最長約 5 秒偵測到中止後重啟）。"

# ============================================================
# Step 3: 複製新程式碼（只加不刪，絕不 /MIR）
# ============================================================
Info "`n[3/5] 套用新程式碼..."

$rc1 = robocopy (Join-Path $PackagePath "backend") $BackendDir /E `
    /XD db_backups rollback_snapshots uploads logs 報價單PDF `
    /XF motrix_erp.db motrix_erp.db-wal motrix_erp.db-shm motrix_erp_demo.db motrix_erp_demo.db-wal motrix_erp_demo.db-shm heartbeat_config.json .deployed_commit.json server.log
if ($LASTEXITCODE -ge 8) { Fail "robocopy backend/ 失敗（exit code $LASTEXITCODE）。" }

$rc2 = robocopy (Join-Path $PackagePath "frontend") $FrontendDir /E
if ($LASTEXITCODE -ge 8) { Fail "robocopy frontend/ 失敗（exit code $LASTEXITCODE）。" }

# 根目錄文件（CHANGELOG.md / MOTRIX-ERP-QUICK.md / GITFLOW.md / .gitignore 等）
Get-ChildItem -Path $PackagePath -File | Where-Object { $_.Name -ne "deploy_manifest.json" } | ForEach-Object {
    Copy-Item $_.FullName -Destination $ProdRoot -Force
}
Ok "  程式碼＋文件已套用。"

# ============================================================
# Step 4: 套用後健康檢查
# ============================================================
Info "`n[4/5] 等待伺服器恢復並健康檢查..."
$healthy = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 2
    try {
        $resp = Invoke-WebRequest -Uri $PingUrl -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch {}
}

$logErrors = @()
$logPath = Join-Path $BackendDir "logs\server.log"
if (Test-Path $logPath) {
    $tail = Get-Content $logPath -Tail 80
    $logErrors = $tail | Select-String -Pattern "Traceback|ERROR" -SimpleMatch:$false
}

if ($healthy -and -not $logErrors) {
    Ok "  /api/ping 回應正常，log 未見新錯誤。"
} else {
    Warn "  套用後健康檢查失敗：healthy=$healthy, log 錯誤筆數=$($logErrors.Count)"
    Warn "  觸發自動回滾..."

    robocopy (Join-Path $rollbackDir "backend") $BackendDir /E | Out-Null
    robocopy (Join-Path $rollbackDir "frontend") $FrontendDir /E | Out-Null

    $conn2 = Get-NetTCPConnection -LocalPort 666 -State Listen -ErrorAction SilentlyContinue
    if ($conn2) { Stop-Process -Id $conn2.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2

    $rolledBackHealthy = $false
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 2
        try {
            $resp = Invoke-WebRequest -Uri $PingUrl -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -eq 200) { $rolledBackHealthy = $true; break }
        } catch {}
    }

    Write-Host ""
    Write-Host "======================================" -ForegroundColor Red
    Write-Host "  更新失敗，已自動回滾到套用前版本" -ForegroundColor Red
    Write-Host "  回滾後健康狀態：$(if ($rolledBackHealthy) { '正常' } else { '仍異常，需要人工介入！' })" -ForegroundColor Red
    Write-Host "  程式碼回滾快照留存於：$rollbackDir" -ForegroundColor Red
    Write-Host "  db 套用前快照留存於：$dbBackupDir" -ForegroundColor Red
    Write-Host "======================================" -ForegroundColor Red
    exit 1
}

# ============================================================
# Step 5: 更新版本追蹤檔
# ============================================================
Info "`n[5/5] 更新版本追蹤檔..."
$deployed = [ordered]@{
    commit       = $manifest.commit
    commit_short = $manifest.commit_short
    branch       = $manifest.branch
    applied_at   = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    built_at     = $manifest.built_at
}
$deployed | ConvertTo-Json -Depth 6 | Set-Content -Path $deployedMarkerPath -Encoding UTF8

Write-Host ""
Write-Host "======================================" -ForegroundColor Green
Write-Host "  更新完成：$($manifest.commit_short)" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host ""
Write-Host "提醒："
Write-Host "  - 套用前 db 快照：$dbBackupDir"
Write-Host "  - 套用前程式碼快照：$rollbackDir"
Write-Host "  - 若本次更新對應到已知落差紀錄（§0），記得回去更新該表格狀態"
