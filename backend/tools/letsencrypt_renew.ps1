<#
  letsencrypt_renew.ps1 — 在「正式機」執行

  用途：把 Posh-ACME 取得的 Let's Encrypt 憑證裝進 backend\certs\，並在必要時
  重啟服務。設計成可以無人值守地每天跑一次。

  搭配文件：LETSENCRYPT-PUBLIC-CERT-PLAN.md（先照那份做完步驟 1～3 再用這支）

  用法：
    # 第一次：把已經簽好的憑證裝上去（不管到期日）
    powershell -ExecutionPolicy Bypass -File letsencrypt_renew.ps1 -Force

    # 設定每日自動續期排程（以 SYSTEM 身分執行，不需要存任何密碼）
    powershell -ExecutionPolicy Bypass -File letsencrypt_renew.ps1 -InstallSchedule

    # 排程實際跑的就是不帶參數這一種：檢查、必要時續期、有變動才重啟
    powershell -ExecutionPolicy Bypass -File letsencrypt_renew.ps1

  【為什麼不用 restart.bat 重啟】
  restart.bat 最後直接在前景跑 uvicorn 並以 pause 結尾——那是給人坐在機器前用的。
  排程工作呼叫它會永遠不返回，而且下次排程還會再開一個。這裡沿用
  apply_update.ps1 的做法：**只停服，讓 autostart.bat 的 crash-restart 迴圈接手
  重新啟動**（約 5 秒內），不自己搶 port 666。

  【為什麼排程要跑 SYSTEM，而 Posh-ACME 的家目錄要搬到 ProgramData】
  Posh-ACME 預設把帳號與憑證存在 %LOCALAPPDATA%\Posh-ACME，那是**每個使用者
  各自一份**。若憑證是用 Motrix 帳號簽的、排程卻以 SYSTEM 執行，SYSTEM 會找不到
  任何憑證，於是「排程每天都成功執行、但什麼都沒做」，直到 90 天後憑證過期、
  整個系統的 HTTPS 一起壞掉——而且中間不會有任何徵兆。
  解法是把 POSHACME_HOME 設成機器層級的共用路徑，並讓帳號改用可攜的加密方式
  （Set-PAAccount -UseAltPluginEncryption），詳見上述文件。本腳本啟動時會檢查
  這件事，沒設好就直接擋下來。
#>
[CmdletBinding()]
param(
    [string]$Domain = "erp.miactw.com",
    # 不管到期日，把目前這張憑證裝上去（第一次切換時用）
    [switch]$Force,
    # 建立每日排程工作後結束，不做其他事
    [switch]$InstallSchedule,
    # 剩餘天數低於這個值又沒能續期成功，就在 log 留下 [警告]
    [int]$WarnDays = 20
)

$ErrorActionPreference = "Stop"

$BackendDir = Split-Path -Parent $PSScriptRoot
$CertsDir   = Join-Path $BackendDir "certs"
$LogDir     = Join-Path $BackendDir "logs"
$LogFile    = Join-Path $LogDir "letsencrypt_renew.log"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

function Log($msg, $color = $null) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    if ($color) { Write-Host $line -ForegroundColor $color } else { Write-Host $line }
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}
function Fail($msg) { Log "[失敗] $msg" Red; exit 1 }
function Warn($msg) { Log "[警告] $msg" Yellow }
function Ok($msg)   { Log "[OK] $msg" Green }

# ── -InstallSchedule：建立排程後結束 ─────────────────────────────────────────
if ($InstallSchedule) {
    $taskName = "MOTRIX-ERP Let's Encrypt Renew"
    $me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Fail "建立排程需要系統管理員權限。請用「以系統管理員身分執行」開啟 PowerShell 後重試。"
    }

    $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
                 -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Domain {1}' -f $PSCommandPath, $Domain)
    $trigger = New-ScheduledTaskTrigger -Daily -At 3:30am
    # SYSTEM：不必儲存任何人的密碼。前提是 POSHACME_HOME 已設成機器層級共用路徑
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
                   -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
    Ok "排程已建立：「$taskName」，每天 03:30 執行。"
    Log "  手動觸發一次：Start-ScheduledTask -TaskName `"$taskName`""
    Log "  查看結果：    Get-Content `"$LogFile`" -Tail 30"
    exit 0
}

Log "===== letsencrypt_renew 開始（domain=$Domain, Force=$Force）====="

# ── 前置檢查 ────────────────────────────────────────────────────────────────
if (-not (Get-Module -ListAvailable -Name Posh-ACME)) {
    Fail "找不到 Posh-ACME 模組。請先執行：Install-Module -Name Posh-ACME -Scope AllUsers"
}
Import-Module Posh-ACME

$poshHome = [Environment]::GetEnvironmentVariable("POSHACME_HOME", "Machine")
if (-not $poshHome) {
    Warn "POSHACME_HOME 沒有設成機器層級變數。以 SYSTEM 執行的排程會看不到你用個人帳號簽的憑證"
    Warn "（見本檔頭說明）。請照 LETSENCRYPT-PUBLIC-CERT-PLAN.md 步驟 3 設定後重簽一次。"
}

