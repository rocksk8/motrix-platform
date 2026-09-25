# 建包的 e2e 判定（build_deploy_package.ps1 用；抽出來是為了能單獨測）。
#
# 2026-09-25：逾時也擋下打包。原本「全部都是逾時 ⇒ 警告、繼續打包」——
# ☠️ 逾時的題**沒有驗到任何東西**，放行等於靜默少驗；平行化之後逾時只會更多。
# 🔑 逾時與斷言失敗仍分開列出（處理方式不同：前者先單獨重跑確認，後者直接修），
#    但兩者都不出包。
# ⚠️ fail closed：exit 非 0 而認不出任何 FAILED 行（收集錯誤、行程被殺、輸出被截斷）⇒ 也擋。

function Get-E2eGateResult {
    param([int]$ExitCode, [string[]]$Lines, [string]$PyExe = "python")
    $failed = @($Lines | Where-Object { $_ -match '^FAILED ' })
    $ids = @($failed | ForEach-Object { ($_ -replace '^FAILED\s+', '') -replace '\s+-\s+.*$', '' })
    $timeouts = New-Object System.Collections.Generic.List[string]
    $asserts = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -lt $failed.Count; $i++) {
        if ($failed[$i] -match 'Timeout') { $timeouts.Add($ids[$i]) } else { $asserts.Add($ids[$i]) }
    }
    # 2026-09-25（PERF #3）：e2e 逐題上限（conftest `_e2e_hard_cap`）結束 worker 時，同一題有兩行 FAILED——
    # xdist 自己那行（被截成 `- w...`、不含 Timeout）＋主控補的 `- Timeout: e2e 逐題上限…` ⇒ 只算逾時、各只列一次。
    $timeouts = @($timeouts | Select-Object -Unique)
    $asserts = @($asserts | Where-Object { $timeouts -notcontains $_ } | Select-Object -Unique)
    $ok = ($ExitCode -eq 0)
    $msg = New-Object System.Collections.Generic.List[string]
    if (-not $ok) {
        if ($failed.Count -eq 0) {
            $msg.Add("e2e 結束碼 $ExitCode，但輸出裡認不出任何 FAILED 行（收集錯誤、行程被殺或輸出被截斷）——無法確認驗過，不出包。")
        }
        if ($asserts.Count -gt 0) {
            $msg.Add("斷言失敗 $($asserts.Count) 題（畫面上真的有東西不對，要修）：")
            foreach ($t in $asserts) { $msg.Add("  $t") }
        }
        if ($timeouts.Count -gt 0) {
            $msg.Add("逾時 $($timeouts.Count) 題（逾時＝沒驗到，不出包；先單獨重跑確認是負載還是缺陷）：")
            foreach ($t in $timeouts) { $msg.Add("  $t") }
        }
        if ($failed.Count -gt 0) {
            $msg.Add("單獨重跑（在 backend\ 底下）：")
            foreach ($t in @($asserts) + @($timeouts)) { $msg.Add("  $PyExe -m pytest `"$t`" -v") }
        }
    }
    return [pscustomobject]@{ Ok = $ok; Timeouts = @($timeouts); Failures = @($asserts); Message = @($msg) }
}
