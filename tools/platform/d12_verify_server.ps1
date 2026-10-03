<#
  D12 真滑鼠拖放驗證用的「開發機」伺服器（不是正式機；資料是全新的測試資料，不會碰到任何正式資料）。

  用法（PowerShell，在這個資料夾的任何位置都可以）：
    powershell -ExecutionPolicy Bypass -File tools\platform\d12_verify_server.ps1          # 啟動（已在跑就只回報）
    powershell -ExecutionPolicy Bypass -File tools\platform\d12_verify_server.ps1 -Stop    # 停止

  做了什麼：在本工作樹（含 D12 預設開新設計器）的 backend 目錄，用專案 venv 起一個只聽本機（127.0.0.1）的 uvicorn，port 8870；
  建兩個標記檔（不寄信、不上雲端）；第一次啟動會建全新資料庫、把管理員 admin 的密碼設成驗證用的開發密碼、
  填一份假的本公司資料並確認、建一個「拖放驗證用」的測試模組草稿（d12demo）。再跑一次是冪等的（重複執行不會壞）。
  帳號：admin ／ 密碼：D12-verify-Mouse-2026（只在這台開發機有效）。
#>
param([switch]$Stop, [int]$Port = 8870)

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$py = 'D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe'
if (-not (Test-Path $py)) { $py = (Get-Command python -ErrorAction Stop).Source }

$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($Stop) {
    if ($conn) { Stop-Process -Id $conn.OwningProcess -Force; Write-Host "已停止（port $Port）" } else { Write-Host "沒有在跑（port $Port）" }
    exit 0
}
if ($conn) { Write-Host "已經在跑：http://localhost:$Port/（帳號 admin ／ 密碼 D12-verify-Mouse-2026）"; exit 0 }

New-Item -ItemType File -Force "$root\.no_cloud_archive", "$root\.no_email_send" | Out-Null
$env:MOTRIX_CREATE_NEW_DB = '1'
$logDir = Join-Path $root 'logs'; New-Item -ItemType Directory -Force $logDir | Out-Null
Start-Process -FilePath $py -ArgumentList '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', $Port `
    -WorkingDirectory "$root\backend" -WindowStyle Hidden `
    -RedirectStandardOutput "$logDir\d12-verify.out.log" -RedirectStandardError "$logDir\d12-verify.err.log" | Out-Null

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { break }
}
if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) { Write-Host "啟動失敗，請看 $logDir\d12-verify.err.log"; exit 1 }
& $py "$PSScriptRoot\d12_verify_seed.py" $Port
Write-Host "完成：http://localhost:$Port/（帳號 admin ／ 密碼 D12-verify-Mouse-2026）"
