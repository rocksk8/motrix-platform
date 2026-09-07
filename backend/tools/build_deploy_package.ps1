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

  【重要】這台開發機的 git repo 根目錄是整個使用者家目錄（C:\Users\hichan），
  不是 MOTRIX-ERP 專案本身——家目錄底下永遠會有大量跟本專案無關的未追蹤個人
  檔案。因此本腳本的「git status 必須乾淨」與「git archive 打包」都只會檢查/
  匯出 MOTRIX-ERP 這個子目錄範圍（用 git pathspec 限定），不會管家目錄其他地方
  乾不乾淨，也不會把其他地方的內容打包進去。
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

# --- 定位 repo 根目錄與專案子目錄 ---
$repoRoot = (git rev-parse --show-toplevel 2>$null)
if (-not $repoRoot) {
    Fail "找不到 git repo（目前目錄不在任何 git 專案內）。請在 MOTRIX ERP 專案內執行本腳本。"
}
$repoRoot = $repoRoot -replace "/", "\"

# 本腳本位於 <專案根目錄>\backend\tools\ 下，往上兩層即為專案根目錄
# （不管專案實際被放在 git repo底下哪個路徑，都能正確算出來）
$projectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName

# 專案根目錄相對於 repo 根目錄的路徑，轉成 git pathspec 用的正斜線格式
if (-not $projectRoot.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    Fail "專案目錄 '$projectRoot' 不在 git repo '$repoRoot' 底下，無法定位 pathspec。"
}
$relPath = $projectRoot.Substring($repoRoot.Length).TrimStart('\') -replace '\\', '/'

Set-Location $repoRoot

Write-Host "======================================"
Write-Host "  MOTRIX ERP - Build Deploy Package"
Write-Host "======================================"
Write-Host "Repo root:     $repoRoot"
Write-Host "Project path:  $relPath （本次 git status／打包範圍只限這裡）`n"

# --- Step 1: git 狀態必須乾淨（只看專案子目錄範圍） ---
$dirty = git status --porcelain -- $relPath
if ($dirty) {
    Write-Host "專案目錄（$relPath）內目前有未 commit 的變更：" -ForegroundColor Yellow
    Write-Host $dirty
    Fail "請先 commit（或 stash）所有變更，再重新執行本腳本。打包內容只會包含已 commit 的版本，未 commit 的東西不會被打包，也不該被打包。"
}

# --- Step 2: 測試必須通過 ---
# 目前的把關只有「git status 乾淨」，不代表「這次 commit 沒把測試弄壞」——
# 曾經發生過測試治具過時、既有測試靜默失敗一段時間才被發現的情況。這裡直接
# 擋在打包之前，測試沒過就不產生部署包，避免明知有壞掉的測試還被拿去套用到
# 正式機。
Write-Host "`n[測試] 執行 pytest（backend/tests/，含 API 整合測試）..."
Push-Location (Join-Path $projectRoot "backend")
python -m pytest -q
$testExit = $LASTEXITCODE
Pop-Location
if ($testExit -ne 0) {
    Fail "測試未全數通過（exit code $testExit），中止打包。請先修好測試再重新執行本腳本。"
}
Write-Host "[OK] 測試全數通過。" -ForegroundColor Green

# --- Step 3: 記錄 commit / 分支資訊 ---
$commit = (git rev-parse HEAD).Trim()
$commitShort = (git rev-parse --short HEAD).Trim()
$branch = (git rev-parse --abbrev-ref HEAD).Trim()

if ($branch -ne "master") {
    Write-Host "[WARN] 目前分支是 '$branch'，不是 'master'。依 GITFLOW.md，正式機理論上只套用 master 的內容，請確認這是預期行為。" -ForegroundColor Yellow
}

Write-Host "Commit:  $commit ($commitShort)"
Write-Host "Branch:  $branch"

# --- Step 4: 讀 version_manifest.json 最新一筆（陣列最前面，新條目永遠插最前面） ---
$versionManifestPath = Join-Path $projectRoot "backend\version_manifest.json"
$versionLatest = $null
if (Test-Path $versionManifestPath) {
    try {
        # -Encoding UTF8：這個檔案沒有 BOM，PowerShell 5.1 的 Get-Content 在繁中
        # Windows 上預設會用系統內碼（cp950）猜編碼，讀到中文附近會亂碼進而
        # 解析失敗，必須強制指定 UTF8 才能正確讀取。
        $entries = Get-Content $versionManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($entries -and $entries.Count -gt 0) {
            $versionLatest = $entries[0]
        }
    } catch {
        Write-Host "[WARN] 無法解析 version_manifest.json，版本標籤留空。" -ForegroundColor Yellow
    }
}

# --- Step 5: 用 git archive 匯出乾淨快照 ---
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $OutDir) {
    $OutDir = Join-Path $projectRoot "deploy_packages"
}
$pkgDir = Join-Path $OutDir "${timestamp}_${commitShort}"
New-Item -ItemType Directory -Force -Path $pkgDir | Out-Null

