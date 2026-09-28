<#
  apply_update.ps1 — 在「正式機」執行

  用途：把 build_deploy_package.ps1 在開發機打包好、手動複製過來的部署包，
  套用到正式機。只換程式碼／schema，絕不覆蓋 db / uploads / PDF / logs / 設定檔。

  安全機制：
    - 身分守門：只能在正式機路徑下執行
    - 套用前：版本比對（避免重複/退版套用）+ 健康檢查記錄 + db 快照 + 程式碼快照（回滾用）
    - 套用中：停服（只停這個安裝的 autostart 迴圈與它的 uvicorn）+ 複製，不做 /MIR 鏡像刪除
      + 依刪除計畫刪掉舊版有、新版沒有的程式檔（backend/tools/apply_plan.py；有上限、先印清單）
      + pip install -r requirements.txt（新版新增的第三方套件一併裝好，避免 import 就炸）
      + 透過排程工作重新啟動迴圈（新的環境變數與新程式碼一起生效）
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
    [switch]$SkipAutoRollback,

    # 刪除計畫的上限（2026-09-28）：要刪的程式檔超過這個數字 ⇒ 不動任何檔、中止。
    # 先讀印出的清單（也寫在 backend\logs\apply_update_<時間>.plan.txt），確認後再用更大的值重跑。
    [int]$MaxDeleteFiles = 200
)

$ErrorActionPreference = "Stop"

# AH-M2（2026-09-28 A 稽核）：這支腳本的版本。開頭與部署包裡那一份比對，不同就拒絕——
#   手動執行時跑到安裝目錄裡的**舊**腳本（沒有先把包裡的 backend\tools 複製過來）會讓整套日常更新規則都不生效。
#   改這支腳本的行為時要改這個值。用常數不用雜湊：演練副本會改路徑與 port，雜湊必然不同。
$ApplyScriptVersion = "2026-09-28j"
# robocopy 一律 /R:3 /W:5（2026-09-28）：預設 /R:1000000 /W:30 ⇒ 被占用的檔會讓套用卡住數天而不是失敗，
#   複製失敗的出口（AH-S7 自動寫回快照）永遠走不到。

$ProdRoot = "C:\Users\Motrix\Desktop\V9.0"
$Port = 666
$AutostartTaskName = "MOTRIX ERP Server Autostart"
$BackendDir = Join-Path $ProdRoot "backend"
$FrontendDir = Join-Path $ProdRoot "frontend"
# 根目錄的程式目錄（2026-09-28）：tools\platform（升級精靈）、product（產品設定檔）。
# 先前只複製根目錄單檔 ⇒ 這兩個目錄永遠停在轉換當時的版本。
$RootProgramDirs = @("tools", "product")

