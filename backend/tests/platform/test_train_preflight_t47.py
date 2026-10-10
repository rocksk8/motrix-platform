# -*- coding: utf-8 -*-
"""列車預檢（tools/platform/train_preflight.py）的自測：六類靜態旗標各有正對照（合成樹會被抓）與反向對照（乾淨不誤報）；
B 層選擇規則；C 層去重；報告分組；dry-run 不執行 pytest。全部用合成樹／注入的 runner，不跑真的 pytest 子行程。"""
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PAGES = "frontend" + "/pages/"            # 合成樹的相對路徑（本檔的 repo 是 tmp_path，不是真的 frontend）
sys.path.insert(0, str(REPO / "tools" / "platform"))
import train_preflight as TP  # noqa: E402


def _w(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _copy(root, rel):
    dst = Path(root) / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / rel, dst)


# ── A1 changelog ─────────────────────────────────────────────────────────

@pytest.fixture()
def cl_repo(tmp_path):
    _copy(tmp_path, "backend/tests/platform/test_changelog_sections.py")
    return tmp_path


def test_a1_clean_changelog_is_not_flagged(cl_repo):
    _w(cl_repo, "backend/modules/m/CHANGELOG.md", "# x\n\n## (next) — a\n- 新\n\n## 1.0.2 — b\n- 二\n\n## 1.0.1 — c\n- 一\n")
    assert TP.check_changelogs(cl_repo) == []


def test_a1_buried_next_block_is_flagged(cl_repo):
    _w(cl_repo, "backend/modules/m/CHANGELOG.md", "# x\n\n## 1.0.2 — b\n- 二\n\n## (next) — a\n- 新\n\n## 1.0.1 — c\n- 一\n")
    f = TP.check_changelogs(cl_repo)
    assert any("被埋住" in x.msg for x in f) and all(x.code == "A1" for x in f)


def test_a1_non_descending_versions_flagged(cl_repo):
    _w(cl_repo, "backend/modules/m/CHANGELOG.md", "# x\n\n## 1.0.1 — c\n- 一\n\n## 1.0.2 — b\n- 二\n")
    assert any("遞減" in x.msg for x in TP.check_changelogs(cl_repo))


def test_a1_missing_scanner_is_reported_not_silently_green(tmp_path):
    f = TP.check_changelogs(tmp_path)
    assert f and isinstance(f[0], TP.Unchecked)


# ── A3 global tests ──────────────────────────────────────────────────────

def _bl(root, tests):
    _w(root, "tools/platform/bottom_layer.json", json.dumps({"global_tests": tests}))


def test_a3_unregistered_global_scan_test_flagged_and_registered_clean(tmp_path):
    _w(tmp_path, "backend/tests/test_x.py", "def test_a():\n    q = 'sqlite_master'\n")
    _bl(tmp_path, [])
    f = TP.check_global_tests(tmp_path)
    assert [x.code for x in f] == ["A3"] and "backend/tests/test_x.py" in f[0].msg
    _bl(tmp_path, ["backend/tests/test_x.py"])
    assert TP.check_global_tests(tmp_path) == []


def test_a3_stale_entry_flagged(tmp_path):
    _w(tmp_path, "backend/tests/test_y.py", "def test_a():\n    pass\n")
    _bl(tmp_path, ["backend/tests/test_y.py"])
    assert any("移除" in x.fix for x in TP.check_global_tests(tmp_path))


# ── A4 doc types ─────────────────────────────────────────────────────────

def _doc_repo(root, registered_code, in_tables):
    _w(root, "backend/modules/pay/api/ap.py", 'DOC_TYPE = "%s"\nregister_doc_type(DOC_TYPE, "x", unified=False)\n' % registered_code)
    keys = ", ".join('"%s": 1' % c for c in in_tables)
    _w(root, "backend/tests/test_approval_flow_scope.py", "def t():\n    EXPECTED_SCOPE = {%s}\nFULL_SCOPE_BODY = {%s}\n" % (keys, keys))
    _w(root, "backend/tools/check_approval_queue_coverage.py", "_QUEUE_TYPE_FOR_DOC_TYPE = {%s}\n_OWNER_MODULE = {%s}\n" % (keys, keys))


