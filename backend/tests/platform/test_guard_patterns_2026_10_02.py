# -*- coding: utf-8 -*-
"""跨檔守門的檔名樣式（tools/platform/guard_patterns.json；作者端守門集 A2 與增量選題底板共用）：資料本身合格、沒有死樣式、
含 d7 回放漏接的家族（archive、legal_amount_rounding）、掃得到 modules/*/tests。
反向控制：①沒有 why／重複／壞 roots 的資料 ⇒ problems 非空 ②拿掉一個樣式 ⇒ 該家族的檔不再被選到 ③樣式不含 * ⇒ 壞資料。"""
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[3] / "tools" / "platform"
sys.path.insert(0, str(TOOLS))
import guard_patterns as GP  # noqa: E402

REPO = TOOLS.parents[1]
REQUIRED = ("*approval*", "*queue*", "*pii*", "*privacy*", "*archive*", "*migration*", "*spec_coverage*", "*font_zoom*",
            "*money_round*", "*legal_amount_rounding*", "*wording*", "*changelog*")


def _tree():
    r = subprocess.run(["git", "-C", str(REPO), "ls-files", "backend"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not r.stdout.strip():
        pytest.skip("不是 git 樹")
    return r.stdout.splitlines()


def test_shipped_file_is_valid_and_has_the_required_families():
    d = GP.load()
    assert GP.problems(d) == []
    for need in REQUIRED:
        assert need in GP.patterns(d), need


def test_every_pattern_hits_at_least_one_real_test_file():
    """死樣式（改名後再也命中不到）會讓守門悄悄變少 ⇒ 這題紅。"""
    d, tree = GP.load(), _tree()
    dead = [g for g in GP.patterns(d) if not GP.match_files(tree, d, pats=(g,))]
    assert dead == [], "這些樣式命中 0 個檔：%s" % dead


def test_scan_covers_module_tests_and_core_tests_but_not_non_tests():
    d = GP.load()
    tree = ["backend/modules/subcontract/tests/test_pii_archive_mirror_x.py", "backend/core/tests/test_privacy_y.py",
            "backend/tests/test_legal_amount_rounding_guard.py", "backend/tests/helper_approval.py", "backend/tests/platform/test_archive_z.py",
            "frontend/pages/approval.html", "backend/tools/test_queue_tool.py"]
    got = GP.match_files(tree, d)
    assert got == sorted(["backend/modules/subcontract/tests/test_pii_archive_mirror_x.py", "backend/core/tests/test_privacy_y.py",
                          "backend/tests/test_legal_amount_rounding_guard.py", "backend/tests/platform/test_archive_z.py"])


def test_reverse_control_dropping_a_pattern_loses_its_family():
    d = GP.load()
    tree = ["backend/tests/test_archive_isolation_x.py", "backend/tests/test_legal_amount_rounding_guard.py"]
    assert GP.match_files(tree, d) == sorted(tree)
    without = tuple(p for p in GP.patterns(d) if p not in ("*archive*", "*legal_amount_rounding*"))
    assert GP.match_files(tree, d, pats=without) == []


def test_problems_flags_bad_data():
    base = {"version": 1, "roots": ["backend/tests"], "patterns": [{"glob": "*x*", "why": "w"}], "static_in_e2e_named": []}
    assert GP.problems(base) == []
    assert GP.problems(dict(base, patterns=[{"glob": "*x*", "why": ""}]))                       # 沒有 why
    assert GP.problems(dict(base, patterns=[{"glob": "*x*", "why": "w"}, {"glob": "*x*", "why": "w"}]))   # 重複
    assert GP.problems(dict(base, patterns=[{"glob": "noglob", "why": "w"}]))                   # 不含 *
    assert GP.problems(dict(base, roots=["tests"]))                                             # roots 不在 backend/
    assert GP.problems(dict(base, static_in_e2e_named=["*other*"]))                             # 不在 patterns
    assert GP.problems(dict(base, patterns=[]))
    assert GP.problems(dict(base, version=2))
