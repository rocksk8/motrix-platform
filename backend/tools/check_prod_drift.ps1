<#
  check_prod_drift.ps1 — 在「開發機」執行，唯讀比對正式機安裝目錄與它自稱的 commit

  解決的問題（MOTRIX-ERP-QUICK.md §0 反覆發生的那個）：
  正式機不是 git repo，任何人（或任何 AI session）直接在 C:\Users\Motrix\Desktop\V9.0
  底下改檔案，開發機這邊完全看不到；等到下一次 apply_update.ps1 執行，Step 3 會把
  部署包整個覆蓋上去，那些改動就無聲無息消失了。過去只能靠「人記得講」，而 §0 那張
  落差表本身就是「人不會記得」的證據。

  作法：正式機的 /api/system/deployed-version 會回報它現在跑在哪個 commit，本腳本
  用 git archive 把那個 commit 的內容還原到暫存目錄、算出每個檔案的 SHA256，再透過
  WinRM 對正式機同一批路徑算一次 SHA256，兩邊逐檔比對。差異就是「部署之後被改過的
  東西」。

  全程唯讀：正式機端只執行 Get-FileHash / Get-ChildItem，不寫入任何檔案、不重啟服務。

  用法（密碼從 STDIN 讀，不進指令列參數）：
    "密碼" | powershell -ExecutionPolicy Bypass -File check_prod_drift.ps1
    "密碼" | powershell -ExecutionPolicy Bypass -File check_prod_drift.ps1 -Commit 2471747

  參數：
    -Commit    指定要比對的 commit（預設：向正式機查詢它自己回報的版本）
    -Username  正式機帳號（預設 Motrix）
#>

[CmdletBinding()]
param(
    [string]$Commit = "",
    [string]$Username = "Motrix",
    [string]$ProdHost = "172.16.10.177",
    [string]$ProdRoot = "C:\Users\Motrix\Desktop\V9.0"
)

$ErrorActionPreference = "Stop"

function Fail($msg) { Write-Host "`n[FAIL] $msg" -ForegroundColor Red; exit 1 }

# 比對範圍：只看會被 apply_update.ps1 Step 3 覆蓋的程式碼樹。
# 刻意排除 db、log、上傳檔、快照等執行期產物（那些本來就會不一樣）。
$ScopeDirs = @("backend", "frontend")
$ExcludePatterns = @(
    '\\__pycache__\\', '\\logs\\', '\\db_backups\\', '\\rollback_snapshots\\',
    '\\certs\\', '\\uploads\\', '\\deploy_logs\\', '\\_demo_',
    '\.db$', '\.db-wal$', '\.db-shm$', '\.log$', '\.pyc$',
    'deploy_dashboard_history\.json$', '\.guide_sync_config\.json$',
    '\.deployed_commit\.json$', 'heartbeat_config\.json$',
    '\.initial_admin_credentials\.txt$'
)

function Test-InScope([string]$rel) {
    foreach ($p in $ExcludePatterns) { if ($rel -match $p) { return $false } }
    return $true
}

Write-Host "======================================"
Write-Host "  MOTRIX ERP - Prod Drift Check"
Write-Host "======================================"

# --- 1. 決定要比對哪個 commit ---
if (-not $Commit) {
    Write-Host "`n[1/4] 向正式機查詢它自己回報的部署版本..."
    $probe = @"
import json, ssl, urllib.request
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
with urllib.request.urlopen('https://$ProdHost`:666/api/system/deployed-version', timeout=10, context=ctx) as r:
    print(json.load(r)['commit'])
"@
    $tmpPy = Join-Path $env:TEMP "motrix_probe_$(Get-Random).py"
    Set-Content -Path $tmpPy -Value $probe -Encoding UTF8
    $Commit = (& python $tmpPy).Trim()
    Remove-Item $tmpPy -ErrorAction SilentlyContinue
    if (-not $Commit) { Fail "查不到正式機的部署版本，請改用 -Commit 明確指定。" }
} else {
    Write-Host "`n[1/4] 使用指定的 commit：$Commit"
}
Write-Host "      比對基準 commit：$Commit"

# --- 2. 還原該 commit 的內容並算雜湊 ---
Write-Host "`n[2/4] 用 git archive 還原該 commit 並計算雜湊..."
$projectRoot = (Get-Item $PSScriptRoot).Parent.Parent.FullName
Push-Location $projectRoot
$expandDir = Join-Path $env:TEMP "motrix_drift_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
New-Item -ItemType Directory -Force -Path $expandDir | Out-Null
$tarPath = Join-Path $expandDir "snapshot.tar"
git archive --format=tar -o $tarPath $Commit
if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "git archive 失敗——這個 commit 在本機 repo 裡不存在？先 git fetch 看看。" }
# tar 路徑歧義的處理原則與 build_deploy_package.ps1 相同，見該檔說明
$tarExe = Join-Path $env:SystemRoot "System32\tar.exe"
if (-not (Test-Path $tarExe)) { Pop-Location; Fail "找不到 $tarExe。" }
Push-Location $expandDir
& $tarExe -xf "snapshot.tar"
if ($LASTEXITCODE -ne 0) { Pop-Location; Pop-Location; Fail "tar 解壓失敗。" }
Remove-Item $tarPath
Pop-Location
Pop-Location

