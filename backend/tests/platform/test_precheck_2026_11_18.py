# -*- coding: utf-8 -*-
"""precheck／run_tests_summary／install_hooks 的題（feat/dev-precheck，DEV-RULES-TOKEN 第 4～11 條）。

只驗純函式與清單檔本身（不真的起 pytest）：precheck_sets.json 沒有死條目、分類規則、PASS/FAIL 判定與最後一行格式、
測試輸出行數上限、預設基準挑「最近的整合線」、hook 文字帶著 precheck 與 --no-verify 的規定。
"""
import importlib.util
import os
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOLS = REPO / "tools" / "platform"
BACKEND = REPO / "backend"


def _tool(name):
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("_t_" + name, str(TOOLS / (name + ".py")))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


PC = _tool("precheck")
RTS = _tool("run_tests_summary")


# ── 清單檔 ──

def test_sets_file_loads_and_has_no_dead_entries():
    sets = PC.load_sets()
    missing = [e["path"] for e in sets["files"] if not (BACKEND / e["path"]).is_file()]
    assert not missing, "precheck_sets.json 列了不存在的檔（改名或刪除了？）：%s" % missing


def test_sets_groups_exist_in_preflight_guards():
    sets = PC.load_sets()
    cfg = json.loads((TOOLS / "preflight_guards.json").read_text(encoding="utf-8"))
    ids = {g["id"] for g in cfg["groups"]}
    assert set(sets["preflight_groups"]) <= ids
    assert set(sets.get("closing_groups", [])) <= ids


def test_sets_reject_duplicates_and_missing_fix(tmp_path):
    base = {"preflight_groups": [], "files": [{"path": "a.py", "why": "w", "fix": "f"}, {"path": "a.py", "why": "w", "fix": "f"}]}
    p = tmp_path / "s.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError):
        PC.load_sets(p)
    base["files"] = [{"path": "a.py", "why": "w"}]
    p.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError):
        PC.load_sets(p)


def test_pm_named_guards_are_in_the_set():
    paths = {e["path"] for e in PC.load_sets()["files"]}
    for must in ("tests/platform/test_module_boundaries.py", "tests/platform/test_l1_does_not_load_m01.py", "tests/test_pdf_escape_2026_10_14.py",
                 "tests/platform/test_e2e_lint_2026_11_13.py", "tests/platform/test_no_text_anchor_in_tests_2026_11_14.py",
                 "tests/platform/test_audit_reads_scoped_to_own_rows_2026_11_14.py",
                 "tests/platform/test_case_summary_purpose.py", "tests/platform/test_route_inventory.py", "tests/platform/test_page_paths_centralized.py"):
        assert must in paths, must


# ── 分類 ──

@pytest.mark.parametrize("code,cls", [("A0", "closing"), ("A1", "closing"), ("C1", "closing"), ("F1", "closing"),
                                      ("A8", "author"), ("A5", "author"), ("P0", "author"), ("A3", "author")])
def test_static_classification(code, cls):
    assert PC.classify_static({"code": code}) == cls


def test_failure_classification_uses_file_entry_then_group():
    sets = PC.load_sets()
    cls, fix, _why = PC.classify_failure("tests/platform/test_changelog_sections.py::test_x", sets)
    assert cls == "closing" and fix
    cls, fix, _why = PC.classify_failure("backend/tests/test_pdf_escape_2026_10_14.py::test_ratchet", sets)
    assert cls == "author" and "esc" in fix
    cls, _fix, why = PC.classify_failure("tests/platform/test_unlisted.py::t", sets, {"tests/platform/test_unlisted.py": "generated"}, {"generated"})
    assert cls == "closing" and "generated" in why
    assert PC.classify_failure("tests/whatever.py::t", sets)[0] == "author"


def test_status_decision():
    assert PC.decide_status([], [], False) == "PASS"
    assert PC.decide_status([{"where": "x"}], [], False) == "FAIL"
    assert PC.decide_status([{"where": "x"}], ["u"], True) == "FAIL"
    assert PC.decide_status([], ["沒跑到"], False) == "INCOMPLETE"
    assert PC.decide_status([], [], True) == "INCOMPLETE"


def _ctx(**over):
    ctx = {"branch": "feat/x", "head": "abcdef0123456789", "base": "1234567890", "base_ref": "train/t88-int", "dirty": False, "secs": 91.4,
           "author": [], "closing": [], "unchecked": [], "warns": [], "static_n": 0, "log": "L.log",
           "tests": {"files": 47, "passed": 800, "failed": 0, "skipped": 3}, "status": "PASS"}
    ctx.update(over)
    return ctx


def test_final_line_is_pasteable_and_carries_counts_and_head():
    line = PC.final_line(_ctx(closing=[{"where": "a"}, {"where": "b"}]))
    assert line.startswith("PRECHECK PASS")
    assert "作者要修 0" in line and "收尾類 2" in line and "head=abcdef012" in line and line.endswith("clean")
    assert PC.final_line(_ctx(dirty=True, status="FAIL", author=[{"where": "x"}])).startswith("PRECHECK FAIL")
    assert PC.final_line(_ctx(dirty=True)).endswith("dirty")