# 2026-08-27：憑證存在（見 backend/tools/https_setup.ps1）代表 uvicorn 現在只服務
# HTTPS，健康檢查要跟著改用 https；自簽憑證沒有受信任的 CA，Invoke-WebRequest
# 預設會擋下憑證驗證失敗，這裡略過驗證（僅用於本機 loopback 健康檢查，不影響
# 其他任何對外連線的憑證驗證）。Windows PowerShell 5.1 沒有
# -SkipCertificateCheck 參數（那是 PS7+ 才有），改用 ServicePointManager 回呼繞過。
$UsesHttps = Test-Path (Join-Path $BackendDir "certs\cert.pem")
if ($UsesHttps) {
    $PingUrl = "https://127.0.0.1:$Port/api/ping"
} else {
    $PingUrl = "http://127.0.0.1:$Port/api/ping"
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

# 結果檔與鎖（UPDATE-DELIVERY §9.2）
$script:LockHeld = $false
$script:RunStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$script:StartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$script:ResultScript = "apply_update"
$script:ResultScriptVersion = $ApplyScriptVersion
$script:ResultPackage = $PackagePath
$script:ResultCommit = $null

function Emit-Result($status, $code) {
    # 一行、無前後空白、大小寫固定、欄位順序固定（B.md §九 定版）。
    Write-Host ("::RESULT:: v=2 status=$status rolled_back=$($script:ProdState)" +
                " service=$($script:ServiceState) exit=$code")
    Write-ResultFile $status $code
    Exit-InstallLock
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

# ── 以下三個函式在 apply_update.ps1 與 rollback_update.ps1 **逐字相同**（UPDATE-DELIVERY §9.2，2026-09-28）──
# 鎖：<ROOT>\backend\.apply.lock，CreateNew 排他建立；內容 {pid, script, started_at, package, host}。
#   已存在 ⇒ 持有者行程還在（powershell）回 "locked"，否則回 "stale"——殘留鎖**不自動清**，由人確認後刪。
#   釋放在 Emit-Result（每一條出口都經過它）；沒拿到鎖的那一次不會刪別人的鎖。
# 結果檔：<ROOT>\backend\logs\<script>_<yyyyMMdd_HHmmss>.result.json，先 .tmp 再改名；前五欄與 ::RESULT:: 同源。
function Enter-InstallLock([string]$scriptName, [string]$pkg) {
    $lockPath = Join-Path $BackendDir ".apply.lock"
    try {
        $fs = [System.IO.File]::Open($lockPath, 'CreateNew', 'Write', 'None')
    } catch {
        $holder = $null
        try { $holder = Get-Content $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $holder = $null }
        $alive = $false
        if ($holder -and $holder.pid) {
            $hp = Get-Process -Id ([int]$holder.pid) -ErrorAction SilentlyContinue
            $alive = [bool]($hp -and $hp.ProcessName -match '^(powershell|pwsh)$')
        }
        $who = if ($holder) { "PID $($holder.pid)（$($holder.script)，$($holder.started_at)，$($holder.package)）" } else { "內容讀不到" }
        Warn "  鎖檔 $lockPath 已存在：$who"
        if ($alive) { return "locked" }
        return "stale"
    }
    try {
        $info = [ordered]@{ pid = $PID; script = $scriptName; started_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss"); package = $pkg; host = $env:COMPUTERNAME }
        $bytes = [System.Text.Encoding]::UTF8.GetBytes(($info | ConvertTo-Json -Compress))
        $fs.Write($bytes, 0, $bytes.Length)
    } finally {
        $fs.Close()
    }
    $script:LockHeld = $true
    return $null
}

function Exit-InstallLock {
    if ($script:LockHeld) {
        Remove-Item (Join-Path $BackendDir ".apply.lock") -Force -ErrorAction SilentlyContinue
        $script:LockHeld = $false
    }
}

function Write-ResultFile($resStatus, $resCode) {
    try {
        if (-not (Test-Path $BackendDir)) { return }
        $logsDir = Join-Path $BackendDir "logs"
        if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Force -Path $logsDir | Out-Null }
        $resPath = Join-Path $logsDir ("{0}_{1}.result.json" -f $script:ResultScript, $script:RunStamp)
        $res = [ordered]@{
            protocol = 2; status = $resStatus; rolled_back = $script:ProdState; service = $script:ServiceState; exit = $resCode
            script = $script:ResultScript; script_version = $script:ResultScriptVersion; timestamp = $script:RunStamp
            package = $script:ResultPackage; commit = $script:ResultCommit
            started_at = $script:StartedAt; finished_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        }
        $tmpPath = "$resPath.tmp"
        [System.IO.File]::WriteAllText($tmpPath, ($res | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))
        Move-Item -Path $tmpPath -Destination $resPath -Force
    } catch {
        Write-Host "[WARN] 結果檔寫入失敗：$($_.Exception.Message)"
    }
}
function Backup-DatabasesOnline([string]$destDir) {
    # D 稽核 DM1：覆寫資料庫之前，把主庫與 demo 庫以 SQLite Online Backup 另存到 $destDir；任一個存在的庫失敗 ⇒ $false
    try {
        New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        $py = Join-Path $env:TEMP ("motrix_pre_rollback_{0}.py" -f $script:RunStamp)
        $code = "import os, sqlite3, sys`nfor s, d in zip(sys.argv[1::2], sys.argv[2::2]):`n    if not os.path.exists(s):`n        continue`n    a = sqlite3.connect(s)`n    b = sqlite3.connect(d)`n    try:`n        a.backup(b)`n    finally:`n        b.close()`n        a.close()`nprint('DB_BACKUP_OK')`n"
        [System.IO.File]::WriteAllText($py, $code, (New-Object System.Text.UTF8Encoding($false)))
        $pyArgs = @($py)
        foreach ($n in @("motrix_erp.db", "motrix_erp_demo.db")) { $pyArgs += (Join-Path $BackendDir $n); $pyArgs += (Join-Path $destDir $n) }
        $r = Invoke-Py $pyArgs
        Remove-Item $py -Force -ErrorAction SilentlyContinue
        if ($r.Exit -ne 0 -or $r.Text -notmatch "DB_BACKUP_OK") { Warn "  回滾前資料庫另存失敗：$($r.Text)"; return $false }
        Ok "  回滾前的資料庫已另存：$destDir"
        return $true
    } catch {
        Warn "  回滾前資料庫另存失敗：$($_.Exception.Message)"
        return $false
    }
}
# ── 逐字相同的區段到此為止 ──

# 本次啟動那一段 server.log（2026-09-28 A：開關誤報、模組健檢誤判的共同根因）。
#   起點＝最後一次「Uvicorn running on」往前最近的「MOTRIX ERP starting」（autostart.bat 每輪迴圈開頭寫）。
#   ⚠ 不可以用「Uvicorn running on」當起點：main.py 在 import 時印的行（開關 MOTRIX_GEO=1／MOTRIX_TENDER_RADAR=1、
#     「模組 <key> <版本> 已載入」）都在它之前 ⇒ 永遠掃不到。
#   找不到 ⇒ $null（呼叫端要說「驗不到」；不可以退回整段 tail——裡面有上一個行程印的同一行，回滾後的檢查會假綠）。
#   $tail 由呼叫端讀：Get-Content -Encoding UTF8（server.log 是 Python 寫的 UTF-8、沒有 BOM；PS 5.1 預設用 ANSI 讀 ⇒ 中文比對不到）。
function Get-StartupRange($tail) {
    $lastStartIdx = -1
    for ($i = $tail.Count - 1; $i -ge 0; $i--) {
        if ($tail[$i] -like "*Uvicorn running on*") { $lastStartIdx = $i; break }
    }
    if ($lastStartIdx -lt 0) { return $null }
    for ($i = $lastStartIdx; $i -ge 0; $i--) {
        if ($tail[$i] -like "*MOTRIX ERP starting*") { return ,@($tail[$i..($tail.Count - 1)]) }
    }
    return $null
}

# 開關生效檢查的判定（Step 5 呼叫；抽出來才測得到）。$range＝Get-StartupRange 的結果。
#   Want＝autostart.bat 寫著要開（set X=1，:: 註解掉的不算）；Missing＝要開而這次啟動那一段 log 沒有「X=1」那一行。
function Get-SwitchMismatch([string]$autostartText, $range, [string[]]$names) {
    $want = @()
    $missing = @()
    foreach ($sw in $names) {
        $wantOn = $false
        foreach ($ln in ($autostartText -split "\r?\n")) {
            $t = $ln.Trim()
            if ($t.StartsWith("::")) { continue }   # 被註解掉的不算
            if ($t -match ("^set\s+" + [regex]::Escape($sw) + "\s*=\s*1$")) { $wantOn = $true }
        }
        if (-not $wantOn) { continue }
        $want += $sw
        if (@($range | Where-Object { $_ -match ([regex]::Escape($sw) + "=1") }).Count -eq 0) { $missing += $sw }
    }
    return @{ Want = $want; Missing = $missing }
}

# 呼叫 python 並回 @{ Text; Exit }。
# ⚠️ PS 5.1：原生執行檔往 stderr 印任何東西，在 $ErrorActionPreference = "Stop" 底下會被包成
#    NativeCommandError 中止整支腳本；輸出是陣列時 -match 回的是元素 ⇒ 一律先合成一個字串（見 Step 1 的註解）。
function Invoke-Py([string[]]$PyArgs) {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & python @PyArgs 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }
    return @{ Text = ($out | Out-String); Exit = $code }
}

# ── 停服／啟動（2026-09-28）─────────────────────────────────────────────
# 先前：凡是命令列含 `uvicorn main:app` 的行程一律殺掉（同一台機器上別的安裝、開發用的 uvicorn 一起倒），
#       而 autostart.bat 的 cmd 迴圈不動 ⇒ 5 秒後用**舊的環境變數**把服務拉回來，而那時複製可能還沒做完。
#       2026-09-27 正式機升級實際踩過這個迴圈（UPGRADE-RUNBOOK §1 ①b）。
# 現在：只認**這個安裝**的行程：
#   ① 迴圈：命令列含本安裝 autostart.bat 完整路徑的 cmd.exe；或是聽 $Port 的那個行程往上找到的
#      cmd.exe（命令列含 autostart.bat）——排程工作用相對路徑啟動時靠這一條
#   ② 迴圈底下的整棵行程樹（uvicorn.exe → python.exe → spawn 子行程）
#   ③ 聽 $Port 的行程（只停 python 系列；別的程式佔用只警告）
#   ④ 命令列是 uvicorn main:app 且帶 --port $Port 的行程，與 parent_pid 指到上面任何一個的 spawn 子行程
# 迴圈先停，才不會把剛殺掉的 uvicorn 又拉起來。複製完由 Start-InstallService 重新啟動。
function Stop-InstallService {
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $byPid = @{}
    foreach ($p in $all) { $byPid[[int]$p.ProcessId] = $p }
    $batFull = (Join-Path $BackendDir "autostart.bat").ToLowerInvariant()
    $loops = New-Object System.Collections.Generic.List[int]
    foreach ($p in $all) {
        if ($p.Name -eq "cmd.exe" -and $p.CommandLine -and $p.CommandLine.ToLowerInvariant().Contains($batFull)) {
            $loops.Add([int]$p.ProcessId)
        }
    }
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
    foreach ($lp in $listeners) {
        $cur = $byPid[$lp]
        $hops = 0
        while ($cur -and $hops -lt 6) {
            $parent = $byPid[[int]$cur.ParentProcessId]
            if (-not $parent) { break }
            if ($parent.Name -eq "cmd.exe" -and $parent.CommandLine -match 'autostart\.bat') {
                if (-not $loops.Contains([int]$parent.ProcessId)) { $loops.Add([int]$parent.ProcessId) }
                break
            }
            if ($parent.Name -notmatch '^(python|pythonw|uvicorn)(\.exe)?$') { break }
            $cur = $parent
            $hops++
        }
    }
    $targets = New-Object System.Collections.Generic.List[int]
    function Add-Tree([int]$rootPid) {
        if (-not $targets.Contains($rootPid)) { $targets.Add($rootPid) }
        foreach ($c in $all) {
            if ([int]$c.ParentProcessId -eq $rootPid -and [int]$c.ProcessId -ne $rootPid -and -not $targets.Contains([int]$c.ProcessId)) {
                Add-Tree ([int]$c.ProcessId)
            }
        }
    }
    foreach ($l in $loops) { Add-Tree $l }
    foreach ($lp in $listeners) {
        $proc = $byPid[$lp]
        if ($proc -and $proc.Name -match '^(python|pythonw|uvicorn)(\.exe)?$') { Add-Tree $lp }
        elseif ($proc) { Warn "  port $Port 由 $($proc.Name)（PID $lp）佔用，不是 python —— 不停它，請人工確認。" }
    }
    $portRe = '--port[= ]+' + $Port + '\b'
    foreach ($p in $all) {
        if ($p.CommandLine -and $p.CommandLine -match 'uvicorn' -and $p.CommandLine -match 'main:app' -and $p.CommandLine -match $portRe) {
            Add-Tree ([int]$p.ProcessId)
        }
    }
    foreach ($p in $all) {
        if ($p.CommandLine -and $p.CommandLine -match 'spawn_main.*parent_pid=(\d+)' -and $targets.Contains([int]$Matches[1])) {
            Add-Tree ([int]$p.ProcessId)
        }
    }
    if ($loops.Count -eq 0) { Info "  沒有找到這個安裝的 autostart 迴圈（cmd.exe … autostart.bat）。" }
    foreach ($t in $targets) {
        $p = $byPid[$t]
        $kind = if ($loops.Contains($t)) { "autostart 迴圈" } else { "服務行程" }
        $cmdShown = if ($p -and $p.CommandLine) { $p.CommandLine } else { "" }
        if ($cmdShown.Length -gt 160) { $cmdShown = $cmdShown.Substring(0, 160) + "…" }
        Info "  結束 $kind PID $t（$(if ($p) { $p.Name })）：$cmdShown"
        Stop-Process -Id $t -Force -ErrorAction SilentlyContinue
    }
    return $targets.Count
}

# 複製完、健康檢查之前啟動。排程工作優先：從遠端工作階段（部署儀表板走 WinRM）直接 Start-Process 的
# 迴圈是那個工作階段的子行程，工作階段結束時可能被一起結束。
function Start-InstallService {
    $task = Get-ScheduledTask -TaskName $AutostartTaskName -ErrorAction SilentlyContinue
    if ($task -and $task.State -ne "Disabled") {
        Start-ScheduledTask -TaskName $AutostartTaskName
        Ok "  已透過排程工作「$AutostartTaskName」重新啟動 autostart 迴圈。"
        return
    }
    $bat = Join-Path $BackendDir "autostart.bat"
    if (-not (Test-Path $bat)) {
        Warn "  找不到 $bat，無法啟動服務（健康檢查會失敗並觸發回滾）。"
        return
    }
    Start-Process -FilePath (Join-Path $env:WINDIR "System32\cmd.exe") -ArgumentList "/c `"$bat`"" `
        -WorkingDirectory $BackendDir -WindowStyle Hidden
    Warn "  排程工作「$AutostartTaskName」不存在或已停用：改由本腳本直接啟動 autostart.bat。遠端工作階段結束時它可能跟著結束，事後請確認排程工作。"
}

# AH-M3（2026-09-28 A 稽核）：停服**之後**才發生的失敗出口——不可以讓服務一直停著。
#   複製失敗（copy_failed_*）⇒ AH-S7（使用者裁示）：先把程式寫回快照（Restore-ProgramAfterCopyFailure，
#     定義在 Step 3 之前），再啟動＋健康檢查；此刻新程式沒跑過 ⇒ DB 沒被碰 ⇒ 完整回到套用前。
#     寫回快照失敗 ⇒ 不啟動（不要用殘骸對正式庫跑 migration），人工處理。
#   刪除失敗（delete_failed，新程式已完整）⇒ 重新啟動，訊息附手動回滾指令；service 仍記 down（沒觀察到它起來）。
function Fail-AfterStop($msg, $status) {
    if ($status -like "copy_failed*") {
        Warn "  複製新程式失敗：把程式寫回套用前的快照（資料庫尚未被新程式碰過）..."
        if (-not (Restore-ProgramAfterCopyFailure)) {
            Fail ($msg + " 寫回快照也沒有完全成功：服務未啟動，需要人工處理；快照：$rollbackDir") $status
        }
        Start-InstallService
        $back = $false
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Seconds 2
            if (Test-Ping -Url $PingUrl -TimeoutSec 5) { $back = $true; break }
        }
        if ($back) { $script:ServiceState = "up"; $script:ProdState = "restored" } else { $script:ProdState = "restored_unhealthy" }
        Fail ($msg + " 已自動回到套用前的程式（資料庫未動）$(if ($back) { '，服務已恢復。' } else { '，但服務健康檢查沒有通過，需要人工確認。' })") $status
    }
    Warn "  套用中途失敗：重新啟動服務（磁碟上是套用到一半的程式）。"
    try { Start-InstallService } catch { Warn "  重新啟動失敗：$($_.Exception.Message)" }
    Fail ($msg + " 服務已嘗試重新啟動。要回到套用前：powershell -ExecutionPolicy Bypass -File `"$BackendDir\tools\rollback_update.ps1`" -SnapshotTimestamp $timestamp") $status
}

# 🔑 **握手行**：它說的是「**正在跑的這一份腳本**看得懂 v2 協定」。
# ⚠️ 對 `apply_update.ps1` 而言它是**多餘的保險**——`_dashboard_remote.ps1:98-104`
#    會在呼叫之前先把套件裡的 `backend\tools\*` 覆蓋過去，所以跑的一定是新版。
# ☠️ 但那段複製包在 `if (Test-Path $srcTools) { ... }` 裡而**沒有 else** ⇒
#    包裡缺 `backend\tools\` 時它**安靜跳過**，正式機就用舊的跑
#    —— 這一行讓那個安靜跳過**變成看得見的**。
# 🔴 而對 `rollback_update.ps1` 它不是保險，是**必要條件**：
#    rollback 分支**沒有**那段預先複製（§34a），所以舊腳本真的會被跑到。
# AH-S11（2026-09-28）：沒被接住的例外也要印結果行、寫結果檔、放鎖——否則下一次看到的是殘留鎖，而沒有人知道這一次發生什麼。
#   Fail 走 exit，不會進這裡；這裡只接「沒有人預料到」的例外。
trap {
    Write-Host "`n[FAIL] 未預期的錯誤：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host ($_.ScriptStackTrace | Out-String)
    # D 稽核 DS1：是我們停掉服務、而磁碟不在還原到一半的狀態（沒動或新版已完整）⇒ 試著把服務拉回來；restoring 不動
    if ($script:ServiceState -eq "down" -and @("not_applied", "applied") -contains $script:ProdState) {
        try { Start-InstallService } catch { Write-Host "[WARN] 重新啟動服務失敗：$($_.Exception.Message)" }
    }
    Emit-Result "unhandled_exception" 1
    exit 1
}

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

$pkgScript = Join-Path $PackagePath "backend\tools\apply_update.ps1"
$pkgVerLine = if (Test-Path $pkgScript) { Select-String -Path $pkgScript -Pattern '^\$ApplyScriptVersion = "([^"]+)"' | Select-Object -First 1 } else { $null }
$pkgVer = if ($pkgVerLine) { $pkgVerLine.Matches[0].Groups[1].Value } else { "(沒有)" }
if ($pkgVer -ne $ApplyScriptVersion) {
    $verMsg = "正在執行的 apply_update.ps1（版本 $ApplyScriptVersion）與部署包裡的（版本 $pkgVer）不同。" +
        "請先把部署包的 backend\tools\* 複製到 $BackendDir\tools\，再執行（UPGRADE-RUNBOOK §8；儀表板會自動做這一步）。正式機尚未被觸碰。"
    Fail $verMsg "script_not_from_package"
}
$script:ResultCommit = $manifest.commit

# 同一時間只准一個套用／回滾（UPDATE-DELIVERY §9.2）：在任何備份、停服之前拿鎖
$lockState = Enter-InstallLock "apply_update" $PackagePath
if ($lockState -eq "locked") { Fail "另一個套用或回滾正在執行（見上方鎖檔內容），這一次未做任何動作。" "apply_locked" }
if ($lockState -eq "stale") { Fail "有殘留的鎖檔（持有的行程已不在）：確認沒有套用或回滾在跑之後，手動刪除 $BackendDir\.apply.lock 再重跑。正式機尚未被觸碰。" "apply_locked_stale" }

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
# AH-S10：與結果檔同一個時間戳 ⇒ logs\apply_update_<ts>.result.json 對得到 rollback_snapshots\<ts>\
$timestamp = $script:RunStamp

$dbBackupDir = Join-Path $BackendDir "db_backups\pre_update_$timestamp"
New-Item -ItemType Directory -Force -Path $dbBackupDir | Out-Null
$dbPath = Join-Path $BackendDir "motrix_erp.db"
$dbBackupPath = Join-Path $dbBackupDir "motrix_erp.db"
# demo 庫（2026-09-28）：新版啟動時對它一樣跑 init_db（main.py），先前沒有快照、沒有乾跑、回滾也不還原
# ⇒ 回滾後是「舊程式碼＋新 schema 的 demo 庫」。與主庫同一套處理。
$demoDbPath = Join-Path $BackendDir "motrix_erp_demo.db"
$demoDbBackupPath = Join-Path $dbBackupDir "motrix_erp_demo.db"
if ((Test-Path $dbPath) -or (Test-Path $demoDbPath)) {
    # 用 SQLite Online Backup API（跟 archive.py _snapshot_sqlite() 每日備份一致的做法），
    # 不用陽春 Copy-Item —— db 是 WAL 模式，伺服器這時可能還在跑，單純複製主檔案可能
    # 漏掉尚未 checkpoint 進主檔案、還留在 -wal 的交易，快照不保證一致。backup() 會產生
    # 真正完整、可安全還原的快照。
    $backupPy = Join-Path $env:TEMP "motrix_predeploy_backup_$timestamp.py"
    @"
import os
import sqlite3
for s, d in ((r'$dbPath', r'$dbBackupPath'), (r'$demoDbPath', r'$demoDbBackupPath')):
    if not os.path.exists(s):
        continue
    src = sqlite3.connect(s)
    dst = sqlite3.connect(d)
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
    # 🔴 2026-09-24（正式機套用乙時誤判）：`& python x 2>&1` 在 PS 5.1 下，只要 python 往 stderr
    #    印任何一行（例：db.py 的 logger.warning），輸出就是**陣列**（ErrorRecord ＋ 字串）。
    #    對陣列用 -notmatch 回傳的是「不符合的元素」—— 非空即為 true ⇒ 成功也被判失敗。
    #    ⇒ 先合成一個字串再比對。以前輸出只有一行，所以一直沒被發現。
    $backupText = ($backupOutput | Out-String)
    if ($backupExit -ne 0 -or ($backupText -notmatch "BACKUP_OK")) {
        Write-Host $backupText
        Fail "升級前 db 備份失敗，中止套用（正式庫尚未被觸碰）。" "backup_failed"
    }
    if (Test-Path $dbPath) { Ok "  db 快照（SQLite Online Backup API）：$dbBackupPath" } else { Warn "  找不到 motrix_erp.db，略過主庫快照。" }
    if (Test-Path $demoDbPath) { Ok "  demo 庫快照（SQLite Online Backup API）：$demoDbBackupPath" }
} else {
    Warn "  找不到 motrix_erp.db，略過 db 快照。"
}

# ============================================================
# Migration 乾跑驗證 —— 新版 db.py 只在 db 快照的「副本」上跑一次，
# 正式庫完全不碰。失敗就在這裡直接中止，不停服、不碰正式庫、
# 不留回滾快照，把「正式庫是第一個試跑新 migration 的地方」的風險
# 移到這一步先擋下來。
# ============================================================
if ((Test-Path $dbPath) -or (Test-Path $demoDbPath)) {
    Info "  Migration 乾跑驗證（主庫$(if (Test-Path $demoDbPath) { '＋demo 庫' })）..."
    $dryRunDb = Join-Path $env:TEMP "motrix_erp_dryrun_$timestamp.db"
    $dryRunDemoDb = Join-Path $env:TEMP "motrix_erp_demo_dryrun_$timestamp.db"
    $dryRunTargets = @()
    if (Test-Path $dbBackupPath) { Copy-Item $dbBackupPath $dryRunDb -Force; $dryRunTargets += $dryRunDb }
    if (Test-Path $demoDbBackupPath) { Copy-Item $demoDbBackupPath $dryRunDemoDb -Force; $dryRunTargets += $dryRunDemoDb }
    $dryRunList = ($dryRunTargets | ForEach-Object { "r'$_'" }) -join ", "

    # 2026-09-28：新包有 backend\tools\migrate_like_startup.py ⇒ 用它（先照啟動規則載入模組，模組 migration 才會跑到；
    #   未完成、模組載入失敗、停用清單讀不到都算乾跑失敗）。授權讀正式機的金鑰檔（只讀），與正式機啟動一致。
    #   沒有這支的舊包 ⇒ 沒有模組 migration，照舊只跑 init_db。
    $dryRunTool = Join-Path $PackagePath "backend\tools\migrate_like_startup.py"
    $dryRunPy = Join-Path $env:TEMP "motrix_dryrun_$timestamp.py"
    if (Test-Path $dryRunTool) {
        $licenseArg = ""
        $prodLicense = Join-Path $BackendDir "license.key"
        if (Test-Path $prodLicense) { $licenseArg = ", '--license', r'$prodLicense'" }
        $dbArgs = ($dryRunTargets | ForEach-Object { "'--db', r'$_'" }) -join ", "
        @"
import runpy, sys
sys.argv = [r'$dryRunTool', $dbArgs$licenseArg]
try:
    runpy.run_path(r'$dryRunTool', run_name='__main__')
except SystemExit as e:
    if e.code == 0:
        print('DRYRUN_OK')
    sys.exit(e.code)
"@ | Set-Content -Path $dryRunPy -Encoding UTF8
    } else {
        @"
import sys
sys.path.insert(0, r'$(Join-Path $PackagePath "backend")')
import db
for p in ($dryRunList,):
    db.init_db(p)
print('DRYRUN_OK')
"@ | Set-Content -Path $dryRunPy -Encoding UTF8
    }

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
    Remove-Item $dryRunDb, $dryRunDemoDb, $dryRunPy -Force -ErrorAction SilentlyContinue
    Remove-Item "$dryRunDb-wal", "$dryRunDb-shm", "$dryRunDemoDb-wal", "$dryRunDemoDb-shm" -Force -ErrorAction SilentlyContinue
    Remove-Item "$dryRunDb.modules_disabled.json", "$dryRunDemoDb.modules_disabled.json" -Force -ErrorAction SilentlyContinue

    # 🔴 2026-09-24（正式機套用乙時誤判）：`& python x 2>&1` 在 PS 5.1 下，只要 python 往 stderr
    #    印任何一行（例：db.py 的 logger.warning），輸出就是**陣列**（ErrorRecord ＋ 字串）。
    #    對陣列用 -notmatch 回傳的是「不符合的元素」—— 非空即為 true ⇒ 成功也被判失敗。
    #    ⇒ 先合成一個字串再比對。以前輸出只有一行，所以一直沒被發現。
    $dryRunText = ($dryRunOutput | Out-String)
    if ($dryRunExit -ne 0 -or ($dryRunText -notmatch "DRYRUN_OK")) {
        Write-Host ""
        Write-Host "======================================" -ForegroundColor Red
        Write-Host "  Migration 乾跑驗證失敗，中止套用（正式庫完全未被觸碰）" -ForegroundColor Red
        Write-Host "======================================" -ForegroundColor Red
        Write-Host $dryRunText
        Fail "新版本的 migration 在 db 快照副本上乾跑失敗，套用到正式庫時很可能也會出錯。請檢查上面的錯誤訊息、修好新版 db.py 的 migration 後重新打包，再重新套用。" "migration_dryrun_failed"
    }
    Ok "  Migration 乾跑驗證通過（新版 db.py 對照正式庫目前的 schema 乾跑一輪，未發現錯誤）。"
} else {
    Warn "  找不到正式庫 motrix_erp.db，略過 migration 乾跑驗證（視為全新安裝）。"
}

# ============================================================
# 刪除計畫（2026-09-28）—— 舊版有、新版沒有的程式檔
# ============================================================
# 🔴 robocopy 只加不刪，而模組載入器看資料夾、不看 lock ⇒ 包裡刪掉、改名或排除的模組資料夾與頁面
#    會繼續被載入。判定在 backend\tools\apply_plan.py（跑**新包裡**那一份；分類與 V9→新版升級共用
#    core.upgrade.classify ⇒ 資料、DB、設定、uploads、PDF 一律不列入）。
# 🔑 在停服之前算好、先印出來、寫進 log；超過 -MaxDeleteFiles ⇒ 什麼都不動就中止。
Info "  刪除計畫..."
$planTool = Join-Path $PackagePath "backend\tools\apply_plan.py"
if (-not (Test-Path $planTool)) {
    Fail "部署包裡沒有 backend\tools\apply_plan.py，無法計算刪除計畫（包太舊或不完整），中止（正式機尚未被觸碰）。" "plan_tool_missing"
}
$planTmp = Join-Path $env:TEMP "motrix_apply_plan_$timestamp.json"
$planLog = Join-Path $BackendDir "logs\apply_update_$timestamp.plan.txt"
$planRun = Invoke-Py @($planTool, "plan", "--root", $ProdRoot, "--pkg", $PackagePath, "--out", $planTmp, "--max", "$MaxDeleteFiles", "--log", $planLog)
Write-Host $planRun.Text
if ($planRun.Exit -eq 3) {
    Fail "要刪除的程式檔超過上限 $MaxDeleteFiles（清單見上方與 $planLog）。請人工確認清單無誤後，以 -MaxDeleteFiles <更大的值> 重跑（正式機尚未被觸碰）。" "delete_plan_too_large"
}
if ($planRun.Exit -ne 0 -or ($planRun.Text -notmatch "APPLY_PLAN_OK")) {
    # apply_plan 明確拒絕（授權有而包沒有的模組、lock 不合法、包種類不對）與「算不出來」分開報（2026-09-28 演練）
    if ($planRun.Text -match "APPLY_PLAN_REFUSED") {
        Fail "部署包被拒絕套用（原因見上方 APPLY_PLAN_REFUSED 那一行），中止（正式機尚未被觸碰）。" "plan_refused"
    }
    Fail "刪除計畫無法產生（exit code $($planRun.Exit)，原因見上方），中止（正式機尚未被觸碰）。" "plan_failed"
}
$plan = Get-Content $planTmp -Raw -Encoding UTF8 | ConvertFrom-Json
Ok "  刪除計畫：刪 $(@($plan.delete).Count) 檔、新增 $(@($plan.added).Count) 檔（清單已寫入 $planLog）"
if (-not $plan.baseline_present) {
    Warn "  沒有上一次套用的檔案清單（backend\.deployed_files.json；V9→新版轉換後的第一次會這樣）：只依 modules.lock 與模組資料夾刪除，其餘 $(@($plan.no_baseline_candidates).Count) 個候選只列出不刪。成功後會寫下清單。"
}

$rollbackRoot = Join-Path $BackendDir "rollback_snapshots"
$rollbackDir = Join-Path $rollbackRoot $timestamp
New-Item -ItemType Directory -Force -Path $rollbackDir | Out-Null
Info "  建立程式碼回滾快照：$rollbackDir"
# 🔴 **做快照失敗要當場擋下**（`RP1`）。
# ☠️ 先前這兩行是 `| Out-Null` 而沒有檢查結束碼 ⇒ **靜默失敗 ⇒ 快照殘缺**，
#    而它**沒有任何症狀** —— 直到有一天真的要用它回滾。
# 🔑 **那一天正是最不能出事的一天，而那一刻沒有第二次機會。**
# 📌 對照就在同一支檔案：`Step 3` 套用新版那兩行本來就有 `-ge 8 ⇒ Fail`
#    ⇒ 這不是新紀律，是**把已有的紀律補到漏掉的那一半**。
# ⚠️ `| Out-Null` 不影響 `$LASTEXITCODE` —— 它由原生執行檔設定，
#    管線接到 cmdlet 不會覆蓋它。
# ⚠️ 這兩條出口的 `rolled_back` 是 `not_applied`（此刻正式機還沒被碰）
#    ⇒ 與「還原到一半」**不可以共用一個 status**：前者重跑就好，後者要叫人。
# 2026-09-28：/XD 補上資料目錄（export_archive＝勞報個資、_demo_*＝demo 資料、uploads／報價單PDF 等）——
#   先前每次套用都把個資複製進 rollback_snapshots。回滾不需要它們：套用本來就不碰資料目錄。
robocopy $BackendDir (Join-Path $rollbackDir "backend") /E /R:3 /W:5 /XD db_backups rollback_snapshots logs uploads 報價單PDF export_archive backup_alerts _demo_* __pycache__ certs /XF motrix_erp.db motrix_erp.db-wal motrix_erp.db-shm motrix_erp_demo.db motrix_erp_demo.db-wal motrix_erp_demo.db-shm heartbeat_config.json .deployed_commit.json server.log license.key autostart.bat .apply.lock | Out-Null
if ($LASTEXITCODE -ge 8) { Fail "建立程式碼回滾快照失敗（backend，exit code $LASTEXITCODE）——快照不完整就繼續套用的話，出事時沒有東西可以回滾。" "snapshot_failed_backend" }
robocopy $FrontendDir (Join-Path $rollbackDir "frontend") /E /R:3 /W:5 | Out-Null
if ($LASTEXITCODE -ge 8) { Fail "建立程式碼回滾快照失敗（frontend，exit code $LASTEXITCODE）——快照不完整就繼續套用的話，出事時沒有東西可以回滾。" "snapshot_failed_frontend" }
foreach ($d in $RootProgramDirs) {
    $src = Join-Path $ProdRoot $d
    if (-not (Test-Path $src)) { continue }
    robocopy $src (Join-Path $rollbackDir $d) /E /R:3 /W:5 /XD __pycache__ | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "建立程式碼回滾快照失敗（$d，exit code $LASTEXITCODE）——快照不完整就繼續套用的話，出事時沒有東西可以回滾。" "snapshot_failed_root_dirs" }
}
# 計畫跟著快照走（回滾時用它刪掉這次新增的檔）；每一個要刪的檔在快照裡都要找得到，否則回滾還原不了它。
$planPath = Join-Path $rollbackDir "apply_plan.json"
# AH-S2（2026-09-28）：套用前的部署紀錄存進快照；手動回滾時還原（否則 prod-status 報錯 commit、重套同版被 duplicate_version 擋）
$deployedBefore = Join-Path $BackendDir ".deployed_commit.json"
if (Test-Path $deployedBefore) { Copy-Item $deployedBefore (Join-Path $rollbackDir "deployed_commit.before.json") -Force }
Move-Item $planTmp $planPath -Force
$snapCheck = Invoke-Py @($planTool, "verify-snapshot", "--plan", $planPath, "--snapshot", $rollbackDir)
if ($snapCheck.Exit -ne 0 -or ($snapCheck.Text -notmatch "APPLY_SNAPSHOT_OK")) {
    Write-Host $snapCheck.Text
    Fail "回滾快照裡缺少要刪除的檔（見上方）——刪了就回滾不回來，中止（正式機尚未被觸碰）。" "snapshot_missing_deleted"
}
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
Info "`n[2/6] 停止伺服器（只停這個安裝的 autostart 迴圈與服務行程）..."
$stoppedCount = Stop-InstallService
Info "  結束 $stoppedCount 個行程。"

