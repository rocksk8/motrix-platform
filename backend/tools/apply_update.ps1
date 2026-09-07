<#
  apply_update.ps1 — 在「正式機」執行

  用途：把 build_deploy_package.ps1 在開發機打包好、手動複製過來的部署包，
  套用到正式機。只換程式碼／schema，絕不覆蓋 db / uploads / PDF / logs / 設定檔。

  安全機制：
    - 身分守門：只能在正式機路徑下執行
    - 套用前：版本比對（避免重複/退版套用）+ 健康檢查記錄 + db 快照 + 程式碼快照（回滾用）
    - 套用中：安全停服（讓既有 autostart crash-restart 迴圈接手重啟，不自己搶 port）+ 只複製，不做 /MIR 鏡像刪除
      + pip install -r requirements.txt（新版新增的第三方套件一併裝好，避免 import 就炸）
    - 套用後：輪詢 /api/ping + 檢查 server.log 有無新錯誤；失敗就自動回滾並重啟

  用法：
    powershell -ExecutionPolicy Bypass -File apply_update.ps1 -PackagePath D:\deploy\20260801_120000_abcd123
    powershell -ExecutionPolicy Bypass -File apply_update.ps1 -PackagePath ... -Force   # 版本比對沒過也強制套用
    powershell -ExecutionPolicy Bypass -File apply_update.ps1 -PackagePath ... -Yes     # 跳過互動確認——僅供自動化測試，或由
                                                                                          # 2026-09-08 新增的 deploy_dashboard.py
                                                                                          # 這類已經在自己的網頁介面做過明確二次
                                                                                          # 確認的受監督工具呼叫（人工確認關卡換了
                                                                                          # 地方，不是被繞過——WinRM 遠端執行不支援
                                                                                          # 事後對正在跑的遠端 script block 注入 y/N，
                                                                                          # 所以由呼叫端自己的 UI 提供等價確認）
    powershell -ExecutionPolicy Bypass -File apply_update.ps1 -CheckOnly                # 只測健康檢查邏輯，不部署（見下方）

  -CheckOnly（2026-09-08 新增）：只對目前正在跑的伺服器打一次 /api/ping、印出結果就結束，
    不做備份／停服／複製程式碼／pip install／回滾等任何動作，也不需要 -PackagePath。用途是
    驗證「健康檢查機制本身」對不對（例如這次修 HTTPS 健康檢查的 curl.exe 邏輯）——2026-09-08
    當天為了驗證一個健康檢查修復，被迫實際跑了兩次完整的部署+回滾循環（各自停服＋可能觸發
    不必要的回滾），這個模式讓同樣的驗證 10 秒內完成、完全不影響正在運作的服務。
#>

