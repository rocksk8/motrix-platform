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
    [string]$OutDir = "",
    # 保留幾份部署包（2026-09-15 使用者要求：「當第三個打包檔的時候自動刪除第一個
    # 打包檔，避免重複堆積」）。0 = 不清理。清理在新包**完整產出並通過驗證之後**
    # 才執行，見 Step 7。
    [int]$KeepPackages = 2
)

$ErrorActionPreference = "Stop"

# ── 計時與統計（2026-09-22，使用者問「打包的時間為什麼會越來越久」）──────
#
# 🔴 問到這一題的時候，我們發現**答不出來**：`deploy_manifest.json` 只記
# commit／branch／built_at，**沒有記耗時也沒有記題數** ⇒ 「越來越久」無法從
# 產物查證，只能靠某個人當時的紀錄，而那份紀錄的原始輸出已經不存在。
# 🔑 ⇒ 下面這些欄位的價值**不在這一次**，是「下一次有人問同一個問題時，
#    答案在產物裡而不在誰的記憶裡」。
$BuildT = [ordered]@{}
$BuildStats = [ordered]@{}
$BuildStart = Get-Date

function Mark-Elapsed($name, $from) {
    $BuildT[$name] = [math]::Round(((Get-Date) - $from).TotalSeconds, 2)
}

function Parse-PytestSummary($lines) {
    # 最後那一行 `N passed, M skipped in X.XXs` 拆成數字。拆不出來留 $null。
    #
    # 這裡原本被我寫成 Python 的三引號 docstring —— PowerShell 會把它當成
    # 一個**字串運算式**，而運算式的值會被送進輸出串流
    # => 這支函式會回「字串 ＋ 雜湊表」兩個東西，而不是一個雜湊表。
    # 語法檢查不會紅（它是合法的 PowerShell），而呼叫端拿到的東西是錯的。
    # 「換一種語言寫註解」在這裡不是風格問題，是行為問題。
    $out = [ordered]@{ passed = $null; failed = $null; skipped = $null }
    foreach ($ln in ($lines | Select-Object -Last 12)) {
        $t = [string]$ln
        if ($t -match "(\d+) passed") { $out.passed = [int]$Matches[1] }
        if ($t -match "(\d+) failed") { $out.failed = [int]$Matches[1] }
        if ($t -match "(\d+) skipped") { $out.skipped = [int]$Matches[1] }
    }
    return $out
}

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
# RG19：記下「跑測試之前」的樣子，Step 3.1 會拿它來比對。
# ⚠️ 用 `@()` 包起來：只有一列時 PowerShell 會給一個字串而不是陣列，
# ☠️ 而 `-notin` 對字串是逐字元比對 —— 那會讓比對變成一個永遠成立的東西。
$dirtyBefore = @($dirty)
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

# --- Step 1.6: 版本紀錄不可以舊於要打包的那個 commit（2026-09-22 新增，§13 VR1）---
# 使用者在 2026-09-22 指出「系統內的版本紀錄還停在 9/15」。那七天有幾百個
# commit，而「版本紀錄」頁面上一筆新的都沒有。
#
# ⚠️ 把 9/16~9/22 補上是**修結果**：補完之後，第八天一樣會停。
# 🔑 會讓下一次不可能發生的是**這道關卡** —— 沒有寫紀錄就打不出包。
#
# 【為什麼排在這裡】它只用到 git 跟 PowerShell 內建的 JSON 解析，不需要
# Python（要用哪一支 Python 是 Step 2.5 才決定的），成本大約 0.1 秒。
# ⇒ 同 Step 2.55 的判準：**便宜又會擋的檢查排最前面。**
#
# 📌 刻意只比**日期**，不比時分：「先 commit、再補寫紀錄」是正常的順序，
# 比到時分的話那個正常順序會被判紅。要擋的是**整批遺忘**，不是順序。
#
# 📌 用 Step 2 釘住的 $commit，不是現在的 HEAD ——
# 要驗的是「**這一包**裡的東西有沒有被記錄」，不是「repo 現在長怎樣」。
Write-Host "`n[版本紀錄] 檢查 version_manifest.json 跟不跟得上 commit..."
$vmPath = Join-Path $projectRoot "backend\version_manifest.json"
if (-not (Test-Path $vmPath)) {
    # ☠️ 找不到檔案**不是跳過，是紅的**：一道「檔案不見就自動消失」的守門，
    # 在輸出上跟一道「通過了」的守門長得一模一樣。
    Fail "找不到 $vmPath，版本紀錄守門無法判定。這道檢查不會因為讀不到檔案就放行。"
}
try {
    # -Encoding UTF8：同 Step 4 —— PS 5.1 在繁中 Windows 上會用 cp950 猜編碼。
    $vmParsed = Get-Content $vmPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    $vmParsed = $null
}
# ⚠️ **先接成變數，再 `@()`。**
# PS 5.1 的 `ConvertFrom-Json` 讀到一個 JSON 陣列時，往 pipeline 送的是
# **一個東西**（那個陣列本身），不是 361 個。
# ☠️ 直接寫 `@(... | ConvertFrom-Json)` 的話，會得到一個「裡面裝著陣列」的
#    單元素陣列 —— `.Count` 是 1、`[0]` 是整個陣列，而 `[0].date` 會
#    member-enumerate 成 361 個日期串在一起。實測過，訊息長達 361 個日期。
# 🔑 `@($變數)` 才會正常展開（管線化一個變數會逐一送出）。
$vmEntries = @($vmParsed)
if (-not $vmEntries -or $vmEntries.Count -eq 0) {
    Fail "version_manifest.json 讀不出任何紀錄（檔案壞掉或是空陣列）。在版本紀錄讀不出來的狀態下打包，等於把這道守門關掉。"
}

