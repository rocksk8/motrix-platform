<#
  apply_module_update.ps1 — 在「正式機」執行：套用**單一模組**更新包（B55，docs/platform/MODULE-UPDATE-DELIVERY.md §1.3）

  與 apply_update.ps1（完整包）同一套保護：身分守門、同一把鎖（.apply.lock）、DB 快照、乾跑、只停本安裝、
  健康檢查、失敗自動回滾、::RESULT:: v2 協定＋結果檔。差別：
    - 只換一個模組（module_update.py apply：先備份到 <ROOT>\module_backups\<key>\<stamp>\，再鏡像替換）
    - 乾跑在 %TEMP% 的疊加樹上跑（只複製 classify=program 的檔，DB 用快照副本；module_apply_steps.py overlay）
    - 健檢多一層：logs\module_states.json（重啟後、正在聽 port 的行程寫的）裡該模組 loaded 且版本＝新版
    - 回滾走 module_update.py rollback；備份損壞（雜湊不符）⇒ 停用該模組再重啟（D 審 DB-S5）

  〔D 審 DB-S1＝U-M1②〕共用函式（Test-Ping、Fail／Info／Warn／Ok、Enter/Exit-InstallLock、Write-ResultFile、
  Backup-DatabasesOnline、Invoke-Py、Stop/Start-InstallService）與 server.log 掃描核心**逐字**取自 apply_update.ps1；
  守門題 test_apply_module_update_ps1_2026_09_28.py 比對，任一邊改了另一邊沒改 ⇒ 紅。apply_update.ps1 本身不動。
  Emit-Result 多一行（結果檔補模組欄位），是唯一允許的差異（守門題去掉那一行後比對）。

  用法（由部署儀表板呼叫；已在它的畫面做過明確確認 ⇒ 帶 -Yes）：
    powershell -ExecutionPolicy Bypass -File apply_module_update.ps1 -PackagePath <包目錄> -Yes
    powershell -ExecutionPolicy Bypass -File apply_module_update.ps1 -PackagePath <包目錄> -Yes -SkipAutoRollback
  沒有演練繞過分支（§7：演練工具把本檔複製到演練目錄、只改寫 $ProdRoot／$Port 兩行）。
#>

[CmdletBinding()]
param(
    [string]$PackagePath,
    [switch]$Yes,
    [switch]$SkipAutoRollback
)

$ErrorActionPreference = "Stop"

# 本腳本的版本（apply_module_update.version.json 登記它與內容雜湊；包的 min_apply_module_script 比的是它）。
$ApplyModuleScriptVersion = "2026-09-29a"

# >>> OWN-ONLY:prod-root
# 去識別化（sale 包）：下面這段是本公司安裝的寫死路徑，sale 包由 product/sale_prune.json 換成「由腳本位置推得＋守門」；見 docs/platform/PRODROOT-GUARD-DESIGN.md
$ProdRoot = "C:\Users\Motrix\Desktop\V9.0"
$Port = 666
# <<< OWN-ONLY:prod-root
$AutostartTaskName = "MOTRIX ERP Server Autostart"
$BackendDir = Join-Path $ProdRoot "backend"
$FrontendDir = Join-Path $ProdRoot "frontend"
$ModuleUpdateTool = Join-Path $ProdRoot "tools\platform\module_update.py"
$StepsTool = Join-Path $BackendDir "tools\module_apply_steps.py"
$TempPrefix = "motrix-modapply-"
# module_update.py --json 的 code（MODULE-UPDATE-DELIVERY §10 表）→ 本腳本的處置。
# §10 的每一個 code 恰好屬於下面四組之一（守門題從 §10 表抓 code 比對，缺／多／重複都紅；稽核 D S5A-M1）。
#   預檢：沒列到的一律 module_preflight_failed（F4）
$PreflightStatus = @{ "pkg_invalid" = "package_invalid"; "already_installed" = "duplicate_version"; "bad_args" = "bad_args" }
#   ① apply 在動檔之前就拒絕（預檢那一類）⇒ 磁碟沒變，只要把服務拉回來
$ApplyUntouchedCodes = @("pkg_invalid", "no_install_lock", "no_base", "no_deployed_marker", "base_mismatch",
                         "core_incompatible", "license_unavailable", "unlicensed", "already_installed", "not_higher",
                         "bad_args", "interrupted_apply_pending", "refused")