[CmdletBinding()]
param(
    [string]$PackagePath,

    [switch]$Force,
    [switch]$Yes,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$ProdRoot = "C:\Users\Motrix\Desktop\V9.0"
$BackendDir = Join-Path $ProdRoot "backend"
$FrontendDir = Join-Path $ProdRoot "frontend"

# 2026-08-27：憑證存在（見 backend/tools/https_setup.ps1）代表 uvicorn 現在只服務
# HTTPS，健康檢查要跟著改用 https；自簽憑證沒有受信任的 CA，Invoke-WebRequest
# 預設會擋下憑證驗證失敗，這裡略過驗證（僅用於本機 loopback 健康檢查，不影響
# 其他任何對外連線的憑證驗證）。Windows PowerShell 5.1 沒有
# -SkipCertificateCheck 參數（那是 PS7+ 才有），改用 ServicePointManager 回呼繞過。
$UsesHttps = Test-Path (Join-Path $BackendDir "certs\cert.pem")
if ($UsesHttps) {
    $PingUrl = "https://127.0.0.1:666/api/ping"
} else {
    $PingUrl = "http://127.0.0.1:666/api/ping"
}

# 2026-09-08 修復：HTTPS 健康檢查曾經用 Invoke-WebRequest +
# [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
# 跳過自簽憑證驗證，但這是個已知地雷——.NET 在 TLS handshake 階段是從「背景執行緒」
# 呼叫這個委派，而 PowerShell 指令碼區塊（{ $true }）需要 Runspace 才能執行，
# 背景執行緒沒有 Runspace，實際呼叫時直接丟「沒有 Runspace 可在這個執行緒中用來
# 執行指令碼」的例外——被下面每個健康檢查迴圈的 catch {} 整個吞掉，完全不留痕跡，
# 造成「healthy=False 但 log 錯誤筆數=0」的誤判自動回滾（伺服器其實正常啟動成功，
# 見 §12 2026-09-08 條目）。改用 curl.exe（Windows 10/11 內建原生執行檔，-k 跳過憑證
# 驗證，不經過 .NET ServicePointManager，完全沒有這個問題）取代 HTTPS 情境下的
# Invoke-WebRequest；HTTP 情境維持原本 Invoke-WebRequest 不變（本來就沒壞過）。
function Test-Ping {
    param([string]$Url, [int]$TimeoutSec = 3)
    if ($UsesHttps) {
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $code = & curl.exe -k -s -o NUL -w "%{http_code}" --max-time $TimeoutSec $Url 2>$null
            return $code -eq "200"
        } catch {
            return $false
        } finally {
            $ErrorActionPreference = $prevEap
        }
    } else {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
            return $resp.StatusCode -eq 200
        } catch {
            return $false
        }
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

if ($CheckOnly) {
    Info "[CheckOnly] 只測試健康檢查邏輯本身，不做任何備份／停服／部署動作。"
    Info "  健康檢查網址：$PingUrl（$(if ($UsesHttps) { 'HTTPS，走 curl.exe -k' } else { 'HTTP，走 Invoke-WebRequest' })）"
    if (Test-Ping -Url $PingUrl -TimeoutSec 5) {
        Ok "  /api/ping 回應 200，健康檢查機制正常。"
        exit 0
    } else {
        Warn "  /api/ping 未回應 200 或逾時——可能是伺服器真的沒開，也可能是健康檢查機制本身還有問題（例如協定/憑證不對）。"
        exit 1
    }
}

if (-not $PackagePath) {
    Fail "-PackagePath 為必填參數（除非搭配 -CheckOnly 使用）。"
}
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
Info "[1/6] 套用前檢查..."

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
$preHealthy = Test-Ping -Url $PingUrl -TimeoutSec 3
Info "  套用前伺服器健康狀態：$(if ($preHealthy) { '正常' } else { '無回應（可能已停機，仍會繼續套用）' })"

# --- 備份（不管等一下順不順利，都先留退路）---
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

$dbBackupDir = Join-Path $BackendDir "db_backups\pre_update_$timestamp"
New-Item -ItemType Directory -Force -Path $dbBackupDir | Out-Null
$dbPath = Join-Path $BackendDir "motrix_erp.db"
$dbBackupPath = Join-Path $dbBackupDir "motrix_erp.db"
if (Test-Path $dbPath) {
    # 用 SQLite Online Backup API（跟 archive.py _snapshot_sqlite() 每日備份一致的做法），
    # 不用陽春 Copy-Item —— db 是 WAL 模式，伺服器這時可能還在跑，單純複製主檔案可能
    # 漏掉尚未 checkpoint 進主檔案、還留在 -wal 的交易，快照不保證一致。backup() 會產生
    # 真正完整、可安全還原的快照。
    $backupPy = Join-Path $env:TEMP "motrix_predeploy_backup_$timestamp.py"
    @"
import sqlite3
src = sqlite3.connect(r'$dbPath')
dst = sqlite3.connect(r'$dbBackupPath')
try:
    src.backup(dst)
finally:
    dst.close()
    src.close()
print('BACKUP_OK')
"@ | Set-Content -Path $backupPy -Encoding UTF8
    $backupOutput = & python $backupPy 2>&1
    $backupExit = $LASTEXITCODE
    Remove-Item $backupPy -Force -ErrorAction SilentlyContinue
    if ($backupExit -ne 0 -or ($backupOutput -notmatch "BACKUP_OK")) {
        Write-Host ($backupOutput | Out-String)
        Fail "升級前 db 備份失敗，中止套用（正式庫尚未被觸碰）。"
    }
    Ok "  db 快照（SQLite Online Backup API）：$dbBackupPath"
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
# 根目錄文件（CHANGELOG.md / MOTRIX-ERP-QUICK.md 等）也要存一份回滾快照——
# Step 3 會在健康檢查「之前」就先覆蓋這些文件，如果沒有這份快照，健康檢查
# 失敗回滾程式碼＋db 時，根目錄文件會維持新版內容，變成「文件說已經是新版，
# 實際跑的程式碼卻是舊版」的落差（2026-09-07 實際發生過，見 §0）。
$rootDocDir = Join-Path $rollbackDir "root_docs"
New-Item -ItemType Directory -Force -Path $rootDocDir | Out-Null
Get-ChildItem -Path $ProdRoot -File | ForEach-Object {
    Copy-Item $_.FullName -Destination $rootDocDir -Force
}
Ok "  回滾快照完成（含根目錄文件）。"

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
Info "`n[2/6] 停止伺服器..."
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

# 等待 port 666 真正釋放，降低跟 autostart crash-restart 迴圈搶綁定的競態
# （行程被殺掉到 OS 真的放開 socket 之間有短暫空窗，太快進到下一步常撞到
#   [Errno 10048] 位址已被使用，迴圈會自行重試到成功，但這段等待可以減少發生機率）
$portFreed = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    $stillListening = Get-NetTCPConnection -LocalPort 666 -State Listen -ErrorAction SilentlyContinue
    if (-not $stillListening) { $portFreed = $true; break }
}
if ($portFreed) {
    Ok "  Port 666 已確認釋放。"
} else {
    Warn "  Port 666 等待 15 秒後仍顯示被佔用，繼續往下走（crash-restart 迴圈本身會自動重試）。"
}
Ok "  伺服器已停止，等待 autostart crash-restart 迴圈接手（見 §1.1，最長約 5 秒偵測到中止後重啟）。"

# ============================================================
# Step 3: 複製新程式碼（只加不刪，絕不 /MIR）
# ============================================================
Info "`n[3/6] 套用新程式碼..."

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
# Step 4: 安裝/更新 Python 依賴
# ============================================================
# 新版程式碼可能在 requirements.txt 新增了套件（例如 2026-09-07 TOTP 功能
# 新增 pyotp）；上面只複製程式碼檔案，不會自動幫正式機的 Python 環境裝新套件，
# 新程式碼一 import 就 ModuleNotFoundError，害健康檢查失敗觸發自動回滾
# （2026-09-07 實際發生過一次，見 §12/§15.4）。這裡在健康檢查前先確保裝好。
Info "`n[4/6] 安裝/更新 Python 依賴..."
$reqPath = Join-Path $BackendDir "requirements.txt"
if (Test-Path $reqPath) {
    # pip 就算成功也常態性往 stderr 印提示訊息（例如「有新版 pip 可更新」）；
    # Windows PowerShell 5.1 對「原生執行檔 + 2>&1」有個地雷——只要 stderr 有
    # 任何輸出，在 $ErrorActionPreference = "Stop"（本檔開頭已設定）底下會被
    # 包成 NativeCommandError 直接中止整支腳本（2026-09-07 實際發生過，見 §12）。
    # 這裡在呼叫期間暫時改成 Continue，用完立刻還原，不影響腳本其餘部分的
    # 錯誤處理行為。
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $pipOutput = & python -m pip install -q -r $reqPath 2>&1
        $pipExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }
    if ($pipExit -ne 0) {
        Warn "  pip install 失敗（exit code $pipExit），繼續往下走——若真的缺套件，下一步健康檢查會抓到並觸發自動回滾："
        Write-Host ($pipOutput | Out-String)
    } else {
        Ok "  requirements.txt 依賴已確認安裝。"
    }
} else {
    Warn "  找不到 $reqPath，略過依賴安裝。"
}

