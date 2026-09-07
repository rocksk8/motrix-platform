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
    [ValidateSet("deploy", "rollback", "list-snapshots", "tail-log", "check-only")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$Username,

    [string]$PackagePath,
    [string]$SnapshotTimestamp,
    [int]$Lines = 300
)

$ErrorActionPreference = "Stop"
$ProdIp = "172.16.10.177"
$ProdRoot = "C:\Users\Motrix\Desktop\V9.0"

function Fail($msg) {
    Write-Host "`n[FAIL] $msg" -ForegroundColor Red
    exit 1
}

if ($Action -eq "deploy" -and -not $PackagePath) {
    Fail "-Action deploy 需要 -PackagePath。"
}
if ($Action -eq "rollback" -and -not $SnapshotTimestamp) {
    Fail "-Action rollback 需要 -SnapshotTimestamp。"
}

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
        Write-Host "推送完成，開始遠端套用..."

        Invoke-Command -Session $session -ArgumentList $remotePkgPath, $ProdRoot -ScriptBlock {
            param($RemotePkgPath, $Root)
            powershell -ExecutionPolicy Bypass -File "$Root\backend\tools\apply_update.ps1" -PackagePath $RemotePkgPath -Yes
        }
    } elseif ($Action -eq "rollback") {
        Write-Host "遠端執行回滾（$SnapshotTimestamp）..."
        Invoke-Command -Session $session -ArgumentList $SnapshotTimestamp, $ProdRoot -ScriptBlock {
            param($Ts, $Root)
            powershell -ExecutionPolicy Bypass -File "$Root\backend\tools\rollback_update.ps1" -SnapshotTimestamp $Ts -Yes
        }
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
        # check-only：目前正式機上「已回滾」的 apply_update.ps1 版本比
        # -CheckOnly 這個功能還舊（實測撞到「找不到符合參數名稱 'CheckOnly'
        # 的參數」），沒辦法直接呼叫該旗標。改成直接在遠端 session 裡執行
        # Test-Ping 用的同一行 curl.exe 指令（外加 curl.exe 路徑解析／
        # -v 詳細輸出），純診斷、不寫入任何檔案，不動備份/停服/部署/回滾。
        # 用來驗證「這次連續兩輪部署都健康檢查失敗，但外部從開發機直接打
        # LAN IP 又能打通」這個落差，是不是 WinRM 巢狀執行環境本身讓
        # curl.exe 打 loopback 出了問題（跟直接在正式機主控台跑不一樣）。
        $raw = Invoke-Command -Session $session -ScriptBlock {
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
    $c = & curl.exe -k -s -o NUL -w "%{http_code}" --max-time 5 https://127.0.0.1:666/api/ping 2>$null
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
            ($out -join "`n")
        }
        [string]$outText = $raw
        Write-Host "===JSON==="
        $outText | ConvertTo-Json
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