#   ② apply 動過檔才失敗（F9）：apply_failed_restored 已由 module_update 還原；其餘用本次 stamp 回滾
$ApplyInFlightCodes = @("apply_failed_restored", "apply_failed_half", "unexpected")
#   ③ 回滾失敗而磁碟上「模組可能是半新半舊或還原不了」⇒ F13：停用該模組再重啟
$RestoreFailedCodes = @("backup_corrupt", "no_backup", "backup_not_found", "restore_mismatch")
#   ④ 回滾「拒絕、一個檔都沒動」（套用之後又有別的寫入）⇒ 磁碟上仍是這次的新模組 ⇒ 同 F13：停用該模組再重啟，
#      不可以停著服務不管（全站停擺）；status module_restore_failed、結果檔 rollback_code 帶 code
$RollbackRefusedCodes = @("module_changed", "state_changed", "base_changed", "interrupted_not_latest")

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

# ::RESULT:: v2（同 apply_update.ps1 的定義：rolled_back＝磁碟上是什麼；service＝觀察到的事實）
$script:ProdState = "not_applied"
$script:ServiceState = "unknown"
$script:LockHeld = $false
$script:RunStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$script:StartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$script:ResultScript = "apply_module_update"
$script:ResultScriptVersion = $ApplyModuleScriptVersion
$script:ResultPackage = $PackagePath
$script:ResultCommit = $null
# 模組欄位（結果檔多四欄：kind／module_key／from_version／to_version）
$script:ModuleKey = $null
$script:FromVersion = $null
$script:ToVersion = $null
$script:ModStamp = $null
$script:RollbackCode = $null

function Emit-Result($status, $code) {
    # 一行、無前後空白、大小寫固定、欄位順序固定（B.md §九 定版）。
    Write-Host ("::RESULT:: v=2 status=$status rolled_back=$($script:ProdState)" +
                " service=$($script:ServiceState) exit=$code")
    Write-ResultFile $status $code
    Add-ModuleResultFields
    Exit-InstallLock
}