def test_a4_new_doc_type_missing_from_tables_flagged(tmp_path):
    _doc_repo(tmp_path, "slipx", ["quotation"])
    f = TP.check_doc_types(tmp_path)
    assert len(f) == 4 and all("slipx" in x.msg for x in f)


def test_a4_registered_everywhere_is_clean(tmp_path):
    _doc_repo(tmp_path, "slipx", ["quotation", "slipx"])
    assert TP.check_doc_types(tmp_path) == []


# ── A5 BEGIN ─────────────────────────────────────────────────────────────

def test_a5_new_begin_site_flagged_and_removed_clean(tmp_path):
    _copy(tmp_path, "backend/tests/test_begin_only_via_begin_write_2026_09_25.py")
    _w(tmp_path, "backend/modules/zz/api/x.py",
       "def go(conn):\n    try:\n        conn.execute('BEGIN IMMEDIATE')\n        conn.commit()\n    finally:\n        conn.close()\n")
    f = TP.check_begin_sites(tmp_path)
    assert [x.code for x in f] == ["A5"] and "modules/zz/api/x.py" in f[0].where
    _w(tmp_path, "backend/modules/zz/api/x.py", "def go(conn):\n    return 1\n")
    assert TP.check_begin_sites(tmp_path) == []


# ── A6 golden ────────────────────────────────────────────────────────────

def _golden_repo(root):
    _w(root, PAGES + "case-x.html", "<html></html>")
    _w(root, "frontend/js/case-x-more.js", "//")
    _w(root, "backend/tests/golden_cx.json", "{}")
    _w(root, "backend/tests/test_e2e_cx.py", 'G = pathlib.Path(__file__).with_name("golden_cx.json")\nPAGE = "case-x.html"\n')


def test_a6_changed_covered_page_flagged_unless_golden_rerecorded(tmp_path):
    _golden_repo(tmp_path)
    f = TP.check_golden(tmp_path, ["frontend/js/case-x-more.js"])
    assert [x.code for x in f] == ["A6"] and "case-x-more.js" in f[0].where
    assert TP.check_golden(tmp_path, ["frontend/js/case-x-more.js", "backend/tests/golden_cx.json"]) == []
    assert TP.check_golden(tmp_path, [PAGES + "other.html"]) == []


# ── B/C 選擇 ─────────────────────────────────────────────────────────────

def _sel_repo(root):
    _w(root, "backend/tests/platform/test_p.py", "def test_a():\n    pass\n")
    _w(root, "backend/tests/test_fast.py", "def test_a():\n    pass\n")
    _w(root, "backend/tests/test_slow.py", "def test_a():\n    pass\n")
    _w(root, "backend/tests/test_unmeasured.py", "def test_a():\n    pass\n")
    _w(root, "backend/tests/test_scan.py", "def test_a():\n    list(p.rglob('*.py'))\n")
    _w(root, "backend/tests/test_e2e_page.py", "def test_a():\n    pass\n")
    _w(root, "backend/modules/pay/tests/test_m.py", "def test_a():\n    pass\n")
    _w(root, "tools/platform/gate_slices.json",
       json.dumps({"slice0": {"paths": [{"label": "p", "path": "tests/platform"}], "exclude": ["tests/platform/test_slow_tool.py"]}}))
    _w(root, "backend/tests/platform/test_slow_tool.py", "def test_a():\n    pass\n")


