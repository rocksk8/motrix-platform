<#
  https_setup.ps1 — 在「正式機」執行一次

  用途：用 mkcert 產生自簽 TLS 憑證（含 SAN，涵蓋正式機 IP／localhost／127.0.0.1），
  放進 backend/certs/。三支啟動腳本（start.bat／restart.bat／autostart.bat）
  下次啟動時偵測到憑證存在就會自動改用 HTTPS，不需要另外改程式碼。

  刻意不加 `mkcert -install`：這次採取「不裝 CA 到每台電腦」的決策，公司內其他
  同事第一次連線會看到瀏覽器「不安全」警告，點「繼續前往」即可正常使用——傳輸
  本身仍是加密的，只是瀏覽器不認得這張自簽憑證的簽發者。

  前置需求：需要先手動下載 mkcert.exe（單一可執行檔，免安裝），放進
  backend/tools/ 目錄或系統 PATH：
    https://github.com/FiloSottile/mkcert/releases

  用法：
    powershell -ExecutionPolicy Bypass -File https_setup.ps1
    powershell -ExecutionPolicy Bypass -File https_setup.ps1 -Host2 172.16.10.177   # 正式機 IP 變動時可覆寫
    powershell -ExecutionPolicy Bypass -File https_setup.ps1 -ExtraNames motrix.internal
    powershell -ExecutionPolicy Bypass -File https_setup.ps1 -ExtraNames motrix.internal -Force

  2026-09-10 新增 -ExtraNames／-Force，起因是 Passkey：
  正式機的內部 DNS 已加了 motrix.internal -> 172.16.10.177，但既有憑證的 SAN
  只有 172.16.10.177 / localhost / 127.0.0.1（實測確認），用網域存取一定會出現
  憑證主機名不符的錯誤。WebAuthn 對「安全內容」很敏感，憑證有錯的頁面是不能
  指望 navigator.credentials 正常運作的——所以要用 motrix.internal 當 RP ID，
  就得先把它加進 SAN 重產憑證。
  另外原本腳本偵測到憑證已存在就直接 exit 0，要重產必須先手動刪檔；-Force
  改成自動備份舊憑證後重產，少一個容易忘的手動步驟。

  【重要決策點：要不要裝 CA】
  本腳本刻意不執行 `mkcert -install`（見上方說明），代價是每台電腦第一次連線
  都會看到「不安全」警告，點「繼續前往」後一般瀏覽功能都正常。但 Passkey／
  WebAuthn 不一定吃這一套——瀏覽器對憑證有錯的頁面會限制部分高權限 API。
  如果要正式啟用 Passkey，建議把 mkcert 的根 CA（mkcert -CAROOT 目錄下的
  rootCA.pem）匯入每台要用 Passkey 的電腦的「受信任的根憑證授權單位」，
  讓網址列是乾淨的鎖頭而不是警告。這件事會反轉上面那個「不裝 CA」的決策，
  屬於要人決定的事，本腳本不自作主張。
#>

[CmdletBinding()]
param(
    [string]$Host2 = "172.16.10.177",
    # 額外要寫進 SAN 的名稱（內部 DNS 網域等），可給多個
    [string[]]$ExtraNames = @(),
    # 憑證已存在時自動備份並重產，不用先手動刪檔
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Fail($msg) {
    Write-Host "`n[FAIL] $msg" -ForegroundColor Red
    exit 1
}
function Info($msg) { Write-Host $msg }
function Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }

Write-Host "======================================"
Write-Host "  MOTRIX ERP - HTTPS 憑證設定（自簽，不裝 CA）"
Write-Host "======================================"

$BackendDir = Split-Path -Parent $PSScriptRoot
$CertsDir = Join-Path $BackendDir "certs"