function Fail($msg, $status = "unknown") {
    Write-Host "`n[FAIL] $msg" -ForegroundColor Red
    Emit-Result $status 1
    exit 1
}
function Info($msg)  { Write-Host $msg }
function Warn($msg)  { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Ok($msg)    { Write-Host "[OK] $msg" -ForegroundColor Green }

# ── 以下函式與 apply_update.ps1 **逐字相同**（守門題比對）──
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
# ── 逐字相同的區段到此為止（Invoke-Py、Stop/Start-InstallService 另在下方，同樣逐字）──

# 結果檔補模組欄位：Write-ResultFile 逐字共用（12 欄），這裡讀回來加四欄再原子改寫。失敗只警告（::RESULT:: 已印）。
function Add-ModuleResultFields {
    try {
        $resPath = Join-Path (Join-Path $BackendDir "logs") ("{0}_{1}.result.json" -f $script:ResultScript, $script:RunStamp)
        if (-not (Test-Path $resPath)) { return }
        $res = Get-Content $resPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $res | Add-Member -NotePropertyName kind -NotePropertyValue "module" -Force
        $res | Add-Member -NotePropertyName module_key -NotePropertyValue $script:ModuleKey -Force
        $res | Add-Member -NotePropertyName from_version -NotePropertyValue $script:FromVersion -Force
        $res | Add-Member -NotePropertyName to_version -NotePropertyValue $script:ToVersion -Force
        if ($script:RollbackCode) { $res | Add-Member -NotePropertyName rollback_code -NotePropertyValue $script:RollbackCode -Force }
        $tmpPath = "$resPath.tmp"
        [System.IO.File]::WriteAllText($tmpPath, ($res | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))
        Move-Item -Path $tmpPath -Destination $resPath -Force
    } catch {
        Write-Host "[WARN] 結果檔補模組欄位失敗：$($_.Exception.Message)"
    }
}

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

# ── 本公司資料設定閘門（COMPANY-SETUP-GATE §6.3；E4）——與 apply_update.ps1 逐字相同 ──
# 模組包不帶 backend\tools ⇒ 兩道都用**安裝目錄**那份 company_setup_cli.py（模組包不改 L1，判定邏輯就是正在跑的那一版）。
function Invoke-CompanySetupCli([string]$Cli, [string[]]$CliArgs, [int]$TimeoutSec = 60) {
    $res = @{ Allowed = $false; Reason = "tool_failed"; Text = ""; Exit = -1 }
    if (-not (Test-Path $Cli)) { $res.Reason = "tool_missing"; return $res }
    $outFile = Join-Path $env:TEMP ("motrix_company_setup_" + [guid]::NewGuid().ToString("N") + ".out")
    $errFile = "$outFile.err"
    try {
        $argLine = (@($Cli) + $CliArgs | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join " "
        $proc = Start-Process -FilePath "python" -ArgumentList $argLine -NoNewWindow -PassThru `
                    -RedirectStandardOutput $outFile -RedirectStandardError $errFile
        $null = $proc.Handle   # 先取 Handle，行程結束後 ExitCode 才讀得到（PS 5.1）
        if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
            try { $proc.Kill() } catch { }
            $res.Reason = "timeout"
            return $res
        }
        $res.Exit = $proc.ExitCode
        $text = ""
        if (Test-Path $outFile) { $text = (Get-Content $outFile -Raw -Encoding UTF8) }
        if (Test-Path $errFile) { $text += (Get-Content $errFile -Raw -Encoding UTF8) }
        $res.Text = "$text"
        $line = @(("$text" -split "\r?\n") | Where-Object { $_.Trim().StartsWith("{") }) | Select-Object -Last 1
        if (-not $line) { $res.Reason = "bad_output"; return $res }
        $obj = $line | ConvertFrom-Json
        $res.Reason = [string]$obj.reason
        $res.Allowed = ($res.Exit -eq 0 -and $obj.allowed -eq $true -and $null -ne $obj.configured)
        return $res
    } catch {
        $res.Reason = "tool_crashed"
        $res.Text = "$_"
        return $res
    } finally {
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
}

# ── 請款單匯款欄位註記（D E4S3-S1：只報不擋）──────────────────────────────
# 讀 company_setup_cli 那一行 JSON 的 payment_bank_missing：缺 ⇒ [WARN]＋`::NOTE:: company_bank_missing=<欄位>`
# （升級後請款單 PDF 會 428，要先請使用者在設定頁補齊）；齊全 ⇒ `::NOTE:: company_bank=ok`；讀不到 ⇒ `company_bank=unknown`。
# 不改 ::RESULT::（欄位順序與值域固定）；本函式不丟例外、不影響升級。
function Write-CompanyBankNote([string]$CliText) {
    $note = "unknown"
    try {
        $line = @(("$CliText" -split "\r?\n") | Where-Object { $_.Trim().StartsWith("{") }) | Select-Object -Last 1
        if ($line) {
            $obj = $line | ConvertFrom-Json
            $miss = $obj.payment_bank_missing
            if ($null -ne $miss) {
                $items = @($miss | ForEach-Object { [string]$_ })
                if ($items.Count -gt 0) { $note = "missing" } else { $note = "ok" }
            }
        }
    } catch { $note = "unknown" }
    if ($note -eq "missing") {
        Write-Host ("[WARN]   請款單匯款欄位未齊全（" + ($items -join "、") + "）：升級後請款單 PDF 會被擋（428 company_bank_required），請先在公司資料設定補齊") -ForegroundColor Yellow
        Write-Host ("::NOTE:: company_bank_missing=" + ($items -join ","))
    } else {
        Write-Host ("::NOTE:: company_bank=" + $note)
    }
    return $note
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

# module_update.py 子命令（--json）：回 @{ Ok; Data; Text }。
#   Data＝最後一行 `MODULE_UPDATE_RESULT {json}` 解出的物件；沒有那一行 ⇒ Ok=$false、Data=$null（ps1 視為失敗）。
function Invoke-ModuleUpdate([string[]]$ToolArgs) {
    $r = Invoke-Py (@($ModuleUpdateTool) + $ToolArgs + @("--json"))
    $data = $null
    foreach ($line in ($r.Text -split "`r?`n")) {
        if ($line -match '^MODULE_UPDATE_RESULT (\{.*\})\s*$') {
            try { $data = $Matches[1] | ConvertFrom-Json } catch { $data = $null }
        }
    }
    $ok = [bool]($data -and $data.ok -and $r.Exit -eq 0)
    return @{ Ok = $ok; Data = $data; Text = $r.Text }
}

# 正在聽 $Port 的行程（載入狀態檔的 pid 必須是其中之一）。
function Get-ListenerPids {
    $pids = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
    return ($pids -join ",")
}

# 等載入狀態檔（DB-S4）：重啟之後、正在聽 port 的行程寫的，模組 $state 且（給了版本時）版本相符。回 @{ Ok; Reason }。
function Wait-ModuleState([string]$key, [string]$version, [string]$state, [string]$sinceIso) {
    $statesFile = Join-Path $BackendDir "logs\module_states.json"
    $why = "（沒有檢查）"
    for ($i = 0; $i -lt 20; $i++) {
        $pyArgs = @($StepsTool, "states", "--file", $statesFile, "--key", $key, "--since", $sinceIso,
                    "--pids", (Get-ListenerPids), "--state", $state)
        if ($version) { $pyArgs += @("--version", $version) }
        $r = Invoke-Py $pyArgs
        if ($r.Exit -eq 0 -and $r.Text -match "STATES_OK") { return @{ Ok = $true; Reason = "" } }
        $why = ($r.Text -split "`r?`n" | Where-Object { $_ -match "STATES_FAIL" } | Select-Object -Last 1)
        if (-not $why) { $why = $r.Text.Trim() }
        Start-Sleep -Seconds 2
    }
    return @{ Ok = $false; Reason = $why }
}

# server.log 的錯誤行（最後一次成功啟動之後）＋模組載入字串（本次啟動那一段；第二道）。回 @{ Errors; Loaded; NotLoaded; Boot }。
#   掃描核心（良性 ConnectionResetError 區塊過濾）與 apply_update.ps1 Step 5 逐字相同（守門題比對）。
#   「已載入／未載入」在 import 時印、早於 Uvicorn running on ⇒ 範圍用 Get-StartupRange（與 apply_update 逐字共用）；
#   找不到本次啟動的起點 ⇒ Boot＝$false（驗不到，不退回整段 tail：回滾後檢查舊版本時，上一個行程印的同一行會假綠）。
#   ⚠ 以 UTF-8 讀（2026-09-28 B 演練：PS 5.1 預設 ANSI 讀 ⇒「已載入」永遠比對不到 ⇒ 誤判不健康而自動回滾）。
function Get-LogCheck([string]$key, [string]$version) {
    $logErrors = @()
    $loadedSeen = $false
    $notLoadedSeen = $false
    $logPath = Join-Path $BackendDir "logs\server.log"
    if (-not (Test-Path $logPath)) { return @{ Errors = @(); Loaded = $false; NotLoaded = $false; Boot = $false } }
    $tail = Get-Content $logPath -Tail 200 -Encoding UTF8
    $bootRange = Get-StartupRange $tail
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
    foreach ($ln in @($bootRange)) {
        if ($ln -like "*模組 $key $version 已載入*") { $loadedSeen = $true }
        if ($ln -like "*模組 $key 未載入*") { $notLoadedSeen = $true }
    }
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
    return @{ Errors = @($logErrors); Loaded = $loadedSeen; NotLoaded = $notLoadedSeen; Boot = [bool]$bootRange }
}

# 健檢：ping 20 次 → 載入狀態檔 → log。回 @{ Healthy; ModuleOk; Reason }。
function Test-ModuleHealth([string]$key, [string]$version, [string]$sinceIso) {
    $healthy = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 2
        $thisTry = Test-Ping -Url $PingUrl -TimeoutSec 5
        Info "    健檢第 $($i + 1)/20 次：$(if ($thisTry) { '成功' } else { '無回應' })"
        if ($thisTry) { $healthy = $true; break }
    }
    if (-not $healthy) { return @{ Healthy = $false; ModuleOk = $false; Reason = "/api/ping 20 次都沒有回應" } }
    $st = Wait-ModuleState $key $version "loaded" $sinceIso
    if (-not $st.Ok) { return @{ Healthy = $true; ModuleOk = $false; Reason = "載入狀態檔：$($st.Reason)" } }
    $lc = Get-LogCheck $key $version
    if ($lc.Errors.Count -gt 0) {
        foreach ($e in $lc.Errors) { Info "    $($e.Line)" }
        return @{ Healthy = $true; ModuleOk = $false; Reason = "server.log 有 $($lc.Errors.Count) 筆錯誤（見上方）" }
    }
    if (-not $lc.Boot) {
        return @{ Healthy = $true; ModuleOk = $false; Reason = "server.log 找不到本次啟動的起點（MOTRIX ERP starting … Uvicorn running on）⇒ 驗不到模組 $key $version 有沒有載入" }
    }
    if ($lc.NotLoaded -or -not $lc.Loaded) {
        return @{ Healthy = $true; ModuleOk = $false; Reason = "server.log 沒有「模組 $key $version 已載入」（或有「未載入」）" }
    }
    return @{ Healthy = $true; ModuleOk = $true; Reason = "" }
}

# DB 快照寫回（主庫＋demo 庫）：覆寫前先另存 pre_rollback（D 稽核 DM1，同 apply_update）。回 $true＝已寫回。
function Restore-Databases([string]$snapDir) {
    $saved = Backup-DatabasesOnline (Join-Path $BackendDir "db_backups\pre_rollback_$($script:RunStamp)")
    if (-not $saved) {
        Warn "  回滾前的資料庫另存失敗 ⇒ 不覆寫資料庫（維持新版 schema；模組 migration 只新增，舊程式讀得了），需要人工確認。"
        return $false
    }
    foreach ($n in @("motrix_erp.db", "motrix_erp_demo.db")) {
        $snap = Join-Path $snapDir $n
        $dst = Join-Path $BackendDir $n
        if (Test-Path $snap) {
            Copy-Item $snap $dst -Force
            Remove-Item "$dst-wal", "$dst-shm" -Force -ErrorAction SilentlyContinue
            Ok "  $n 已還原至套用前快照。"
        }
    }
    return $true
}

# 模組回滾（停服之後呼叫）。回 @{ Ok; NeedsDisable; Code; Text }：NeedsDisable＝回滾沒把模組還原（③④）⇒ F13。
function Invoke-ModuleRollback {
    $rbArgs = @("rollback", "--root", $ProdRoot, "--key", $script:ModuleKey)
    if ($script:ModStamp) { $rbArgs += @("--backup", $script:ModStamp) }
    $rb = Invoke-ModuleUpdate $rbArgs
    Write-Host $rb.Text
    $code = if ($rb.Data) { [string]$rb.Data.code } else { "" }
    if (-not $rb.Ok) { $script:RollbackCode = $code }
    $needsDisable = [bool]((-not $rb.Ok) -and (($RestoreFailedCodes + $RollbackRefusedCodes) -contains $code))
    return @{ Ok = $rb.Ok; NeedsDisable = $needsDisable; Code = $code; Text = $rb.Text }
}

# F13（D 審 DB-S5、S5A-M1）：回滾沒把模組還原（備份壞／不在／還原不一致，或回滾拒絕、一檔不動）⇒
#   把該模組寫進停用清單再重啟、確認它是 disabled；停用寫入失敗 ⇒ 不重啟。
function Fail-DisableModule([string]$code) {
    $script:ProdState = "applied_no_restore"
    $why = if ($RollbackRefusedCodes -contains $code) { "回滾被拒絕（$code：套用之後又有別的寫入，一個檔都沒動）" } else { "回滾沒有成功（$code：備份損壞、不在或還原後不一致）" }
    $d = Invoke-Py @($StepsTool, "disable", "--key", $script:ModuleKey)
    Write-Host $d.Text
    if ($d.Exit -ne 0 -or $d.Text -notmatch "DISABLE_OK") {
        Fail "模組 $($script:ModuleKey) $why，而且寫入停用清單失敗 ⇒ 服務未重新啟動（不健康的模組不可以載入），需要人工處理。" "module_restore_failed"
    }
    $restartAt = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    Start-InstallService
    $st = Wait-ModuleState $script:ModuleKey $null "disabled" $restartAt
    if ($st.Ok) { $script:ServiceState = "up" }
    Fail "模組 $($script:ModuleKey) $why ⇒ 已把它停用並重新啟動（其他模組照常）$(if ($st.Ok) { '' } else { '，但沒有確認到它是停用狀態：' + $st.Reason })。需要開發機人工處理後，到「模組管理」重新啟用。" "module_restore_failed"
}

# 未預期的例外：印結果行、寫結果檔、放鎖（同 apply_update AH-S11）；我們停了服務且磁碟不是換到一半 ⇒ 拉回來。
trap {
    Write-Host "`n[FAIL] 未預期的錯誤：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host ($_.ScriptStackTrace | Out-String)
    if ($script:ServiceState -eq "down" -and @("not_applied", "applied") -contains $script:ProdState) {
        try { Start-InstallService } catch { Write-Host "[WARN] 重新啟動服務失敗：$($_.Exception.Message)" }
    }
    Emit-Result "unhandled_exception" 1
    exit 1
}

Write-Host "::PROTOCOL:: v=2"
Write-Host "======================================"
Write-Host "  MOTRIX ERP - Apply Module Update"
Write-Host "======================================"

# ── Step 0：身分守門 ─────────────────────────────────────────────
# >>> OWN-ONLY:prod-guard
$scriptRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
if ($scriptRoot -ne $ProdRoot) {
    Fail "偵測到執行路徑為 '$scriptRoot'，不是正式機路徑 '$ProdRoot'。本腳本只允許在正式機執行，中止。" "not_prod_machine"
}
Info "身分確認：正式機（$ProdRoot）`n"
# <<< OWN-ONLY:prod-guard

# ── Step 1：參數與包 ─────────────────────────────────────────────
if (-not $PackagePath) { Fail "-PackagePath 為必填參數。" "bad_args" }
if (-not (Test-Path $PackagePath)) { Fail "找不到更新包路徑：$PackagePath" "package_missing" }
$pkgLockPath = Join-Path $PackagePath "module-update.lock.json"
if (-not (Test-Path $pkgLockPath)) { Fail "更新包內找不到 module-update.lock.json（$PackagePath），不是單一模組更新包。" "package_invalid" }
try { $pkgLock = Get-Content $pkgLockPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $pkgLock = $null }
if (-not $pkgLock -or $pkgLock.kind -ne "module_update") { Fail "module-update.lock.json 的 kind 不是 module_update（$PackagePath）。" "package_invalid" }
$script:ResultCommit = $pkgLock.built_from

# ── Step 2：鎖（與 apply_update／rollback_update 同一把）──────────────
$lockState = Enter-InstallLock "apply_module_update" $PackagePath
if ($lockState -eq "locked") { Fail "另一個套用或回滾正在進行（見上方鎖檔內容），這次不動任何東西。" "apply_locked" }
if ($lockState -eq "stale") { Fail "有殘留的鎖檔（持有者已不在）：確認沒有套用在跑之後，手動刪除 $BackendDir\.apply.lock 再重試。" "apply_locked_stale" }

# 上一次中斷留下的疊加樹（只清本腳本的前綴；此刻我們持有鎖 ⇒ 沒有別的套用在用它們）
Get-ChildItem -Path $env:TEMP -Directory -Filter "$TempPrefix*" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }

# ── Step 3：預檢（只讀）──────────────────────────────────────────
Info "[1/7] 預檢..."
$pf = Invoke-ModuleUpdate @("preflight", "--root", $ProdRoot, "--pkg", $PackagePath, "--require-base")
Write-Host $pf.Text
if (-not $pf.Ok) {
    $why = if ($pf.Data -and $pf.Data.error) { $pf.Data.error } else { "預檢沒有回結果（見上方輸出）" }
    $code = if ($pf.Data) { $pf.Data.code } else { $null }
    $st = if ($PreflightStatus.ContainsKey([string]$code)) { $PreflightStatus[[string]$code] } else { "module_preflight_failed" }
    Fail "預檢未通過（$code）：$why" $st
}
$script:ModuleKey = $pf.Data.key
$script:FromVersion = $pf.Data.from_version
$script:ToVersion = $pf.Data.to_version
Ok "  可以套用 $($script:ModuleKey)：$(if ($script:FromVersion) { $script:FromVersion } else { '（原本沒有）' }) → $($script:ToVersion)"

# 本公司資料設定預檢（COMPANY-SETUP-GATE §6.3-1，同 apply_update；停服之前）：判定「未設定」或判定不了 ⇒ 不動任何東西
$gateCli = Join-Path $BackendDir "tools\company_setup_cli.py"
$prodDbForGate = Join-Path $BackendDir "motrix_erp.db"
if (Test-Path $prodDbForGate) {
    Info "  本公司資料設定預檢..."
    $gateId = Invoke-CompanySetupCli $gateCli @("ensure-install-id", "--root", $ProdRoot)
    if ($gateId.Exit -ne 0) {
        Write-Host $gateId.Text
        Fail "本公司資料設定預檢無法建立安裝識別檔（$($gateId.Reason)），中止（正式機尚未被觸碰）。" "refused_company_setup"
    }
    $gatePre = Invoke-CompanySetupCli $gateCli @("preflight", "--db", $prodDbForGate, "--root", $ProdRoot)
    Write-Host $gatePre.Text
    if (-not $gatePre.Allowed) {
        Fail "本公司資料會是「未設定」或無法判定（原因：$($gatePre.Reason)），中止（正式機尚未被觸碰）；處置見 COMPANY-SETUP-GATE §6.2／§6.3。" "refused_company_setup"
    }
    Ok "  本公司資料設定預檢通過（$($gatePre.Reason)）。"
    $null = Write-CompanyBankNote $gatePre.Text
} else {
    Warn "  找不到正式庫 motrix_erp.db，略過本公司資料設定預檢。"
}

if (-not $Yes) {
    $ans = Read-Host "確定套用模組 $($script:ModuleKey) $($script:ToVersion)？(y/N)"
    if ($ans -ne "y") { Fail "使用者取消。" "user_cancelled" }
}

# ── Step 4：DB 快照 ──────────────────────────────────────────────
Info "[2/7] 資料庫快照..."
$dbSnapDir = Join-Path $BackendDir ("db_backups\pre_module_{0}_{1}" -f $script:ModuleKey, $script:RunStamp)
if (-not (Backup-DatabasesOnline $dbSnapDir)) { Fail "資料庫快照失敗，不動任何東西。" "backup_failed" }

# ── Step 5：乾跑（疊加樹：migration＋模組載入）────────────────────────
Info "[3/7] 乾跑（%TEMP% 疊加樹，只含程式檔；DB 用快照副本）..."
$ovDir = Join-Path $env:TEMP ("{0}{1}" -f $TempPrefix, $script:RunStamp)
$ovDbDir = "$ovDir-db"
$dry = $null
try {
    $ov = Invoke-Py @($StepsTool, "overlay", "--install", $ProdRoot, "--pkg", $PackagePath, "--key", $script:ModuleKey, "--dest", $ovDir)
    Write-Host $ov.Text
    if ($ov.Exit -ne 0 -or $ov.Text -notmatch "OVERLAY_OK") { Fail "建立乾跑疊加樹失敗（見上方）。" "migration_dryrun_failed" }
    New-Item -ItemType Directory -Force -Path $ovDbDir | Out-Null
    $dbArgs = @()
    foreach ($n in @("motrix_erp.db", "motrix_erp_demo.db")) {
        $snap = Join-Path $dbSnapDir $n
        if (Test-Path $snap) { Copy-Item $snap (Join-Path $ovDbDir $n) -Force; $dbArgs += @("--db", (Join-Path $ovDbDir $n)) }
    }
    # 乾跑工具＝疊加樹裡那一份（安裝目錄那份的複本；它載入的是它所在的 backend＝疊加樹）
    $mlsArgs = @((Join-Path $ovDir "backend\tools\migrate_like_startup.py")) + $dbArgs +
               @("--expect-module", "$($script:ModuleKey)=$($script:ToVersion)")
    $lic = Join-Path $BackendDir "license.key"
    if (Test-Path $lic) { $mlsArgs += @("--license", $lic) }
    Push-Location (Join-Path $ovDir "backend")
    try { $dry = Invoke-Py $mlsArgs } finally { Pop-Location }
    Write-Host $dry.Text
} finally {
    Remove-Item $ovDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $ovDbDir -Recurse -Force -ErrorAction SilentlyContinue
}
if ($dry.Text -match "MODULE_LOAD_FAIL") { Fail "乾跑：新版模組在疊加樹上載入不起來（見上方），不動任何東西。" "module_load_dryrun_failed" }
if ($dry.Exit -ne 0 -or $dry.Text -notmatch "MIGRATE_LIKE_STARTUP_OK" -or $dry.Text -notmatch "MODULE_LOAD_OK") {
    Fail "乾跑：migration 失敗或有未完成的模組 migration（見上方），不動任何東西。" "migration_dryrun_failed"
}
Ok "  乾跑通過：migration 完成、$($script:ModuleKey) $($script:ToVersion) 載得起來。"

# ── Step 6：停服（只停本安裝）──────────────────────────────────────
Info "[4/7] 停止服務..."
Stop-InstallService | Out-Null
$script:ServiceState = "down"

# ── Step 7：換檔 ────────────────────────────────────────────────
Info "[5/7] 替換模組..."
$script:ModStamp = $script:RunStamp
$script:ProdState = "applied_no_restore"
$ap = Invoke-ModuleUpdate @("apply", "--root", $ProdRoot, "--pkg", $PackagePath, "--require-base", "--stamp", $script:ModStamp)
Write-Host $ap.Text
if (-not $ap.Ok) {
    $apCode = if ($ap.Data) { [string]$ap.Data.code } else { "" }
    if ($ApplyUntouchedCodes -contains $apCode) {
        # 動檔之前就拒絕（§10：預檢那一類／stamp 不對）⇒ 磁碟沒變，把服務拉回來
        $script:ProdState = "not_applied"
        Start-InstallService
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Seconds 2
            if (Test-Ping -Url $PingUrl -TimeoutSec 5) { $script:ServiceState = "up"; break }
        }
        $st = if ($PreflightStatus.ContainsKey($apCode)) { $PreflightStatus[$apCode] } else { "module_preflight_failed" }
        Fail "替換前被拒絕（$apCode）：$(if ($ap.Data) { $ap.Data.error })；沒有動任何檔，服務已重新啟動。" $st
    }
    # F9：換檔中途失敗。apply_failed_restored ⇒ module_update 已用本次備份還原；
    #     apply_failed_half／unexpected／沒有結果行 ⇒ 用本次 stamp 回滾（備份以 in_progress 留著）
    if ($apCode -ne "apply_failed_restored") {
        $rb = Invoke-ModuleRollback
        if ($rb.NeedsDisable) { Fail-DisableModule $rb.Code }
        if (-not $rb.Ok) {
            Fail "替換模組中途失敗，回滾也沒有成功（$($rb.Code)，見上方）——服務未重新啟動，需要人工處理。" "module_copy_failed"
        }
    }
    $script:ProdState = "restored_unhealthy"
    Start-InstallService
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 2
        if (Test-Ping -Url $PingUrl -TimeoutSec 5) { $script:ServiceState = "up"; $script:ProdState = "restored"; break }
    }
    Fail "替換模組中途失敗，已回到套用前的模組（資料庫未動）$(if ($script:ServiceState -eq 'up') { '，服務已恢復。' } else { '，但服務健康檢查沒有通過，需要人工確認。' })" "module_copy_failed"
}
if ($ap.Data.stamp) { $script:ModStamp = $ap.Data.stamp }
$script:ProdState = "applied"

