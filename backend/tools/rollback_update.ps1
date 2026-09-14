<#
  rollback_update.ps1 — 在「正式機」執行

  用途：把正式機手動還原回 apply_update.ps1 之前某一次套用時留下的快照
  （backend/rollback_snapshots/<timestamp>/ ＋ backend/db_backups/pre_update_<timestamp>/）。
  跟 apply_update.ps1 健康檢查失敗時的「自動回滾」邏輯是同一套（照抄該檔案第
  392-426 行），差別只在於這裡是「操作者主動選一個時間戳觸發」，不是被動因
  健康檢查失敗才觸發——例如套用後才發現功能邏輯有問題（健康檢查本身通過，
  但實際操作發現不對勁），這種情況 apply_update.ps1 自己不會自動回滾。

  用法：
    powershell -ExecutionPolicy Bypass -File rollback_update.ps1 -SnapshotTimestamp 20260908_030839
    powershell -ExecutionPolicy Bypass -File rollback_update.ps1 -SnapshotTimestamp ... -Yes   # 跳過互動確認
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SnapshotTimestamp,

    [switch]$Yes
)

$ErrorActionPreference = "Stop"

$ProdRoot = "C:\Users\Motrix\Desktop\V9.0"
$BackendDir = Join-Path $ProdRoot "backend"
$FrontendDir = Join-Path $ProdRoot "frontend"

# 跟 apply_update.ps1 同一套健康檢查手法。
#
# 2026-09-08：這裡原本還是 curl.exe -k 的舊版做法，跟 apply_update.ps1 當晚
# 早已改用 backend/tools/_healthcheck_ping.py（Python + OpenSSL，不經過
# Windows Schannel）不同步——兩支腳本原本各自維護一份幾乎一樣的 Test-Ping，
# apply_update.ps1 那邊修過、這邊忘了同步改，導致手動觸發回滾（這支腳本的
# 使用情境：健康檢查本身通過，但實際操作發現功能邏輯不對）仍然會踩到同一個
# curl.exe/Schannel 不穩定的問題。已同步改用 _healthcheck_ping.py，並補上
# 跟 apply_update.ps1 一致的逾時/迴圈次數/逐次記錄。詳見
# MOTRIX-ERP-QUICK.md §12 同日條目。
$UsesHttps = Test-Path (Join-Path $BackendDir "certs\cert.pem")
if ($UsesHttps) {
    $PingUrl = "https://127.0.0.1:666/api/ping"
} else {
    $PingUrl = "http://127.0.0.1:666/api/ping"
}

