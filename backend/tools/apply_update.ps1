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
    powershell -ExecutionPolicy Bypass -File apply_update.ps1 -PackagePath ... -SkipAutoRollback -Yes  # 見下方，謹慎使用

  -CheckOnly（2026-09-08 新增）：只對目前正在跑的伺服器打一次 /api/ping、印出結果就結束，
    不做備份／停服／複製程式碼／pip install／回滾等任何動作，也不需要 -PackagePath。用途是
    驗證「健康檢查機制本身」對不對（例如這次修 HTTPS 健康檢查的 curl.exe 邏輯）——2026-09-08
    當天為了驗證一個健康檢查修復，被迫實際跑了兩次完整的部署+回滾循環（各自停服＋可能觸發
    不必要的回滾），這個模式讓同樣的驗證 10 秒內完成、完全不影響正在運作的服務。

  -SkipAutoRollback（2026-09-08 再新增）：健康檢查機制本身這一晚已經證實會用至少三種
    不同方式誤判（Schannel/Runspace 崩潰、Python 健康檢查腳本本身的例外、Windows asyncio
    良性 ConnectionResetError 雜訊被當成錯誤），每修好一種就冒出下一種，導致明明程式碼跟
    pytest（467/467）都沒問題，卻連續套用失敗被自動回滾，兩邊檔案一直對不齊。這個旗標讓
    Step 5 健康檢查照常執行、照常印出結果，但**不**在判定失敗時自動觸發回滾——只印出醒目
    警告，把新程式碼留在原地，改成需要人工用瀏覽器或 -CheckOnly 確認真實健康狀態後自己決定
    是否要用 rollback_update.ps1 手動回滾。**不是關掉健康檢查，是把「自動判定→自動回滾」
    這個目前不可靠的自動化環節換成人工決定**；db／程式碼快照（Step 1）完全不受影響，
    仍然照常建立，人工要回滾一樣有得用。只建議在像這次這種「健康檢查本身已被證實反覆
    誤判、且已用其他管道獨立確認過服務其實正常」的情況下才使用，不是日常部署的預設選項。
#>

