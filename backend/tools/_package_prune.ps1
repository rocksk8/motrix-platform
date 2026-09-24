# 部署包清理規則（build_deploy_package.ps1 Step 7 用；抽出來是為了能單獨測）。
#
# 兩條規則，符合任一條就刪：
#   ① 份數：只保留最新 $Keep 份（2026-09-15 使用者：「當第三個打包檔的時候自動刪除第一個打包檔」）
#   ② 天數：超過 $MaxAgeDays 天的刪掉（2026-09-25 使用者：「當匯出升級檔超過一周，就自動刪除過時升級檔」）
# 兩條都不會刪 $Current（這一次剛做好的包）。$Keep／$MaxAgeDays 設 0 ＝ 關掉那一條。
#
# 只認名字符合 `yyyyMMdd_HHmmss_<commit>` 的資料夾；年齡看**名字裡的時間戳**，不看 LastWriteTime
# （複製到隨身碟之類的動作會改掉 LastWriteTime）。名字裡的時間解析不出來的一律不動。

$script:PackageNamePattern = '^(\d{8}_\d{6})_[0-9a-fA-F]{7,40}$'

function Get-StalePackageNames {
    param(
        [string[]]$Names,
        [int]$Keep,
        [int]$MaxAgeDays,
        [datetime]$Now,
        [string]$Current = ""
    )
    $pkgs = @($Names | Where-Object { $_ -match $script:PackageNamePattern } | Sort-Object)
    $stale = New-Object System.Collections.Generic.List[string]
    if ($Keep -gt 0) {
        foreach ($n in @($pkgs | Select-Object -SkipLast $Keep)) { if ($n -ne $Current) { $stale.Add($n) } }
    }
    if ($MaxAgeDays -gt 0) {
        $cutoff = $Now.AddDays(-$MaxAgeDays)
        foreach ($n in $pkgs) {
            if ($n -eq $Current -or $stale.Contains($n)) { continue }
            $ts = [regex]::Match($n, $script:PackageNamePattern).Groups[1].Value
            $t = [datetime]::MinValue
            if ([datetime]::TryParseExact($ts, 'yyyyMMdd_HHmmss', [Globalization.CultureInfo]::InvariantCulture,
                                          [Globalization.DateTimeStyles]::None, [ref]$t)) {
                if ($t -lt $cutoff) { $stale.Add($n) }
            }
        }
    }
    return @($stale | Sort-Object)
}