def test_select_cheap_rules(tmp_path):
    _sel_repo(tmp_path)
    secs = {"backend/tests/test_fast.py": 2.0, "backend/tests/test_slow.py": 60.0, "backend/tests/test_scan.py": 70.0}
    files, why = TP.select_cheap(tmp_path, secs, full=True)
    assert "tests/platform/test_p.py" in files                      # tests/platform 入選
    assert "tests/platform/test_slow_tool.py" not in files           # gate_slices exclude 的慢題不入選
    assert "tests/test_fast.py" in files and why["tests/test_fast.py"].startswith("實測")
    assert "tests/test_slow.py" not in files                         # 量過而且慢 ⇒ 不選
    assert "tests/test_unmeasured.py" not in files                   # 沒量過的普通檔不猜
    assert "tests/test_scan.py" not in files                         # 掃描特徵但已知 >3 倍門檻 ⇒ 不選
    assert "tests/test_e2e_page.py" not in files                     # e2e 檔不選
    secs["backend/tests/test_scan.py"] = 5.0
    assert "tests/test_scan.py" in TP.select_cheap(tmp_path, secs, full=True)[0]
    assert "tests/test_scan.py" in TP.select_cheap(tmp_path, {}, full=True)[0]  # 沒量過但有掃描特徵 ⇒ 入選


def test_targets_dedupe_impacted_dirs(tmp_path):
    _sel_repo(tmp_path)
    plan = TP.build_targets(tmp_path, ["backend/modules/pay/api/x.py", "backend/modules/nodir/api/y.py"], True,
                            {"backend/modules/pay/tests/test_m.py": 1.0}, full=True)
    assert plan["impacted_keys"] == ["pay", "nodir"] and plan["no_test_dir"] == ["nodir"]
    assert "modules/pay/tests/test_m.py" in plan["cheap"]
    assert "modules/pay/tests" not in plan["targets"]                # 已被便宜清單涵蓋的目錄不重複加
    plan2 = TP.build_targets(tmp_path, ["backend/modules/pay/api/x.py"], True, {}, full=True)
    assert "modules/pay/tests" in plan2["targets"]
    assert "modules/pay/tests" not in TP.build_targets(tmp_path, ["backend/modules/pay/api/x.py"], False, {})["targets"]


# ── 報告與流程 ───────────────────────────────────────────────────────────

def test_preflight_dry_run_never_calls_the_runner(tmp_path, monkeypatch):
    _sel_repo(tmp_path)
    monkeypatch.setattr(TP, "static_checks", lambda repo, changed, base="x": [])
    monkeypatch.setattr(TP, "changed_files", lambda repo, base: [])
    called = []
    code, text, data = TP.preflight(tmp_path, dry_run=True, runner=lambda *a: called.append(a))
    assert called == [] and code == 0 and data["rc"] is None and "測試：選" in text


def test_preflight_reports_all_reds_in_one_pass_and_exit_1(tmp_path, monkeypatch):
    _sel_repo(tmp_path)
    monkeypatch.setattr(TP, "static_checks", lambda repo, changed, base="x": [TP.Finding("A5", "x.py:3", "新的 BEGIN", "改用 begin_write")])
    monkeypatch.setattr(TP, "changed_files", lambda repo, base: ["backend/modules/pay/api/x.py"])
    out = ("FAILED tests/platform/test_p.py::test_a - AssertionError: x\nFAILED modules/pay/tests/test_m.py::test_a - boom\n"
           "2 failed, 10 passed in 3.00s\n")
    code, text, data = TP.preflight(tmp_path, runner=lambda repo, targets: (1, out, 3.0))
    assert code == 1
    assert "[A5]" in text and "歸屬 pay" in text and "歸屬 core" in text and "2 failed" in text


def test_preflight_all_green_exit_0(tmp_path, monkeypatch):
    _sel_repo(tmp_path)
    monkeypatch.setattr(TP, "static_checks", lambda repo, changed, base="x": [])
    monkeypatch.setattr(TP, "changed_files", lambda repo, base: [])
    code, text, _ = TP.preflight(tmp_path, runner=lambda repo, targets: (0, "5 passed in 1s\n", 1.0))
    assert code == 0 and "全綠" in text