$vmDates = @($vmEntries | ForEach-Object { $_.date } | Where-Object { $_ -match "^\d{4}-\d{2}-\d{2}$" })
if ($vmDates.Count -eq 0) {
    Fail "version_manifest.json 裡一筆有日期的紀錄都沒有（或日期格式不是 YYYY-MM-DD）。"
}
# ⚠️ 不要用 `Measure-Object -Maximum`：PS 5.1 的它只吃數字，一串字串會回空，
# 🔑 而回空之後下面拿 $null 去比較 —— **那會通過**。
$vmNewest = ($vmDates | Sort-Object | Select-Object -Last 1)

$commitDate = git show -s --format=%cs $commit
$gitDateExit = $LASTEXITCODE
$commitDate = "$commitDate".Trim()
if ($gitDateExit -ne 0 -or $commitDate -notmatch "^\d{4}-\d{2}-\d{2}$") {
    # ☠️ 量尺本身壞掉的時候**不可以**當成通過：`"" -lt ""` 是假的，
    # 🔑 也就是說一個「什麼都沒量到」的比較，會給你它能給的最好結果。
    Fail "取不到 commit $commitShort 的日期（git exit=$gitDateExit，值='$commitDate'）。守門在量不到的時候一律擋下，不放行。"
}

if ($vmNewest -lt $commitDate) {
    Write-Host "  版本紀錄最新一筆：$vmNewest" -ForegroundColor Yellow
    Write-Host "  這一包的 commit ：$commitDate（$commitShort）" -ForegroundColor Yellow
    # 警告：不要在這裡教人用 git log --since。
    # D 在 2026-09-22 實測過：--since/--until 得 73 筆，完整 git log
    # 再自己過濾得 74 筆 —— 漏掉的正是 b6e29ea（2026-09-16，Passkey 備份
    # BLOB，也就是這整串缺陷最早的那個受害者）。
    # 走訪剪枝在這段「兩天爆量」的歷史上不可靠，而它漏掉的那一筆，
    # 看起來跟「那天本來就沒有東西可以寫」一模一樣。
    # 這裡是**唯一一個會被人照著打**的地方，指錯工具等於把缺陷寫進修法。
    @'
  補這一段的來源（不是記憶）：
    git log --pretty='%ad|%h|%s' --date=short | awk -F'|' '$1>="<起日>" && $1<="<迄日>"'
  再對照 docs/windows/STATE.md 這幾天新增的節。
'@ | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
    Fail "版本紀錄停在 $vmNewest，而這一包的 commit 是 $commitDate —— 中間這段時間出貨的東西，使用者在『版本紀錄』頁面上一筆都看不到。請先補上 backend\version_manifest.json（來源見上方指令），再重新打包。"
}

# 📌 順帶驗 Step 4 依賴的那個假設：它直接取 $entries[0] 當版本標籤。
# ☠️ 有人把新紀錄接在**結尾**的話，上面那一題照樣綠（最大值確實是新的），
#    而 deploy_manifest.json 的版本標籤會標到一筆舊的 —— 安靜地錯。
$vmFirstDate = "$($vmEntries[0].date)".Trim()
if ($vmFirstDate -ne $vmNewest) {
    Fail "version_manifest.json 的第一筆日期是 '$vmFirstDate'，但最新的是 '$vmNewest'。新紀錄必須插在陣列**最前面**：Step 4 直接取第一筆當這個部署包的版本標籤，順序不對的話包上會標到一筆舊的版本，而且不會有任何錯誤訊息。"
}
Write-Host "[OK] 版本紀錄共 $($vmEntries.Count) 筆，最新一筆 $vmNewest，不舊於這一包的 commit（$commitDate）。" -ForegroundColor Green

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

# --- Step 2.52: 版本紀錄的反方向（2026-09-22 新增，§13 VR7）---
# Step 1.6 守的是「manifest 舊於這一包的 commit」。A-2 指出它只守一半：
#   manifest 有、DB 沒有   正常 —— 服務還沒重啟，下次開機會同步進去
#   DB 有、manifest 沒有   🔴 重建資料庫就永久消失，而 Step 1.6 看不到
# 實際發生過：四筆 2026-08-01 的紀錄只活在資料庫裡，已經 52 天。
#
# 【為什麼不併進 Step 1.6】那一關只用 git 與 PS 內建 JSON，這一關要讀 SQLite，
# 而 PowerShell 5.1 沒有 SQLite ⇒ 需要 Python，也就是要等 Step 2.5 挑完直譯器。
#
# ⚠️ **讀不到資料庫是失敗，不是跳過。** 一道從來不會觸發的守門，
# 跟一道運作良好的守門在輸出上完全一樣。
Write-Host "`n[版本紀錄] 反方向檢查：資料庫裡有而 manifest 沒有的..."
$vsyncScript = Join-Path $projectRoot "backend\tools\check_version_sync.py"
if (-not (Test-Path $vsyncScript)) {
    Fail "找不到 $vsyncScript —— VR7 的守門無法執行。這道檢查不會因為腳本不見就放行。"
}
# ⚠️ 第二道（第一道在 `check_version_sync.py` 裡自己 reconfigure stdout）。
# ☠️ 這台機器的主控台預設是 cp932 ⇒ 中文輸出會丟 UnicodeEncodeError
#    ⇒ 行程 exit 1 ⇒ **這裡會判成「守門沒過」，而它其實過了。**
# 🔑 兩道都留：腳本會被人直接跑，而這裡也會有下一支中文輸出的腳本。
$prevIoEnc3 = $env:PYTHONIOENCODING
$env:PYTHONIOENCODING = "utf-8"
try {
    & $pyExe $vsyncScript | ForEach-Object { Write-Host "  $_" }
    $vsyncExit = $LASTEXITCODE
} finally {
    $env:PYTHONIOENCODING = $prevIoEnc3
}
if ($vsyncExit -ne 0) {
    Fail "版本紀錄反方向守門沒過（見上方訊息）。資料庫裡有而 manifest 沒有的紀錄，在重建資料庫或災難還原之後會永久消失，而畫面上不會有任何跡象。"
}