$expected = @{}
foreach ($d in $ScopeDirs) {
    $base = Join-Path $expandDir $d
    if (-not (Test-Path $base)) { continue }
    Get-ChildItem $base -Recurse -File | ForEach-Object {
        $rel = $_.FullName.Substring($expandDir.Length).TrimStart('\')
        if (Test-InScope $rel) { $expected[$rel] = (Get-FileHash $_.FullName -Algorithm SHA256).Hash }
    }
}
Write-Host "      基準檔案數：$($expected.Count)"

# --- 3. 對正式機算同一批路徑的雜湊（唯讀） ---
Write-Host "`n[3/4] 透過 WinRM 對正式機計算雜湊（唯讀，不寫入任何東西）..."
$pw = [Console]::In.ReadLine()
if (-not $pw) { Fail "沒有從 STDIN 讀到密碼。用法：`"密碼`" | powershell -File check_prod_drift.ps1" }
$cred = New-Object System.Management.Automation.PSCredential($Username, (ConvertTo-SecureString $pw -AsPlainText -Force))
$pw = $null

$session = New-PSSession -ComputerName $ProdHost -Credential $cred
try {
    # 排除規則必須在「遠端」就套用，不能只在本機端過濾結果：正式機的
    # backend\logs\server.log 是執行中的 uvicorn 開著的，Get-FileHash 會直接
    # 拋 FileReadError（被另一個行程使用中）並讓整個 Invoke-Command 中止。
    # 另外對每個檔案個別 try/catch，任何一個檔案讀不到都不該讓整次掃描報廢。
    $remote = Invoke-Command -Session $session -ArgumentList $ProdRoot, $ScopeDirs, $ExcludePatterns -ScriptBlock {
        param($Root, $Dirs, $Excludes)
        $out = @{}
        foreach ($d in $Dirs) {
            $base = Join-Path $Root $d
            if (-not (Test-Path $base)) { continue }
            Get-ChildItem $base -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
                $rel = $_.FullName.Substring($Root.Length).TrimStart('\')
                $skip = $false
                foreach ($p in $Excludes) { if ($rel -match $p) { $skip = $true; break } }
                if ($skip) { return }
                try {
                    $out[$rel] = (Get-FileHash $_.FullName -Algorithm SHA256 -ErrorAction Stop).Hash
                } catch {
                    $out[$rel] = "UNREADABLE"
                }
            }
        }
        $out
    }
} finally {
    Remove-PSSession $session
}

$actual = @{}
foreach ($k in $remote.Keys) { if (Test-InScope $k) { $actual[$k] = $remote[$k] } }
Write-Host "      正式機檔案數：$($actual.Count)"

# --- 4. 比對 ---
Write-Host "`n[4/4] 比對結果"
Write-Host "======================================"
$modified = @(); $onlyProd = @(); $onlyExpected = @()
foreach ($k in $expected.Keys) {
    if (-not $actual.ContainsKey($k)) { $onlyExpected += $k }
    elseif ($actual[$k] -ne $expected[$k]) { $modified += $k }
}
foreach ($k in $actual.Keys) { if (-not $expected.ContainsKey($k)) { $onlyProd += $k } }

if ($modified.Count -eq 0 -and $onlyProd.Count -eq 0 -and $onlyExpected.Count -eq 0) {
    Write-Host "[OK] 正式機內容與 commit $Commit 完全一致，沒有部署後的直接改動。" -ForegroundColor Green
} else {
    if ($modified.Count) {
        Write-Host "`n[!] 內容被改過（$($modified.Count) 個）——下次 apply_update.ps1 會覆蓋掉這些改動：" -ForegroundColor Yellow
        $modified | Sort-Object | ForEach-Object { Write-Host "      $_" }
    }
    if ($onlyProd.Count) {
        Write-Host "`n[!] 只有正式機有（$($onlyProd.Count) 個）——新增但沒進 git 的檔案：" -ForegroundColor Yellow
        $onlyProd | Sort-Object | ForEach-Object { Write-Host "      $_" }
    }
    if ($onlyExpected.Count) {
        Write-Host "`n[!] 正式機缺少（$($onlyExpected.Count) 個）——被刪掉或套用不完整：" -ForegroundColor Yellow
        $onlyExpected | Sort-Object | ForEach-Object { Write-Host "      $_" }
    }
    Write-Host "`n處理方式見 MOTRIX-ERP-QUICK.md §14.2（拉檔回開發機的步驟）：" -ForegroundColor Cyan
    Write-Host "  這些差異要先判斷是「正式機上有價值的改動」還是「殘留/實驗」，"
    Write-Host "  有價值的要先拉回開發機合併進 git，再重新打包部署——直接部署會弄丟它們。"
}

Remove-Item $expandDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "======================================"