def test_unchecked_scanner_makes_the_run_not_green(tmp_path, monkeypatch):
    _sel_repo(tmp_path)
    monkeypatch.setattr(TP, "static_checks", lambda repo, changed, base="x": [TP.Unchecked("A2", "匯入失敗")])
    monkeypatch.setattr(TP, "changed_files", lambda repo, base: [])
    code, text, _ = TP.preflight(tmp_path, static_only=True)
    assert code == 1 and "未能檢查" in text


def test_real_tree_a1_a3_a4_a5_have_no_false_positives():
    """現行樹這四類應全綠（A2 要掃全部產品檔、A6 看變動，不在這裡跑）。誤報＝工具壞了。"""
    assert TP.check_changelogs(REPO) == []
    assert TP.check_global_tests(REPO) == []
    assert TP.check_doc_types(REPO) == []
    assert TP.check_begin_sites(REPO) == []


# ── A0 / A7 / A8 / 固定清單 ─────────────────────────────────────────────

def _fake_regen(root, body):
    _w(root, "tools/platform/regen_all.py", body)


def test_a0_uses_regen_all_run_api_stale_ok_error_and_absent(tmp_path):
    assert TP.check_generated(tmp_path) == []                       # 工具還沒進樹 ⇒ 略過（B 層的 test_generated_maps 仍會抓）
    _fake_regen(tmp_path, "def run(repo, check_only=False, py=None, **k):\n    assert check_only\n"
                          "    return {'ok': False, 'stale': ['test_map.json', 'dep_graph.json'], 'error': None}\n")
    f = TP.check_generated(tmp_path)
    assert [x.code for x in f] == ["A0"] and "test_map.json" in f[0].msg and "dep_graph.json" in f[0].msg
    _fake_regen(tmp_path, "def run(repo, check_only=False, py=None, **k):\n    return {'ok': True, 'stale': [], 'error': None}\n")
    assert TP.check_generated(tmp_path) == []
    _fake_regen(tmp_path, "def run(repo, check_only=False, py=None, **k):\n    return {'ok': False, 'stale': [], 'error': 'dep_scan 失敗'}\n")
    f = TP.check_generated(tmp_path)
    assert len(f) == 1 and isinstance(f[0], TP.Unchecked) and "dep_scan" in f[0].msg
    _fake_regen(tmp_path, "def run(*a, **k):\n    raise RuntimeError('boom')\n")
    assert isinstance(TP.check_generated(tmp_path)[0], TP.Unchecked)


def _style_repo(root):
    _w(root, PAGES + "case-y.html", "<html></html>")
    _w(root, "backend/tests/golden_sty.json", "{}")
    _w(root, "backend/tests/test_e2e_sty.py",
       'G = pathlib.Path(__file__).with_name("golden_sty.json")\nPAGE = "case-y.html"\nSEL = [".cm-header", ".cm-tab.active"]\nJS = "getComputedStyle(el)"\n')


def test_a6_style_golden_is_flagged_only_when_css_relevant_lines_change(tmp_path):
    _style_repo(tmp_path)
    ch = [PAGES + "case-y.html"]
    content_only = '+++ b/x\n+<div style="padding:8px" x-data>新區塊</div>\n-<span>舊</span>\n'
    assert TP.check_golden(tmp_path, ch, diff_fn=lambda files: content_only) == []                     # 內容性改動（行內 style）不旗標
    assert [x.code for x in TP.check_golden(tmp_path, ch, diff_fn=lambda files: '+<h1 class="cm-header big">')] == ["A6"]
    assert [x.code for x in TP.check_golden(tmp_path, ch, diff_fn=lambda files: "+<style>.a{}</style>")] == ["A6"]
    assert TP.check_golden(tmp_path, ["frontend/css/site.css"], diff_fn=lambda files: "")[0].code == "A6"   # 動到 CSS 檔
    assert TP.check_golden(tmp_path, ch + ["backend/tests/golden_sty.json"], diff_fn=lambda files: "+cm-header") == []


