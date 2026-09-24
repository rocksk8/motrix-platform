"""部署包清理：超過一週的升級檔自動刪除（使用者 2026-09-25：「當匯出升級檔超過一周，就自動刪除過時升級檔」）。

規則在 backend/tools/_package_prune.ps1::Get-StalePackageNames（build_deploy_package.ps1 Step 7 呼叫）：
① 只保留最新 KeepPackages 份 ② 超過 MaxAgeDays 天的刪掉；符合任一條就刪，這一次剛做好的包永遠不刪；
名字不是 `yyyyMMdd_HHmmss_<commit>` 的資料夾（使用者手動放的）不動。
以 Windows PowerShell 5.1 實跑那支函式（正式機與開發機跑的都是 5.1）。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="部署腳本只在 Windows 上跑")

TOOLS = Path(__file__).resolve().parents[1] / "tools"
PRUNE = TOOLS / "_package_prune.ps1"
BUILD = TOOLS / "build_deploy_package.ps1"
NOW = "2026-09-25 12:00:00"


def _stale(names, keep, max_age, current=""):
    ps = (f". '{PRUNE}'; "
          f"$n = '{json.dumps(names)}' | ConvertFrom-Json; "
          f"$r = @(Get-StalePackageNames -Names $n -Keep {keep} -MaxAgeDays {max_age} "
          f"-Now ([datetime]::ParseExact('{NOW}', 'yyyy-MM-dd HH:mm:ss', $null)) -Current '{current}'); "
          "ConvertTo-Json -InputObject $r -Compress")
    out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip() or "[]")


D8, D6, D1, D0 = ("20260917_110000_aaaaaaa", "20260919_120000_bbbbbbb",
                  "20260924_120000_ccccccc", "20260925_115000_ddddddd")


def test_packages_older_than_a_week_are_removed():
    assert _stale([D8, D6, D1, D0], keep=0, max_age=7, current=D0) == [D8]


def test_exactly_seven_days_old_is_kept_one_second_more_is_removed():
    edge, over = "20260918_120000_eeeeeee", "20260918_115959_fffffff"
    assert _stale([edge, over, D0], keep=0, max_age=7, current=D0) == [over]


def test_count_rule_still_applies_and_the_two_rules_combine():
    # 份數規則：保留最新 2 份 ⇒ D8、D6 都該刪；D8 同時也超過一週 ⇒ 只列一次
    assert _stale([D8, D6, D1, D0], keep=2, max_age=7, current=D0) == [D8, D6]


def test_the_package_just_built_is_never_removed():
    # 時間戳異常（例如系統時間錯）使剛做好的包看起來很舊：仍不可刪
    assert _stale([D8], keep=0, max_age=7, current=D8) == []
    assert _stale([D8, D6], keep=1, max_age=0, current=D6) == [D8]


def test_folders_not_named_like_a_package_are_left_alone():
    manual = ["20260901_備份", "舊包_留存", "20260901_000000", "20260901_000000_notahex"]
    assert _stale(manual + [D0], keep=1, max_age=7, current=D0) == []


def test_zero_disables_each_rule():
    assert _stale([D8, D6, D1, D0], keep=0, max_age=0, current=D0) == []
    assert _stale([D8, D6, D1, D0], keep=0, max_age=30, current=D0) == []


def test_the_build_script_parses_and_wires_the_age_rule():
    ps = ("$e = $null; $t = $null; "
          f"[void][System.Management.Automation.Language.Parser]::ParseFile('{BUILD}', [ref]$t, [ref]$e); "
          "$e.Count")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "0", ("build_deploy_package.ps1 語法錯誤", out.stdout, out.stderr)
    src = BUILD.read_text(encoding="utf-8-sig")
    assert "[int]$MaxAgeDays = 7" in src
    assert '_package_prune.ps1' in src and "Get-StalePackageNames" in src and "-MaxAgeDays $MaxAgeDays" in src
    assert PRUNE.read_bytes()[:3] == b"\xef\xbb\xbf", "含中文的 .ps1 要有 BOM（PowerShell 5.1 否則以系統編碼解讀）"
