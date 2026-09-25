<#
  _dashboard_remote.ps1 — 在「開發機」執行（由 deploy_dashboard.py 呼叫，也可以手動執行）

  用途：deploy_dashboard.py（2026-09-08 新增的本機部署儀表板）透過 WinRM 對
  正式機做「推送部署包＋套用」／「觸發回滾」／「列出可回滾的快照時間戳」
  三種動作的實際執行者。寫死在這個檔案裡（不是 Python 動態組字串），避免
  字串組裝注入風險，方便獨立檢視/測試。

  密碼從 STDIN 讀（Read-Host -AsSecureString 只讀一行），不會出現在任何
  指令列參數、Process 清單、或這個腳本自己的輸出/log 裡。

  用法（一般不會手動打，由 deploy_dashboard.py 組好呼叫）：
    echo <密碼> | powershell -File _dashboard_remote.ps1 -Action deploy -Username Motrix -PackagePath <本機部署包絕對路徑>
    echo <密碼> | powershell -File _dashboard_remote.ps1 -Action rollback -Username Motrix -SnapshotTimestamp 20260908_030839
    echo <密碼> | powershell -File _dashboard_remote.ps1 -Action list-snapshots -Username Motrix
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("deploy", "rollback", "list-snapshots", "tail-log", "check-only", "health", "upgrade")]
    [string]$Action,

    # CORE-SPEC §9e D4：V9 → 新版升級精靈的單一步驟（固定清單，不接受任意指令）
    [ValidateSet("", "push", "stop-services", "preflight", "backup", "convert", "verify", "start-services", "rollback-code", "rollback-full")]
    [string]$Step = "",
    # 備份目錄的時間戳記（只准字母數字底線連字號，由儀表板產生並驗證）
    [string]$BackupStamp = "",

    [Parameter(Mandatory = $true)]
    [string]$Username,

    [string]$PackagePath,
    [string]$SnapshotTimestamp,
    [int]$Lines = 300,
    # 2026-09-08 新增：字串而不是 [switch]——這支腳本的所有參數都是透過
    # deploy_dashboard.py 的 _ps_cmd()（固定用 -Name 'value' 空白分隔形式組
    # 指令字串）傳進來，[switch] 參數用這種傳法容易產生繫結歧義（該用
    # -Name:$true 而非 -Name 'value'）。用字串 "true"/"false" 換取呼叫端
    # 一致性，內部再轉成布林。
    [string]$SkipAutoRollback = "false"
)

$ErrorActionPreference = "Stop"
$ProdIp = "172.16.10.177"
$ProdRoot = "C:\Users\Motrix\Desktop\V9.0"

function Fail($msg) {
    Write-Host "`n[FAIL] $msg" -ForegroundColor Red
    exit 1
}
function Ok($msg) {
    Write-Host "[OK] $msg" -ForegroundColor Green
}

if ($Action -eq "deploy" -and -not $PackagePath) {
    Fail "-Action deploy 需要 -PackagePath。"
}
if ($Action -eq "rollback" -and -not $SnapshotTimestamp) {
    Fail "-Action rollback 需要 -SnapshotTimestamp。"
}
if ($Action -eq "upgrade") {
    if (-not $Step) { Fail "-Action upgrade 需要 -Step。" }
    if (-not $PackagePath) { Fail "-Action upgrade 需要 -PackagePath（新版部署包）。" }
    if ($BackupStamp -notmatch '^[A-Za-z0-9_-]+$') { Fail "-BackupStamp 不合法：只准字母、數字、底線、連字號。" }
}
# 升級用的正式機位置：全部在安裝目錄以外（upgrade.py 會拒絕放在安裝目錄內的來源與備份）
$ProdDesktop = "C:\Users\Motrix\Desktop"
$UpgradeBackupRoot = Join-Path $ProdDesktop "MOTRIX-UPGRADE-BACKUP"
#: 排程工作名稱（docs/quick §1.1）；停服務時三個都停，恢復時依序開回
$ProdTasks = @("MOTRIX ERP Server Autostart", "MOTRIX ERP Daily Backup", "MOTRIX ERP Heartbeat")