# ============================================================
# Step 5: 套用後健康檢查
# ============================================================
Info "`n[5/6] 等待伺服器恢復並健康檢查..."
$healthy = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Ping -Url $PingUrl -TimeoutSec 3) { $healthy = $true; break }
}

$logErrors = @()
$logPath = Join-Path $BackendDir "logs\server.log"
if (Test-Path $logPath) {
    $tail = Get-Content $logPath -Tail 200
    # crash-restart 迴圈搶 port 666 重新綁定時，重試階段偶爾會留下 1～2 次
    # [Errno 10048]（位址已被使用）之類的暫時性錯誤，迴圈本身會自動重試到成功；
    # 這類「最終有成功啟動」的暫時性錯誤不該被算成這次更新失敗。只檢查
    # tail 範圍內「最後一次成功啟動」（Uvicorn running on）之後的內容——
    # 找不到成功啟動標記時，代表整段 tail 都還沒真正起來，維持全範圍檢查。
    $lastStartIdx = -1
    for ($i = $tail.Count - 1; $i -ge 0; $i--) {
        if ($tail[$i] -like "*Uvicorn running on*") { $lastStartIdx = $i; break }
    }
    $scanRange = $tail
    if ($lastStartIdx -ge 0 -and $lastStartIdx -lt ($tail.Count - 1)) {
        $scanRange = $tail[($lastStartIdx + 1)..($tail.Count - 1)]
    } elseif ($lastStartIdx -eq ($tail.Count - 1)) {
        $scanRange = @()
    }
    $logErrors = $scanRange | Select-String -Pattern "Traceback|ERROR" -SimpleMatch:$false
}