def test_a7_hardcoded_db_version_flagged_unless_file_defines_its_own_fake_db(tmp_path):
    _w(tmp_path, "backend/db.py", "CURRENT_VERSION = 118\n")
    _w(tmp_path, "backend/tests/test_old.py", 'ARGS = ["--expect-db-version", "116"]\n')
    f = TP.check_db_version_literals(tmp_path)
    assert [x.code for x in f] == ["A7"] and "116" in f[0].msg and "118" in f[0].msg
    _w(tmp_path, "backend/tests/test_old.py", 'ARGS = ["--expect-db-version", "118"]\n')
    assert TP.check_db_version_literals(tmp_path) == []
    _w(tmp_path, "backend/tests/test_old.py", 'FAKE = "CURRENT_VERSION = 116"\nARGS = ["--expect-db-version", "116"]\n')
    assert TP.check_db_version_literals(tmp_path) == []             # 夾具自己造的假 db.py


def test_a8_bare_get_db_in_changed_test_flagged_only_without_db_fixture(tmp_path):
    _w(tmp_path, "backend/tests/test_new.py",
       "import db\n\ndef test_bare():\n    db.get_db()\n\ndef test_ok(client):\n    db.get_db()\n\ndef test_no_db():\n    pass\n")
    f = TP.check_bare_get_db(tmp_path, ["backend/tests/test_new.py", "backend/tests/not_changed.py"])
    assert [x.code for x in f] == ["A8"] and "test_bare" in f[0].msg
    assert TP.check_bare_get_db(tmp_path, []) == []


def test_always_files_are_selected_even_without_timing_data(tmp_path):
    _w(tmp_path, "backend/tests/test_version_manifest_2026_09_22.py", "def test_a():\n    pass\n")
    _w(tmp_path, "tools/platform/gate_slices.json", json.dumps({"slice0": {"paths": [{"label": "p", "path": "tests/platform"}], "exclude": []}}))
    files, why = TP.select_cheap(tmp_path, {})
    assert "tests/test_version_manifest_2026_09_22.py" in files and why["tests/test_version_manifest_2026_09_22.py"] == "固定清單"


# ── 窄版預設與時間預算 ───────────────────────────────────────────────────

def test_default_selection_is_narrow_and_full_cheap_is_opt_in(tmp_path):
    _sel_repo(tmp_path)
    _w(tmp_path, "backend/tests/platform/test_scanner.py", "def test_a():\n    list(p.rglob('*.py'))\n")
    _w(tmp_path, "backend/tests/test_version_manifest_2026_09_22.py", "def test_a():\n    pass\n")
    _w(tmp_path, "backend/tests/test_globalish.py", "def test_a():\n    q = 'sqlite_master'\n")
    _w(tmp_path, "tools/platform/scope_gate_dummy.txt", "x")
    secs = {"backend/tests/test_fast.py": 1.0}
    narrow, why = TP.select_cheap(tmp_path, secs)
    assert "tests/platform/test_scanner.py" in narrow and why["tests/platform/test_scanner.py"] == "tests/platform 掃描特徵"
    assert "tests/test_version_manifest_2026_09_22.py" in narrow                       # 固定清單
    assert "tests/platform/test_p.py" not in narrow                                    # 沒有掃描特徵的 platform 檔：窄版不選
    assert "tests/test_fast.py" not in narrow and "tests/test_scan.py" not in narrow    # 量過的小檔、其他掃描型：只在 --full-cheap
    full, _ = TP.select_cheap(tmp_path, secs, full=True)
    assert set(narrow) < set(full) and "tests/platform/test_p.py" in full and "tests/test_fast.py" in full


