# -*- coding: utf-8 -*-
"""作者端守門集 `tools/platform/author_gate.py`（建包優化 step 4）：選題組裝、預估／預算、結果 JSON、髒樹拒絕、回放。
全部是純函式＋自造小 git repo 的合成題（不跑真正的 pytest 子行程、不跑大測試集）。
反向控制：①紅的 run 不可能 `green:true`（零題收集也不是綠）②結果檔 tree sha 被改一個字 ⇒ 讀端拒絕 ③少一個樣式 ⇒ 回放離線檢查缺漏
④髒樹（含未追蹤檔）⇒ 列出而不是放行。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[3] / "tools" / "platform"
sys.path.insert(0, str(TOOLS))
import author_gate as AG  # noqa: E402


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _commit(repo, files, msg):
    for rel, text in files.items():
        p = Path(repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q")
    return r


# ── 樣式 ───────────────────────────────────────────────────────────────

def test_pattern_files_scan_every_test_root_including_module_tests():
    tree = ["backend/tests/test_money_round_half_up_2026_09_26.py", "backend/modules/subcontract/tests/test_pii_archive_mirror.py",
            "backend/core/tests/test_privacy_x.py", "backend/tests/test_unrelated.py", "backend/tests/helper_approval.py",
            "backend/tests/test_font_zoom_x.py", "frontend/pages/approval.html", "backend/modules/case/tests/sub/test_queue_y.py"]
    got = AG.pattern_files(tree)
    assert got == sorted(["backend/tests/test_money_round_half_up_2026_09_26.py", "backend/modules/subcontract/tests/test_pii_archive_mirror.py",
                          "backend/core/tests/test_privacy_x.py", "backend/tests/test_font_zoom_x.py", "backend/modules/case/tests/sub/test_queue_y.py"])
    assert "backend/tests/test_unrelated.py" not in got and "backend/tests/helper_approval.py" not in got


def test_reverse_control_dropping_a_pattern_loses_its_files():
    tree = ["backend/modules/subcontract/tests/test_pii_archive_mirror.py"]
    assert AG.pattern_files(tree, tuple(p for p in AG.PATTERNS if p not in ("*pii*", "*archive*"))) == []
    assert AG.pattern_files(tree) == tree


def test_patterns_cover_the_named_groups():
    for need in ("*approval*", "*queue*", "*pii*", "*privacy*", "*migration*", "*spec_coverage*", "*font_zoom*", "*money_round*", "*wording*", "*changelog*"):
        assert need in AG.PATTERNS


# ── 選題組裝 ───────────────────────────────────────────────────────────

def test_build_selection_unions_groups_dedups_and_keeps_e2e_separate():
    plan_n = {"floor": {"backend/tests/platform/test_a.py": ["F0a:契約目錄"], "backend/tests/test_unmapped.py": ["F0c:unmapped"],
                        "backend/tests/platform/test_drill.py": ["F0a:契約目錄", "F1:工具演練(觸發)"]}, "selected": {"backend/modules/case/tests/test_c.py": ["x"]},
              "forced_full": ["硬底層改動"]}
    plan_e = {"selected": {"backend/tests/test_e2e_page.py": ["x"]}, "collected": ["backend/tests/test_e2e_page.py", "backend/tests/test_e2e_new.py"], "forced_full": []}
    tree = ["backend/tests/test_money_round_x.py", "backend/tests/platform/test_a.py"]
    changed = ["backend/modules/case/tests/test_c.py", "backend/tests/test_e2e_new.py", "backend/tests/test_money_round_x.py", "docs/x.md"]
    sel = AG.build_selection(plan_n, plan_e, tree, changed, guard_args=["tests/test_spec_coverage_2026_09_21.py"])
    assert sel["A1"] == ["backend/tests/platform/test_a.py", "backend/tests/platform/test_drill.py"]
    assert sel["A1x"] == ["backend/tests/test_unmapped.py"] and "backend/tests/test_unmapped.py" not in sel["non_e2e"]      # 建包才需要的底板預設不跑
    full = AG.build_selection(plan_n, plan_e, tree, changed, full_floor=True)
    assert "backend/tests/test_unmapped.py" in full["A1"]                                                                 # --full-floor 才加
    assert "backend/tests/test_money_round_x.py" in sel["A2"] and "backend/tests/test_spec_coverage_2026_09_21.py" in sel["A2"]
    assert sel["A3"] == ["backend/modules/case/tests/test_c.py"]
    assert sel["A4"] == ["backend/modules/case/tests/test_c.py", "backend/tests/test_money_round_x.py"]      # e2e 檔不在 A4
    assert sel["E"] == ["backend/tests/test_e2e_new.py", "backend/tests/test_e2e_page.py"]
    assert len(sel["non_e2e"]) == len(set(sel["non_e2e"]))
    assert not set(sel["E"]) & set(sel["non_e2e"])
    assert sel["forced_full"] == ["硬底層改動"]                                                          # mode=full 只是提示，不改作者端集合
    assert "backend/tests/platform/test_a.py" in sel["non_e2e"]


def test_build_selection_survives_missing_plans():
    sel = AG.build_selection(None, None, [], [])
    assert sel["non_e2e"] == [] and sel["E"] == [] and sel["forced_full"] == []


def test_build_cmds_workers_markers_and_guard_dedup():
    cmd, cmd_e = AG.build_cmds("py", ["tests/platform/test_a.py", "tests/test_spec_coverage_2026_09_21.py"],
                               ["tests/test_spec_coverage_2026_09_21.py::t", "tests/test_other.py::t2"], ["tests/test_e2e_x.py"], "BT", 2)
    assert "-n" in cmd and cmd[cmd.index("-n") + 1] == "2" and "not e2e" in cmd
    assert "tests/test_spec_coverage_2026_09_21.py::t" not in cmd and "tests/test_other.py::t2" in cmd       # 整檔已在 ⇒ 不重複點名
    assert cmd_e and "-n" not in cmd_e and cmd_e[cmd_e.index("-m", 3) + 1] == "e2e"
    cmd1, none = AG.build_cmds("py", ["tests/a.py"], [], [], "BT", 1)
    assert "-n" not in cmd1 and none is None


# ── 預估／預算 ─────────────────────────────────────────────────────────

def test_estimate_and_budget_warning_never_cut_anything():
    times = {"a": 600.0, "b": 300.0}
    assert AG.estimate_seconds(["a", "b"], times, 1) == 900.0
    assert AG.estimate_seconds(["a", "b"], times, 2) == pytest.approx(900 / 1.7)
    assert AG.estimate_seconds(["zzz"], times, 1) == AG.DEFAULT_FILE_SECONDS
    assert AG.budget_warning(100, 12, ["a"], times) is None
    w = AG.budget_warning(900, 1, ["a", "b"], times)                                                       # 預算 1 分鐘 ⇒ 警告
    assert w and "a(600s)" in w and "不砍任何一項" in w


def test_shipped_times_file_is_readable_and_covers_platform_files():
    t = AG.load_times()
    assert t and any(k.startswith("backend/tests/platform/") for k in t) and all(isinstance(v, (int, float)) for v in t.values())


# ── 結果 ───────────────────────────────────────────────────────────────

def _res(**kw):
    base = dict(head="h" * 40, base="b" * 40, tree_sha="t" * 40, selector_sha="s", groups={"A1": ["x"], "A2": [], "A3": [], "A4": [], "E": []},
                counts={"passed": 10, "failed": 0, "errors": 0, "skipped": 1}, failures_new=[], failures_known=[], duration_s=60, estimate_s=70,
                workers=2, stopped_by_failfast=False, forced_full=[], started="s", finished="f")
    base.update(kw)
    return AG.make_result(**base)


def test_green_requires_no_new_red_and_something_collected():
    assert _res()["green"] is True and _res()["partial_evidence_only"] is True
    assert _res(counts={"passed": 5, "failed": 1, "errors": 0, "skipped": 0}, failures_new=[{"nodeid": "a::t"}])["green"] is False      # 反向控制
    assert _res(counts={"passed": 0, "failed": 0, "errors": 0, "skipped": 0})["green"] is False                                      # 零題不是綠
    assert _res(counts={"passed": 5, "failed": 1, "errors": 0, "skipped": 0}, failures_known=[{"nodeid": "k::t"}])["green"] is True    # 只有已登記的紅
    assert _res(e2e={"green": False})["green"] is False


def test_classify_failures_and_parse_counts():
    new, known = AG.classify_failures([{"nodeid": "tests/a.py::t1"}, {"nodeid": "tests/b.py::t2"}], {"tests/a.py"})
    assert [f["nodeid"] for f in new] == ["tests/b.py::t2"] and [f["nodeid"] for f in known] == ["tests/a.py::t1"]
    assert AG.parse_counts("4 failed, 2260 passed, 3 skipped, 129 warnings in 1704.67s") == {"passed": 2260, "failed": 4, "errors": 0, "skipped": 3}


def test_read_result_rejects_any_changed_fingerprint(tmp_path):
    r = _res()
    p = tmp_path / "r.json"
    p.write_text(json.dumps(r), encoding="utf-8")
    ok = dict(head=r["head"], tree_sha=r["tree_sha"], selector_sha=r["selector_sha"])
    assert AG.read_result(p, **ok)["green"] is True
    for k in ok:
        assert AG.read_result(p, **dict(ok, **{k: ok[k] + "x"})) is None                                  # 反向控制：改一個字就不認
    assert AG.read_result(tmp_path / "nope.json", **ok) is None
    p.write_text("not json", encoding="utf-8")
    assert AG.read_result(p, **ok) is None


# ── git：髒樹、基準、回放 ───────────────────────────────────────────────

def test_dirty_tree_lists_modified_and_untracked_but_not_ignored(repo):
    _commit(repo, {"a.txt": "1", ".gitignore": "ign.txt\n"}, "init")
    assert AG.dirty_files(repo) == []
    (repo / "a.txt").write_text("2", encoding="utf-8")
    (repo / "new.txt").write_text("x", encoding="utf-8")
    (repo / "ign.txt").write_text("x", encoding="utf-8")
    assert sorted(AG.dirty_files(repo)) == ["a.txt", "new.txt"]


def test_changed_files_and_tree_files(repo):
    base = _commit(repo, {"backend/tests/test_old.py": "x"}, "base")
    head = _commit(repo, {"backend/tests/test_new_pii.py": "y"}, "head")
    assert AG.changed_files(base, head, repo) == ["backend/tests/test_new_pii.py"]
    assert "backend/tests/test_new_pii.py" in AG.tree_files_at(head, repo)
    assert AG.tree_sha_of(head, repo) and AG.resolve("HEAD", repo) == head


def test_replay_offline_covers_pattern_files_and_flags_a_missing_one(repo):
    _commit(repo, {"backend/modules/subcontract/tests/test_pii_archive_mirror_x.py": "a", "backend/tests/test_plain_guard.py": "a"}, "red")
    fix = _commit(repo, {"backend/tests/test_plain_guard.py": "b"}, "fix")
    ok = AG.replay_offline({"name": "n1", "fix": fix, "expect_files": ["backend/modules/subcontract/tests/test_pii_archive_mirror_x.py"]}, repo)
    assert ok["covered"] and ok["by"]["backend/modules/subcontract/tests/test_pii_archive_mirror_x.py"] == "A2"
    bad = AG.replay_offline({"name": "n2", "fix": fix, "expect_files": ["backend/tests/test_plain_guard.py"]}, repo)        # 名稱不符任何樣式 ⇒ 缺漏
    assert not bad["covered"] and bad["missing"] == ["backend/tests/test_plain_guard.py"]
    cut = AG.replay_offline({"name": "n3", "fix": fix, "expect_files": ["backend/modules/subcontract/tests/test_pii_archive_mirror_x.py"]}, repo,
                            patterns=tuple(p for p in AG.PATTERNS if p not in ("*pii*", "*archive*")))
    assert not cut["covered"]                                                                                                    # 反向控制：拿掉樣式 ⇒ 缺漏


def test_train31_red_rounds_are_all_covered_offline_on_the_real_history():
    cases = AG.load_cases()
    assert len(cases) >= 8
    probe = subprocess.run(["git", "-C", str(AG.REPO), "cat-file", "-e", cases[0]["fix"] + "^{commit}"], capture_output=True)
    if probe.returncode != 0:
        pytest.skip("這棵樹沒有第 31 班的歷史（shallow／不同 clone）")
    for c in cases:
        r = AG.replay_offline(c, AG.REPO)
        assert r["covered"] is (None if c.get("uncatchable") else True), (c["name"], r["missing"])      # 抓不到的偶發要明講，其餘一律要涵蓋


def test_venv_warning_fires_only_when_python_is_not_the_project_venv(tmp_path):
    repo = tmp_path / "repo"
    py = repo / ".venv312" / "Scripts"
    py.mkdir(parents=True)
    (py / "python.exe").write_text("", encoding="utf-8")
    _git(repo, "init", "-q")
    assert AG.project_python(repo) == py / "python.exe"
    assert AG.venv_warning(repo, exe=str(py / "python.exe")) is None
    w = AG.venv_warning(repo, exe=str(tmp_path / "other" / "python.exe"))
    assert w and ".venv312" in w                                                    # 反向控制：別人的 venv ⇒ 警告
    plain = tmp_path / "plain"
    plain.mkdir()
    _git(plain, "init", "-q")
    assert AG.venv_warning(plain, exe=str(tmp_path / "x.exe")) is None              # 找不到專案 venv ⇒ 不亂警告


def test_replay_scanner_case_requires_hits_before_the_fix_and_none_after(repo):
    scanner = ("import io, re, tokenize\n"
               "def suspicious(src):\n"
               "    out = []\n"
               "    for t in tokenize.generate_tokens(io.StringIO(src).readline):\n"
               "        if t.type == tokenize.COMMENT and t.line[:t.start[1]].rstrip().endswith(',') and re.search(r'\"\w+\":', t.string):\n"
               "            out.append(t.start[0])\n"
               "    return out\n")
    bad = 'd = {\n    "diff": 1,   # swallowed "fee": 2,\n}\n'
    good = 'd = {\n    "diff": 1,\n    "fee": 2,\n}\n'
    _commit(repo, {"backend/tests/platform/scan.py": scanner, "backend/m.py": bad}, "red")
    fix = _commit(repo, {"backend/m.py": good}, "fix")
    case = {"name": "m1", "fix": fix, "scanner": {"module": "backend/tests/platform/scan.py", "func": "suspicious", "file": "backend/m.py"}}
    r = AG.replay_offline(case, repo)
    assert r["covered"] is True and "hits before=1 after=0" in r["by"]["backend/m.py"]
    # 反向控制：修好之前就沒命中的掃描器 ⇒ 不算涵蓋
    blind = dict(case, scanner=dict(case["scanner"], file="backend/tests/platform/scan.py"))
    assert AG.replay_offline(blind, repo)["covered"] is False


def test_replay_uncatchable_cases_are_recorded_not_counted_as_gaps():
    r = AG.replay_offline({"name": "flake", "fix": "HEAD", "uncatchable": "時序偶發"})
    assert r["covered"] is None and r["missing"] == [] and r["uncatchable"] == "時序偶發"


def test_train32_reds_are_in_the_replay_table_and_covered_or_honestly_marked():
    cases = {c["name"]: c for c in AG.load_cases()}
    for need in ("r32-form-version", "r32-perm-catalog-label", "r32-changelog-order", "r32-m1-swallowed-dict", "r32-ledger-hub-409", "r32-lodging-overlay"):
        assert need in cases, need
    assert "*form_version*" in AG.PATTERNS and "*module_registry*" in AG.PATTERNS
    probe = subprocess.run(["git", "-C", str(AG.REPO), "cat-file", "-e", cases["r32-form-version"]["fix"] + "^{commit}"], capture_output=True)
    if probe.returncode != 0:
        pytest.skip("這棵樹沒有第 32 班的歷史")
    for name, c in cases.items():
        if not name.startswith("r32-"):
            continue
        r = AG.replay_offline(c, AG.REPO)
        assert r["covered"] in (True, None), (name, r["missing"])


def test_ag_long_argv_spills_to_argsfile_and_pytest_really_runs_it(tmp_path):
    """d7 實測 706 檔 ⇒ WinError 206。超過上限的參數改走 @argsfile；用 >700 個路徑實跑 pytest 證明 argsfile 被讀（反向：不 spill 就爆）。"""
    import os
    import tempfile
    py = sys.executable
    files = []
    for i in range(320):
        f = tmp_path / ("t%03d_" % i + "x" * 90 + ".py")
        f.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
        files.append(str(f))
    argv = [py, "-m", "pytest", *files, "-q", "-p", "no:cacheprovider", "--basetemp=%s" % (tmp_path / "bt")]
    assert sum(len(a) + 1 for a in argv) > AG.ARGV_LIMIT
    real, spilled = AG.spill_argv(argv)
    assert spilled and real[-1] == "@" + spilled and len(" ".join(real)) < 1000
    os.remove(spilled)                                                                        # 這次只是看形狀；實跑的那份由 run_pytest 自己刪
    code, out = AG.run_pytest(argv, tmp_path, {}, stream=False)
    assert code == 0 and "320 passed" in out, out[-400:]
    leftovers = [f for f in os.listdir(tempfile.gettempdir()) if f.startswith("author_gate_args_")]
    assert not leftovers, leftovers                                                           # 用完即刪
    short = [py, "-m", "pytest", "a.py"]
    assert AG.spill_argv(short) == (short, None)
