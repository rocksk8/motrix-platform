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
#>

[CmdletBinding()]
param(
    [string]$Host2 = "172.16.10.177"
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
$mkcert = Get-Command mkcert.exe -ErrorAction SilentlyContinue
if (-not $mkcert) {
    $localMkcert = Join-Path $PSScriptRoot "mkcert.exe"
    if (Test-Path $localMkcert) { $mkcert = Get-Item $localMkcert }
}
if (-not $mkcert) {
    Fail "找不到 mkcert.exe。請先下載並放進 backend\tools\ 目錄或系統 PATH：`n  https://github.com/FiloSottile/mkcert/releases`n（選 windows amd64 版本，下載後直接改名成 mkcert.exe 即可，不需要安裝）"
}
Info "使用 mkcert：$($mkcert.Source)"

if (-not (Test-Path $CertsDir)) {
    New-Item -ItemType Directory -Path $CertsDir | Out-Null
}

$certFile = Join-Path $CertsDir "cert.pem"
$keyFile  = Join-Path $CertsDir "key.pem"

if ((Test-Path $certFile) -and (Test-Path $keyFile)) {
    Info "`n憑證已存在：$certFile"
    Info "如果要重新產生（例如換過正式機 IP），請先手動刪除 backend\certs\ 底下的檔案再重跑這支腳本。"
    exit 0
}

Info "`n產生憑證中（SAN：$Host2, localhost, 127.0.0.1）..."
& $mkcert.Source -cert-file $certFile -key-file $keyFile $Host2 localhost 127.0.0.1
if ($LASTEXITCODE -ne 0) {
    Fail "mkcert 執行失敗（exit code $LASTEXITCODE）。"
}

Ok "憑證已產生：`n  $certFile`n  $keyFile"

Write-Host "`n======================================"
Write-Host "  下一步"
Write-Host "======================================"
Write-Host "1. 重新啟動服務（執行 restart.bat，或等 autostart.bat 迴圈下次自動重啟）"
Write-Host "2. 瀏覽器改用 https://${Host2}:666 連線"
Write-Host "3. 第一次連線瀏覽器會顯示「不安全」/「憑證無效」警告，這是預期行為"
Write-Host "   （因為沒有裝這張自簽憑證的 CA 到系統信任清單）——點「進階」→「繼續前往」即可"
Write-Host "4. 用 superadmin 登入後，記得到「通知設定」頁面把「系統網址」欄位手動改成"
Write-Host "   https://$($Host2):666 並存檔，否則系統寄出的通知信連結還是會指向舊的 http 版本"