# ── Step 8／9：重啟＋健檢 ─────────────────────────────────────────
Info "[6/7] 重新啟動並健康檢查..."
$restartAt = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
Start-InstallService
$hc = Test-ModuleHealth $script:ModuleKey $script:ToVersion $restartAt
# 本公司資料設定（COMPANY-SETUP-GATE §6.3-2，同 apply_update）：與 ping 失敗同級 ⇒ 自動回滾；-SkipAutoRollback 不適用
$companyGateFailed = $false
if ($hc.Healthy -and $hc.ModuleOk -and (Test-Path $prodDbForGate)) {
    $gatePost = Invoke-CompanySetupCli $gateCli @("status", "--db", $prodDbForGate, "--root", $ProdRoot)
    Write-Host $gatePost.Text
    if (-not $gatePost.Allowed) {
        $companyGateFailed = $true
        $hc = @{ Healthy = $true; ModuleOk = $false; Reason = "本公司資料設定檢查未通過（$($gatePost.Reason)）" }
    }
}
if ($hc.Healthy -and $hc.ModuleOk) {
    $script:ServiceState = "up"
    Ok "  服務正常、$($script:ModuleKey) $($script:ToVersion) 已載入。"
    Emit-Result "success" 0
    exit 0
}
Warn "  健康檢查沒過：$($hc.Reason)"
if ($hc.Healthy) { $script:ServiceState = "up" }
if ($SkipAutoRollback -and -not $companyGateFailed) {
    Warn "  已依 -SkipAutoRollback 略過自動回滾——新版模組留在原地。要回到套用前：module_update.py rollback --root `"$ProdRoot`" --key $($script:ModuleKey) --backup $($script:ModStamp)"
    # 同 apply_update P0-00：結束碼 0，而這是一次失敗 ⇒ 由 status 說出來
    Emit-Result "unhealthy_not_rolled_back" 0
    exit 0
}

# ── 自動回滾（§2 R 系列）─────────────────────────────────────────
Info "[7/7] 自動回滾..."
$failStatus = if ($companyGateFailed) { "company_setup_rolled_back" } elseif ($hc.Healthy) { "module_unhealthy_rolled_back" } else { "unhealthy_rolled_back" }
Stop-InstallService | Out-Null
$script:ServiceState = "down"
$rb = Invoke-ModuleRollback
if ($rb.NeedsDisable) { Fail-DisableModule $rb.Code }
if (-not $rb.Ok) {
    Fail "健康檢查沒過（$($hc.Reason)），而模組回滾失敗（見上方）——服務未重新啟動，需要人工處理。" $failStatus
}
$script:ProdState = "restoring"
$dbRestored = Restore-Databases $dbSnapDir
$restartAt = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
Start-InstallService
$back = Test-ModuleHealth $script:ModuleKey $script:FromVersion $restartAt
if ($back.Healthy) { $script:ServiceState = "up" }
if ($script:FromVersion) {
    $script:ProdState = if ($back.Healthy -and $back.ModuleOk) { "restored" } else { "restored_unhealthy" }
} else {
    # 原本沒有這個模組 ⇒ 回滾後它不在，只看 ping
    $script:ProdState = if ($back.Healthy) { "restored" } else { "restored_unhealthy" }
}
if (-not $dbRestored) { $script:ProdState = "restored_unhealthy" }
Fail "健康檢查沒過（$($hc.Reason)），已自動回滾到套用前的模組$(if ($dbRestored) { '與資料庫' } else { '（資料庫未覆寫，見上方）' })；回滾後：$(if ($script:ProdState -eq 'restored') { '正常' } else { '仍異常，需要人工確認：' + $back.Reason })。" $failStatus