# 等待 port 真正釋放（行程被殺掉到 OS 真的放開 socket 之間有短暫空窗，
# 太快重新啟動常撞到 [Errno 10048] 位址已被使用）
$portFreed = $false
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    $stillListening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $stillListening) { $portFreed = $true; break }
}
if ($portFreed) {
    Ok "  Port $Port 已確認釋放。"
} else {
    Warn "  Port $Port 等待 15 秒後仍顯示被佔用，繼續往下走（新迴圈啟動時會自動重試綁定）。"
}
Ok "  伺服器已停止；複製與依賴安裝完成後由本腳本重新啟動迴圈。"

# 🔴 **我們自己停掉了它** ⇒ 從這裡開始 `service=down`，
# 直到某一次 ping 成功才會變回 `up`。
# ☠️ 少了這一行，`:358`（robocopy 中途失敗）會報 `service=unknown`，
#    而實際上**是我們把它停掉的** —— 那個差別決定使用者要不要現在去開機。
$script:ServiceState = "down"

# AH-S7（2026-09-28 使用者裁示）：複製新程式失敗時由 Fail-AfterStop 呼叫。
#   刪掉這次新增的檔 → 快照寫回 backend／frontend／tools／product／根目錄文件；回傳是否全部成功（不啟動服務）。
function Restore-ProgramAfterCopyFailure {
    $script:ProdState = "restoring"
    $ok = $true
    $clean = Invoke-Py @($planTool, "cleanup-snapshot", "--root", $ProdRoot, "--pkg", $PackagePath, "--snapshot", $rollbackDir)
    Write-Host $clean.Text
    if ($clean.Exit -ne 0 -or ($clean.Text -notmatch "APPLY_SNAPCLEAN_OK")) { $ok = $false }
    foreach ($pair in @(@("backend", $BackendDir), @("frontend", $FrontendDir))) {
        robocopy (Join-Path $rollbackDir $pair[0]) $pair[1] /E /R:3 /W:5 /XD certs /XF license.key autostart.bat .apply.lock heartbeat_config.json .deployed_commit.json | Out-Null
        if ($LASTEXITCODE -ge 8) { Warn "  寫回快照失敗（$($pair[0])，exit $LASTEXITCODE）"; $ok = $false }
    }
    foreach ($d in $RootProgramDirs) {
        $snap = Join-Path $rollbackDir $d
        if (-not (Test-Path $snap)) { continue }
        robocopy $snap (Join-Path $ProdRoot $d) /E /R:3 /W:5 /XD certs /XF license.key autostart.bat .apply.lock heartbeat_config.json .deployed_commit.json | Out-Null
        if ($LASTEXITCODE -ge 8) { Warn "  寫回快照失敗（$d，exit $LASTEXITCODE）"; $ok = $false }
    }
    $rd = Join-Path $rollbackDir "root_docs"
    if (Test-Path $rd) { Get-ChildItem -Path $rd -File | ForEach-Object { Copy-Item $_.FullName -Destination $ProdRoot -Force } }
    return $ok
}

