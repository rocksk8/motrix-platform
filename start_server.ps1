<#
  MOTRIX ERP — 一鍵啟動/停止開發伺服器

  用法：
  1. 在此資料夾中右鍵點選此檔案 → 選「使用 PowerShell 執行」
  2. 或直接在 PowerShell 中執行：powershell -ExecutionPolicy Bypass -File start_server.ps1
#>

$ProjectRoot = Get-Location
$BackendDir = "$ProjectRoot\backend"
$Port = 5000

Write-Host @"
╔════════════════════════════════════════════╗
║     MOTRIX ERP 開發伺服器啟動工具         ║
╚════════════════════════════════════════════╝
"@ -ForegroundColor Cyan

# 檢查是否已有 uvicorn 運行在指定 port
$Process = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
if ($Process) {
    Write-Host "✓ 伺服器已在運行 (Port $Port)" -ForegroundColor Green
    Write-Host "`n選擇操作：" -ForegroundColor Yellow
    Write-Host "  1 - 停止伺服器"
    Write-Host "  2 - 重新啟動"
    Write-Host "  3 - 退出"
    $Choice = Read-Host "`n請輸入 (1-3)"

    switch ($Choice) {
        "1" {
            Write-Host "`n正在停止伺服器..." -ForegroundColor Yellow
            Get-Process | Where-Object { $_.Port -eq $Port -or ($_.ProcessName -like "*uvicorn*" -or $_.ProcessName -like "*python*") } | Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
            Write-Host "✓ 伺服器已停止" -ForegroundColor Green
            exit 0
        }
        "2" {
            Write-Host "`n正在重新啟動..." -ForegroundColor Yellow
            Get-Process | Where-Object { $_.ProcessName -like "*uvicorn*" -or $_.ProcessName -like "*python*" } | Stop-Process -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
        default { exit 0 }
    }
}

Write-Host "`n啟動開發伺服器..." -ForegroundColor Yellow
Write-Host "位置: $BackendDir" -ForegroundColor Gray
Write-Host "埠號: $Port`n" -ForegroundColor Gray

# 檢查 Python 環境
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "❌ 找不到 Python，請先安裝 Python 3.10+" -ForegroundColor Red
    Read-Host "按 Enter 鍵退出"
    exit 1
}

# 進入後端目錄
Set-Location $BackendDir

# 檢查依賴
Write-Host "檢查依賴..." -ForegroundColor Gray
$RequirementsFile = "requirements.txt"
if (Test-Path $RequirementsFile) {
    Write-Host "安裝依賴 (如需要)..." -ForegroundColor Gray
    pip install -q -r $RequirementsFile
    if (-not $?) {
        Write-Host "❌ 依賴安裝失敗" -ForegroundColor Red
        Read-Host "按 Enter 鍵退出"
        exit 1
    }
}

# 啟動伺服器
Write-Host "✓ 伺服器啟動成功！" -ForegroundColor Green
Write-Host "`n📍 訪問地址：http://localhost:$Port" -ForegroundColor Cyan
Write-Host "📁 前端位置：$(Join-Path $ProjectRoot 'frontend')" -ForegroundColor Gray
Write-Host "🛑 關閉此視窗可停止伺服器`n" -ForegroundColor Yellow

# 啟動 uvicorn
uvicorn main:app --host 0.0.0.0 --port $Port --reload

if ($?) {
    Write-Host "`n✓ 伺服器已優雅關閉" -ForegroundColor Green
} else {
    Write-Host "`n❌ 伺服器異常停止" -ForegroundColor Red
}

Read-Host "`n按 Enter 鍵退出"