# --- Step 2.55: 規格覆蓋率守門（2026-09-22 新增，YC）---
# 【為什麼排在這裡】這道檢查自己只跑 0.73 秒，而它抓的東西（規格宣告了條件
# 而沒有人寫測試／測試宣稱一個規格沒有的編號）跟「測試會不會通過」完全無關
# ——它在 Step 3 之前就能判定。
#
# 過去它排在 Step 3（全量測試）之後，所以每一次「忘了登記」都要先等
# 431 秒的完整測試跑完才會知道。2026-09-22 一天因此損失兩次 7 分 11 秒。
# 判準：**便宜又會擋的檢查排最前面。**
#
# ⚠️ 為什麼不是排在 Step 1.5（YC1 的字面位置）之後：這道檢查要用 Python，
# 而**挑哪一支 Python 是 Step 2.5 才決定的**（這台機器 PATH 上有 4 支，
# 其中幾支缺依賴 —— 那正是 Step 2.5 存在的理由）。
# 🔑 排在 Step 2.5 之前就得裸呼叫 `python`，而那是 Step 2.5 要防的那個 bug。
# ⇒ 挪到 Step 2.5 之後，省下的時間一樣（Step 2.5 只有幾秒）。
#
# ⚠️ **Step 3 照舊會再跑它一次，不要因為這裡跑過就排除掉。**
# 🔑 前面這次是「快速攔截」，後面那次是「最終關卡」——目的不同：
# 中間任何一步都可能改到檔案（例如有人在打包途中 commit），
# 而**只在前面擋一次的話，最終產出就沒有被那道守門看過。**
Write-Host "`n[覆蓋率] 規格條件與測試的對應（快速攔截，Step 3 會再跑一次）..."
$coverageTest = "backend\tests\test_spec_coverage_2026_09_21.py"
if (Test-Path (Join-Path $projectRoot $coverageTest)) {
    $prevIoEnc2 = $env:PYTHONIOENCODING
    $env:PYTHONIOENCODING = "utf-8"
    Push-Location $projectRoot
    try {
        # ⚠️ `--basetemp` 是**必要的**，不是省事：這個 repo 的 conftest
        # 明確拒絕沒有指定 basetemp 的執行：`%TEMP%\pytest-of-<user>\pytest-current` 是共用的，另一個視窗同時在跑就會互相刪對方
        # 的暫存目錄）。⇒ 漏掉它的話這道守門**每次都以 ERROR 收場**，
        # 而那會被讀成「覆蓋率沒過」。
        $covTemp = Join-Path $env:TEMP "motrix-pytest-cov-$(Get-Date -Format 'yyyyMMdd_HHmmss')"
        & $pyExe -m pytest $coverageTest -q --no-header --basetemp="$covTemp" 2>&1 |
            ForEach-Object { Write-Host "  $_" }
        $covExit = $LASTEXITCODE
    } finally {
        Pop-Location
        $env:PYTHONIOENCODING = $prevIoEnc2
    }
    if ($covExit -ne 0) {
        # ⚠️ **一個字串，不要用 `+` 串** —— PowerShell 的參數位置不是運算式，
        # `Fail "a" + "b"` 會把三個東西當成三個參數傳進去（而 `Fail` 只收一個
        # ⇒ 後面兩段安靜消失）。語法檢查抓不到這一種。
        Fail "規格覆蓋率守門沒過（見上方訊息）。這道檢查只花不到一秒，所以它排在全量測試之前——先把登記補完再打包，不要等 7 分鐘。"
    }
    Write-Host "[OK] 覆蓋率守門通過。" -ForegroundColor Green
} else {
    # ⚠️ 找不到就**明說**，不要靜靜跳過：一道「檔案不見了就自動消失」的守門，
    # 跟一道「通過了」的守門在輸出上長得一樣。
    Write-Host "  [警告] 找不到 $coverageTest —— 這道守門這次沒有跑。" -ForegroundColor Yellow
}