# ============================================================
# Step 3: 複製新程式碼（絕不 /MIR；刪除只依停服前印出的刪除計畫）
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

# 2026-09-28：/XF 補 autostart.bat —— 它是**這台機器的設定**（對外連線總開關 MOTRIX_TENDER_RADAR／MOTRIX_GEO），
#   包裡那份是出貨預設值；先前每次套用都被蓋掉（core/upgrade.py 的 PACKAGE_DEFAULT_CONFIG 同一條規則）。
$rc1 = robocopy (Join-Path $PackagePath "backend") $BackendDir /E /R:3 /W:5 `
    /XD db_backups rollback_snapshots uploads logs 報價單PDF export_archive backup_alerts _demo_* `
    /XF motrix_erp.db motrix_erp.db-wal motrix_erp.db-shm motrix_erp_demo.db motrix_erp_demo.db-wal motrix_erp_demo.db-shm heartbeat_config.json .deployed_commit.json .deployed_files.json server.log autostart.bat
if ($LASTEXITCODE -ge 8) { Fail-AfterStop "robocopy backend/ 失敗（exit code $LASTEXITCODE）。" "copy_failed_backend" }

$rc2 = robocopy (Join-Path $PackagePath "frontend") $FrontendDir /E /R:3 /W:5
if ($LASTEXITCODE -ge 8) { Fail-AfterStop "robocopy frontend/ 失敗（exit code $LASTEXITCODE）。" "copy_failed_frontend" }