function Test-Ping {
    param([string]$Url, [int]$TimeoutSec = 3)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # 2026-09-08（再修）：同步 apply_update.ps1 的修法——2>$null 會把失敗
        # 原因整個丟掉，改成 2>&1 合併輸出，失敗時印出腳本回報的實際原因。
        $out = & python (Join-Path $PSScriptRoot "_healthcheck_ping.py") $Url $TimeoutSec 2>&1
        if ($LASTEXITCODE -ne 0 -and $out) { Warn "    健康檢查失敗詳情：$($out -join ' | ')" }
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

function Fail($msg) {
    Write-Host "`n[FAIL] $msg" -ForegroundColor Red
    exit 1
}
function Info($msg)  { Write-Host $msg }
function Warn($msg)  { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Ok($msg)    { Write-Host "[OK] $msg" -ForegroundColor Green }

Write-Host "======================================"
Write-Host "  MOTRIX ERP - Rollback"
Write-Host "======================================"

# ============================================================
# Step 0: 身分守門 —— 只能在正式機執行
# ============================================================
$scriptRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
if ($scriptRoot -ne $ProdRoot) {
    Fail "偵測到執行路徑為 '$scriptRoot'，不是正式機路徑 '$ProdRoot'。本腳本只允許在正式機執行，中止。"
}
Info "身分確認：正式機（$ProdRoot）`n"

# ============================================================
# Step 1: 驗證這個時間戳的快照真的存在
# ============================================================
$rollbackDir  = Join-Path $BackendDir "rollback_snapshots\$SnapshotTimestamp"
$dbBackupPath = Join-Path $BackendDir "db_backups\pre_update_$SnapshotTimestamp\motrix_erp.db"
$dbPath       = Join-Path $BackendDir "motrix_erp.db"

if (-not (Test-Path $rollbackDir)) {
    Fail "找不到程式碼快照：$rollbackDir"
}
if (-not (Test-Path $dbBackupPath)) {
    Fail "找不到 db 快照：$dbBackupPath"
}
Info "[1/2] 快照驗證通過："
Info "  程式碼快照：$rollbackDir"
Info "  db 快照：$dbBackupPath"

if (-not $Yes) {
    Write-Host ""
    $answer = Read-Host "確認要把正式機回滾到 $SnapshotTimestamp 這個快照嗎？(y/N)"
    if ($answer -ne "y" -and $answer -ne "Y") {
        Fail "使用者取消，未做任何回滾動作。"
    }
}

# ============================================================
# Step 2: 還原（照抄 apply_update.ps1 第392-426行的自動回滾邏輯）
# ============================================================
Info "`n[2/2] 開始回滾..."

# 先停服務再動檔案（含 db）——避免正在跑的伺服器跟覆寫的檔案打架。
$conn = Get-NetTCPConnection -LocalPort 666 -State Listen -ErrorAction SilentlyContinue
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

robocopy (Join-Path $rollbackDir "backend") $BackendDir /E | Out-Null
robocopy (Join-Path $rollbackDir "frontend") $FrontendDir /E | Out-Null

$rootDocDir = Join-Path $rollbackDir "root_docs"
if (Test-Path $rootDocDir) {
    Get-ChildItem -Path $rootDocDir -File | ForEach-Object {
        Copy-Item $_.FullName -Destination $ProdRoot -Force
    }
    Ok "  根目錄文件已還原。"
}

Copy-Item $dbBackupPath $dbPath -Force
# 還原乾淨的主檔案後，殘留的 -wal/-shm（來自回滾前那個版本寫入）內容已經跟它
# 對不上，必須一併清掉，否則下次連線時 SQLite 可能把過期的 WAL 內容重新套用
# 回來，等於沒回滾乾淨。
Remove-Item "$dbPath-wal", "$dbPath-shm" -Force -ErrorAction SilentlyContinue
Ok "  資料庫已還原：$dbBackupPath"

$healthy = $false
$hcStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 2
    $thisTry = Test-Ping -Url $PingUrl -TimeoutSec 5
    Info "    健檢第 $($i + 1)/20 次（經過 $([int]$hcStopwatch.Elapsed.TotalSeconds)s）：$(if ($thisTry) { '成功' } else { '無回應' })"
    if ($thisTry) { $healthy = $true; break }
}

Write-Host ""
if ($healthy) {
    Write-Host "======================================" -ForegroundColor Green
    Write-Host "  回滾完成，健康狀態正常：$SnapshotTimestamp" -ForegroundColor Green
    Write-Host "======================================" -ForegroundColor Green
} else {
    Write-Host "======================================" -ForegroundColor Red
    Write-Host "  回滾動作已執行，但健康檢查仍異常，需要人工介入！" -ForegroundColor Red
    Write-Host "======================================" -ForegroundColor Red
    # 跟 apply_update.ps1 一致：健康檢查失敗可能是服務真的中斷，也可能又是
    # 健康檢查機制本身的偽陰性，直接印出 port 666 監聽狀態協助判斷。
    Write-Host ""
    Write-Host "  port 666 目前監聽狀態（協助判斷是否為服務真的中斷）：" -ForegroundColor Yellow
    $conns = Get-NetTCPConnection -LocalPort 666 -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "    （完全沒有任何連線/監聽在 port 666 上——服務可能真的沒起來）" -ForegroundColor Yellow
    } else {
        foreach ($c in $conns) {
            $procName = try { (Get-Process -Id $c.OwningProcess -ErrorAction Stop).ProcessName } catch { "(process 已不存在)" }
            Write-Host "    State=$($c.State)  PID=$($c.OwningProcess)  Process=$procName" -ForegroundColor Yellow
        }
    }
    exit 1
}