def test_run_pytest_budget_timeout_returns_incomplete_with_partial_output(tmp_path, monkeypatch):
    import subprocess

    def boom(cmd, **kw):
        assert kw.get("timeout") == 60
        raise subprocess.TimeoutExpired(cmd, 60, output="FAILED tests/platform/test_x.py::t - boom\n")
    monkeypatch.setattr(TP.subprocess, "run", boom)
    rc, out, secs = TP.run_pytest(tmp_path, ["tests/x.py"], tag="pf_unit", timeout=60)
    assert rc == TP.INCOMPLETE_RC and "FAILED tests/platform/test_x.py" in out


def test_preflight_over_budget_is_incomplete_exit_3_never_green(tmp_path, monkeypatch):
    _sel_repo(tmp_path)
    monkeypatch.setattr(TP, "static_checks", lambda repo, changed, base="x": [])
    monkeypatch.setattr(TP, "changed_files", lambda repo, base: [])
    code, text, data = TP.preflight(tmp_path, runner=lambda repo, targets: (TP.INCOMPLETE_RC, "FAILED tests/platform/test_p.py::t - x\n", 61.0))
    assert code == 3 and "未完成" in text and "不能當作綠" in text and "全綠" not in text


def test_budget_min_is_passed_to_run_pytest_as_seconds(tmp_path, monkeypatch):
    _sel_repo(tmp_path)
    monkeypatch.setattr(TP, "static_checks", lambda repo, changed, base="x": [])
    monkeypatch.setattr(TP, "changed_files", lambda repo, base: [])
    seen = {}
    monkeypatch.setattr(TP, "run_pytest", lambda repo, targets, **kw: seen.update(kw) or (0, "1 passed\n", 1.0))
    TP.preflight(tmp_path, budget_min=2.5)
    assert seen["timeout"] == 150


def test_narrow_selection_drops_measured_slow_files_but_keeps_the_always_list(tmp_path):
    _sel_repo(tmp_path)
    _w(tmp_path, "backend/tests/platform/test_scan_slow.py", "def test_a():\n    list(p.rglob('*.py'))\n")
    _w(tmp_path, "backend/tests/platform/test_scan_fast.py", "def test_a():\n    list(p.rglob('*.py'))\n")
    _w(tmp_path, "backend/tests/platform/test_generated_maps.py", "def test_a():\n    list(p.rglob('*.py'))\n")
    secs = {"backend/tests/platform/test_scan_slow.py": 31.0, "backend/tests/platform/test_scan_fast.py": 29.0,
            "backend/tests/platform/test_generated_maps.py": 120.0}
    files, _ = TP.select_cheap(tmp_path, secs)
    assert "tests/platform/test_scan_slow.py" not in files and "tests/platform/test_scan_fast.py" in files
    assert "tests/platform/test_generated_maps.py" in files                   # 固定清單不受慢檔門檻影響
    assert "tests/platform/test_scan_slow.py" in TP.select_cheap(tmp_path, secs, full=True)[0]


def test_full_lint_targets_are_platform_dir_plus_existing_guard_files_and_use_three_workers(tmp_path):
    """--full-lint（M1）：目標＝tests/platform 整個目錄＋清單內存在的檔（不存在的略過）；預檢以 FULL_LINT_WORKERS 個 worker 跑。"""
    b = tmp_path / "backend"
    (b / "tests" / "platform").mkdir(parents=True)
    (b / "tests" / "test_system_audit_2026_09_14.py").write_text("", encoding="utf-8")
    t = TP.full_lint_targets(tmp_path)
    assert t[0] == "tests/platform" and "tests/test_system_audit_2026_09_14.py" in t
    assert "tests/test_view_filter_marking_2026_09_25.py" not in t, "不存在的檔不放進目標"
    assert TP.FULL_LINT_WORKERS == 3
    assert len(TP.FULL_LINT_FILES) == len(set(TP.FULL_LINT_FILES))
    for f in ("tests/test_system_audit_2026_09_14.py", "tests/test_write_endpoints_are_audited_2026_09_24.py", "tests/test_approval_no_freeze_2026_09_30.py"):
        assert f in TP.FULL_LINT_FILES, "T53 抓到的守門檔必須在清單內：" + f
