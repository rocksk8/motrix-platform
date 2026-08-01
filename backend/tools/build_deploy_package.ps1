<#
  build_deploy_package.ps1 — 在「開發／測試機」執行

  用途：把目前 git 已 commit 的 backend/ + frontend/ + 根目錄文件，打包成一份
  可以複製到正式機、交給 apply_update.ps1 套用的部署包。

  重點：只打包「git 已追蹤且已 commit」的內容（git archive），不含任何未
  commit 的變更 —— 這是為了讓「拿去正式機套用的東西」永遠等於「git 上看得到
  的東西」，避免來源不可靠的問題（見 MOTRIX-ERP-QUICK.md §0 已知落差第 3 筆）。

  用法：
    powershell -ExecutionPolicy Bypass -File build_deploy_package.ps1
    powershell -ExecutionPolicy Bypass -File build_deploy_package.ps1 -OutDir D:\some\path

  執行前提：在此腳本所在的 git repo 根目錄（或其子目錄）下執行；
  git status 必須乾淨（沒有未 commit 的變更），否則中止。
#>

[CmdletBinding()]
param(
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

function Fail($msg) {
    Write-Host "`n[FAIL] $msg" -ForegroundColor Red
    exit 1
}

# --- 定位 repo 根目錄 ---
$repoRoot = (git rev-parse --show-toplevel 2>$null)
if (-not $repoRoot) {
    Fail "找不到 git repo（目前目錄不在任何 git 專案內）。請在 MOTRIX ERP 專案內執行本腳本。"
}
$repoRoot = $repoRoot -replace "/", "\"
Set-Location $repoRoot

Write-Host "======================================"
Write-Host "  MOTRIX ERP - Build Deploy Package"
Write-Host "======================================"
Write-Host "Repo root: $repoRoot`n"

# --- Step 1: git 狀態必須乾淨 ---
$dirty = git status --porcelain
if ($dirty) {
    Write-Host "目前有未 commit 的變更：" -ForegroundColor Yellow
    Write-Host $dirty
    Fail "請先 commit（或 stash）所有變更，再重新執行本腳本。打包內容只會包含已 commit 的版本，未 commit 的東西不會被打包，也不該被打包。"
}

# --- Step 2: 記錄 commit / 分支資訊 ---
$commit = (git rev-parse HEAD).Trim()
$commitShort = (git rev-parse --short HEAD).Trim()
$branch = (git rev-parse --abbrev-ref HEAD).Trim()

if ($branch -ne "master") {
    Write-Host "[WARN] 目前分支是 '$branch'，不是 'master'。依 GITFLOW.md，正式機理論上只套用 master 的內容，請確認這是預期行為。" -ForegroundColor Yellow
}

Write-Host "Commit:  $commit ($commitShort)"
Write-Host "Branch:  $branch"

# --- Step 3: 讀 version_manifest.json 最後一筆 ---
$versionManifestPath = Join-Path $repoRoot "backend\version_manifest.json"
$versionLatest = $null
if (Test-Path $versionManifestPath) {
    try {
        $entries = Get-Content $versionManifestPath -Raw | ConvertFrom-Json
        if ($entries -and $entries.Count -gt 0) {
            $versionLatest = $entries[-1]
        }
    } catch {
        Write-Host "[WARN] 無法解析 version_manifest.json，版本標籤留空。" -ForegroundColor Yellow
    }
}

# --- Step 4: 用 git archive 匯出乾淨快照 ---
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $OutDir) {
    $OutDir = Join-Path $repoRoot "deploy_packages"
}
$pkgDir = Join-Path $OutDir "${timestamp}_${commitShort}"
New-Item -ItemType Directory -Force -Path $pkgDir | Out-Null

Write-Host "`n[1/2] git archive 匯出至 $pkgDir ..."
$tarPath = Join-Path $pkgDir "snapshot.tar"
git archive --format=tar -o $tarPath $commit
Push-Location $pkgDir
tar -xf $tarPath
Remove-Item $tarPath
Pop-Location

# 部署包只需要 backend/ + frontend/ + 根目錄文件，其餘（如 .github/、測試用暫存檔等）
# git archive 本來就只會匯出 git 追蹤的內容，這裡不需要額外過濾。

# --- Step 5: 寫 deploy_manifest.json ---
$manifest = [ordered]@{
    commit               = $commit
    commit_short         = $commitShort
    branch               = $branch
    built_at             = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    version_manifest_latest = $versionLatest
}
$manifestPath = Join-Path $pkgDir "deploy_manifest.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding UTF8

Write-Host "[2/2] 寫入 deploy_manifest.json"

Write-Host "`n======================================"
Write-Host "  完成！部署包路徑：" -ForegroundColor Green
Write-Host "  $pkgDir" -ForegroundColor Green
Write-Host "======================================"
Write-Host ""
Write-Host "下一步（手動）："
Write-Host "  1. 把整個資料夾 '$pkgDir' 複製到正式機（隨身碟／網路芳鄰／雲端硬碟皆可）"
Write-Host "  2. 在正式機執行："
Write-Host "     powershell -ExecutionPolicy Bypass -File backend\tools\apply_update.ps1 -PackagePath <複製過去的路徑>"
Write-Host ""
