# -*- coding: utf-8 -*-
"""T35 item 4：測試時間預算警報（tools/platform/time_budget.py）——只警告、永不擋建包。"""
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOLS = REPO / "tools" / "platform"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import time_budget as TB  # noqa: E402

BASE = {"tests": 100, "total_ws": 1000.0, "files": {"backend/tests/a.py": 500.0, "backend/tests/b.py": 500.0}}


def _junit(tmp_path, rows, name="j.xml"):
    body = "".join('<testcase classname="%s" name="t%d" time="%s"/>' % (c, i, t) for i, (c, t) in enumerate(rows))
    p = tmp_path / name
    p.write_text('<testsuites><testsuite>%s</testsuite></testsuites>' % body, encoding="utf-8")
    return p


def test_classname_to_file_handles_module_paths_and_classes():
    assert TB.classname_to_file("tests.platform.test_x") == "backend/tests/platform/test_x.py"
    assert TB.classname_to_file("modules.payroll.tests.test_y.TestK") == "backend/modules/payroll/tests/test_y.py"
    assert TB.classname_to_file("") == ""


def test_no_alarm_at_baseline():
    r = TB.check({"backend/tests/a.py": 500.0, "backend/tests/b.py": 500.0}, 100, BASE)
    assert r["alarms"] == [] and r["total_ws"] == 1000.0


def test_new_slow_file_alarms_but_new_fast_file_does_not():
    cur = {"backend/tests/a.py": 500.0, "backend/tests/b.py": 500.0, "backend/tests/new_slow.py": 31.0, "backend/tests/new_fast.py": 5.0}
    r = TB.check(cur, 120, BASE, changelog_text="- 時間預算：新增兩個檔")        # 總量成長已有理由，只剩單檔規則
    kinds = [(a["kind"], a["file"]) for a in r["alarms"]]
    assert kinds == [("new_file", "backend/tests/new_slow.py")], kinds


def test_grown_file_needs_both_absolute_and_relative_growth():
    a = TB.check({"backend/tests/a.py": 540.0, "backend/tests/b.py": 500.0}, 100, BASE, "- 時間預算：x")
    assert [x["kind"] for x in a["alarms"]] == []                               # +40 但只 1.08 倍
    b = TB.check({"backend/tests/a.py": 500.0, "backend/tests/b.py": 500.0, "backend/tests/c.py": 0.0,
                  "backend/tests/d.py": 0.0}, 100, {**BASE, "files": {**BASE["files"], "backend/tests/c.py": 10.0}}, "")
    assert b["alarms"] == []
    c = TB.check({"backend/tests/c.py": 60.0}, 1, {"tests": 1, "total_ws": 10.0, "files": {"backend/tests/c.py": 10.0}}, "- 時間預算：x")
    assert [x["kind"] for x in c["alarms"]] == ["grown_file"]                   # +50 且 6 倍


def test_total_growth_alarms_unless_changelog_justifies_it():
    cur = {"backend/tests/a.py": 520.0, "backend/tests/b.py": 540.0}            # +6%
    assert [a["kind"] for a in TB.check(cur, 110, BASE, "")["alarms"]] == ["total_growth"]
    ok = TB.check(cur, 110, BASE, "# t\n\n- 時間預算：新增 10 題 API 整合\n")
    assert ok["alarms"] == [] and ok["justified"] is True
    within = {"backend/tests/a.py": 510.0, "backend/tests/b.py": 540.0}          # +5.0% 剛好不超過
    assert TB.check(within, 105, BASE, "")["alarms"] == []


def test_justification_only_counts_near_the_top_of_the_changelog():
    old = "\n".join(["x"] * (TB.JUSTIFY_LINES + 5)) + "\n- 時間預算：很久以前的理由\n"
    assert TB.has_justification(old) is False
    assert TB.has_justification("- 時間預算：現在的理由\n") is True
    assert TB.has_justification("- 時間預算：\n") is False                      # 沒有理由文字不算


def test_cli_and_run_check_never_fail_the_build(tmp_path):
    j = _junit(tmp_path, [("tests.test_a", "1.5")])
    assert TB.main(["check", str(j), "--baseline", str(tmp_path / "nope.json")]) == 0     # 基準不存在 ⇒ 仍 0
    r = TB.run_check([tmp_path / "missing.xml"])
    assert "error" in r and r["alarms"] == []                                   # junit 不存在 ⇒ 回錯誤、不丟例外
    bl = tmp_path / "b.json"
    TB.update_baseline([j], "t", bl)
    assert TB.main(["check", str(j), "--baseline", str(bl), "--json"]) == 0
    assert json.loads(bl.read_text(encoding="utf-8"))["files"] == {"backend/tests/test_a.py": 1.5}


def test_committed_baseline_is_loadable_and_covers_this_test_file_family():
    b = TB.load_baseline()
    assert b["tests"] > 5000 and b["total_ws"] > 3000 and b["files"]
    assert "backend/tests/platform/test_stage_select_2026_10_02.py" in b["files"]


def test_build_script_wires_junit_and_the_warn_only_check():
    ps1 = (REPO / "backend" / "tools" / "build_deploy_package.ps1").read_text(encoding="utf-8-sig")
    assert ps1.count('"--junitxml=${pytestTemp}_ne.xml"') == 1 and ps1.count('"--junitxml=${pytestTemp}_e2e.xml"') == 1
    i = ps1.index("time_budget.py")
    seg = ps1[i - 400:i + 1600]
    assert "try {" in seg and "catch" in seg, "時間預算呼叫必須在 try/catch 內（警告不可擋建包）"
    assert 'BuildStats["time_budget"]' in ps1
    assert not re.search(r"time_budget[^\n]*\bFail\b", ps1), "時間預算不可 Fail"