# --- Step 2.6: 後端端點入口檢查（只警告，不擋，2026-09-11 新增）---
# 本專案已經連續兩次出現「後端上線、前端沒入口」：WebAuthn 的設定頁沒被
# 部署，端點回 503 卻沒有任何地方能填 RP ID；叫料（material_orders.py）修好
# 四個缺陷、7 題 API 測試全綠，卻整整一天沒有任何前端呼叫得到它。
# 兩次都不是「寫錯」，是「寫完忘了另一半」——而純 API 測試對這種缺陷完全無感。
# 判斷方式是字串比對（路由最後一個非參數片段有沒有出現在 frontend/ 裡），
# 本來就會有誤判，所以**只印警告、絕不擋打包**——拿它擋打包只會變成
# 每次都在想辦法繞過。詳見 check_endpoint_entrypoints.py 檔頭。
Write-Host "`n[入口檢查] 比對後端路由與 frontend/ 的呼叫點..."
$entryScript = Join-Path $projectRoot "backend\tools\check_endpoint_entrypoints.py"
if (Test-Path $entryScript) {
    # PYTHONIOENCODING：這台機器 locale 是 cp932，不指定的話子行程 print 中文會 UnicodeEncodeError
    $prevIoEnc = $env:PYTHONIOENCODING
    $env:PYTHONIOENCODING = "utf-8"
    try {
        & $pyExe $entryScript | ForEach-Object { Write-Host "  $_" }
    } catch {
        Write-Host "  [SKIP] 入口檢查自己壞了，不影響打包：$_" -ForegroundColor DarkYellow
    } finally {
        $env:PYTHONIOENCODING = $prevIoEnc
    }
} else {
    Write-Host "  [SKIP] 找不到 check_endpoint_entrypoints.py" -ForegroundColor DarkYellow
}

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
# 2026-09-15：打包時整台機器被吃滿、其他事做不了。實測（本機 Ryzen 5 5600X，
# 6 實體核心 / 12 執行緒，940 題非 e2e）：
#
#   -n auto(=12) ＋ 背景排程開著   274 秒   峰值 33 個 python 行程   1.86 GB
#   -n auto(=12) ＋ 背景排程停用   185 秒   峰值 19 個              1.34 GB
#   -n 8         ＋ 背景排程停用   171 秒   峰值 23 個              1.63 GB
#   -n 6         ＋ 背景排程停用   175 秒   峰值 20 個              1.34 GB
#
# 兩個結論：
#   ① 記憶體從來不是瓶頸（32 GB 機器上峰值不到 2 GB）——**吃滿的是 CPU**。
#   ② `-n auto` 取的是**邏輯**處理器數（12），把 12 個 worker 塞進 6 個實體核心
#      只會互相搶，**比用 6 個還慢**。改成依實體核心數開，快一點、而且留一半
#      的執行緒給使用者，打包期間機器還能用。
#
# 背景排程那一項在 backend/tests/conftest.py（`MOTRIX_DISABLE_SCHEDULERS=1`）——
# `import main` 是 module-level 執行，每個 worker 都會在 import 當下立刻跑一次
# 完整備份，等於同一次測試跑了 N 遍。
$physCores = 0
try {
    $physCores = (Get-CimInstance Win32_Processor | Measure-Object -Property NumberOfCores -Sum).Sum
} catch { $physCores = 0 }
if (-not $physCores -or $physCores -lt 2) { $physCores = 4 }   # 查不到就用保守值
$workers = [Math]::Max(2, [Math]::Min($physCores, 8))

# 降到 BelowNormal，子行程（pytest worker）會繼承。**不影響總時間多少**
# （CPU 本來就吃得滿），但可以讓打包期間滑鼠、瀏覽器、編輯器還跟得上——
# 使用者回報的痛點是「機器不能用」，不是「跑太久」。
$prevPriority = $null
try {
    $prevPriority = (Get-Process -Id $PID).PriorityClass
    (Get-Process -Id $PID).PriorityClass = 'BelowNormal'
    Write-Host "  行程優先權暫時降為 BelowNormal（打包期間機器仍可正常使用）" -ForegroundColor DarkGray
} catch {
    Write-Host "  [WARN] 無法調整行程優先權，維持預設（不影響正確性）" -ForegroundColor Yellow
}

