# 正式機診斷腳本

Write-Host "=== MOTRIX ERP 正式機診斷 ===" -ForegroundColor Cyan
Write-Host "執行時間: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

# 1. 檢查版本
Write-Host "`n[1] 檢查部署版本..." -ForegroundColor Yellow
$deployPath = "backend\.deployed_commit.json"
if (Test-Path $deployPath) {
    $deployed = Get-Content $deployPath -Encoding UTF8 | ConvertFrom-Json
    Write-Host "已部署 commit: $($deployed.commit)"
    Write-Host "部署時間: $($deployed.deployed_at)"
} else {
    Write-Host "未找到 .deployed_commit.json" -ForegroundColor Red
}

# 2. 檢查服務
Write-Host "`n[2] 檢查 uvicorn 進程..." -ForegroundColor Yellow
$procs = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "uvicorn" }
if ($procs) {
    Write-Host "找到 uvicorn (PID: $($procs[0].Id))"
} else {
    Write-Host "uvicorn 未運行" -ForegroundColor Red
}

# 3. 測試連線
Write-Host "`n[3] 測試 localhost:666..." -ForegroundColor Yellow
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:666/api/ping" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
    Write-Host "/api/ping 回應: HTTP $($resp.StatusCode)"
} catch {
    Write-Host "連線失敗: $($_.Exception.Message)" -ForegroundColor Red
}

# 4. 檢查 log
Write-Host "`n[4] 最近 server.log..." -ForegroundColor Yellow
$logPath = "backend\logs\server.log"
if (Test-Path $logPath) {
    Get-Content $logPath -Tail 10 -Encoding UTF8
} else {
    Write-Host "server.log 找不到" -ForegroundColor Red
}

Write-Host "`n=== 診斷完成 ===" -ForegroundColor Cyan