Write-Host "`n[1/2] git archive 匯出至 $pkgDir （範圍限定 $relPath）..."
$tarPath = Join-Path $pkgDir "snapshot.tar"
# <commit>:<relPath> 是 git 的 tree-ish 語法，直接指到子目錄的 tree 物件，
# 匯出的檔案會以 backend/、frontend/ 等開頭（不帶 Desktop/MOTRIX-ERP/ 前綴），
# 符合 apply_update.ps1 預期的部署包結構。
git archive --format=tar -o $tarPath "${commit}:${relPath}"
if ($LASTEXITCODE -ne 0) {
    Fail "git archive 失敗（exit code $LASTEXITCODE），部署包可能不完整，已中止。"
}

# 2026-09-08 修復：bare `tar` 在某些呼叫環境下（例如透過 deploy_dashboard.py
# 這類外部 Python process 啟動、繼承了不同 PATH 順序的情境）會解析到 Git for
# Windows 內建的 Unix 風格 tar（通常在 Git\usr\bin\tar.exe），而不是 Windows
# 內建的 BSD tar（System32\tar.exe）——Unix tar 把 `C:\Users\...` 這種路徑的
# 開頭 `C:` 誤判成「要連線的遠端主機」語法（老式 tar 的 -f host:path 遠端磁帶
# 機用法），直接印「Cannot connect to C: resolve failed」失敗，且這行呼叫沒有
# 任何 exit code 檢查，會靜默放行、產出只有 deploy_manifest.json 的空殼部署包
# ——實際發生過一次，見 §12 2026-09-08 條目。改用完整路徑指定 Windows 內建的
# tar.exe，徹底避開 PATH 解析順序的不確定性；並補上退出碼檢查。
$tarExe = Join-Path $env:SystemRoot "System32\tar.exe"
Push-Location $pkgDir
& $tarExe -xf $tarPath
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    Fail "tar 解壓失敗（exit code $LASTEXITCODE），部署包不完整，已中止。"
}
Remove-Item $tarPath
Pop-Location

# 額外驗證：確認真的解壓出東西，不要只信 exit code（防禦縱深——即使兩個
# exit code 檢查都誤判通過，這裡再擋一次明顯不合理的空殼輸出）。
if (-not (Test-Path (Join-Path $pkgDir "backend")) -or -not (Test-Path (Join-Path $pkgDir "frontend"))) {
    Fail "部署包解壓後找不到 backend/ 或 frontend/ 目錄，內容不完整，已中止。請檢查 $pkgDir。"
}

# 部署包只需要 backend/ + frontend/ + 根目錄文件，其餘（如 .github/、測試用暫存檔等）
# git archive 本來就只會匯出 git 追蹤的內容，這裡不需要額外過濾。

# --- Step 6: 寫 deploy_manifest.json ---
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