$pytestTemp = Join-Path $env:TEMP "motrix-pytest-$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Write-Host "`n[測試] 執行 pytest（非 e2e，backend/tests/，含 API 整合測試，pytest-xdist 平行化，$workers 個 worker）..."
Push-Location (Join-Path $projectRoot "backend")
# ⚠️ `--durations=20` 是**零額外時間**：那一輪本來就要跑，它只是把 pytest
# 已經量到的分布印出來。而它量到的正是「**打包環境下**」的分布 ——
# 🔑 那是我們先前唯一拿不到的那一格（單獨跑一支探針量不到 `-n 6` 的競爭）。
$_tNonE2e = Get-Date
& $pyExe -m pytest -q -m "not e2e" -n $workers --durations=20 --basetemp="$pytestTemp" 2>&1 |
    Tee-Object -Variable nonE2eOut |
    ForEach-Object { Write-Host $_ }
# ⚠️ `$LASTEXITCODE` 由原生執行檔設定，**管線接到 cmdlet 不會覆蓋它** ——
# 用 `$?` 的話拿到的是 `ForEach-Object` 的結果，那永遠是 True。
$testExit = $LASTEXITCODE
Mark-Elapsed "pytest_not_e2e" $_tNonE2e
$BuildStats["not_e2e"] = Parse-PytestSummary $nonE2eOut
$BuildStats["workers"] = $workers
if ($testExit -ne 0) {
    Pop-Location
    Fail "測試未全數通過（exit code $testExit），中止打包。請先修好測試再重新執行本腳本。"
}
Write-Host "[OK] 非 e2e 測試全數通過。" -ForegroundColor Green

# --- Step 3.1: 測試有沒有在工作樹留下東西（2026-09-22 新增，RG19）---
# 【這道檢查在回答什麼】「除了我們已知的那幾個，還有沒有第八個？」
#
# 🔑 **這是行為證據，不是從常數推的。** 從 `db.py` 的常數清單推路徑答不了
# 三件事：執行期才算出來的路徑、函式內的區域路徑變數、
# 以及「跑全量到底會不會寫到別的地方」——而最後那一件正是這裡回答的。
#
# 📌 **成本是零**：打包流程本來就跑全量，這裡只多一次 `git status` 比對。
#
# ⚠️ 只**警告不擋**：測試留下的檔案不會進部署包（`git archive` 只匯出已追蹤
# 內容），所以它不是這一包的品質問題。
# ☠️ 而它是**下一次打包**的品質問題：Step 1 要求 git 狀態乾淨，
#    所以今天多出來的未追蹤檔案，會讓下一個人的打包直接被擋，
#    而他完全不知道那是上一次跑測試留下的。
$dirtyAfter = @(git status --porcelain -- $relPath)
$leaked = @($dirtyAfter | Where-Object { $_ -notin $dirtyBefore })
if ($leaked.Count -gt 0) {
    Write-Host "  [警告] 跑完測試之後，工作樹多出這些東西：" -ForegroundColor Yellow
    $leaked | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
    @'
  ⇒ 它們不會進這一包（git archive 只匯出已追蹤內容），而它們會讓**下一次**
    打包在 Step 1 被擋下，而那個人不會知道是上一次跑測試留下的。
    處置：把路徑加進 .gitignore（同 backend/_demo_* 那一段的理由），
    或讓那支測試自己清乾淨。
'@ | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
} else {
    Write-Host "[OK] 跑完測試之後工作樹沒有多出任何東西。" -ForegroundColor Green
}

Write-Host "`n[測試] 執行 pytest（e2e，真實瀏覽器）..."
$_tE2e = Get-Date
# `-rf` 讓失敗的那幾題印出 `FAILED <題> - <例外類別>: <訊息>` —— 那一行是
# 下面分類的依據。
& $pyExe -m pytest -q -rf -m "e2e" --durations=20 --basetemp="${pytestTemp}_e2e" 2>&1 |
    Tee-Object -Variable e2eOut |
    ForEach-Object { Write-Host $_ }
$e2eExit = $LASTEXITCODE
Mark-Elapsed "pytest_e2e" $_tE2e
$BuildStats["e2e"] = Parse-PytestSummary $e2eOut
Pop-Location

# 🔴 **逾時與斷言失敗要分開判**（2026-09-22）。
#
# 這一段原本一律只印一句「已知這類測試偶爾因系統負載造成瀏覽器渲染逾時」
# 然後繼續打包。
# ☠️ 而 2026-09-22 那一次它是**內容斷言**（`assert '業務' in [...]`），
#    不是逾時 —— 一個真的錯誤被一句「已知偶爾」放過去了。
# 🔑 改文字是修結果；**修作法是讓判定看得見那個區別**，而 pytest 給得出來：
#    `-rf` 的摘要行帶著例外類別。
#
# ⚠️ **fail closed**：只有**認得出來的逾時**才降級成警告。
# ☠️ 分類不出來（收集錯誤、行程被殺、輸出被截斷）⇒ **中止**。
#    認不得就放行的話，這道判定會在它最該擋的時候消失。
$e2eFailLines = @($e2eOut | Where-Object { $_ -match "^FAILED " })
$e2eTimeoutOnly = $false
if ($e2eExit -ne 0 -and $e2eFailLines.Count -gt 0) {
    # 逐行看例外類別；**全部**都是逾時才算逾時。
    $nonTimeout = @($e2eFailLines | Where-Object { $_ -notmatch "Timeout" })
    $e2eTimeoutOnly = ($nonTimeout.Count -eq 0)
}
if ($e2eExit -eq 0) {
    Write-Host "[OK] e2e 測試也全數通過。" -ForegroundColor Green
} elseif ($e2eTimeoutOnly) {
    Write-Host "[WARN] e2e 有 $($e2eFailLines.Count) 題**逾時**（exit $e2eExit）——真實瀏覽器在系統負載高時會渲染逾時，不必然代表程式碼壞掉。繼續打包，建議事後單獨重跑：python -m pytest -m e2e -v" -ForegroundColor Yellow
} else {
    $e2eFailLines | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Fail "e2e 測試失敗，而失敗的原因**不是逾時**（見上方 FAILED 行）。逾時可以續跑，斷言失敗不行——那代表畫面上真的有東西不對。要確認請單獨跑：python -m pytest -m e2e -v"
}