# 2026-09-08 修復：`Read-Host -AsSecureString` 依賴主控台的遮罩輸入機制，
# stdin 被 deploy_dashboard.py 用管線重新導向（不是真的互動主控台）時會
# 直接卡死、永遠讀不到內容（實測：換成一般 Read-Host 也能證實這點——它確實
# 讀得到管線輸入，但反而會把讀到的密碼原樣回顯進輸出，被儀表板的工作紀錄
# 畫面顯示出來，是更嚴重的資安問題）。改用 [Console]::In.ReadLine() 直接讀
# 一行純文字，不經過主控台遮罩機制也不會回顯，讀到後再手動轉成 SecureString。
$plainPw = [Console]::In.ReadLine()
$securePw = ConvertTo-SecureString -String $plainPw -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential($Username, $securePw)

Write-Host "連線正式機（$ProdIp）..."
$session = New-PSSession -ComputerName $ProdIp -Credential $cred

try {
    if ($Action -eq "deploy") {
        $pkgName = Split-Path $PackagePath -Leaf
        $remoteDest = "C:\Users\Motrix\Desktop"
        $remotePkgPath = "$remoteDest\$pkgName"

        Write-Host "推送部署包：$PackagePath → $remotePkgPath ..."
        Copy-Item -Path $PackagePath -Destination $remoteDest -ToSession $session -Recurse -Force
        Write-Host "推送完成..."

        # 2026-09-08（重大發現＋修復）：下面呼叫的是正式機「既有安裝路徑」的
        # apply_update.ps1（$Root\backend\tools\...），不是剛推送過去這份套件
        # 裡的版本——因為 apply_update.ps1 自己有身分守門機制（Step 0：只能在
        # $ProdRoot 底下執行，防止不小心從錯誤路徑執行部署腳本本身），不能直接
        # 改成從套件路徑呼叫。但這造成一個嚴重後果：PowerShell 腳本一旦開始
        # 執行，用的就是啟動當下讀進記憶體的內容，跟磁碟上的檔案「之後」被
        # Step 3 覆蓋無關；而只要這次部署因健康檢查失敗被自動回滾，Step 3
        # 複製進去的新檔案又會被回滾邏輯用套用前快照蓋回去——代表只要從沒有
        # 一次真正成功套用過，$Root 這份 apply_update.ps1 會一直凍結在「最後
        # 一次成功套用」當下的版本，完全不會執行到套件裡任何後續才寫的修復
        # （這晚稍早「健檢第 N/20 次」log 從未出現過、-SkipAutoRollback 直接
        # 報「找不到符合參數名稱」，都是這個根因的直接證據）。
        # 修復：呼叫既有安裝路徑的 apply_update.ps1 之前，先把套件裡
        # backend/tools/ 底下的工具腳本本身同步覆蓋過去——身分守門仍然通過
        # （還是從 $Root 執行），但實際執行的內容就是套件裡已經過 pytest／
        # 語法檢查驗證的最新版。只同步工具腳本，不影響 db／業務程式碼／
        # uploads 等其餘部署流程（那些仍照 apply_update.ps1 自己的 Step 3
        # 邏輯，含備份/回滾保護）。
        Write-Host "同步部署工具腳本本身（backend/tools/）至正式機既有位置，確保這次執行的是套件內驗證過的最新版..."
        Invoke-Command -Session $session -ArgumentList $remotePkgPath, $ProdRoot -ScriptBlock {
            param($RemotePkgPath, $Root)
            $srcTools = Join-Path $RemotePkgPath "backend\tools"
            $dstTools = Join-Path $Root "backend\tools"
            if (Test-Path $srcTools) {
                Copy-Item -Path (Join-Path $srcTools "*") -Destination $dstTools -Recurse -Force
            }
        }
        Write-Host "工具腳本同步完成，開始遠端套用..."

        # 2026-09-08（重大修復）：先前這裡直接呼叫巢狀 powershell，完全沒有
        # 檢查/回傳它的結束碼。apply_update.ps1 健康檢查失敗、觸發自動回滾
        # 時確實會 exit 1，但 Invoke-Command 的 ScriptBlock 不會因為裡面一個
        # 原生執行檔的非零結束碼而拋出例外，這個失敗訊號從頭到尾沒有機會
        # 傳回開發機這邊——不管正式機那邊實際是成功、健康檢查失敗自動回滾、
        # 還是任何其他失敗，這支腳本都會正常執行完畢、exit code 維持 0，
        # deploy_dashboard.py 的 `success = proc.returncode == 0` 因此永遠
        # 判定成功。已改為在遠端 ScriptBlock 內额外印出一行帶標記的結束碼，
        # 本機這邊解析出來後才決定真的要不要 Fail（非 0 就整支腳本失敗）。
        # 用 | ForEach-Object（不是 $x = Invoke-Command ...）串流處理——直接賦值
        # 給變數的話，PowerShell 要等整個遠端命令跑完才會把結果一次寫進變數，
        # 這段部署可能耗時 1~2 分鐘（健康檢查迴圈+pip install+robocopy），
        # 畫面會整段時間空白、最後才一次噴出全部內容，等於弄丟了原本「即時
        # 滾動 log」的體驗。用管線接 ForEach-Object，每個物件從遠端一抵達
        # 就立刻處理／印出，結束碼標記那一行到達時再另外攔截存起來即可。
        $skipRollbackBool = ($SkipAutoRollback -eq "true")
        if ($skipRollbackBool) {
            Write-Host "[注意] 本次套用帶 -SkipAutoRollback：健康檢查若判定異常，正式機不會自動回滾，需要人工確認。" -ForegroundColor Yellow
        }
        $remoteExitCode = $null
        Invoke-Command -Session $session -ArgumentList $remotePkgPath, $ProdRoot, $skipRollbackBool -ScriptBlock {
            param($RemotePkgPath, $Root, $SkipRollback)
            $applyArgs = @("-ExecutionPolicy", "Bypass", "-File", "$Root\backend\tools\apply_update.ps1", "-PackagePath", $RemotePkgPath, "-Yes")
            if ($SkipRollback) { $applyArgs += "-SkipAutoRollback" }
            & powershell @applyArgs
            Write-Output "===EXITCODE=$LASTEXITCODE==="
        } | ForEach-Object {
            if ($_ -match '^===EXITCODE=(-?\d+)===$') {
                $remoteExitCode = [int]$matches[1]
            } else {
                Write-Host $_
            }
        }
        if ($null -eq $remoteExitCode) {
            Fail "無法取得正式機 apply_update.ps1 的實際執行結果（WinRM 輸出未包含結束碼標記，可能連線中途中斷，不能當成套用成功）。"
        }
        if ($remoteExitCode -ne 0) {
            Fail "正式機 apply_update.ps1 執行失敗（exit code $remoteExitCode）——上方輸出如果出現「更新失敗，已自動回滾」，代表健康檢查沒過、正式機已自動還原到套用前版本；若沒有那段文字，代表更早的步驟（如 Migration 乾跑驗證）就中止了，正式庫完全未被觸碰。"
        }
        Ok "正式機 apply_update.ps1 執行成功（exit code 0）。"
    } elseif ($Action -eq "rollback") {
        Write-Host "遠端執行回滾（$SnapshotTimestamp）..."
        # 同上，回滾也要真的檢查遠端 rollback_update.ps1 的結束碼，不能只看
        # WinRM 連線本身有沒有出錯。
        $remoteExitCode = $null
        Invoke-Command -Session $session -ArgumentList $SnapshotTimestamp, $ProdRoot -ScriptBlock {
            param($Ts, $Root)
            powershell -ExecutionPolicy Bypass -File "$Root\backend\tools\rollback_update.ps1" -SnapshotTimestamp $Ts -Yes
            Write-Output "===EXITCODE=$LASTEXITCODE==="
        } | ForEach-Object {
            if ($_ -match '^===EXITCODE=(-?\d+)===$') {
                $remoteExitCode = [int]$matches[1]
            } else {
                Write-Host $_
            }
        }
        if ($null -eq $remoteExitCode) {
            Fail "無法取得正式機 rollback_update.ps1 的實際執行結果（WinRM 輸出未包含結束碼標記，可能連線中途中斷，不能當成回滾成功）。"
        }
        if ($remoteExitCode -ne 0) {
            Fail "正式機 rollback_update.ps1 執行失敗（exit code $remoteExitCode），詳見上方輸出。"
        }
        Ok "正式機 rollback_update.ps1 執行成功（exit code 0）。"
    } elseif ($Action -eq "list-snapshots") {
        # list-snapshots：跟 apply_update.ps1 一樣，rollback_snapshots/<ts> 與
        # db_backups/pre_update_<ts> 用同一個時間戳，只需要列其中一份資料夾名稱。
        $result = Invoke-Command -Session $session -ArgumentList $ProdRoot -ScriptBlock {
            param($Root)
            $dir = Join-Path $Root "backend\rollback_snapshots"
            if (-not (Test-Path $dir)) { return @() }
            Get-ChildItem $dir -Directory | Sort-Object Name -Descending | Select-Object -First 10 -ExpandProperty Name
        }
        # 用 @() 強制陣列語境——ConvertTo-Json 對「剛好只有 1 個元素」的輸入
        # 預設不會加陣列括號（PS 5.1 沒有 -AsArray 參數），沒有這層強制，
        # Python 那端解析 JSON 在剛好只有 1 個快照時會拿到裸物件而不是陣列。
        # ConvertTo-Json 預設會跨多行印出，前面加一行固定的分隔標記，讓
        # Python 那端可以直接切出 JSON 區塊，不用逐行猜哪裡是 JSON 開頭。
        Write-Host "===JSON==="
        @($result) | ConvertTo-Json
    } elseif ($Action -eq "check-only") {
        # check-only：2026-09-08 當晚連續三次部署健康檢查誤判失敗時新增的
        # 純診斷動作（不寫入任何檔案，不動備份/停服/部署/回滾）。A/B 兩段
        # 測的是 curl.exe（直接呼叫／巢狀一層呼叫，模擬 apply_update.ps1
        # 當時的執行深度），C 段測 port 666 監聽狀態——三個假設（WinRM 巢狀
        # 執行、孤兒 socket）都在當晚被這三段測試獨立推翻，最後改用
        # backend/tools/_healthcheck_ping.py（Python + OpenSSL，不經過
        # curl.exe／Schannel）取代 apply_update.ps1 的健康檢查機制，見
        # MOTRIX-ERP-QUICK.md §12 同日條目。這裡的 curl.exe 測試留著當作
        # 一般性的連線診斷工具，D 段另外測新的 Python 健康檢查腳本本身
        # （巢狀深度跟 apply_update.ps1 實際呼叫方式一致），用來驗證下次
        # 部署時正式機上的新版健康檢查機制本身能不能正常運作。
        # D 段要測的 _healthcheck_ping.py 內容從「開發機這支腳本自己旁邊」讀，
        # 不是正式機上的檔案——正式機現在跑的是回滾後的舊版，backend/tools/
        # 底下還沒有這支新檔案（要等下次部署成功才會有）。把內容當參數傳進
        # WinRM session，在正式機寫一份暫存檔案來測，等於預先驗證「這支腳本
        # 之後部署上去，在正式機這個環境跑起來真的沒問題」，不用等部署完才知道。
        $localPingScript = Get-Content (Join-Path $PSScriptRoot "_healthcheck_ping.py") -Raw
        $raw = Invoke-Command -Session $session -ArgumentList $localPingScript -ScriptBlock {
            param($PingScriptContent)
            $out = @()
            $out += "curl.exe 路徑解析：$((Get-Command curl.exe -ErrorAction SilentlyContinue).Source)"
            $out += ""
            $out += "--- A. 直接在這層 WinRM session 呼叫 curl.exe（先前測過會成功）---"
            $code = & curl.exe -k -s -o NUL -w "%{http_code}" --max-time 5 https://127.0.0.1:666/api/ping 2>&1
            $out += "回傳 http_code = [$code]"
            $out += ""
            $out += "--- B. 巢狀一層：跟真正部署時 apply_update.ps1 的執行深度一致 ---"
            $out += "（WinRM session -> 子行程 powershell -File <暫存.ps1> -> curl.exe，不用 -Command 字串，避開多層轉送引號被吃掉的問題）"
            $tmpScript = Join-Path $env:TEMP "motrix_nested_curl_test.ps1"
            @'
$ErrorActionPreference = "Stop"
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    $c = & curl.exe -k -s -o NUL -w "%{http_code}" --max-time 5 https://127.0.0.1:666/api/ping 2>&1
    Write-Output "nested_http_code=[$c]"
} catch {
    Write-Output "nested_exception=$_"
} finally {
    $ErrorActionPreference = $prevEap
}
'@ | Set-Content -Path $tmpScript -Encoding UTF8
            $nested = & powershell -ExecutionPolicy Bypass -File $tmpScript 2>&1
            Remove-Item $tmpScript -Force -ErrorAction SilentlyContinue
            $out += ($nested | Out-String)
            $out += ""
            $out += "--- C. port 666 目前監聽狀態（找有沒有殘留的孤兒/多個 listener）---"
            $conns = Get-NetTCPConnection -LocalPort 666 -ErrorAction SilentlyContinue
            if (-not $conns) {
                $out += "（目前完全沒有任何連線/監聽在 port 666 上）"
            } else {
                foreach ($c in $conns) {
                    $procInfo = try { (Get-Process -Id $c.OwningProcess -ErrorAction Stop).ProcessName } catch { "(process 已不存在)" }
                    $out += "State=$($c.State)  PID=$($c.OwningProcess)  Process=$procInfo"
                }
            }
            $out += ""
            $out += "--- D. 預先驗證新版健康檢查腳本（_healthcheck_ping.py），巢狀深度跟 apply_update.ps1 -> Test-Ping 實際呼叫方式一致（WinRM session -> 子行程 powershell -File -> python） ---"
            $pingTmp = Join-Path $env:TEMP "motrix_healthcheck_ping_predeploy_test.py"
            $PingScriptContent | Set-Content -Path $pingTmp -Encoding UTF8
            $wrapperTmp = Join-Path $env:TEMP "motrix_healthcheck_wrapper_predeploy_test.ps1"
            @"
`$prevEap = `$ErrorActionPreference
`$ErrorActionPreference = "Continue"
try {
    & python '$pingTmp' "https://127.0.0.1:666/api/ping" 5 2>&1
    Write-Output "exit_code=[`$LASTEXITCODE]"
} finally {
    `$ErrorActionPreference = `$prevEap
}
"@ | Set-Content -Path $wrapperTmp -Encoding UTF8
            try {
                $dResult = & powershell -ExecutionPolicy Bypass -File $wrapperTmp 2>&1
                $out += ($dResult | Out-String)
            } finally {
                Remove-Item $pingTmp, $wrapperTmp -Force -ErrorAction SilentlyContinue
            }
            ($out -join "`n")
        }
        [string]$outText = $raw
        Write-Host "===JSON==="
        $outText | ConvertTo-Json
    } elseif ($Action -eq "upgrade") {
        $pkgName = Split-Path $PackagePath -Leaf
        $remotePkg = Join-Path $ProdDesktop $pkgName
        $bk = Join-Path $UpgradeBackupRoot $BackupStamp
        if ($Step -eq "push") {
            Write-Host "推送新版部署包：$PackagePath → $remotePkg ..."
            Copy-Item -Path $PackagePath -Destination $ProdDesktop -ToSession $session -Recurse -Force
            Ok "推送完成。"
            return
        }
        Write-Host "遠端執行升級步驟：$Step（安裝目錄 $ProdRoot，備份目錄 $bk）"
        $remoteExitCode = $null
        Invoke-Command -Session $session -ArgumentList $Step, $ProdRoot, $remotePkg, $bk, $ProdTasks -ScriptBlock {
            param($Step, $Root, $Pkg, $Bk, $Tasks)
            $tool = Join-Path $Pkg "tools\platform\upgrade.py"
            if ($Step -ne "stop-services" -and $Step -ne "start-services" -and -not (Test-Path $tool)) {
                Write-Output "找不到 $tool（部署包還沒推送，或不是新版的包）"
                Write-Output "===EXITCODE=1==="
                return
            }
            switch ($Step) {
                "stop-services" {
                    foreach ($t in $Tasks) { Disable-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue | Out-Null; Write-Output "已停用排程：$t" }
                    # 只停 python 系列、而且只停正在監聽 666 的行程（比照 restart.bat）
                    foreach ($c in @(Get-NetTCPConnection -LocalPort 666 -State Listen -ErrorAction SilentlyContinue)) {
                        $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
                        if ($p -and $p.ProcessName -match '^python') { Stop-Process -Id $p.Id -Force; Write-Output "已停止 $($p.ProcessName) PID=$($p.Id)" }
                        elseif ($p) { Write-Output "port 666 被 $($p.ProcessName) 佔用，不是 python，不動它" }
                    }
                    # autostart.bat 的 crash-restart 迴圈會把服務拉回來 ⇒ 一併停掉（比照 restart.bat 以 commandline 比對）
                    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'autostart\.bat|autostart_hidden\.vbs' } |
                        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Output "已停止 autostart 迴圈 PID=$($_.ProcessId)" }
                    Start-Sleep -Seconds 3
                    $left = @(Get-NetTCPConnection -LocalPort 666 -State Listen -ErrorAction SilentlyContinue).Count
                    if ($left -gt 0) { Write-Output "⚠ port 666 仍有 $left 個監聽者"; Write-Output "===EXITCODE=1===" } else { Write-Output "port 666 已無監聽"; Write-Output "===EXITCODE=0===" }
                    return
                }
                "start-services" {
                    foreach ($t in $Tasks) { Enable-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue | Out-Null; Write-Output "已啟用排程：$t" }
                    Start-ScheduledTask -TaskName $Tasks[0] -ErrorAction SilentlyContinue
                    Write-Output "已觸發 $($Tasks[0])（含 90 秒延遲，約 2 分鐘後服務回來；Heartbeat 下一輪會恢復打卡）"
                    Write-Output "===EXITCODE=0==="
                    return
                }
            }
            $args2 = switch ($Step) {
                "preflight"     { @("preflight", "--root", $Root, "--v9-port", "666") }
                "backup"        { @("backup", "--root", $Root, "--backup-dir", $Bk) }
                "convert"       { @("convert", "--root", $Root, "--backup-dir", $Bk, "--new-source", $Pkg) }
                "verify"        { @("verify", "--root", $Root, "--backup-dir", $Bk, "--port", "6671") }
                "rollback-code" { @("rollback", "--root", $Root, "--backup-dir", $Bk, "--mode", "code") }
                "rollback-full" { @("rollback", "--root", $Root, "--backup-dir", $Bk, "--mode", "full", "--yes") }
            }
            $env:PYTHONIOENCODING = "utf-8"
            & python $tool @args2 2>&1 | ForEach-Object { "$_" }
            Write-Output "===EXITCODE=$LASTEXITCODE==="
        } | ForEach-Object {
            if ($_ -match '^===EXITCODE=(-?\d+)===$') { $remoteExitCode = [int]$matches[1] } else { Write-Host $_ }
        }
        if ($null -eq $remoteExitCode) { Fail "取不到升級步驟 $Step 的結束碼（連線可能中斷），不能當成成功。" }
        if ($remoteExitCode -ne 0) { Fail "升級步驟 $Step 失敗（exit code $remoteExitCode），詳見上方輸出。" }
        Ok "升級步驟 $Step 完成。"
    } elseif ($Action -eq "health") {
        # health（CORE-SPEC §9e D1，2026-09-25）：部署前健康檢查，**完全唯讀**。
        # 只收集事實、不做判斷——判斷規則在開發機 deploy_insights.evaluate_health()（有測試）。
        # 單一字串回傳（先在遠端 ConvertTo-Json），理由同 tail-log：避開 Remoting 對物件加簽的屬性。
        $raw = Invoke-Command -Session $session -ArgumentList $ProdRoot -ScriptBlock {
            param($Root)
            $b = Join-Path $Root "backend"
            $alertFile = Join-Path $Root "backup_alerts\BACKUP_ALERT.txt"
            $alertText = ""
            if (Test-Path $alertFile) { $alertText = ((Get-Content $alertFile -TotalCount 5) -join "`n") }
            $latestBackup = $null
            $bdir = Join-Path $b "db_backups"
            if (Test-Path $bdir) {
                $f = Get-ChildItem $bdir -Recurse -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
                if ($f) { $latestBackup = @{ name = $f.Name; at = $f.LastWriteTime.ToString("s") } }
            }
            $disks = @()
            foreach ($d in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
                if ($d.Free -ne $null) { $disks += @{ name = $d.Name; freeGB = [math]::Round($d.Free / 1GB, 1) } }
            }
            $listen = @(Get-NetTCPConnection -LocalPort 666 -State Listen -ErrorAction SilentlyContinue).Count
            $pii = @()
            foreach ($d in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
                foreach ($sub in @("我的雲端硬碟\系統存檔_個資", "My Drive\系統存檔_個資")) {
                    $p = Join-Path $d.Root $sub
                    if (Test-Path -LiteralPath $p) { $pii += $p }
                }
            }
            $deployed = $null
            $dm = Join-Path $b ".deployed_commit.json"
            if (Test-Path $dm) { $deployed = (Get-Content $dm -Raw) }
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
        }
        [string]$outText = $raw
        Write-Host "===JSON==="
        Write-Host $outText
    } else {
        # tail-log：純讀取 server.log 最後 N 行，供部署健康檢查失敗時人工診斷
        # 用（跟 apply_update.ps1 的「healthy=False, log 錯誤筆數=N」是同一份
        # 檔案），完全唯讀不動任何東西。
        #
        # 在遠端 scriptblock 內就先用 -join 併成單一字串再回傳——PS Remoting
        # 對「陣列」回傳值的每個元素都會加簽 PSComputerName/RunspaceId/
        # PSShowComputerName 這幾個額外屬性，ConvertTo-Json 會把每個看起來
        # 明明是純字串的陣列元素序列化成帶這些欄位的物件，前端 join 出一串
        # [object Object]（實測踩到）。回傳單一字串再用 [string] 強制轉型，
        # 繞開這整個問題。
        $raw = Invoke-Command -Session $session -ArgumentList $ProdRoot, $Lines -ScriptBlock {
            param($Root, $N)
            $logPath = Join-Path $Root "backend\logs\server.log"
            if (-not (Test-Path $logPath)) { return "" }
            (Get-Content $logPath -Tail $N) -join "`n"
        }
        [string]$logText = $raw
        Write-Host "===JSON==="
        $logText | ConvertTo-Json
    }
} finally {
    Remove-PSSession $session
}