[CmdletBinding()]
param(
    [string]$PackagePath,

    [switch]$Force,
    [switch]$Yes,
    [switch]$CheckOnly,
    [switch]$SkipAutoRollback
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

# 2026-09-08 修復（第一輪）：HTTPS 健康檢查曾經用 Invoke-WebRequest +
# [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
# 跳過自簽憑證驗證，但這是個已知地雷——.NET 在 TLS handshake 階段是從「背景執行緒」
# 呼叫這個委派，而 PowerShell 指令碼區塊（{ $true }）需要 Runspace 才能執行，
# 背景執行緒沒有 Runspace，實際呼叫時直接丟「沒有 Runspace 可在這個執行緒中用來
# 執行指令碼」的例外——被下面每個健康檢查迴圈的 catch {} 整個吞掉，完全不留痕跡，
# 造成「healthy=False 但 log 錯誤筆數=0」的誤判自動回滾。當時改用 curl.exe
# （Windows 10/11 內建原生執行檔，-k 跳過憑證驗證，不經過 .NET ServicePointManager）
# 取代 Invoke-WebRequest。
#
# 2026-09-08 修復（第二輪，同一晚更晚）：curl.exe 這個做法後來也不可靠——
# 同一晚連續三次部署，套用後健康檢查都判定失敗（healthy=False），但事後用
# 完全相同的 curl.exe 呼叫（含直接呼叫／巢狀一層呼叫、拉寬 timeout）獨立
# 重測每次都正常回應 200，代表問題只在部署當下的即時狀態才會出現。同一段
# 時間，開發機這邊用 Python requests 打同一支端點的背景輪詢每次都正確回報
# 真實狀態，形成明顯對照。curl.exe 在 Windows 上預設走 Schannel（實測 -v
# 輸出可見自簽憑證連線會發生兩次 TLS renegotiation），改用
# backend/tools/_healthcheck_ping.py（Python 內建 ssl 模組，走 OpenSSL，
# 不經過 Schannel）統一 HTTP/HTTPS 兩種情境，繞開整條 Schannel 路徑。
# 這是根據當晚實際證據做的合理猜測，不是已證實的根因——如果之後這支健康
# 檢查仍然誤判，下一個該懷疑的方向是「部署當下 port 666 重新綁定那個瞬間」
# 本身的競態，而不是健康檢查呼叫的實作細節。
function Test-Ping {
    param([string]$Url, [int]$TimeoutSec = 3)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        # 2026-09-08（再修）：先前用 2>$null 把 _healthcheck_ping.py 失敗時印出的
        # 實際例外訊息整個丟掉，導致每次健康檢查誤判都只看得到「healthy=False」
        # 沒有原因——這正是這一晚不斷重複盲目猜測根因的主因之一。改成 2>&1
        # 合併輸出，失敗時透過 Warn 印出腳本自己回報的失敗原因。
        $out = & python (Join-Path $PSScriptRoot "_healthcheck_ping.py") $Url $TimeoutSec 2>&1
        if ($LASTEXITCODE -ne 0 -and $out) { Warn "    健康檢查失敗詳情：$($out -join ' | ')" }
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

# ══════════════════════════════════════════════════════════════════
# `::RESULT::` 協定 v2（P0-00）—— 每一條出口都要印一行
# ══════════════════════════════════════════════════════════════════
#
# 🔴 為什麼要這個：先前 deploy_dashboard.py 用「結束碼 ＋ 掃關鍵字」判定，
# 而本檔 `-SkipAutoRollback` 那條分支在健康檢查**失敗**時 `exit 0`，
# 印的又是「略過**自動回滾**」（守門找的是「**已**自動回滾」，差一個字）
# ⇒ 儀表板把它記成**成功**，而正式機上跑的是一個沒過健康檢查的版本。
#
# 🔑 關鍵字比對是**散文比對**：它要求每一條新出口的作者，記得把字寫成
#    守門認得的形狀。這裡改成**結構化輸出**，而且是機器產生的。
#
# ⚠️ `$script:ProdState` 回答的是「**正式機的磁碟上現在是什麼**」，
#    不是「這次成功了沒」。停服**不算**改變它 —— 磁碟上還是舊程式碼，
#    autostart 迴圈會把它拉回來，那個狀態自己會好。
$script:ProdState = "not_applied"

# 🔴 **`service` 是獨立的一維，不可以塞進 `rolled_back`**（§34c）。
# `rolled_back` 問的是**磁碟上是什麼**，`service` 問的是**它現在跑不跑**。
# ☠️ 混在一起會長出 `applied_no_restore_and_down` 這種組合爆炸。
#
# 三個值各自對應一個**觀察到的事實**，不是推論：
#   up      我們在最後一個動作之後 ping 成功過
#   down    我們**停掉了它**，而之後沒有任何一次 ping 成功
#   unknown 我們沒有停過它，也沒有成功 ping 過（＝沒量過）
# 📌 `:358` 那條出口（robocopy 中途失敗）就是 `down` ——
#    **而那一件決定使用者要不要現在衝去開機。**
$script:ServiceState = "unknown"

function Emit-Result($status, $code) {
    # 一行、無前後空白、大小寫固定、欄位順序固定（B.md §九 定版）。
    Write-Host ("::RESULT:: v=2 status=$status rolled_back=$($script:ProdState)" +
                " service=$($script:ServiceState) exit=$code")
}

# ⚠️ `$status` 預設 `unknown` 是刻意的：日後有人新增一條 `Fail` 而忘了給狀態，
#    它會印 `status=unknown` ⇒ 而 dashboard 的值域檢查會把 `unknown` 判成失敗。
# 🔑 **忘記的代價是「被記成失敗」，不是「被記成成功」** —— 方向要是這一邊。
function Fail($msg, $status = "unknown") {
    Write-Host "`n[FAIL] $msg" -ForegroundColor Red
    Emit-Result $status 1
    exit 1
}
function Info($msg)  { Write-Host $msg }
function Warn($msg)  { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Ok($msg)    { Write-Host "[OK] $msg" -ForegroundColor Green }

# 🔑 **握手行**：它說的是「**正在跑的這一份腳本**看得懂 v2 協定」。
# ⚠️ 對 `apply_update.ps1` 而言它是**多餘的保險**——`_dashboard_remote.ps1:98-104`
#    會在呼叫之前先把套件裡的 `backend\tools\*` 覆蓋過去，所以跑的一定是新版。
# ☠️ 但那段複製包在 `if (Test-Path $srcTools) { ... }` 裡而**沒有 else** ⇒
#    包裡缺 `backend\tools\` 時它**安靜跳過**，正式機就用舊的跑
#    —— 這一行讓那個安靜跳過**變成看得見的**。
# 🔴 而對 `rollback_update.ps1` 它不是保險，是**必要條件**：
#    rollback 分支**沒有**那段預先複製（§34a），所以舊腳本真的會被跑到。
Write-Host "::PROTOCOL:: v=2"
Write-Host "======================================"
Write-Host "  MOTRIX ERP - Apply Update"
Write-Host "======================================"

# ============================================================
# Step 0: 身分守門 —— 只能在正式機執行
# ============================================================
$scriptRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
if ($scriptRoot -ne $ProdRoot) {
    Fail "偵測到執行路徑為 '$scriptRoot'，不是正式機路徑 '$ProdRoot'。本腳本只允許在正式機執行，中止。" "not_prod_machine"
}
Info "身分確認：正式機（$ProdRoot）`n"

if ($CheckOnly) {
    Info "[CheckOnly] 只測試健康檢查邏輯本身，不做任何備份／停服／部署動作。"
    Info "  健康檢查網址：$PingUrl（走 _healthcheck_ping.py，$(if ($UsesHttps) { 'HTTPS' } else { 'HTTP' })）"
    if (Test-Ping -Url $PingUrl -TimeoutSec 5) {
        Ok "  /api/ping 回應 200，健康檢查機制正常。"
        $script:ServiceState = "up"        # ping 成功＝觀察到的事實
        Emit-Result "checkonly_ok" 0
        exit 0
    } else {
        Warn "  /api/ping 未回應 200 或逾時——可能是伺服器真的沒開，也可能是健康檢查機制本身還有問題（例如協定/憑證不對）。"
        Emit-Result "checkonly_failed" 1
        exit 1
    }
}

if (-not $PackagePath) {
    Fail "-PackagePath 為必填參數（除非搭配 -CheckOnly 使用）。" "bad_args"
}
if (-not (Test-Path $PackagePath)) {
    Fail "找不到部署包路徑：$PackagePath" "package_missing"
}
$manifestPath = Join-Path $PackagePath "deploy_manifest.json"
if (-not (Test-Path $manifestPath)) {
    Fail "部署包內找不到 deploy_manifest.json（$PackagePath），不是合法的部署包。" "package_invalid"
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
        Fail "這個部署包（commit $($manifest.commit_short)）跟正式機目前已套用的版本相同，看起來是重複套用。如果確定要強制重套，請加 -Force。" "duplicate_version"
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
    # 2026-09-08 修復：跟 pip install 那個地雷同一類——Windows PowerShell 5.1
    # 對「原生執行檔 + 2>&1」的問題，只要 python.exe 往 stderr 印任何東西
    # （含它自己一個真正的 Traceback），在 $ErrorActionPreference = "Stop"
    # 底下會被包成 NativeCommandError 直接中止整支腳本，且只印得出 Traceback
    # 第一行，看不到完整錯誤內容。呼叫期間暫時改成 Continue，用完立刻還原。
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $backupOutput = & python $backupPy 2>&1
        $backupExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }
    Remove-Item $backupPy -Force -ErrorAction SilentlyContinue
    if ($backupExit -ne 0 -or ($backupOutput -notmatch "BACKUP_OK")) {
        Write-Host ($backupOutput | Out-String)
        Fail "升級前 db 備份失敗，中止套用（正式庫尚未被觸碰）。" "backup_failed"
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

    # 2026-09-08 修復（見上方 db 備份那段同款註解）：這裡尤其重要——這支
    # dry-run 腳本本來就是「預期它可能會真的丟例外」的檢查，沒有這層防護，
    # 一旦新版 migration 真的有問題，PowerShell 只會印出 Traceback 第一行
    # 就整個崩潰，看不到下面設計好的「Migration 乾跑驗證失敗」說明訊息，
    # 也看不到完整的錯誤內容，等於白設計了這個安全機制。
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $dryRunOutput = & python $dryRunPy 2>&1
        $dryRunExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }
    Remove-Item $dryRunDb, $dryRunPy -Force -ErrorAction SilentlyContinue

    if ($dryRunExit -ne 0 -or ($dryRunOutput -notmatch "DRYRUN_OK")) {
        Write-Host ""
        Write-Host "======================================" -ForegroundColor Red
        Write-Host "  Migration 乾跑驗證失敗，中止套用（正式庫完全未被觸碰）" -ForegroundColor Red
        Write-Host "======================================" -ForegroundColor Red
        Write-Host ($dryRunOutput | Out-String)
        Fail "新版本的 migration 在 db 快照副本上乾跑失敗，套用到正式庫時很可能也會出錯。請檢查上面的錯誤訊息、修好新版 db.py 的 migration 後重新打包，再重新套用。" "migration_dryrun_failed"
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
        Fail "使用者取消，未做任何套用動作（備份已保留，可直接刪除或留著沒差）。" "user_cancelled"
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

# 🔴 **我們自己停掉了它** ⇒ 從這裡開始 `service=down`，
# 直到某一次 ping 成功才會變回 `up`。
# ☠️ 少了這一行，`:358`（robocopy 中途失敗）會報 `service=unknown`，
#    而實際上**是我們把它停掉的** —— 那個差別決定使用者要不要現在去開機。
$script:ServiceState = "down"

# ============================================================
# Step 3: 複製新程式碼（只加不刪，絕不 /MIR）
# ============================================================
Info "`n[3/6] 套用新程式碼..."

# 🔴 **危險值要在動作之前設，不是之後。**
# ☠️ 之後才設的話，複製到一半失敗會報出一個**比實際安全**的狀態：
#    畫面說「沒開始」，而正式機已經停服＋半複製。
# 🔑 而它有個附帶好處：日後有人在這一行之後新增一條 `Fail`，
#    **它會自動報對**，不必記得改。
# 📌 起點選在這裡而不是 Step 2 停服：停服不改變磁碟上的東西，
#    autostart 迴圈會把舊程式碼拉回來 ⇒ 那個狀態自己會好。
#    **真正不可逆的是下一行開始寫入 $BackendDir。**
$script:ProdState = "applied_no_restore"

$rc1 = robocopy (Join-Path $PackagePath "backend") $BackendDir /E `
    /XD db_backups rollback_snapshots uploads logs 報價單PDF `
    /XF motrix_erp.db motrix_erp.db-wal motrix_erp.db-shm motrix_erp_demo.db motrix_erp_demo.db-wal motrix_erp_demo.db-shm heartbeat_config.json .deployed_commit.json server.log
if ($LASTEXITCODE -ge 8) { Fail "robocopy backend/ 失敗（exit code $LASTEXITCODE）。" "copy_failed_backend" }

$rc2 = robocopy (Join-Path $PackagePath "frontend") $FrontendDir /E
if ($LASTEXITCODE -ge 8) { Fail "robocopy frontend/ 失敗（exit code $LASTEXITCODE）。" "copy_failed_frontend" }

# 兩個 robocopy 都過了 ⇒ 新程式碼**完整**在正式機磁碟上。
# ⚠️ 這**不代表它是好的** —— 健康檢查還沒跑。`applied` 講的是磁碟狀態，
#    不是健康狀態；那兩件事由 `status` 那一欄分開講。
$script:ProdState = "applied"

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
# 2026-09-08 加寬：實測發現正式機 HTTPS（自簽憑證）連線 curl.exe 會發生兩次
# schannel TLS renegotiation，單次 3 秒逾時偶爾不夠、造成健康檢查偽陰性
# （見 MOTRIX-ERP-QUICK.md §12 同日條目——連續兩輪部署都在這裡誤判觸發
# 不必要的回滾，事後用同一行 curl.exe 手動重測完全正常）。單次逾時
# 3→5 秒、迴圈次數 15→20（總等待上限拉寬，多數情況仍會在前幾次就成功
# 提前跳出，不影響正常部署的速度）。
Info "`n[5/6] 等待伺服器恢復並健康檢查..."
$healthy = $false
$hcStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 2
    $thisTry = Test-Ping -Url $PingUrl -TimeoutSec 5
    Info "    健檢第 $($i + 1)/20 次（經過 $([int]$hcStopwatch.Elapsed.TotalSeconds)s）：$(if ($thisTry) { '成功' } else { '無回應' })"
    if ($thisTry) { $healthy = $true; break }
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
    # 2026-09-08（再修）：Windows 上 asyncio ProactorEventLoop 在 TCP 連線被
    # 對方突然重置時，固定會在 _ProactorBasePipeTransport._call_connection_lost
    # 這個 callback 印出一段 ConnectionResetError traceback——這是 Python 在
    # Windows 上眾所皆知、對服務健康完全無影響的雜訊（asyncio 自己的例外處理
    # 機制會接住，不會讓 process 真的掛掉；套用當下 Test-Ping／使用者實際
    # 操作都會製造大量短命連線，觸發機率不低）。舊版 "Traceback|ERROR" 不分
    # 大小寫比對，連「ConnectionResetError」這個字本身都算命中，一次這種
    # 雜訊事件就貢獻 3 行「錯誤」，服務明明正常運作卻被誤判成失敗（實測：
    # 09/08 09:14 那次套用，服務前後都正常回應，log 錯誤筆數卻算出 6，
    # 就是兩次這種雜訊各貢獻 3 行）。掃描前先把這個已知良性雜訊區塊整段
    # 濾掉，其餘真正的 Traceback/ERROR 不受影響、不會被連帶放過。
    # 逐行掃描、整段跳過已知良性雜訊區塊（從「Exception in callback ...
    # _call_connection_lost」那一行開始，跳到那一段自己的 ConnectionResetError/
    # OSError 結尾行為止）——用逐行狀態機而不是一次性多行 regex，避免
    # 觸發行本身開頭那段時間戳＋ERROR 字樣（跟真正的例外訊息同一行）沒被
    # 一併濾掉、殘留成一個孤兒 "ERROR " 片段又被下面重新命中。
    $cleanedLines = New-Object System.Collections.Generic.List[string]
    $inBenignBlock = $false
    foreach ($ln in $scanRange) {
        if (-not $inBenignBlock -and $ln -match "Exception in callback _ProactorBasePipeTransport\._call_connection_lost") {
            $inBenignBlock = $true
            continue
        }
        if ($inBenignBlock) {
            if ($ln -match "^(ConnectionResetError|OSError):") { $inBenignBlock = $false }
            continue
        }
        $cleanedLines.Add($ln)
    }
    $logErrors = $cleanedLines | Select-String -Pattern "Traceback|ERROR" -SimpleMatch:$false
    if ($logErrors) {
        Info "  比對範圍內找到的錯誤行（共 $($logErrors.Count) 筆）："
        foreach ($e in $logErrors) { Info "    $($e.Line)" }
    }
}

if ($healthy -and -not $logErrors) {
    Ok "  /api/ping 回應正常，log 未見新錯誤。"

    # --- 開關生效檢查（2026-09-22 §8 FX1b）---
    #
    # 為什麼需要這一段：autostart.bat 的 set MOTRIX_* 在 :loop 標籤【之前】
    # ⇒ 部署之後如果沒有重跑【排程工作】，接手的是已經在跑的那個
    # crash-restart 迴圈，而它拿的是【舊的】環境變數。
    # 88 份部署紀錄裡「重跑排程工作」出現次數是 0 —— 一個只寫在文件裡、
    # 而沒有任何東西在驗它發生過的步驟，等於不存在。
    #
    # 它的失敗長什麼樣（DEPLOY.md 自己寫的）：
    #   「推送成功、服務正常、畫面正常，就是雷達不掃、地圖上沒有點。」
    # 那三句話沒有一句會讓人想到環境變數。
    #
    # 判準：autostart.bat 裡【寫著要開】的，就必須在這次啟動的 log 裡看得到
    # 對應那一行。後端啟動時會印（main.py），而那一行讀的是 os.environ ——
    # 它回答的是「這個行程實際拿到什麼」，不是「檔案裡寫了什麼」。
    #
    # 只檢查「該開而沒開」這一個方向：沒有要求開的就不會有那一行，
    # 而那是正常狀態。漏報的代價是「有人偷偷開了而我們沒喊」，
    # 漏喊的代價是「以為開了而其實沒開」——後者才是這一條在防的。
    $switchNames = @("MOTRIX_TENDER_RADAR", "MOTRIX_GEO")
    $autostartPath = Join-Path $BackendDir "autostart.bat"
    $switchMismatch = @()
    if ((Test-Path $autostartPath) -and $scanRange) {
        $autostartText = Get-Content $autostartPath -Raw -ErrorAction SilentlyContinue
        foreach ($sw in $switchNames) {
            $wantOn = $false
            foreach ($ln in ($autostartText -split "\r?\n")) {
                $t = $ln.Trim()
                if ($t.StartsWith("::")) { continue }   # 被註解掉的不算
                if ($t -match ("^set\s+" + [regex]::Escape($sw) + "\s*=\s*1$")) { $wantOn = $true }
            }
            $sawLine = @($scanRange | Where-Object { $_ -match ([regex]::Escape($sw) + "=1") }).Count -gt 0
            if ($wantOn -and -not $sawLine) {
                $switchMismatch += $sw
            } elseif ($wantOn) {
                Ok "  開關 $sw：autostart.bat 要求開啟，這次啟動的 log 裡看得到它 —— 生效。"
            }
        }
    } else {
        Info "  開關生效檢查略過（找不到 autostart.bat，或這次沒有取到啟動後的 log）。"
    }
    if ($switchMismatch.Count -gt 0) {
        Write-Host ""
        Write-Host "======================================" -ForegroundColor Yellow
        Write-Host "  開關沒有生效：$($switchMismatch -join '、')" -ForegroundColor Yellow
        Write-Host "  autostart.bat 裡寫著要開，而這次啟動的 log 裡【沒有】對應那一行。" -ForegroundColor Yellow
        Write-Host "  最可能的原因：這次沒有重跑【排程工作】，接手的是舊的那個" -ForegroundColor Yellow
        Write-Host "  crash-restart 迴圈，而它拿的是舊的環境變數。" -ForegroundColor Yellow
        Write-Host "  處置：到工作排程器把 MOTRIX ERP 那個工作【結束後重新執行】。" -ForegroundColor Yellow
        Write-Host "  不處理的後果：服務正常、畫面正常，而雷達不掃、地圖上沒有點。" -ForegroundColor Yellow
        Write-Host "======================================" -ForegroundColor Yellow
    }
} elseif ($SkipAutoRollback) {
    Write-Host ""
    Write-Host "======================================" -ForegroundColor Yellow
    Write-Host "  健康檢查判定異常：healthy=$healthy, log 錯誤筆數=$($logErrors.Count)" -ForegroundColor Yellow
    Write-Host "  已依 -SkipAutoRollback 略過自動回滾——新程式碼維持在原地，不會被還原。" -ForegroundColor Yellow
    Write-Host "  這不代表服務真的正常，只是健康檢查機制本身這一晚已多次證實不可靠，" -ForegroundColor Yellow
    Write-Host "  改為需要人工確認。請立刻用瀏覽器或 -CheckOnly 確認真實健康狀態；" -ForegroundColor Yellow
    Write-Host "  如果確認真的壞了，回滾快照留存於：$rollbackDir" -ForegroundColor Yellow
    Write-Host "  db 套用前快照留存於：$dbBackupDir（用 rollback_update.ps1 手動回滾）" -ForegroundColor Yellow
    Write-Host "======================================" -ForegroundColor Yellow
    if ($logErrors) {
        Write-Host "  （log 錯誤內容已列印在上方，供人工判斷是否為已知良性雜訊之外的真實問題）" -ForegroundColor Yellow
    }
    # 🔴🔴 **P0-00 本尊**：結束碼是 0，而這是一次**失敗**。
    # 健康檢查沒過、`-SkipAutoRollback` 讓它不回滾 ⇒ 新程式碼留在正式機上。
    # ☠️ 先前儀表板用結束碼判 ⇒ 把它記成成功 ⇒ **而沒有人會來看。**
    Emit-Result "unhealthy_not_rolled_back" 0
    exit 0
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
    $rbStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 2
        $thisTry = Test-Ping -Url $PingUrl -TimeoutSec 5
        Info "    回滾後複驗第 $($i + 1)/20 次（經過 $([int]$rbStopwatch.Elapsed.TotalSeconds)s）：$(if ($thisTry) { '成功' } else { '無回應' })"
        if ($thisTry) { $rolledBackHealthy = $true; break }
    }

    Write-Host ""
    Write-Host "======================================" -ForegroundColor Red
    Write-Host "  更新失敗，已自動回滾到套用前版本" -ForegroundColor Red
    Write-Host "  回滾後健康狀態：$(if ($rolledBackHealthy) { '正常' } else { '仍異常，需要人工介入！' })" -ForegroundColor Red
    Write-Host "  程式碼回滾快照留存於：$rollbackDir" -ForegroundColor Red
    Write-Host "  db 套用前快照留存於：$dbBackupDir" -ForegroundColor Red
    Write-Host "======================================" -ForegroundColor Red

    if (-not $rolledBackHealthy) {
        # 2026-09-08：回滾後複驗失敗有兩種可能——正式機真的掛了，或者又是
        # 健康檢查機制本身的偽陰性（同一晚已發生過）。直接把 port 666 目前
        # 監聽狀態印出來，不用再另外跑一次診斷工具才知道是哪一種：如果這裡
        # 顯示有 process 正常監聽，代表服務其實還活著，優先懷疑是健康檢查
        # 本身的問題，不要急著當成真的服務中斷處理。
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
    }
    # ⚠️ 回滾**完成**不等於正式機**是好的**：`$rolledBackHealthy` 為 false 時
    #    腳本自己印的是「仍異常，需要人工介入！」。
    # ☠️ 兩者合成一個「已還原」⇒ **使用者最需要知道的那一格又被蓋掉了**，
    #    只是降了一層 —— 而那正是這整件事要修的東西。
    $script:ProdState = if ($rolledBackHealthy) { "restored" } else { "restored_unhealthy" }
    # ⚠️ `$rolledBackHealthy` 為 false 時**維持 `down`**，不改成 `unknown`：
    # 我們確實停掉了它，而之後 20 次 ping 沒有一次成功 ⇒ 照上面的定義就是 `down`。
    # 📌 「它可能其實活著、只是健康檢查偽陰性」那個可能性**由上方印出的
    #    port 666 監聽狀態負責**，不由這個欄位負責 —— 一個欄位只講一件事。
    if ($rolledBackHealthy) { $script:ServiceState = "up" }
    Emit-Result "unhealthy_rolled_back" 1
    exit 1
}

# 走到這裡代表健康檢查通過過（ping 成功）⇒ 觀察到的事實。
$script:ServiceState = "up"

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

# ⚠️ 成功那一條**也要印**。少了它，成功與「忘記印」在 dashboard 眼裡
# 完全相同（都是撈不到結果行）⇒ 而 fail-closed 會把每一次成功記成失敗。
# 🔑 「每一條出口都印」裡的「每一條」包含成功那一條。
Emit-Result "success" 0