def test_report_has_both_blocks_and_ends_with_the_final_line():
    items = [{"where": "[測試] t::a", "msg": "m", "fix": "照這樣修"}]
    lines = PC.build_report(_ctx(author=items, closing=items, status="FAIL"))
    text = "\n".join(lines)
    assert "【作者要修】1 項" in text and "【收尾類（整合者處理，不擋交件）】1 項" in text and "修法：照這樣修" in text
    assert lines[-1].startswith("PRECHECK FAIL")


def test_report_caps_long_lists():
    many = [{"where": "[A8] f%d" % i, "msg": "m", "fix": "f"} for i in range(PC.MAX_SHOW + 5)]
    text = "\n".join(PC.build_report(_ctx(author=many, status="FAIL")))
    assert "另 5 項" in text


def test_touches_code_ignores_docs_only_pushes():
    assert not PC.touches_code(["docs/platform/PLAYBOOK.md", "README.md"])
    assert PC.touches_code(["docs/x.md", "backend/modules/case/api/quotations.py"])
    assert PC.touches_code(["frontend/js/app.js"])


# ── 預設基準：最近的整合線 ──

def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


def _sha(repo, rev):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", rev], check=True, capture_output=True, text=True).stdout.strip()


def test_pick_base_prefers_the_nearest_train_over_origin_platform(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / "a").write_text("1")
    _git(r, "add", "a")
    _git(r, "commit", "-q", "-m", "a")
    plat = _sha(r, "HEAD")
    _git(r, "update-ref", "refs/remotes/origin/platform", plat)
    _git(r, "checkout", "-q", "-b", "train/t99-int")
    (r / "b").write_text("2")
    _git(r, "add", "b")
    _git(r, "commit", "-q", "-m", "b")
    train = _sha(r, "HEAD")
    _git(r, "checkout", "-q", "-b", "feat/mine")
    (r / "c").write_text("3")
    _git(r, "add", "c")
    _git(r, "commit", "-q", "-m", "c")
    mb, ref = PC.pick_base(r)
    assert (mb, ref) == (train, "train/t99-int")
    assert mb != plat


def test_pick_base_without_any_integration_ref_is_empty(tmp_path):
    r = tmp_path / "r2"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / "a").write_text("1")
    _git(r, "add", "a")
    _git(r, "commit", "-q", "-m", "a")
    assert PC.pick_base(r) == ("", "")


# ── run_tests_summary ──

_XML = """<testsuites><testsuite>
<testcase classname="tests.platform.test_precheck_2026_11_18" name="test_sets_file_loads_and_has_no_dead_entries"/>
<testcase classname="tests.platform.test_precheck_2026_11_18" name="test_a"><failure message="boom: 修這裡&#10;detail">x</failure></testcase>
<testcase classname="tests.platform.test_precheck_2026_11_18" name="test_b"><error message="setup died">x</error></testcase>
<testcase classname="tests.platform.test_precheck_2026_11_18" name="test_c"><skipped message="s"/></testcase>
</testsuite></testsuites>"""


def test_parse_junit_failures_counts_and_nodeids():
    counts, fails = RTS.parse_junit_failures(_XML, BACKEND)
    assert counts == {"passed": 1, "failed": 1, "skipped": 1, "error": 1}
    assert [f["nodeid"] for f in fails] == ["tests/platform/test_precheck_2026_11_18.py::test_a", "tests/platform/test_precheck_2026_11_18.py::test_b"]
    assert fails[0]["message"] == "boom: 修這裡" and fails[1]["kind"] == "error"


def test_parse_junit_failures_garbage_is_none():
    assert RTS.parse_junit_failures("", BACKEND) == (None, [])
    assert RTS.parse_junit_failures("<not xml", BACKEND) == (None, [])


def test_render_never_exceeds_twenty_lines_and_ends_with_log():
    fails = [{"nodeid": "tests/t_%d.py::test_x" % i, "kind": "failed", "message": "m" * 300} for i in range(100)]
    s = RTS.summarize({"passed": 5, "failed": 100, "skipped": 1, "error": 0}, fails, 12.3, "C:/log.txt", 1)
    lines = RTS.render(s)
    assert len(lines) <= RTS.MAX_LINES
    assert lines[0].startswith("FAIL") and "紅 100" in lines[0]
    assert lines[-1] == "log：C:/log.txt"
    assert any("另" in x and "見 log" in x for x in lines)
    assert all(len(x) <= 140 for x in lines[1:-1])


def test_render_green_is_two_lines_and_missing_junit_is_not_green():
    green = RTS.render(RTS.summarize({"passed": 9, "failed": 0, "skipped": 0, "error": 0}, [], 1.0, "L", 0))
    assert len(green) == 2 and green[0].startswith("PASS")
    none = RTS.render(RTS.summarize(None, [], 1.0, "L", 2))
    assert "沒有拿到 junit" in none[0]


# ── hook／安裝 ──

def test_pre_push_hook_runs_precheck_and_documents_no_verify():
    text = (REPO / ".githooks" / "pre-push").read_text(encoding="utf-8")
    assert "precheck.py" in text and "--hook" in text
    assert "--no-verify" in text and "不得" in text
    assert "prepush_check.py" in text                                     # 整合分支仍走原本的檢查


def test_install_hooks_problems_mentions_missing_registration(tmp_path):
    IH = _tool("install_hooks")
    r = tmp_path / "bare"
    r.mkdir()
    _git(r, "init", "-q")
    ps = IH.problems(r)
    assert any("core.hooksPath" in p for p in ps)
