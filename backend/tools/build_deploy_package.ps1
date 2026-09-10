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

  【repo 範圍】本腳本的「git status 必須乾淨」與「git archive 打包」都只涵蓋
  MOTRIX-ERP 專案目錄範圍（用 git pathspec 限定）。
  2026-09-10 更正：先前這裡寫「這台開發機的 git repo 根目錄是整個使用者家目錄
  （C:\Users\hichan）」，那是 MOTRIX-ERP 還在家目錄 repo 底下時的情況；專案已於
  commit e6bf102 拆成獨立 git repo，$repoRoot 現在就是專案根目錄本身、$relPath
  恆為空字串（pathspec 等同「整個 repo」）。兩種情況本腳本都能正確運作，但看到
  「Project path:」那行印出空白時不要以為是壞掉了。
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

# --- Step 2: 記錄 commit / 分支資訊 ---
# 2026-09-08 修復：這裡原本排在 pytest（Step 3）之後才記錄 commit hash，
# 有個潛在的競態——如果打包過程中（pytest 跑 6+ 分鐘）repo 又有新的
# commit 進來（例如背景跑這支腳本的同時，另一個 session／終端機又
# commit 了新變更），Step 3 抓到的 HEAD 會是「pytest 剛剛跑完之後」的
# 最新狀態，可能已經不是「剛剛真正跑過 pytest 驗證」的那個 commit——
# archive 出來的部署包內容跟「已驗證通過測試」這個保證就對不上了。改成
# 在 pytest 開始前就先把 commit hash 釘住，之後全程使用這個變數，跟
# git 上實際 HEAD 之後有沒有異動無關。當晚實測過一次：這支腳本背景執行
# 期間，另一個對話動作確實在 pytest 跑到一半時對同一個 repo 做了新
# commit，只是那次剛好被既有的 flaky 測試提前擋下沒有走到 archive 那步，
# 沒有真的產出型別不一致的部署包，但這個競態本身是真實存在的，必須修。
$commit = (git rev-parse HEAD).Trim()
$commitShort = (git rev-parse --short HEAD).Trim()
$branch = (git rev-parse --abbrev-ref HEAD).Trim()

if ($branch -ne "master") {
    Write-Host "[WARN] 目前分支是 '$branch'，不是 'master'。依 GITFLOW.md，正式機理論上只套用 master 的內容，請確認這是預期行為。" -ForegroundColor Yellow
}

Write-Host "Commit:  $commit ($commitShort)"
Write-Host "Branch:  $branch"