foreach ($d in $RootProgramDirs) {
    $src = Join-Path $PackagePath $d
    if (-not (Test-Path $src)) { continue }
    robocopy $src (Join-Path $ProdRoot $d) /E /R:3 /W:5 /XD __pycache__ | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail-AfterStop "robocopy $d/ 失敗（exit code $LASTEXITCODE）。" "copy_failed_root_dirs" }
}

# autostart.bat：機器上有 ⇒ 保留；沒有 ⇒ 從包補上；兩邊不同 ⇒ 提示人比對（與 core/upgrade.py sync_package_default_config 同規則）
$pkgAutostart = Join-Path $PackagePath "backend\autostart.bat"
$prodAutostart = Join-Path $BackendDir "autostart.bat"
if (Test-Path $pkgAutostart) {
    if (-not (Test-Path $prodAutostart)) {
        Copy-Item $pkgAutostart $prodAutostart
        Warn "  這台機器沒有 autostart.bat，已從部署包補上出貨預設版本。"
    } elseif ((Get-FileHash $pkgAutostart).Hash -ne (Get-FileHash $prodAutostart).Hash) {
        Info "  autostart.bat 保留這台機器的版本（與部署包的預設版本不同；新版若有要加的設定請人工比對）。"
    }
}

# 刪除計畫（停服前已印出、已確認快照裡都有）
$delRun = Invoke-Py @($planTool, "execute", "--root", $ProdRoot, "--pkg", $PackagePath, "--plan", $planPath)
Write-Host $delRun.Text
if ($delRun.Exit -ne 0 -or ($delRun.Text -notmatch "APPLY_DELETE_OK")) {
    Fail-AfterStop "依刪除計畫刪除舊程式檔失敗（見上方）——新程式碼已複製、舊檔可能殘留，需要人工處理；快照：$rollbackDir。" "delete_failed"
}

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
Info "`n[4b/6] 重新啟動服務..."
Start-InstallService

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
    $tail = Get-Content $logPath -Tail 200 -Encoding UTF8
    $bootRange = Get-StartupRange $tail
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
    # 對應那一行（範圍＝Get-StartupRange：import 時印的，在 Uvicorn running on 之前；
    # 2026-09-28 A：原本掃 Uvicorn running on 之後 ⇒ 每次部署都誤報）。後端啟動時會印（main.py），而那一行讀的是 os.environ ——
    # 它回答的是「這個行程實際拿到什麼」，不是「檔案裡寫了什麼」。
    #
    # 只檢查「該開而沒開」這一個方向：沒有要求開的就不會有那一行，
    # 而那是正常狀態。漏報的代價是「有人偷偷開了而我們沒喊」，
    # 漏喊的代價是「以為開了而其實沒開」——後者才是這一條在防的。
    $switchNames = @("MOTRIX_TENDER_RADAR", "MOTRIX_GEO")
    $autostartPath = Join-Path $BackendDir "autostart.bat"
    $switchMismatch = @()
    if ((Test-Path $autostartPath) -and $bootRange) {
        $autostartText = Get-Content $autostartPath -Raw -ErrorAction SilentlyContinue
        $sm = Get-SwitchMismatch $autostartText $bootRange $switchNames
        $switchMismatch = @($sm.Missing)
        foreach ($sw in $sm.Want) {
            if ($switchMismatch -notcontains $sw) { Ok "  開關 $sw：autostart.bat 要求開啟，這次啟動的 log 裡看得到它 —— 生效。" }
        }
    } else {
        Info "  開關生效檢查略過（找不到 autostart.bat，或 server.log 裡找不到本次啟動的起點「MOTRIX ERP starting」）——驗不到，不代表生效。"
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
    # 2026-09-28：連迴圈一起停（先前只停聽 port 的行程，迴圈 5 秒後用還原到一半的程式碼把它拉起來）。
    $null = Stop-InstallService
    Start-Sleep -Seconds 2

    # 🔴 **危險值在動作之前設**（與 `:420` 同一條紀律）。
    # ☠️ 設在之後的話，下面兩條新出口會報 `applied`
    #    ——語意是「新版**完整**寫進正式機」，**而它正在還原**。
    $script:ProdState = "restoring"

    # 2026-09-28：先刪掉這次**新增**的程式檔（robocopy /E 寫回快照不會刪它們；
    # 新增的模組資料夾留著 ⇒ 舊版的載入器照樣載它）。被刪的舊檔由下面寫回快照還原。
    # D 稽核 DM2：以快照為準——安裝目錄有、快照沒有的程式檔一律刪（不只「這次的 added」）
    $cleanRun = Invoke-Py @($planTool, "cleanup-snapshot", "--root", $ProdRoot, "--pkg", $PackagePath, "--snapshot", $rollbackDir)
    Write-Host $cleanRun.Text
    $cleanFailed = ($cleanRun.Exit -ne 0 -or ($cleanRun.Text -notmatch "APPLY_SNAPCLEAN_OK"))

    # 🔴 還原寫回也要檢查（`RP2`）。
    # ☠️ 先前失敗**不中止**，直接流進下面的健康檢查 —— 而半還原的 backend
    #    也可能回得出 `/api/ping` ⇒ 報 `restored`＝「已還原且健康」，
    #    **而磁碟上是還原到一半的殘骸。**
    robocopy (Join-Path $rollbackDir "backend") $BackendDir /E /R:3 /W:5 /XD certs /XF license.key autostart.bat .apply.lock heartbeat_config.json .deployed_commit.json | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "自動回滾寫回正式機失敗（backend，exit code $LASTEXITCODE）——正式機現在是還原到一半的狀態，需要人工處理。" "restore_copy_failed_backend" }
    robocopy (Join-Path $rollbackDir "frontend") $FrontendDir /E /R:3 /W:5 /XD certs /XF license.key autostart.bat .apply.lock heartbeat_config.json .deployed_commit.json | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "自動回滾寫回正式機失敗（frontend，exit code $LASTEXITCODE）——正式機現在是還原到一半的狀態，需要人工處理。" "restore_copy_failed_frontend" }
    foreach ($d in $RootProgramDirs) {
        $snap = Join-Path $rollbackDir $d
        if (-not (Test-Path $snap)) { continue }
        robocopy $snap (Join-Path $ProdRoot $d) /E /R:3 /W:5 /XD certs /XF license.key autostart.bat .apply.lock heartbeat_config.json .deployed_commit.json | Out-Null
        if ($LASTEXITCODE -ge 8) { Fail "自動回滾寫回正式機失敗（$d，exit code $LASTEXITCODE）——正式機現在是還原到一半的狀態，需要人工處理。" "restore_copy_failed_root_dirs" }
    }

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
    # D 稽核 DM1（使用者裁示）：覆寫資料庫之前先另存「回滾前」的主庫與 demo 庫；另存失敗就不覆寫
    $dbSaved = Backup-DatabasesOnline (Join-Path $BackendDir "db_backups\pre_rollback_$timestamp")
    if (-not $dbSaved) {
        Warn "  回滾前的資料庫另存失敗 ⇒ 不覆寫資料庫（維持新版 schema；新版 migration 只新增，舊程式讀得了），需要人工確認。"
    } elseif (Test-Path $dbBackupPath) {
        Copy-Item $dbBackupPath $dbPath -Force
        # 還原乾淨的主檔案後，殘留的 -wal/-shm（來自新版寫入）內容已經跟它對不上，
        # 必須一併清掉，否則下次連線時 SQLite 可能把過期的 WAL 內容重新套用回來，
        # 等於沒回滾乾淨。
        Remove-Item "$dbPath-wal", "$dbPath-shm" -Force -ErrorAction SilentlyContinue
        Ok "  資料庫已還原至升級前快照：$dbBackupPath"
    } else {
        Warn "  找不到升級前 db 快照（$dbBackupPath），資料庫維持目前狀態，可能仍是新版 schema，需要人工檢查！"
    }
    # demo 庫同一套（2026-09-28）：新版啟動時也對它跑了 init_db。
    if ($dbSaved -and (Test-Path $demoDbBackupPath)) {
        Copy-Item $demoDbBackupPath $demoDbPath -Force
        Remove-Item "$demoDbPath-wal", "$demoDbPath-shm" -Force -ErrorAction SilentlyContinue
        Ok "  demo 庫已還原至升級前快照：$demoDbBackupPath"
    }

    if ($cleanFailed) {
        Fail "自動回滾：快照裡沒有的程式檔沒有刪乾淨（見上方）——舊程式碼已寫回，但多出來的檔（可能含新模組資料夾）還在，服務未重新啟動，需要人工處理。快照：$rollbackDir" "restore_cleanup_failed"
    }
    Start-InstallService

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
        Write-Host "  port $Port 目前監聽狀態（協助判斷是否為服務真的中斷）：" -ForegroundColor Yellow
        $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
        if (-not $conns) {
            Write-Host "    （完全沒有任何連線/監聽在 port $Port 上——服務可能真的沒起來）" -ForegroundColor Yellow
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

# 這一版的程式檔清單（backend\.deployed_files.json）：下一次套用用它算「舊版有、新版沒有」的檔。
# 只在成功時寫；回滾時快照裡的舊清單會被寫回。寫失敗不影響這次（服務已健康），但下一次會少一個刪除依據 ⇒ 警告。
$baseRun = Invoke-Py @($planTool, "baseline", "--root", $ProdRoot, "--plan", $planPath)
if ($baseRun.Exit -ne 0 -or ($baseRun.Text -notmatch "APPLY_BASELINE_OK")) {
    Write-Host $baseRun.Text
    Warn "  寫入 backend\.deployed_files.json 失敗：下一次套用將只能依 modules.lock 刪除，請人工確認。"
} else {
    Ok "  已寫入這一版的程式檔清單（backend\.deployed_files.json）。"
}

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