# 2026-09-15：測試暫存跑完就自己刪。
#
# 上面那個 --basetemp 的名字帶時間戳，**每次執行都是新目錄**，所以 pytest 不會
# 覆蓋、也沒有任何機制會清——一次打包留下 3～4 GB（實測：非 e2e 那半 3.1 GB／
# 8,627 個檔，絕大多數是測試期間真的產生的單據 PDF）。2026-09-14 一次清出
# 190 GB、2026-09-15 又清出 136 GB（84 個目錄），全部都是這樣累積的。
#
# 只在**測試通過**時刪：失敗時那些檔案是唯一的現場（哪張單的 PDF 沒產出、
# 哪個 DB 狀態不對），刪掉就只剩一行 assert 訊息可以看。非 e2e 失敗會在上面
# 直接 Fail 中止，走不到這裡；這裡處理的是 e2e。
$tempsToClean = @($pytestTemp)
if ($e2eExit -eq 0) { $tempsToClean += "${pytestTemp}_e2e" }
else { Write-Host "  e2e 失敗，保留其測試暫存供追查：${pytestTemp}_e2e" -ForegroundColor DarkGray }
foreach ($tp in $tempsToClean) {
    if (Test-Path -LiteralPath $tp) {
        $freedMB = 0
        try {
            $freedMB = [math]::Round((Get-ChildItem -LiteralPath $tp -Recurse -File -Force -ErrorAction SilentlyContinue |
                                      Measure-Object -Property Length -Sum).Sum / 1MB, 0)
        } catch { }
        # rd 比 Remove-Item 快非常多（一次打包有上萬個小檔）
        cmd /c rd /s /q "$tp" 2>$null
        if (Test-Path -LiteralPath $tp) {
            Write-Host "  [WARN] 測試暫存刪不掉（可能有檔案被佔用）：$tp" -ForegroundColor Yellow
        } else {
            Write-Host "  已清除測試暫存（釋出約 $freedMB MB）：$tp" -ForegroundColor DarkGray
        }
    }
}

# 測試跑完就把優先權還回去——後面的 git archive / robocopy 是 IO 為主，
# 壓著它只是讓打包變慢，沒有好處。
if ($prevPriority) {
    try { (Get-Process -Id $PID).PriorityClass = $prevPriority } catch { }
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
$_tArchive = Get-Date
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
if (-not $OutDir) {
    $OutDir = Join-Path $projectRoot "deploy_packages"
}
# 2026-09-25：-OutDir 給相對路徑時，下面 Push-Location 進 $pkgDir 之後 `Remove-Item $tarPath`
# 會把相對路徑再疊一次（...\deploy_packages\X\deploy_packages\X\snapshot.tar）⇒ 測試全綠、
# 包卻在最後一步失敗。⇒ 一開始就轉成絕對路徑。
if (-not [System.IO.Path]::IsPathRooted($OutDir)) {
    $OutDir = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $OutDir))
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

# --- Step 5.5: 寫 backend/.build_commit（BR1）---
#
# 🔴 出貨包裡**沒有 .git** ⇒ 正式機的行程問不到「我載入的是哪一版」。
#    而 2026-09-23 的事故正是這個問題的後果：666 的行程 05:56 起來、
#    載入 dd50d2e，磁碟上已經往前 25 個 commit，**使用者一個都沒看到**，
#    而 git 是對的、全量是綠的、他的畫面是舊的 —— 三邊都不會報錯。
#
# ⚠️ 這一份與 .deployed_commit.json **不是同一件事**：
#      .deployed_commit.json  apply_update.ps1 寫的「磁碟上被套用成什麼」
#      .build_commit          「這份程式碼是從哪個 commit 打包出來的」
#    兩者不一致正是 BR1 要抓的那一格。
#
# ⚠️ 用 $commit（Step 2 釘住的那一個），不要在這裡重抓 HEAD ——
#    pytest 跑了好幾分鐘，期間 HEAD 可能已經動過（那個競態 Step 2 的註解寫過）。
# ⚠️ 內容是純 ASCII 的 40 字 SHA；明著指定 -Encoding ascii，
#    因為 Set-Content 在 PS 5.1 預設走系統 ANSI codepage。
$buildCommitPath = Join-Path $pkgDir "backend\.build_commit"
Set-Content -Path $buildCommitPath -Value $commit -Encoding ascii -NoNewline
if (-not (Test-Path $buildCommitPath)) {
    Fail "寫入 backend/.build_commit 失敗，正式機將無法回報執行中的版本，已中止。"
}
Write-Host "      .build_commit: $commitShort"