# --- Step 1.5: 部署工具腳本語法驗證 ---
# 這批部署工具（apply_update.ps1／rollback_update.ps1／_dashboard_remote.ps1／
# build_deploy_package.ps1 自己）完全沒有 pytest 覆蓋，這裡的 git-status-乾淨
# 檢查也只管「有沒有 commit」，不管內容對不對——過去好幾次語法/邏輯 bug
# （tar 路徑解析成遠端主機語法、健康檢查誤判觸發不必要回滾等，見
# MOTRIX-ERP-QUICK.md §12）都是靠「真的在正式機套用一次」才發現。這裡先
# 擋掉最低成本能抓到的一種：語法本身就寫錯（漏括號、字串沒收尾等），不用
# 等正式機才發現腳本直接崩潰。只驗證語法（tokenize），不驗證邏輯正確性。
Write-Host "`n[語法檢查] 驗證 backend/tools/*.ps1 語法..."
$psFiles = Get-ChildItem (Join-Path $projectRoot "backend\tools") -Filter "*.ps1"
$syntaxOk = $true
foreach ($f in $psFiles) {
    $parseErrors = $null
    [System.Management.Automation.PSParser]::Tokenize((Get-Content $f.FullName -Raw), [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count -gt 0) {
        $syntaxOk = $false
        Write-Host "  [FAIL] $($f.Name)：" -ForegroundColor Red
        $parseErrors | ForEach-Object { Write-Host "    $($_.Message)" -ForegroundColor Red }
    }
}
if (-not $syntaxOk) {
    Fail "backend/tools/ 底下有 .ps1 語法錯誤，中止打包（見上方訊息）。"
}
Write-Host "[OK] 語法檢查通過（共 $($psFiles.Count) 支 .ps1）。" -ForegroundColor Green

# --- Step 2.5: 釘住 Python 直譯器並驗證依賴齊全（2026-09-10 新增）---
# 為什麼需要這一段：這台機器 PATH 上同時有 4 個 Python（hermes venv、Programs\
# Python313、WindowsApps shim、AppData\Local\Python\bin 的 PyManager shim），裸
# 呼叫 `python` 在不同呼叫環境會解析到不同一支。2026-09-10 就踩到——透過部署
# 儀表板（pythonw 子行程）觸發打包時解析到 pythoncore-3.14-64，那支沒裝
# python-multipart，於是所有走 Form/File 的端點測試在 fixture 階段就
# RuntimeError，整套 470 題幾乎全 E；而症狀要往下捲三千行才看得到真正的原因，
# 當下被誤讀成「測試壞了」。這跟 2026-09-08 的 tar 事故（Unix tar vs 內建
# tar.exe，commit 549d319）是同一個根因：**在腳本裡呼叫裸執行檔名，等於把
# 「用哪一支」交給呼叫端的 PATH 決定**。當時的結論只套用到 tar，沒有推廣到
# Python，這裡補上。
#
# 作法：先解析出實際路徑並印出來（之後所有 pytest 呼叫一律用 $pyExe，不再用
# 裸 python），再跑一次 import 檢查——缺套件就直接 Fail 並指名是哪一支
# Python、缺什麼，比讓 470 題全 E 好判讀太多。
# 2026-09-10 再修：原本這裡只做「解析出第一支 python → 缺套件就 Fail」。
# 擋是對的（總比 470 題全 E 好判讀），但這台機器 PATH 上有 4 支 Python，
# 「第一支」是誰完全取決於呼叫端的環境——我自己的 shell 解析到裝好依賴的
# venv、使用者自己的 PowerShell 解析到 WindowsApps 的 3.14 stub，同一支腳本
# 一個能跑一個不能，而使用者除了手動改 PATH 沒有別的辦法。
#
# 改成：把候選逐一試過去，挑第一支「依賴齊全」的來用；全都不合格才 Fail，
# 而且列出每一支各缺什麼。仍然印出實際選中的路徑（守門的原意是可追溯，
# 不是為了擋人）。
$depCheck = "import multipart, fastapi, uvicorn, pydantic, aiofiles, pyotp, qrcode, boto3, openpyxl, PIL, webauthn, cryptography"

$candidates = @()
$candidates += @(Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
$candidates += @(Get-Command python3 -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
# 專案內或常見的 venv 位置（PATH 上沒有時的後備）
foreach ($v in @("$projectRoot\venv\Scripts\python.exe",
                 "$projectRoot\.venv\Scripts\python.exe",
                 "$projectRoot\backend\venv\Scripts\python.exe")) {
    if (Test-Path $v) { $candidates += $v }
}
$candidates = @($candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique)

if ($candidates.Count -eq 0) {
    Fail "PATH 上找不到 python。請確認開發環境的 Python 可用後再重新執行。"
}

Write-Host "`n[環境] 找到 $($candidates.Count) 支 Python，逐一檢查依賴..."
# ⚠️ PS 5.1 原生執行檔 stderr 地雷（本專案第 5 次，前四次是 pip install／tar／
# db備份／mkcert）：$ErrorActionPreference = "Stop" 之下，只要原生執行檔往
# stderr 輸出任何東西、又用 2>&1 收進來，PowerShell 就會把它 promote 成終止型
# NativeCommandError——即使那正是我們**預期**會發生的事（這裡就是要靠 ImportError
# 判斷缺套件）。這個迴圈本來就會故意跑出 traceback，所以必須先切成 Continue。
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$pyExe = $null
$report = @()
foreach ($c in $candidates) {
    $ver = (& $c -c "import sys; print(sys.version.split()[0])" 2>$null)
    $out = (& $c -c $depCheck 2>&1)
    if ($LASTEXITCODE -eq 0) {
        Write-Host ("        [OK]   {0,-8} {1}" -f $ver, $c) -ForegroundColor Green
        if (-not $pyExe) { $pyExe = $c }
    } else {
        $missing = ($out | Select-String -Pattern "No module named '([^']+)'" |
                    ForEach-Object { $_.Matches[0].Groups[1].Value }) -join ", "
        if (-not $missing) { $missing = "無法執行" }
        Write-Host ("        [缺]   {0,-8} {1}  ← 缺 {2}" -f $ver, $c, $missing)
        $report += "  $c  (缺 $missing)"
    }
}

$ErrorActionPreference = $prevEAP

if (-not $pyExe) {
    Fail @"
所有找到的 Python 都缺少 backend/requirements.txt 列出的套件：
$($report -join "`n")
請對其中一支安裝依賴後重試，例如：
  & "$($candidates[0])" -m pip install -r "$projectRoot\backend\requirements.txt"
"@
}

Write-Host "[環境] 測試將使用：$pyExe" -ForegroundColor Green
Write-Host "[OK] 依賴齊全。" -ForegroundColor Green

# --- Step 3: 測試必須通過 ---
# 目前的把關只有「git status 乾淨」，不代表「這次 commit 沒把測試弄壞」——
# 曾經發生過測試治具過時、既有測試靜默失敗一段時間才被發現的情況。這裡直接
# 擋在打包之前，測試沒過就不產生部署包，避免明知有壞掉的測試還被拿去套用到
# 正式機。
#
# 2026-09-08：pytest.ini 標記的 e2e 測試（真實瀏覽器 Playwright，目前 3 題）
# 裡有一題 test_login_create_submit_approve_smoke 是已知 flaky——單獨跑穩定
# 通過，但夾在整套 460+ 題裡跑，偶爾因系統負載造成瀏覽器渲染逾時（非程式碼
# 邏輯問題，見 MOTRIX-ERP-QUICK.md §12 多次排查記錄，已推翻背景執行緒資源
# 洩漏等假設）。這一題卡住整條打包關卡好幾次，每次都要整套 6+ 分鐘重跑到
# 運氣好過關為止。改成兩段：非 e2e 測試（絕大多數、穩定）當硬性關卡，e2e
# 測試分開跑、失敗只警告不中止——e2e 測試本身仍然會執行（不是跳過不驗證），
# 只是「瀏覽器渲染在系統忙碌時偶發變慢」這種環境雜訊不該擋住整條部署管線，
# 這是架構地圖與 §12 早就記載的長期建議，這裡正式落地。
#
# 2026-09-09：非 e2e 這段加上 pytest-xdist 的 "-n auto"（動態分派給多個
# worker process）。動手前已先驗證過 backend/tests/conftest.py 的隔離機制
# （每題測試各自獨立的 tmp_path DB/檔案，沒有寫死路徑或 port）撐得住多
# process 平行跑：同一份 470 題非 e2e 測試序列跑一次、-n auto 跑一次，
# 兩邊 pass/fail 清單逐題比對完全一致，且序列 390 秒／平行 166 秒（約
# 2.35 倍加速）。之後不需要每次都「平行完再序列驗證一次」，那樣會抵銷
# 平行化的意義——這裡只是一次性把關，不是常態雙跑。
# 2026-09-10：移除原本對 test_daily_backup_writes_to_s3_and_marker_prevents_rerun
# 的 --deselect。那題不是真的不穩，是斷言範圍寫太寬（比對整個 fake S3 的物件
# 總數，會被同一 worker 上較早測試殘留、尚未結束的背景備份執行緒干擾），已改成
# 只比對每日備份前綴，測試本身修好了就不該再從關卡挖洞跳過它。
#
# 2026-09-10：加 --basetemp。%TEMP%\pytest-of-<user>\pytest-current 是 pytest 每次
# 執行都會重建的符號連結，這台機器上有一個目標讀不到的損壞 reparse point，
# os.stat() 回 WinError 5（不是「找不到」），pytest 的 cleanup_dead_symlinks 會
# 在 session 收尾整個炸掉——**測試全過也會回非 0**，而輸出最後一行是
# PermissionError，很容易被誤讀成測試失敗。指定獨立的 basetemp 可完全繞開；
# 要根治得用系統管理員權限 rd 掉那個連結（一般權限 Remove-Item/rd/del 全部
# Access denied，已實測）。
$pytestTemp = Join-Path $env:TEMP "motrix-pytest-$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Write-Host "`n[測試] 執行 pytest（非 e2e，backend/tests/，含 API 整合測試，pytest-xdist 平行化）..."
Push-Location (Join-Path $projectRoot "backend")
& $pyExe -m pytest -q -m "not e2e" -n auto --basetemp="$pytestTemp"
$testExit = $LASTEXITCODE
if ($testExit -ne 0) {
    Pop-Location
    Fail "測試未全數通過（exit code $testExit），中止打包。請先修好測試再重新執行本腳本。"
}
Write-Host "[OK] 非 e2e 測試全數通過。" -ForegroundColor Green

Write-Host "`n[測試] 執行 pytest（e2e，真實瀏覽器，失敗僅警告不中止打包）..."
& $pyExe -m pytest -q -m "e2e" --basetemp="${pytestTemp}_e2e"
$e2eExit = $LASTEXITCODE
Pop-Location
if ($e2eExit -ne 0) {
    Write-Host "[WARN] e2e 測試未全數通過（exit code $e2eExit）——已知這類測試偶爾因系統負載造成瀏覽器渲染逾時，非必然代表程式碼壞掉。繼續打包，但建議事後單獨重跑這個檔案確認（python -m pytest -m e2e -v）。" -ForegroundColor Yellow
} else {
    Write-Host "[OK] e2e 測試也全數通過。" -ForegroundColor Green
}

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
            Write-Host "[版本] version_manifest.json 最新一筆：$($versionLatest.version)（$($versionLatest.date)）"
        } else {
            Write-Host "[WARN] version_manifest.json 解析成功但沒有任何條目，版本標籤留空。" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[WARN] 無法解析 version_manifest.json（$($_.Exception.Message)），版本標籤留空。" -ForegroundColor Yellow
    }
} else {
    # 2026-09-10：原本這個 else 分支不存在——檔案找不到時會靜默留 null、不印
    # 任何東西，deploy_manifest.json 的 version_manifest_latest 就變成 null，
    # 事後完全看不出是「檔案沒找到」還是「解析失敗」。2026-09-10 那兩份部署包
    # 就是 null（見 WEEKLY-AUDIT §E-5）。這裡補上，讓靜默失敗變成看得見的警告。
    Write-Host "[WARN] 找不到 $versionManifestPath，版本標籤留空。" -ForegroundColor Yellow
}

# --- Step 5: 用 git archive 匯出乾淨快照 ---
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $OutDir) {
    $OutDir = Join-Path $projectRoot "deploy_packages"
}
$pkgDir = Join-Path $OutDir "${timestamp}_${commitShort}"
New-Item -ItemType Directory -Force -Path $pkgDir | Out-Null

