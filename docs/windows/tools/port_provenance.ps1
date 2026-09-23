# port_provenance.ps1 -- BR2 反查（唯讀）
#
# 問題：「現在跑著的東西，有哪些是使用者以為已經更新了的」
#
# 從「正在監聽的埠」回推：誰啟的 / 載入哪個版本 / 期待不期待改碼生效。
# 唯讀：只查詢，不 kill、不重啟、不改檔。
#
# 判定三層（不是只看 --reload）：
#   reload   指令列有 --reload            => 改碼會自己生效
#   launcher 從祖先鏈的行程名推啟動方式    => 決定「使用者期待什麼」
#   staleness 載入版本與 HEAD 差幾個 commit => 決定「現在是不是真的落後了」
# 間隔 = 沒有 reload  且  啟動方式屬於「人在開發機上手動起的」
#        （正式機刻意不 reload，那不是間隔）

param(
  [int[]] $Ports = @(666, 6667, 8765),
  [string] $RepoDir = "C:\Users\hichan\Desktop\MOTRIX-ERP"
)

$ErrorActionPreference = "Continue"

function Get-Ancestry {
  param([int] $TargetPid)
  $chain = @()
  $cur = $TargetPid
  $seen = @{}
  for ($i = 0; $i -lt 12; $i++) {
    if ($seen.ContainsKey($cur)) { break }
    $seen[$cur] = $true
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$cur" -ErrorAction SilentlyContinue
    if (-not $p) {
      $chain += [pscustomobject]@{ Pid = $cur; Name = "(已結束)"; Cmd = ""; Created = $null; Ppid = $null }
      break
    }
    $chain += [pscustomobject]@{
      Pid = $p.ProcessId; Name = $p.Name
      Cmd = ($p.CommandLine -replace '\s+', ' ')
      Created = $p.CreationDate; Ppid = $p.ParentProcessId
    }
    if (-not $p.ParentProcessId -or $p.ParentProcessId -eq 0) { break }
    $cur = $p.ParentProcessId
  }
  return $chain
}

function Get-Launcher {
  param($chain)
  # 由外往內看祖先的行程名，第一個認得的就是啟動方式
  foreach ($n in ($chain | Select-Object -ExpandProperty Name)) {
    switch -Regex ($n) {
      'nohup\.exe'    { return @{ kind = "bash-nohup"; expect = $true;  note = "Git-Bash 背景啟動（不在任何檔案裡的入口）" } }
      'bash\.exe|sh\.exe' { return @{ kind = "bash";   expect = $true;  note = "從 bash shell 啟動" } }
      'wscript\.exe|cscript\.exe' { return @{ kind = "vbs/排程"; expect = $false; note = "autostart_hidden.vbs（正式機路徑）" } }
      'svchost\.exe|taskeng\.exe|taskhostw\.exe' { return @{ kind = "排程工作"; expect = $false; note = "Windows 排程" } }
      'cmd\.exe'      { return @{ kind = "cmd/.bat";   expect = $true;  note = "人在機器前跑 .bat" } }
      'powershell\.exe|pwsh\.exe' { return @{ kind = "powershell/.ps1"; expect = $true; note = "人跑 .ps1" } }
      'explorer\.exe' { return @{ kind = "explorer";   expect = $true;  note = "使用者雙擊啟動" } }
    }
  }
  return @{ kind = "未知"; expect = $true; note = "祖先鏈認不出啟動方式（父行程可能已結束）" }
}

function Get-LoadedCommit {
  param($created, [string] $repo)
  if (-not $created) { return @{ sha = "未查"; behind = "未查"; how = "沒有 CreationDate" } }
  $stamp = $created.ToString("yyyy-MM-ddTHH:mm:ss")
  Push-Location $repo
  $env:GIT_CEILING_DIRECTORIES = "C:\Users\hichan"
  $sha = (& git rev-list -1 --before=$stamp HEAD 2>$null)
  $head = (& git rev-parse HEAD 2>$null)
  $behind = ""
  if ($sha) { $behind = (& git rev-list --count "$sha..$head" 2>$null) }
  Pop-Location
  if (-not $sha) { return @{ sha = "未查"; behind = "未查"; how = "git 查不到" } }
  return @{ sha = $sha.Substring(0, 7); behind = $behind; how = "由 CreationDate **推定**（不是問行程）" }
}

"=== BR2 反查：從監聽埠回推『使用者以為更新了嗎』 ==="
$env:GIT_CEILING_DIRECTORIES = "C:\Users\hichan"
Push-Location $RepoDir
$head = (& git rev-parse --short HEAD 2>$null)
Pop-Location
"repo HEAD = $head"
""

foreach ($prt in $Ports) {
  $conns = Get-NetTCPConnection -LocalPort $prt -State Listen -ErrorAction SilentlyContinue
  if (-not $conns) { "── port $prt : 沒有監聽者"; ""; continue }
  foreach ($c in ($conns | Select-Object -Unique OwningProcess)) {
    $chain = Get-Ancestry -TargetPid $c.OwningProcess
    $listener = $chain[0]
    $reload = ($chain | Where-Object { $_.Cmd -like '*--reload*' }).Count -gt 0
    $L = Get-Launcher $chain
    $V = Get-LoadedCommit $listener.Created $RepoDir
    $gap = (-not $reload) -and $L.expect

    "── port $prt  <- PID $($listener.Pid) $($listener.Name)"
    "   啟動時間   $($listener.Created)"
    "   祖先鏈     " + (($chain | ForEach-Object { "$($_.Name)($($_.Pid))" }) -join "  <- ")
    "   指令       " + $(if ($listener.Cmd.Length -gt 150) { $listener.Cmd.Substring(0,150) + "…" } else { $listener.Cmd })
    "   --reload   $reload"
    "   啟動方式   $($L.kind) -- $($L.note)"
    "   期待改碼生效？ $($L.expect)"
    "   載入版本   $($V.sha)   落後 HEAD $($V.behind) 個 commit   [$($V.how)]"
    if ($gap) {
      "   判定       🔴 **間隔**：沒有 --reload，而這個啟動方式的使用者期待改碼生效"
      if ($V.behind -ne "未查" -and [int]$V.behind -gt 0) {
        "              且現在**真的落後 $($V.behind) 個 commit** => 使用者以為更新了的東西，它不知道"
      } else {
        "              目前尚未落後（剛起來），但下一個 commit 起就會"
      }
    } else {
      if ($reload) { "   判定       ✅ 不是間隔：有 --reload，改碼會自己生效" }
      else { "   判定       ✅ 不是間隔：這個啟動方式**刻意**不 reload（正式機型），但仍要看落後幾個 commit" }
    }
    ""
  }
}