if ($healthy -and -not $logErrors) {
    Ok "  /api/ping 回應正常，log 未見新錯誤。"
} else {
    Warn "  套用後健康檢查失敗：healthy=$healthy, log 錯誤筆數=$($logErrors.Count)"
    Warn "  觸發自動回滾（程式碼 + 資料庫）..."

    # 先停服務再動檔案（含 db）——新版伺服器這時可能還在跑，直接覆寫 db 檔案
    # 有鎖定/衝突風險；也避免舊版程式碼複製回去的同時新版還在寫入。
    $conn2 = Get-NetTCPConnection -LocalPort 666 -State Listen -ErrorAction SilentlyContinue
    if ($conn2) { Stop-Process -Id $conn2.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2

    robocopy (Join-Path $rollbackDir "backend") $BackendDir /E | Out-Null
    robocopy (Join-Path $rollbackDir "frontend") $FrontendDir /E | Out-Null

    # 根目錄文件（MOTRIX-ERP-QUICK.md / CHANGELOG.md 等）也一併回滾，否則文件
    # 會停留在「已經是新版」的內容，跟被回滾回舊版的實際程式碼對不上（見上方
    # Step 3.5 快照時的說明／§0）。
    $rootDocDir = Join-Path $rollbackDir "root_docs"
    if (Test-Path $rootDocDir) {
        Get-ChildItem -Path $rootDocDir -File | ForEach-Object {
            Copy-Item $_.FullName -Destination $ProdRoot -Force
        }
        Ok "  根目錄文件已還原至升級前版本。"
    }

    # 新版可能已經對正式庫套用過 migration（伺服器一啟動就會自動跑 init_db()）。
    # 只回滾程式碼、不回滾資料庫的話，回滾後會是「舊程式碼 + 新 schema」的不一致
    # 狀態——多數 migration 只是加欄位/加表，舊程式碼還撐得住，但只要哪次改了
    # 不相容的變更就會出事。這裡把資料庫也還原回升級前的快照，才是真正回到
    # 升級前的狀態。
    if (Test-Path $dbBackupPath) {
        Copy-Item $dbBackupPath $dbPath -Force
        # 還原乾淨的主檔案後，殘留的 -wal/-shm（來自新版寫入）內容已經跟它對不上，
        # 必須一併清掉，否則下次連線時 SQLite 可能把過期的 WAL 內容重新套用回來，
        # 等於沒回滾乾淨。
        Remove-Item "$dbPath-wal", "$dbPath-shm" -Force -ErrorAction SilentlyContinue
        Ok "  資料庫已還原至升級前快照：$dbBackupPath"
    } else {
        Warn "  找不到升級前 db 快照（$dbBackupPath），資料庫維持目前狀態，可能仍是新版 schema，需要人工檢查！"
    }

    $rolledBackHealthy = $false
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 2
        if (Test-Ping -Url $PingUrl -TimeoutSec 3) { $rolledBackHealthy = $true; break }
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
# Step 6: 更新版本追蹤檔
# ============================================================
Info "`n[6/6] 更新版本追蹤檔..."
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
