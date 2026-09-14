<#
  setup_passkey_client.ps1 — 在「每一台要用 Passkey 的電腦」上執行一次

  用途：PASSKEY-CA-ROLLOUT.md 第 5 步。用戶端要能用 https://motrix.internal:666
  取得乾淨鎖頭，必須同時滿足兩個條件，缺一不可：

    (a) 信任正式機的 mkcert 根 CA
    (b) 解析得到 motrix.internal

  這支腳本把兩件一起做完並驗證，因為實務上的失敗模式就是「只做了 (a)、忘了 (b)」
  ——CA 裝好了但瀏覽器連不上那個網址，看起來像沒生效，很容易誤判成憑證有問題。

  需要系統管理員（改 hosts）。不是管理員時會自己跳 UAC 重新啟動，不用手動開視窗。

  用法（一般 PowerShell 視窗即可，會自己提權）：
    powershell -ExecutionPolicy Bypass -File backend\tools\setup_passkey_client.ps1

    -CaFile   根 CA 路徑，預設 <專案>\..\MOTRIX-ERP-CA\rootCA.pem
              （用 fetch_root_ca.ps1 取回；其他電腦請把該檔一起帶過去）
    -ProdIp   正式機 IP，預設 172.16.10.177
    -HostName 內部網域，預設 motrix.internal
#>

[CmdletBinding()]
param(
    [string]$CaFile   = "",
    [string]$ProdIp   = "172.16.10.177",
    [string]$HostName = "motrix.internal",
    [string]$Thumbprint = "A9AF974F0BD6CE35B47CDB95CAA5E2B324DAE61C"
)

$ErrorActionPreference = "Continue"

if (-not $CaFile) {
    $CaFile = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) "..\MOTRIX-ERP-CA\rootCA.pem"
    $CaFile = [System.IO.Path]::GetFullPath($CaFile)
}

# ── 自我提權（改 hosts 一定要管理員）──────────────────────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "需要系統管理員權限（要改 hosts），正在跳出 UAC 重新啟動..."
    Write-Host "（請在跳出的視窗按「是」；沒看到視窗的話檢查工作列）"
    $argList = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-NoExit",
        "-File", "`"$PSCommandPath`"",
        "-CaFile", "`"$CaFile`"", "-ProdIp", $ProdIp, "-HostName", $HostName
    )
    try {
        Start-Process -FilePath "powershell" -Verb RunAs -ArgumentList $argList
        Write-Host "已在新的管理員視窗繼續，請看那個視窗的輸出。"
        exit 0
    } catch {
        Write-Host "[失敗] 無法提權：$($_.Exception.Message)"
        Write-Host "       請手動用「以系統管理員身分執行」開 PowerShell，再跑一次這支腳本。"
        exit 1
    }
}

Write-Host ""
Write-Host "根 CA   : $CaFile"
Write-Host "正式機  : $HostName -> $ProdIp"
Write-Host ""

if (-not (Test-Path $CaFile)) {
    Write-Host "[失敗] 找不到根 CA：$CaFile"
    Write-Host "       在開發機用 backend\tools\fetch_root_ca.ps1 取回，再把該檔複製到這台電腦。"
    exit 1
}

# ── (a) 安裝根 CA ───────────────────────────────────────────────────────────
Write-Host "[1/3] 安裝根 CA 到 LocalMachine\Root..."
try {
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $CaFile
} catch {
    Write-Host "      [失敗] 無法解析憑證：$($_.Exception.Message)"
    exit 1
}
Write-Host "      主體 : $($cert.Subject)"
Write-Host "      指紋 : $($cert.Thumbprint)"

if ($Thumbprint -and $cert.Thumbprint -ne $Thumbprint) {
    Write-Host ""
    Write-Host "      [注意] 指紋與預期的 $Thumbprint 不同。"
    Write-Host "             若正式機的 CA 重新產生過這是正常的，但請先確認來源正確再繼續"
    Write-Host "             （安裝根 CA 等於讓這台電腦信任該 CA 簽出的所有憑證）。"
    Write-Host "             確認無誤請加 -Thumbprint '$($cert.Thumbprint)' 重跑。"
    exit 1
}

$already = Get-ChildItem Cert:\LocalMachine\Root -ErrorAction SilentlyContinue |
    Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
if ($already) {
    Write-Host "      已存在，略過安裝"
} else {
    # certutil 的訊息會依系統語言變化，成功與否一律以事後查存放區為準
    & certutil -addstore -f Root $CaFile 2>&1 | Out-Null
    $ok = Get-ChildItem Cert:\LocalMachine\Root -ErrorAction SilentlyContinue |
        Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
    if ($ok) { Write-Host "      [OK] 已安裝" }
    else { Write-Host "      [失敗] 安裝後在存放區找不到"; exit 1 }
}

# ── (b) hosts ───────────────────────────────────────────────────────────────
Write-Host "[2/3] 設定 hosts（$HostName -> $ProdIp）..."
$hosts = "$env:SystemRoot\System32\drivers\etc\hosts"
$lines = @(Get-Content $hosts -ErrorAction SilentlyContinue)
$existing = $lines | Where-Object { $_ -match "^\s*[^#].*\b$([regex]::Escape($HostName))\b" }

if ($existing) {
    Write-Host "      已存在：$($existing -join ' | ')"
    if ($existing -notmatch [regex]::Escape($ProdIp)) {
        Write-Host "      [注意] 現有這筆指向的不是 $ProdIp，請人工確認是否要改。腳本不動它。"
    }
} else {
    # 用 Environment::NewLine 而不是反引號跳脫，避免不同呼叫方式下的引號地雷
    Add-Content -Path $hosts -Value ("$ProdIp`t$HostName") -Encoding ascii
    Write-Host "      [OK] 已加入"
}

# ── 驗證 ────────────────────────────────────────────────────────────────────
Write-Host "[3/3] 驗證..."
try {
    $ips = [System.Net.Dns]::GetHostAddresses($HostName) | ForEach-Object { $_.IPAddressToString }
    Write-Host "      解析 : $HostName -> $($ips -join ', ')"
} catch {
    Write-Host "      [失敗] 仍然解析不到 $HostName"
    exit 1
}

try {
    $req = [System.Net.HttpWebRequest]::Create("https://$ProdIp`:666/api/ping")
    $req.Host = $HostName
    $req.Timeout = 10000
    $resp = $req.GetResponse()
    Write-Host "      TLS  : [OK] 憑證驗證通過，HTTP $([int]$resp.StatusCode)"
    $resp.Close()
} catch {
    Write-Host "      TLS  : [失敗] $($_.Exception.Message.Split([char]10)[0])"
    Write-Host "             CA 或 hosts 可能沒生效，或正式機服務沒在跑。"
    exit 1
}

Write-Host ""
Write-Host "完成！這台電腦已可用 https://$HostName`:666 取得受信任的連線。"
Write-Host ""
Write-Host "請在瀏覽器開 https://$HostName`:666 確認網址列是乾淨的鎖頭（沒有警告）。"
Write-Host "全部要用 Passkey 的電腦都做完之後，才進行 PASSKEY-CA-ROLLOUT.md 第 7 步（設定 RP ID）。"
Write-Host ""