$cert = $null
try {
    $cert = Get-PACertificate -MainDomain $Domain
} catch {
    Fail "讀不到 $Domain 的憑證：$($_.Exception.Message)"
}
if (-not $cert) {
    Fail @"
Posh-ACME 裡沒有 $Domain 的憑證。請先照 LETSENCRYPT-PUBLIC-CERT-PLAN.md 步驟 3 簽一張：
  Set-PAServer LE_PROD
  New-PACertificate '$Domain' -AcceptTOS -Contact '<你的 email>' -Plugin Cloudflare -PluginArgs @{ CFToken = `$token }
"@
}

$daysLeft = [int]([datetime]$cert.NotAfter - (Get-Date)).TotalDays
Log "目前憑證：$($cert.Subject)，到期 $($cert.NotAfter)（剩 $daysLeft 天）"

# ── 續期（Posh-ACME 只在進入續期視窗時才真的動作）─────────────────────────
if (-not $Force) {
    try {
        Submit-Renewal -MainDomain $Domain | Out-Null
        Log "Submit-Renewal 執行完畢。"
    } catch {
        Warn "Submit-Renewal 失敗：$($_.Exception.Message)"
        Warn "憑證仍是舊的；若剩餘天數持續下降要盡快處理。"
    }
    $cert = Get-PACertificate -MainDomain $Domain
    $daysLeft = [int]([datetime]$cert.NotAfter - (Get-Date)).TotalDays
}

# ── 比對「正在服務的憑證」與「Posh-ACME 手上的憑證」──────────────────────
# 用檔案雜湊比對就夠了，而且比解析 PEM 可靠——fullchain 是多張憑證串接，
# X509Certificate2 只會讀到第一張。
$liveCert = Join-Path $CertsDir "cert.pem"
$liveKey  = Join-Path $CertsDir "key.pem"

# fullchain 而不是單張葉憑證：少了中繼憑證，部分客戶端（尤其非瀏覽器）會驗不過
$srcCert = $cert.FullChainFile
$srcKey  = $cert.KeyFile
foreach ($f in @($srcCert, $srcKey)) {
    if (-not (Test-Path $f)) { Fail "Posh-ACME 回報的檔案不存在：$f" }
}

$needInstall = $Force
if (-not $needInstall) {
    if (-not (Test-Path $liveCert)) {
        $needInstall = $true
        Log "backend\certs\cert.pem 不存在，視為需要安裝。"
    } else {
        $a = (Get-FileHash $liveCert -Algorithm SHA256).Hash
        $b = (Get-FileHash $srcCert  -Algorithm SHA256).Hash
        $needInstall = ($a -ne $b)
    }
}

if (-not $needInstall) {
    Log "服務中的憑證已經是最新的，不需要動作。"
    if ($daysLeft -lt $WarnDays) {
        Warn "但剩餘天數只有 $daysLeft 天（門檻 $WarnDays）——續期沒有生效，請人工檢查。"
    }
    Log "===== 結束（無變動）====="
    exit 0
}

# ── 安裝：先備份，再覆蓋 ────────────────────────────────────────────────────
if (-not (Test-Path $CertsDir)) { New-Item -ItemType Directory -Path $CertsDir -Force | Out-Null }

if (Test-Path $liveCert) {
    $backupDir = Join-Path $CertsDir ("backup_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    Copy-Item $liveCert $backupDir -Force
    if (Test-Path $liveKey) { Copy-Item $liveKey $backupDir -Force }
    Ok "舊憑證已備份到 $backupDir（回滾就是把這兩個檔複製回去再停服一次）"
}

Copy-Item $srcCert $liveCert -Force
Copy-Item $srcKey  $liveKey  -Force
Ok "新憑證已就位：$liveCert / $liveKey"

# ── 停服，讓 autostart 的 crash-restart 迴圈接手重啟 ────────────────────────
Log "停止伺服器（由 autostart crash-restart 迴圈接手重啟）..."
$conn = Get-NetTCPConnection -LocalPort 666 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    Log "  Kill PID $($conn.OwningProcess)（listening on 666）"
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
} else {
    Log "  Port 666 目前無人監聽。"
}
Get-WmiObject Win32_Process | Where-Object {
    $_.CommandLine -like "*uvicorn*main:app*" -or $_.CommandLine -like "*spawn_main*parent_pid*"
} | ForEach-Object {
    Log "  Kill PID $($_.ProcessId)"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

# 等 port 真正釋放，降低跟 crash-restart 迴圈搶綁定的競態（同 apply_update.ps1）
for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    if (-not (Get-NetTCPConnection -LocalPort 666 -State Listen -ErrorAction SilentlyContinue)) { break }
}

# ── 等服務回來並實際驗一次 TLS ─────────────────────────────────────────────
Log "等待服務重新啟動..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$verified = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 3
    try {
        # 刻意用網域而不是 localhost：要驗的正是「這張憑證對這個名字有效，
        # 而且是公開受信任的簽發者」——用 localhost 兩件事都驗不到。
        $r = Invoke-WebRequest -Uri "https://$Domain`:666/api/ping" -UseBasicParsing -TimeoutSec 10
        if ($r.StatusCode -eq 200) { $verified = $true; break }
    } catch {
        # 服務還沒起來，或憑證/DNS 有問題——迴圈結束後再一起判斷
    }
}

if ($verified) {
    Ok "服務已恢復，且 https://$Domain`:666 憑證驗證通過（未使用任何憑證豁免）。"
    Log "===== 結束（已更新憑證）====="
} else {
    Warn "服務在 2 分鐘內沒有回應，或 https://$Domain`:666 的憑證驗證失敗。"
    Warn "請人工檢查：(1) autostart 迴圈是否還在跑 (2) $Domain 是否解析得到 (3) 憑證是否正確。"
    Warn "回滾：把 $backupDir 裡的兩個檔複製回 $CertsDir，再停一次服務讓迴圈重啟。"
    Log "===== 結束（需要人工處理）====="
    exit 1
}