# --- 找 mkcert.exe（PATH 或 backend/tools/ 底下）---
# 注意：Get-Command 回傳的 ApplicationInfo 有 .Source，但 Get-Item 回傳的
# FileInfo 沒有這個屬性（只有 .FullName）——統一在這裡就轉成路徑字串，
# 避免後面 `& $mkcert.Source` 在走 backend/tools/ 這條分支時因為 .Source
# 是 $null 而炸掉（& $null ... 會丟「運算元後面的運算式產生的資料類型無效」）。
$mkcertPath = $null
$mkcertCmd = Get-Command mkcert.exe -ErrorAction SilentlyContinue
if ($mkcertCmd) {
    $mkcertPath = $mkcertCmd.Source
} else {
    $localMkcert = Join-Path $PSScriptRoot "mkcert.exe"
    if (Test-Path $localMkcert) { $mkcertPath = (Get-Item $localMkcert).FullName }
}
if (-not $mkcertPath) {
    Fail "找不到 mkcert.exe。請先下載並放進 backend\tools\ 目錄或系統 PATH：`n  https://github.com/FiloSottile/mkcert/releases`n（選 windows amd64 版本，下載後直接改名成 mkcert.exe 即可，不需要安裝）"
}
Info "使用 mkcert：$mkcertPath"

if (-not (Test-Path $CertsDir)) {
    New-Item -ItemType Directory -Path $CertsDir | Out-Null
}

$certFile = Join-Path $CertsDir "cert.pem"
$keyFile  = Join-Path $CertsDir "key.pem"

if ((Test-Path $certFile) -and (Test-Path $keyFile)) {
    if (-not $Force) {
        Info "`n憑證已存在：$certFile"
        Info "如果要重新產生（例如換過正式機 IP、或要把新的內部網域加進 SAN），"
        Info "請加上 -Force（會自動備份舊憑證），或手動刪除 backend\certs\ 底下的檔案再重跑。"
        Info "`n目前這張憑證的 SAN 可以這樣查："
        Info "  `$c = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2('$certFile')"
        Info "  (`$c.Extensions | Where-Object { `$_.Oid.Value -eq '2.5.29.17' }).Format(`$true)"
        Info "  （用 OID 2.5.29.17 而不是 FriendlyName——中文版 Windows 會把它在地化成「主體別名」，"
        Info "    用英文字串比對會查不到，誤以為憑證沒有 SAN）"
        exit 0
    }
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backupDir = Join-Path $CertsDir "backup_$stamp"
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Copy-Item $certFile $backupDir -Force
    Copy-Item $keyFile  $backupDir -Force
    Ok "舊憑證已備份至：$backupDir"
    Remove-Item $certFile, $keyFile -Force
}

# SAN 清單：正式機 IP + loopback 兩種寫法 + 呼叫端額外指定的名稱（如內部 DNS 網域）
$sanNames = @($Host2, "localhost", "127.0.0.1") + $ExtraNames | Where-Object { $_ } | Select-Object -Unique
Info "`n產生憑證中（SAN：$($sanNames -join ', ')）..."
& $mkcertPath -cert-file $certFile -key-file $keyFile @sanNames
if ($LASTEXITCODE -ne 0) {
    Fail "mkcert 執行失敗（exit code $LASTEXITCODE）。"
}

Ok "憑證已產生：`n  $certFile`n  $keyFile"

# 產完立刻把 SAN 印出來核對——這次就是因為沒人查過 SAN，才會一路做到要設定
# RP ID 時才發現網域根本不在憑證裡。
try {
    $newCert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($certFile)
    $sanExt = $newCert.Extensions | Where-Object { $_.Oid.Value -eq "2.5.29.17" }
    if ($sanExt) {
        Info "`n實際寫入憑證的 SAN（請核對你要的名稱都在裡面）："
        Info ($sanExt.Format($true))
    }
} catch {
    Info "（無法讀回憑證核對 SAN，不影響憑證本身：$($_.Exception.Message)）"
}

Write-Host "`n======================================"
Write-Host "  下一步"
Write-Host "======================================"
Write-Host "1. 重新啟動服務（執行 restart.bat，或等 autostart.bat 迴圈下次自動重啟）"
Write-Host "2. 瀏覽器改用 https://${Host2}:666 連線"
Write-Host "3. 第一次連線瀏覽器會顯示「不安全」/「憑證無效」警告，這是預期行為"
Write-Host "   （因為沒有裝這張自簽憑證的 CA 到系統信任清單）——點「進階」→「繼續前往」即可"
Write-Host "4. 用 superadmin 登入後，記得到「通知設定」頁面把「系統網址」欄位手動改成"
Write-Host "   https://$($Host2):666 並存檔，否則系統寄出的通知信連結還是會指向舊的 http 版本"
