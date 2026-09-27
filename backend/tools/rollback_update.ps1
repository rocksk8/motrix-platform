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
$Port = 666
$AutostartTaskName = "MOTRIX ERP Server Autostart"
$BackendDir = Join-Path $ProdRoot "backend"
$FrontendDir = Join-Path $ProdRoot "frontend"
# 根目錄的程式目錄（2026-09-28，與 apply_update.ps1 同一份）：快照裡有就還原
$RootProgramDirs = @("tools", "product")

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
    $PingUrl = "https://127.0.0.1:$Port/api/ping"
} else {
    $PingUrl = "http://127.0.0.1:$Port/api/ping"
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

# ══════════════════════════════════════════════════════════════════
# `::RESULT::` 協定 v2（§34a）
# ══════════════════════════════════════════════════════════════════
#
# 🔴 **這支比 `apply_update.ps1` 更需要它，而理由是機制層的。**
# `_dashboard_remote.ps1` 的 `rollback` 分支（`:149-170`）**沒有**預先複製
# 套件裡的 `backend\tools\*`（那段只在 `deploy` 分支的 `:98-104`）
# ⇒ 這一份新腳本**只能靠一次成功的部署**才會上正式機。
# ☠️ 而危險的順序正是最可能發生的那一條：
#    部署失敗 ⇒ 自動回滾用套用前快照蓋回去 ⇒ 正式機的 tools **退回舊版**
#    ⇒ 使用者手動回滾 ⇒ 舊腳本不印這些行
# ⇒ 所以 dashboard 那一側對 `rollback` **必須先握手再啟用 fail-closed**，
#   否則那一刻會把回滾記成失敗 —— 而那一刻使用者最需要的正是
#   **「回滾到底成功了沒」**。
#
# ⚠️ `rolled_back` 在這支腳本裡的語意：
#    not_applied  **這一次執行沒有改動磁碟**（早期中止）
#    applied_no_restore  還原做到一半
#    restored   還原完成，且還原後 ping 成功
#    restored_unhealthy  還原完成，而 ping 一直沒成功
#
# 🔴 **讀法乙**（§44 定版）：這個欄位回答的是「**這一次執行改動了什麼**」，
#    不是「磁碟上現在是什麼」。兩支腳本同一個讀法 ⇒ 同一個情境同一個值。
# ⚠️ 而**參考點不同**，那由畫面負責講：
#      deploy 的 not_applied   ＝ 正式機完全沒被碰過
#      rollback 的 not_applied ＝ 還原沒開始，維持在按回滾之前的樣子
#      （而那個樣子通常是「一次失敗的部署剛動過它」）
#    ⇒ 機器值一份、人話兩份，見 `deploy_dashboard.describe_rolled_back()`。
#
# 🔴 初始值**不可以是 `unknown`**（§42）：
# ☠️ 那會讓每一條早退出口都報「我不知道」，**而其實它知道** ——
#    它知道自己什麼都還沒做。那是〈危險值在動作之前就設〉的相反病。
# 📌 `unknown` 留在值域裡當**金絲雀**：它不從任何顯式出口產生，
#    所以它一旦出現，就表示有人加了出口而漏設值。
$script:ProdState = "not_applied"

# `service`：只講**觀察到的事實**（定義與 apply_update.ps1 一致）
#   up / down / unknown
$script:ServiceState = "unknown"

function Emit-Result($status, $code) {
    Write-Host ("::RESULT:: v=2 status=$status rolled_back=$($script:ProdState)" +
                " service=$($script:ServiceState) exit=$code")
}

# ⚠️ `$status` 預設 `unknown` ⇒ 日後新增一條 `Fail` 而忘了給狀態，
#    它會印 `status=unknown`，而 dashboard 的值域檢查把它判成失敗。
#    🔑 **忘記的代價落在「被記成失敗」，不是「被記成成功」。**
function Fail($msg, $status = "unknown") {
    Write-Host "`n[FAIL] $msg" -ForegroundColor Red
    Emit-Result $status 1
    exit 1
}
function Info($msg)  { Write-Host $msg }
function Warn($msg)  { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Ok($msg)    { Write-Host "[OK] $msg" -ForegroundColor Green }

# ── 以下三個函式與 apply_update.ps1 **逐字相同**（2026-09-28）──────────────────
# 不抽成共用檔：dashboard 的 rollback 分支不預先複製 tools（見下方握手行註解），
# 共用檔版本對不上時兩支會一起壞。改一邊就要改另一邊；
# tests/platform/test_apply_plan_2026_09_28.py 比對兩份函式本體。
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
# ── 逐字相同的區段到此為止 ──────────────────────────────────────────────

# 🔴 **握手行 —— 對這支腳本它是必要條件不是加分**（理由見上方）。
# dashboard 收到它才啟用 fail-closed；收不到就退回結束碼判定，
# 並在畫面上明著標「本次以舊版協定判定」。
Write-Host "::PROTOCOL:: v=2"
Write-Host "======================================"
Write-Host "  MOTRIX ERP - Rollback"
Write-Host "======================================"

# ============================================================
# Step 0: 身分守門 —— 只能在正式機執行
# ============================================================
$scriptRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
if ($scriptRoot -ne $ProdRoot) {
    Fail "偵測到執行路徑為 '$scriptRoot'，不是正式機路徑 '$ProdRoot'。本腳本只允許在正式機執行，中止。" "rollback_not_prod_machine"
}
Info "身分確認：正式機（$ProdRoot）`n"

# ============================================================
# Step 1: 驗證這個時間戳的快照真的存在
# ============================================================
$rollbackDir  = Join-Path $BackendDir "rollback_snapshots\$SnapshotTimestamp"
$dbBackupPath = Join-Path $BackendDir "db_backups\pre_update_$SnapshotTimestamp\motrix_erp.db"
$dbPath       = Join-Path $BackendDir "motrix_erp.db"
$demoDbBackupPath = Join-Path $BackendDir "db_backups\pre_update_$SnapshotTimestamp\motrix_erp_demo.db"
$demoDbPath       = Join-Path $BackendDir "motrix_erp_demo.db"
# 2026-09-28：apply_update 把刪除計畫存在快照裡（apply_plan.json）；它的 added＝那次套用**新增**的程式檔。
# robocopy /E 寫回快照不會刪它們 ⇒ 新增的模組資料夾留著，舊版的載入器照樣載它。
$planPath     = Join-Path $rollbackDir "apply_plan.json"
$planTool     = Join-Path $PSScriptRoot "apply_plan.py"
$baselinePath = Join-Path $BackendDir ".deployed_files.json"

if (-not (Test-Path $rollbackDir)) {
    Fail "找不到程式碼快照：$rollbackDir" "rollback_snapshot_missing"
}
if (-not (Test-Path $dbBackupPath)) {
    Fail "找不到 db 快照：$dbBackupPath" "rollback_db_snapshot_missing"
}
$hasPlan = Test-Path $planPath
if ($hasPlan -and -not (Test-Path $planTool)) {
    Fail "快照裡有 apply_plan.json，但這台機器沒有 $planTool，無法刪掉那次新增的程式檔，未做任何回滾動作。" "rollback_plan_tool_missing"
}
Info "[1/2] 快照驗證通過："
Info "  程式碼快照：$rollbackDir"
Info "  db 快照：$dbBackupPath"
if (Test-Path $demoDbBackupPath) { Info "  demo 庫快照：$demoDbBackupPath" }
if ($hasPlan) {
    $planObj = Get-Content $planPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Info "  那次套用新增的程式檔：$(@($planObj.added).Count) 個（回滾時刪除；清單在 $planPath）"
} else {
    Warn "  快照裡沒有 apply_plan.json（2026-09-28 之前的 apply_update 建的快照）：那次套用新增的程式檔不會被刪除，回滾後請人工核對 backend\modules 與 frontend\pages。"
}

if (-not $Yes) {
    Write-Host ""
    $answer = Read-Host "確認要把正式機回滾到 $SnapshotTimestamp 這個快照嗎？(y/N)"
    if ($answer -ne "y" -and $answer -ne "Y") {
        Fail "使用者取消，未做任何回滾動作。" "rollback_user_cancelled"
    }
}

# ============================================================
# Step 2: 還原（照抄 apply_update.ps1 第392-426行的自動回滾邏輯）
# ============================================================
Info "`n[2/2] 開始回滾..."

# 🔴 **危險值在動作之前設**（與 apply_update.ps1 同一個紀律）：
# 從停服那一刻起，`service=down`、磁碟即將被覆寫。
# ☠️ 之後才設的話，還原到一半失敗會報出一個**比實際安全**的狀態。
$script:ServiceState = "down"
# 🔴 **危險值在動作之前設**。
# ⚠️ 這裡是 `restoring` 不是 `applied_no_restore`：後者的語意含
#    「**沒有還原**」，而這支腳本正在還原 —— 方向相反。
$script:ProdState = "restoring"

# 先停服務再動檔案（含 db）——避免正在跑的伺服器跟覆寫的檔案打架。
# 2026-09-28：連 autostart 迴圈一起停（先前只停聽 port 的行程，迴圈 5 秒後用還原到一半的程式碼把它拉起來）。
$null = Stop-InstallService
Start-Sleep -Seconds 2

# 先刪那次套用新增的程式檔（被那次套用刪掉的舊檔由下面寫回快照還原）。
# --pkg 指安裝目錄：分類要用**現在裝著的** core.upgrade（＝那次套用的新版，也是寫這份計畫的那一版）。
$cleanFailed = $false
if ($hasPlan) {
    $cleanRun = Invoke-Py @($planTool, "cleanup-added", "--root", $ProdRoot, "--pkg", $ProdRoot, "--plan", $planPath)
    Write-Host $cleanRun.Text
    $cleanFailed = ($cleanRun.Exit -ne 0 -or ($cleanRun.Text -notmatch "APPLY_CLEANUP_OK"))
}

# 🔴 還原寫回要檢查結束碼（`RP3`）—— 與 `apply_update.ps1` 的自動回滾同一件事。
# ☠️ 失敗不中止 ⇒ 流進下面的健康檢查 ⇒ 碰巧過了就報「已還原」，
#    **而磁碟上是還原到一半的殘骸。**
robocopy (Join-Path $rollbackDir "backend") $BackendDir /E | Out-Null
if ($LASTEXITCODE -ge 8) { Fail "回滾寫回正式機失敗（backend，exit code $LASTEXITCODE）——正式機現在是還原到一半的狀態，需要人工處理。" "rollback_copy_failed_backend" }
robocopy (Join-Path $rollbackDir "frontend") $FrontendDir /E | Out-Null
if ($LASTEXITCODE -ge 8) { Fail "回滾寫回正式機失敗（frontend，exit code $LASTEXITCODE）——正式機現在是還原到一半的狀態，需要人工處理。" "rollback_copy_failed_frontend" }
foreach ($d in $RootProgramDirs) {
    $snap = Join-Path $rollbackDir $d
    if (-not (Test-Path $snap)) { continue }
    robocopy $snap (Join-Path $ProdRoot $d) /E | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "回滾寫回正式機失敗（$d，exit code $LASTEXITCODE）——正式機現在是還原到一半的狀態，需要人工處理。" "rollback_copy_failed_root_dirs" }
}
# 程式檔清單（.deployed_files.json）要跟著程式回到快照那一版：快照裡有 ⇒ 上面已寫回；
# 快照裡沒有（轉換後第一次套用前的快照）⇒ 刪掉現在這份，否則下一次套用會拿**新版**的清單當舊版算刪除。
if (-not (Test-Path (Join-Path $rollbackDir "backend\.deployed_files.json")) -and (Test-Path $baselinePath)) {
    Remove-Item $baselinePath -Force
    Info "  快照當時沒有程式檔清單 ⇒ 已移除現在的 backend\.deployed_files.json（下一次套用會以「沒有清單」處理）。"
}

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
# demo 庫同一套（2026-09-28）：新版啟動時也對它跑了 init_db。
if (Test-Path $demoDbBackupPath) {
    Copy-Item $demoDbBackupPath $demoDbPath -Force
    Remove-Item "$demoDbPath-wal", "$demoDbPath-shm" -Force -ErrorAction SilentlyContinue
    Ok "  demo 庫已還原：$demoDbBackupPath"
}

# AH-S2：部署紀錄回到快照當時（apply_update 2026-09-28 起把套用前的那份存在快照裡）
$deployedBefore = Join-Path $rollbackDir "deployed_commit.before.json"
if (Test-Path $deployedBefore) {
    Copy-Item $deployedBefore (Join-Path $BackendDir ".deployed_commit.json") -Force
    Ok "  部署紀錄（.deployed_commit.json）已還原為快照當時的版本。"
} else {
    Warn "  快照裡沒有套用前的部署紀錄：backend\.deployed_commit.json 仍是回滾前的版本，prod-status 會顯示錯的 commit，重套同一版要加 -Force。"
}

if ($cleanFailed) {
    Fail "回滾：那次套用新增的程式檔沒有刪乾淨（見上方）——舊程式碼與資料庫已寫回，但新增的檔（可能含新模組資料夾）還在，服務未重新啟動，需要人工處理。清單：$planPath" "rollback_cleanup_failed"
}
Start-InstallService

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
    $script:ProdState = "restored"
    $script:ServiceState = "up"
    Emit-Result "rollback_ok" 0
} else {
    Write-Host "======================================" -ForegroundColor Red
    Write-Host "  回滾動作已執行，但健康檢查仍異常，需要人工介入！" -ForegroundColor Red
    Write-Host "======================================" -ForegroundColor Red
    # 跟 apply_update.ps1 一致：健康檢查失敗可能是服務真的中斷，也可能又是
    # 健康檢查機制本身的偽陰性，直接印出 port 監聽狀態協助判斷。
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
    # ⚠️ 還原**動作**完成了，而正式機**沒有**回到健康 ——
    # 兩件事要分開講：`rolled_back=restored_unhealthy` 說「還原做完了」，
    # `service=down` 說「它現在沒在服務」。
    # ☠️ 合成一句「回滾失敗」會讓人以為快照沒被套用，而去做第二次回滾。
    $script:ProdState = "restored_unhealthy"
    Emit-Result "rollback_failed" 1
    exit 1
}