# --- Step 5.6: 精簡 backend/version_manifest.json（PK1 → T12）---
#
# 🔴 這份檔案有兩個讀者：
#   ① GET /api/system/version（routers/auth.py）—— 登入頁版本號，取**最新**一筆（T10）
#   ② helpers/startup.py::_sync_module_versions() —— 開機時寫進 module_versions，
#      給「系統更新紀錄」頁（module-versions.html）顯示；**沒有 module 的條目會被略過**
#
# PK1 原本只考慮 ①，把它精簡成 [{version,date}] ⇒ ② 收不到任何新說明，**而且不報錯**
# （T12，安靜降級）。使用者可見的說明文字本來就是寫給使用者的，所以 T12 改成：
# 每一筆只保留使用者可見欄位 module/version/date/time/content（投影，不是整份原樣照搬——
# 日後若有人在條目上加內部欄位，也不會因此流出去）。
# ⚠️ 讀不到／空陣列 ⇒ 從包裡移除（登入頁版本號留空，Step 4 已經警告過），
#    驗包 verify_package.py 的 (5b) 會把它擋下來（缺檔不是 PASS）。
$pkgVersionManifestPath = Join-Path $pkgDir "backend\version_manifest.json"
$projectedVersionManifest = $null
try {
    # ⚠️ **不要包 @()**：PowerShell 5.1 的 ConvertFrom-Json 把整個 JSON 陣列當成**一個**物件送出，
    #    再包 @() 就變成「陣列裡裝一個陣列」⇒ foreach 只跑一次，每個欄位都是整欄的陣列
    #    （2026-09-24 單獨執行這一段時抓到的；test_verify_package 的 t12 執行題守著）。
    $allEntries = Get-Content -Path $versionManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($allEntries -and $allEntries.Count -gt 0) {
        $projectedVersionManifest = @(foreach ($e in $allEntries) {
            [ordered]@{
                module  = $e.module
                version = $e.version
                date    = $e.date
                time    = $e.time
                content = $e.content
            }
        })
    }
} catch {
    Write-Host "[WARN] 無法重讀 version_manifest.json 以產生精簡版（$($_.Exception.Message)）。" -ForegroundColor Yellow
}
if ($projectedVersionManifest) {
    # ⚠️ **不要用管線**：單一元素的陣列丟進管線會被 PowerShell 攤平成裸物件，
    # 產出 `{...}` 而不是 `[{...}]`。用 `-InputObject` 明著傳，陣列不會被攤平。
    ConvertTo-Json -InputObject $projectedVersionManifest -Depth 3 |
        Set-Content -Path $pkgVersionManifestPath -Encoding UTF8
    Write-Host "      version_manifest.json 已投影為使用者可見欄位（$($projectedVersionManifest.Count) 筆）"
} elseif (Test-Path $pkgVersionManifestPath) {
    Remove-Item -LiteralPath $pkgVersionManifestPath -Force
    Write-Host "[WARN] version_manifest.json 沒有可用的紀錄，已從包裡移除（登入頁版本號將留空；驗包會擋下）。" -ForegroundColor Yellow
}

# --- Step 6: 寫 deploy_manifest.json ---
Mark-Elapsed "archive" $_tArchive
$BuildT["total_so_far"] = [math]::Round(((Get-Date) - $BuildStart).TotalSeconds, 2)

$manifest = [ordered]@{
    commit               = $commit
    commit_short         = $commitShort
    branch               = $branch
    built_at             = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    version_manifest_latest = $versionLatest
    # 🔴 2026-09-22 新增：使用者問「打包的時間為什麼會越來越久」，
    # 而我們**答不出來** —— 這裡先前只有 commit／branch／built_at。
    # 🔑 這幾欄的價值不在這一次，是**下一次有人問同一個問題時，
    #    答案在產物裡而不在誰的記憶裡**。
    durations_sec        = $BuildT
    tests                = $BuildStats
    env                  = [ordered]@{
        phys_cores = $physCores
        workers    = $workers
        priority   = "BelowNormal"
    }
}
$manifestPath = Join-Path $pkgDir "deploy_manifest.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding UTF8

Write-Host "[2/2] 寫入 deploy_manifest.json"

