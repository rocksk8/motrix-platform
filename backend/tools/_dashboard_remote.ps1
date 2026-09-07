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
    [ValidateSet("deploy", "rollback", "list-snapshots")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$Username,

    [string]$PackagePath,
    [string]$SnapshotTimestamp
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

$securePw = Read-Host -AsSecureString
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
    } else {
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
    }
} finally {
    Remove-PSSession $session
}