Write-Host "`n[1/2] git archive 匯出至 $pkgDir..."
$tarPath = Join-Path $pkgDir "snapshot.tar"
# 匯出整個 commit 的內容（包含根目錄的所有檔案，符合 apply_update.ps1 預期）
git archive --format=tar -o $tarPath $commit
if ($LASTEXITCODE -ne 0) {
    Fail "git archive 失敗（exit code $LASTEXITCODE），部署包可能不完整，已中止。"
}

# === 解壓：這一段在 2026-09-08~09-10 之間來回改過三次，動之前先讀完 ===
#
# 這裡有「兩個」互相獨立的路徑歧義來源，只處理其中一個都還是會壞：
#
# (1) 用哪一支 tar。這台機器上同時存在 Windows 內建的 bsdtar
#     （%SystemRoot%\System32\tar.exe）與 Git for Windows 的 msys/GNU tar
#     （C:\Program Files\Git\usr\bin\tar.exe）。549d319（09-08）因為 Unix tar
#     把 C:\ 誤判成遠端主機而改用 System32 tar；942e3c4（09-10）又以「與
#     git archive 格式相容」為由改回優先挑 Git tar——但 git archive 產生的是
#     標準 POSIX tar，bsdtar 讀得好好的，這個理由並不成立，改回去之後
#     `/usr/bin/tar: Cannot connect to C: resolve failed` 立刻重現。
#     結論：優先用 System32 的 bsdtar，且寫完整路徑（不受 PATH 順序影響）。
#
# (2) 傳給 tar 的路徑長什麼樣。就算挑對了 tar，只要傳的是 C:\... 這種含冒號的
#     絕對路徑，老式 tar 的 `-f host:path` 遠端磁帶機語法就有機會再咬一次。
#     反正下面本來就 Push-Location 進 $pkgDir 了，直接傳相對檔名，讓這個問題
#     從根本上不存在——兩支 tar 都吃得下。
#
# 兩個都處理掉之後，就算日後 PATH 或 Git 安裝位置變動也不會再踩到。
$tarExe = Join-Path $env:SystemRoot "System32\tar.exe"
if (-not (Test-Path $tarExe)) {
    # 極少數環境沒有內建 bsdtar（Windows 10 1803 以前）才退回 Git tar。
    # 這條路徑要加 --force-local，明確告訴 GNU tar「檔名裡的冒號不是主機名」。
    $gitPaths = @(
        "C:\Program Files\Git\usr\bin\tar.exe",
        "C:\Program Files (x86)\Git\usr\bin\tar.exe"
    )
    $tarExe = $gitPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $tarExe) {
        Fail "找不到可用的 tar（既沒有 $env:SystemRoot\System32\tar.exe，也沒有 Git for Windows 的 tar）。"
    }
    $tarExtraArgs = @("--force-local")
} else {
    $tarExtraArgs = @()
}
$tarName = Split-Path $tarPath -Leaf
Write-Host "      解壓工具：$tarExe"
Push-Location $pkgDir
& $tarExe @tarExtraArgs -xf $tarName
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
