<#
  fetch_root_ca.ps1 — 在「開發機」執行

  用途：PASSKEY-CA-ROLLOUT.md 第 4 步——把正式機的 mkcert 根 CA（rootCA.pem）
  取回開發機，供之後分發給每一台要用 Passkey 的電腦安裝。

  為什麼需要這支腳本（而不是一行 Invoke-Command）：
    這一步一定要連正式機，也就一定要正式機的帳密。把明文密碼寫進指令列是壞
    習慣（會留在指令歷程、工作階段紀錄、甚至聊天視窗裡——這個專案已經發生過
    兩次「密碼誤打進聊天視窗」）。本腳本改用 Get-Credential 的原生輸入框，
    並在第一次成功後把憑證存成 DPAPI 加密檔（只有這台機器的這個帳號解得開），
    之後再跑就不用再打密碼。

  用法：
    powershell -ExecutionPolicy Bypass -File backend\tools\fetch_root_ca.ps1
    powershell -ExecutionPolicy Bypass -File backend\tools\fetch_root_ca.ps1 -Force   # 忽略既有憑證檔，重新輸入密碼

  產出：
    <專案根>\..\MOTRIX-ERP-CA\rootCA.pem      取回的根 CA（刻意放在專案外，不會被 git 追蹤）
    %USERPROFILE%\motrix_cred.xml             DPAPI 加密的憑證檔（僅本機本帳號可解）

  注意：這支腳本對正式機只做「讀取」（Test-Path / Get-Content），不寫入任何東西。
#>

[CmdletBinding()]
param(
    [string]$ProdHost = "172.16.10.177",
    [string]$ProdUser = "Motrix",
    [switch]$Force
)

# 原生執行檔／遠端呼叫前把 ErrorActionPreference 切成 Continue：
# PowerShell 5.1 在 Stop 模式下會把任何 stderr 輸出 promote 成終止例外，
# 即使指令本身成功（本專案已踩過四次，見 MOTRIX-ERP-QUICK.md）。
$ErrorActionPreference = "Continue"

$credPath = Join-Path $env:USERPROFILE "motrix_cred.xml"
$outDir   = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) "..\MOTRIX-ERP-CA"
$outDir   = [System.IO.Path]::GetFullPath($outDir)
$outFile  = Join-Path $outDir "rootCA.pem"

Write-Host ""
Write-Host "正式機   : $ProdUser@$ProdHost"
Write-Host "憑證檔   : $credPath"
Write-Host "取回位置 : $outFile"
Write-Host ""

# ── 取得憑證 ────────────────────────────────────────────────────────────────
if ((Test-Path $credPath) -and -not $Force) {
    Write-Host "[1/3] 使用既有的加密憑證檔（要重新輸入密碼請加 -Force）"
    try {
        $cred = Import-Clixml -Path $credPath
    } catch {
        Write-Host "      憑證檔讀取失敗（$($_.Exception.Message)），改為重新輸入"
        $cred = $null
    }
} else {
    $cred = $null
}

if (-not $cred) {
    Write-Host "[1/3] 請在跳出的視窗輸入正式機密碼（帳號已帶入 $ProdUser）"
    $cred = Get-Credential -UserName $ProdUser -Message "MOTRIX 正式機 ($ProdHost)"
    if (-not $cred) { Write-Host "`n[中止] 沒有輸入憑證。" ; exit 1 }
}

# ── 讀取正式機上的 rootCA.pem（唯讀）───────────────────────────────────────
Write-Host "[2/3] 連線正式機讀取 rootCA.pem（唯讀，不寫入任何東西）..."
try {
    $r = Invoke-Command -ComputerName $ProdHost -Credential $cred -ErrorAction Stop -ScriptBlock {
        $p = Join-Path $env:LOCALAPPDATA "mkcert\rootCA.pem"
        [pscustomobject]@{
            HostName = $env:COMPUTERNAME
            Caroot   = (Join-Path $env:LOCALAPPDATA "mkcert")
            Exists   = (Test-Path $p)
            Content  = if (Test-Path $p) { Get-Content $p -Raw } else { "" }
        }
    }
} catch {
    Write-Host ""
    Write-Host "[失敗] 無法連線或存取被拒：$($_.Exception.Message)"
    Write-Host "       檢查順序：①密碼是否正確 ②WinRM 通道是否還在（見 MOTRIX-ERP-QUICK.md §14.3b）"
    Write-Host "                 ③正式機是否開機且在同一網段"
    exit 1
}

Write-Host "      連上 $($r.HostName)，CAROOT = $($r.Caroot)"
if (-not $r.Exists) {
    Write-Host ""
    Write-Host "[失敗] 正式機上找不到 rootCA.pem。它應該在 $($r.Caroot)。"
    Write-Host "       若正式機重灌過或 mkcert 重新初始化過，憑證需要整套重做（見 PASSKEY-CA-ROLLOUT.md）。"
    exit 1
}

# 憑證成功用過才存檔，避免把打錯的密碼存起來
if (-not (Test-Path $credPath) -or $Force) {
    $cred | Export-Clixml -Path $credPath
    Write-Host "      已把憑證存成 $credPath（DPAPI 加密，僅本機本帳號可解），下次不用再輸入密碼"
}

# ── 寫出並驗證 ──────────────────────────────────────────────────────────────
Write-Host "[3/3] 寫出並驗證..."
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
# PEM 是純 ASCII，用 ascii 編碼避免任何 BOM 混進憑證檔（certutil 對 BOM 很敏感）
Set-Content -Path $outFile -Value $r.Content -NoNewline -Encoding ascii

try {
    $cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $outFile
    Write-Host ""
    Write-Host "  主體     : $($cert.Subject)"
    Write-Host "  指紋     : $($cert.Thumbprint)"
    Write-Host "  有效期至 : $($cert.NotAfter)"
    Write-Host ""
    # 2026-09-10 在正式機實測到的指紋，用來確認拿到的是同一張
    $expected = "A9AF974F0BD6CE35B47CDB95CAA5E2B324DAE61C"
    if ($cert.Thumbprint -eq $expected) {
        Write-Host "  [OK] 指紋與 2026-09-10 在正式機實測的一致"
    } else {
        Write-Host "  [注意] 指紋與文件記載的 $expected 不同。"
        Write-Host "         若正式機的 CA 重新產生過，這是正常的——但 PASSKEY-CA-ROLLOUT.md"
        Write-Host "         裡的指紋要同步更新，而且**所有已安裝舊 CA 的電腦都要重裝**。"
    }
} catch {
    Write-Host "  [警告] 檔案寫出了，但無法解析成憑證：$($_.Exception.Message)"
    exit 1
}

Write-Host ""
Write-Host "完成！根 CA 已取回：$outFile"
Write-Host ""
Write-Host "下一步（PASSKEY-CA-ROLLOUT.md 第 5 步）——每一台要用 Passkey 的電腦都要做兩件事："
Write-Host "  (a) 安裝這張 CA（需系統管理員）："
Write-Host "      certutil -addstore -f Root `"$outFile`""
Write-Host "  (b) 讓該台電腦解析得到 motrix.internal。主網卡 DNS 是 8.8.8.8 的機器解析不到，"
Write-Host "      最省事的做法是加 hosts（需系統管理員）："
Write-Host "      Add-Content C:\Windows\System32\drivers\etc\hosts `"$ProdHost`tmotrix.internal`""
Write-Host "      只裝 CA 而沒有 (b)，瀏覽器仍然連不上 https://motrix.internal:666。"
Write-Host ""