# --- Step 7: 清掉過舊的部署包 ---
#
# 2026-09-15 使用者要求：「當第三個打包檔的時候自動刪除第一個打包檔，避免重複堆積」。
# 一份包約 35 MB，一天打好幾次的話會一直長。
#
# 刻意排在最後（新包已完整解壓、通過 backend/frontend 存在性驗證、manifest 也寫好了）
# ——打包中途失敗時一律走 Fail 直接 exit，永遠不會走到這裡，**不會出現「新包沒做成、
# 舊包卻被刪掉」**。
#
# 只刪名字符合 `yyyyMMdd_HHmmss_<commit>` 的資料夾：這個目錄是使用者自己會進去翻的，
# 手動放進來的東西（改名留存的包、筆記、複製到一半的資料夾）不能被掃掉。
# 排序用資料夾名稱而不是 LastWriteTime——名字開頭就是時間戳，字串排序即時間排序，
# 而 LastWriteTime 會被「複製到隨身碟」之類的動作改掉。
$_tPrune = Get-Date
if ($KeepPackages -gt 0) {
    $pkgPattern = '^\d{8}_\d{6}_[0-9a-fA-F]{7,40}$'
    $allPkgs = Get-ChildItem $OutDir -Directory -ErrorAction SilentlyContinue |
               Where-Object { $_.Name -match $pkgPattern } |
               Sort-Object Name
    $stale = @($allPkgs | Select-Object -SkipLast $KeepPackages)
    if ($stale.Count -gt 0) {
        Write-Host "`n[清理] 保留最新 $KeepPackages 份，刪除較舊的 $($stale.Count) 份："
        foreach ($old in $stale) {
            # 用 Remove-Item 而不是 Step 3 的 `rd`：那裡處理的是 pytest 暫存（數萬個
            # 小檔，rd 快很多），一份部署包才一千多個檔，差別可以忽略，換來的是不必
            # 處理 cmd 的引號轉義、失敗時拿得到例外訊息。
            try {
                Remove-Item -LiteralPath $old.FullName -Recurse -Force -ErrorAction Stop
                Write-Host "  已刪除 $($old.Name)" -ForegroundColor DarkGray
            } catch {
                # 刪不掉不該讓整次打包失敗——包已經做好了，這只是清理
                Write-Host "  [WARN] $($old.Name) 刪除失敗（檔案被占用？）：$($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
        Write-Host "  （要保留更多份：-KeepPackages N；完全不清理：-KeepPackages 0）" -ForegroundColor DarkGray
    }
}

Mark-Elapsed "prune" $_tPrune
$BuildT["total"] = [math]::Round(((Get-Date) - $BuildStart).TotalSeconds, 2)

# 🔴 **同一份數字要再寫一次到不會被刪的地方。**
#
# `KeepPackages=2` 會把舊包整個刪掉 ⇒ 只寫進包裡的 `deploy_manifest.json`
# 的話，**每一筆都記了，而只剩最後兩筆** ⇒ 下一次問「打包為什麼越來越久」
# 還是查不到。2026-09-22 就是這樣：四個視窗查了半小時，結論是「查不到」。
#
# 📌 落點選 `backend/tools/deploy_logs/`（已在 `.gitignore:62`）：
#    ① 不被 `KeepPackages` 掃到 —— 它只看 `deploy_packages/`
#    ② **不會弄髒 `git status`** —— Step 1 要求乾淨，寫一個**被追蹤**的檔
#       會讓下一次打包被自己擋住
# ⚠️ 代價寫明：它**不進 git 歷史**，換一台機器就沒有。
#    要跨機器保存是一個獨立的決定，不在這一次。
#
# ⚠️ 而它與包裡那份**刻意不一致**：manifest 在 Step 6 寫，那時 prune 還沒跑
#    ⇒ manifest 記到 `archive` 為止，**這裡才有 `prune` 與 `total`**。
#    不寫這一段的話，下一個人比對兩邊會以為有一個壞了。
try {
    $histDir = Join-Path $projectRoot "backend\tools\deploy_logs"
    if (-not (Test-Path $histDir)) { New-Item -ItemType Directory -Path $histDir | Out-Null }
    $histPath = Join-Path $histDir "build_history.jsonl"
    $histLine = ([ordered]@{
        built_at      = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        commit        = $commitShort
        package       = (Split-Path $pkgDir -Leaf)
        durations_sec = $BuildT
        tests         = $BuildStats
        env           = [ordered]@{
            phys_cores = $physCores
            workers    = $workers
            priority   = "BelowNormal"
        }
    } | ConvertTo-Json -Depth 6 -Compress)
    Add-Content -Path $histPath -Value $histLine -Encoding UTF8
    Write-Host "`n[紀錄] 耗時已附加到 backend\tools\deploy_logs\build_history.jsonl" -ForegroundColor DarkGray
    Write-Host "  total=$($BuildT.total)s  非e2e=$($BuildT.pytest_not_e2e)s  e2e=$($BuildT.pytest_e2e)s  archive=$($BuildT.archive)s  prune=$($BuildT.prune)s" -ForegroundColor DarkGray
} catch {
    # ⚠️ 寫不進歷史檔**不該讓打包失敗** —— 包已經做好了，這是紀錄不是產物。
    # 而它要**說出來**：一個安靜失敗的紀錄機制，跟沒有紀錄機制一樣。
    Write-Host "  [WARN] 耗時紀錄寫入失敗（$($_.Exception.Message)）——包本身不受影響" -ForegroundColor Yellow
}

Write-Host "`n======================================"
Write-Host "  完成！部署包路徑：" -ForegroundColor Green
Write-Host "  $pkgDir" -ForegroundColor Green
Write-Host "======================================"
Write-Host ""
Write-Host "下一步（手動）："
Write-Host "  1. 把整個資料夾 '$pkgDir' 複製到正式機（隨身碟／網路芳鄰／雲端硬碟皆可）"
Write-Host "  2. 在正式機執行："
Write-Host "     powershell -ExecutionPolicy Bypass -File backend\tools\apply_update.ps1 -PackagePath <複製過去的路徑>"
# --- 第 3 步：那個從來沒有人做過的步驟（2026-09-22 §8 FX1b）---
#
# 88 份部署紀錄裡「重跑排程工作」出現次數是 0。
# 那不是有人偷懶 —— 是「下一步」這張清單上從來沒有它。
#
# 為什麼非做不可：autostart.bat 的 set MOTRIX_* 在 :loop 標籤【之前】
# ⇒ 不重跑排程工作的話，接手的是已經在跑的那個 crash-restart 迴圈，
#   而它拿的是【舊的】環境變數。
# 它的失敗長什麼樣（DEPLOY.md 自己寫的）：
#   「推送成功、服務正常、畫面正常，就是雷達不掃、地圖上沒有點。」
#
# ⚠️ 這支腳本【問不到】那台機器：它對外打 HTTP 的次數是 0，
#    而且打包的當下正式機還沒被更新。
#    ⇒ 自動比對做在 apply_update.ps1 裡（它在正式機上跑、restart 之後，
#      比對 autostart.bat 說要開的 vs 這次啟動 log 裡看得到的）。
#    ⇒ 這裡只負責把【人工確認的方法】寫出來。
Write-Host "  3. 【重要】如果這一版改過 autostart.bat 或兩個開關，"
Write-Host "     要到工作排程器把 MOTRIX ERP 那個工作【結束後重新執行】——"
Write-Host "     只等 crash-restart 迴圈接手的話，跑的還是舊的環境變數。"
Write-Host "     確認方式（superadmin 登入後）：GET /api/system/runtime-switches"
Write-Host "     它回的是【這個行程實際拿到什麼】，不是設定檔裡寫了什麼。"
Write-Host "     apply_update.ps1 也會自動比對一次，不一致會用黃字喊。"
Write-Host ""
