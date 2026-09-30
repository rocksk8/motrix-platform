# -*- coding: utf-8 -*-
"""tools/platform/pre_train_check.py：預演列車（分支推月台前，先在拋棄式樹上合進 origin/platform 跑合併後才紅的守門）。

純函式用合成輸入；合併用真的 git（tmp 倉庫）；主流程用假 Runner 驗指令順序、環境、上限與清理。
反向控制（突變）清單見 PLAYBOOK §G5 第 19 項與提交訊息。
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("_pre_train_check_t", REPO / "tools" / "platform" / "pre_train_check.py")
PT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PT)

SRC = (REPO / "tools" / "platform" / "pre_train_check.py").read_text(encoding="utf-8")


# ── 純函式 ────────────────────────────────────────────────────────────────────

PYTEST_OUT = """\
..F..E
=========================== short test summary info ============================
FAILED tests/platform/test_page_paths_centralized.py::test_no_new_hardcoded_pages - AssertionError: 3 new
FAILED modules/case/tests/test_approval_providers.py::test_sets_match
ERROR tests/test_alpine_double_init_2026_09_23.py::test_population - KeyError: 'x'
ERROR tests/test_broken.py - ImportError: nope
FAILED tests/platform/test_page_paths_centralized.py::test_no_new_hardcoded_pages - AssertionError: 3 new
2 failed, 3 passed, 2 errors in 10.00s
"""


def test_parse_failures_reads_failed_and_error_lines_and_dedups():
    fs = PT.parse_failures(PYTEST_OUT)
    assert [f["nodeid"] for f in fs] == [
        "tests/platform/test_page_paths_centralized.py::test_no_new_hardcoded_pages",
        "modules/case/tests/test_approval_providers.py::test_sets_match",
        "tests/test_alpine_double_init_2026_09_23.py::test_population",
        "tests/test_broken.py"]
    assert fs[0]["kind"] == "FAILED" and "3 new" in fs[0]["msg"] and fs[3]["kind"] == "ERROR"
    assert PT.parse_failures("") == [] and PT.parse_failures("2 passed in 1s") == []


def test_guard_kind_names_the_guard_family():
    k = PT.guard_kind
    assert k("tests/test_spec_coverage_2026_09_21.py::t") == "規格編號 C_OWNED"
    assert k("tests/platform/test_page_paths_centralized.py::t") == "page_paths 棘輪"
    assert k("tests/platform/test_scope_gate_2026_09_30.py::t") == "scope_gate／global_tests"
    assert k("tests/platform/test_unit_cards.py::t") == "單位卡／UNIT-INDEX"
    assert k("tests/platform/test_l1_interface_snapshot.py::t") == "L1 介面／底線名稱"
    assert k("modules/case/tests/test_approval_providers.py::t") == "簽核提供者集合"
    assert k("tests/test_alpine_double_init_2026_09_23.py::t") == "alpine double-init"
    assert k("tests/test_something_else.py::t") == "其他守門"


def test_owner_is_the_module_key_for_module_tests_else_test_map_else_core():
    assert PT.owner_of("modules/case/tests/test_x.py::t") == "case"
    assert PT.owner_of("backend/modules/crm/tests/test_x.py::t") == "crm"
    assert PT.owner_of("tests/test_x.py::t") == "core"
    assert PT.owner_of("tests/test_x.py::t", lambda n: ("arap", ["arap"])) == "arap"

    def boom(_):
        raise RuntimeError("no map")
    assert PT.owner_of("tests/test_x.py::t", boom) == "core", "test_map 讀不到卻沒退回 core"


def test_group_reds_groups_by_owner_and_shows_only_the_branchs_own_files():
    fs = PT.parse_failures(PYTEST_OUT)
    changed = ["backend/modules/case/api/a.py", "backend/helpers/h.py", "backend/modules/crm/x.py"]
    groups = PT.group_reds(fs, changed)
    by = {g["owner"]: g for g in groups}
    assert set(by) == {"core", "case"} and by["core"]["count"] == 3 and by["case"]["count"] == 1
    assert groups[0]["owner"] == "core", "題數多的組要排前面"
    assert by["case"]["branch_files"] == ["backend/modules/case/api/a.py"], "把別的模組的檔算成 case 的"
    assert by["core"]["branch_files"] == ["backend/helpers/h.py"], "core 的相關檔含了模組內的檔"
    assert set(by["core"]["kinds"]) == {"page_paths 棘輪", "alpine double-init", "其他守門"}


def test_format_report_prints_groups_steps_missing_and_a_rerun_command():
    fs = PT.parse_failures(PYTEST_OUT)
    rep = PT.format_report("wip/x", "a" * 40, "origin/platform", [("合併", True, ""), ("pytest", False, "exit 1")],
                           PT.group_reds(fs, ["backend/helpers/h.py"]), ["簽核提供者集合（modules/*/tests/test_approval_providers*.py）"],
                           125, len(fs), "2 failed, 3 passed")
    for needle in ("wip/x", "歸屬 core", "歸屬 case", "page_paths 棘輪", "✘ pytest", "找不到守門檔", "test_page_paths_centralized",
                   "MOTRIX_TRAIN=1", "2 分鐘"):
        assert needle in rep, needle
    ok = PT.format_report("b", "a" * 40, "origin/platform", [("合併", True, "")], [], [], 5, 0, "9 passed")
    assert "結果：無紅" in ok


def test_expand_guards_globs_keeps_node_ids_and_reports_missing(tmp_path):
    b = tmp_path / "backend"
    (b / "tests").mkdir(parents=True)
    (b / "modules" / "case" / "tests").mkdir(parents=True)
    (b / "modules" / "crm" / "tests").mkdir(parents=True)
    for rel in ("tests/test_a.py", "modules/case/tests/test_approval_providers.py", "modules/crm/tests/test_approval_providers_x.py"):
        (b / rel).write_text("", encoding="utf-8")
    args, missing = PT.expand_guards(b, [("A", "tests/test_a.py::test_one"), ("P", "modules/*/tests/test_approval_providers*.py"),
                                         ("Gone", "tests/test_gone.py")])
    assert args == ["tests/test_a.py::test_one", "modules/case/tests/test_approval_providers.py",
                    "modules/crm/tests/test_approval_providers_x.py"]
    assert missing == ["Gone（tests/test_gone.py）"], "找不到的守門檔沒有被列出（改名後會靜默少驗）"


def test_the_committed_guard_list_resolves_in_this_repo():
    """正對照：GUARDS 列的每一項在目前的樹上都找得到（改名了這題就紅，提醒同步 GUARDS）。"""
    args, missing = PT.expand_guards(REPO / "backend")
    assert missing == [], missing
    assert any("test_fz_no_raw_vh_is_left_in_the_frontend" in a for a in args)
    assert any(a.startswith("modules/") and "approval_providers" in a for a in args)
    names = " ".join(args)
    for needle in ("test_spec_coverage", "test_alpine_double_init", "test_company_setup_output_points", "test_system_audit",
                   "test_page_shell_scripts"):
        assert needle in names, needle


def test_pytest_command_is_capped_low_load_and_not_e2e(tmp_path):
    cmd = PT.build_pytest_cmd("py", ["tests/a.py"], str(tmp_path / "bt"), 2)
    assert cmd[cmd.index("-n") + 1] == "2" and "tests/platform" in cmd and "tests/a.py" in cmd
    assert cmd[len(cmd) - 1 - cmd[::-1].index("-m") + 1] == "not e2e"     # 最後一個 -m（第一個是 python -m pytest）
    assert any(c.startswith("--basetemp=") for c in cmd), "沒有 --basetemp 會被 conftest 拒絕"
    assert "-rfE" in cmd


def test_safe_scratch_only_accepts_our_own_direct_children(tmp_path):
    root = tmp_path / "scratch"
    root.mkdir()
    assert PT.safe_scratch(root / "pre-train-x-1", root)
    for bad in (root, tmp_path, root / "other", root / "pre-train-x" / "deeper", root.parent / "pre-train-y", Path("C:/")):
        assert not PT.safe_scratch(bad, root), bad


def test_workers_are_clamped_to_two(monkeypatch, capsys):
    seen = {}

    def fake(argv, **kw):
        seen.update(kw)
        return 0, "ok"
    monkeypatch.setattr(PT, "run_check", fake)
    PT.main(["wip/x", "--workers", "8", "--no-fetch"])
    assert seen["workers"] == 2, "使用者上限 -n 2，卻讓人傳 8"


def test_the_tool_never_pushes_or_resets():
    code = "\n".join(l for l in SRC.splitlines() if not l.lstrip().startswith(("#", '"""')))
    assert '"push"' not in code and "'push'" not in code and '"reset"' not in code and '"checkout"' not in code


# ── 合併（真的 git）──────────────────────────────────────────────────────────────

def _g(repo, *a):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a], capture_output=True,
                          text=True, check=True).stdout


def _mk_repo(tmp_path, conflict):
    r = tmp_path / "repo"
    r.mkdir()
    _g(r, "init", "-q", "-b", "platform")
    (r / "a.txt").write_text("line1\n", encoding="utf-8")
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", "base")
    _g(r, "checkout", "-q", "-b", "feat")
    (r / ("a.txt" if conflict else "b.txt")).write_text("feat\n", encoding="utf-8")
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", "feat")
    sha = _g(r, "rev-parse", "HEAD").strip()
    _g(r, "checkout", "-q", "platform")
    (r / "a.txt").write_text("platform\n", encoding="utf-8")
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", "plat")
    return r, sha


def test_merge_into_clean_merge(tmp_path):
    r, sha = _mk_repo(tmp_path, conflict=False)
    ok, conflicts = PT.merge_into(PT.Runner(), r, sha, "feat")
    assert ok and conflicts == []
    assert (r / "b.txt").exists() and (r / "a.txt").read_text(encoding="utf-8") == "platform\n"


def test_merge_into_conflict_lists_files_and_aborts(tmp_path):
    r, sha = _mk_repo(tmp_path, conflict=True)
    ok, conflicts = PT.merge_into(PT.Runner(), r, sha, "feat")
    assert not ok and conflicts == ["a.txt"]
    assert not (r / ".git" / "MERGE_HEAD").exists(), "衝突後沒有 merge --abort，樹卡在合併中"
    assert _g(r, "status", "--porcelain").strip() == "", "abort 之後工作樹不乾淨"


def _rr_entries(r):
    d = r / ".git" / "rr-cache"
    return list(d.iterdir()) if d.is_dir() else []


def test_merge_does_not_write_rerere_records(tmp_path):
    """使用者要求「no rerere pollution」：倉庫本身開了 rerere 也不寫記錄。
    正對照：不帶 `-c rerere.enabled=false` 的同一個衝突合併，確實會寫 rr-cache（證明這題看得出污染）。"""
    r, sha = _mk_repo(tmp_path, conflict=True)
    _g(r, "config", "rerere.enabled", "true")
    PT.merge_into(PT.Runner(), r, sha, "feat")
    assert _rr_entries(r) == [], "預演的衝突合併寫進了 rerere 記錄"
    subprocess.run(["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@t", "merge", "--no-ff", "--no-edit", sha],
                   capture_output=True, text=True)
    assert _rr_entries(r), "正對照失敗：不關 rerere 應該會留下記錄（這題失去偵測能力）"
    _g(r, "merge", "--abort")


# ── 主流程（假 Runner）─────────────────────────────────────────────────────────────

class FakeRunner:
    def __init__(self, pytest_rc=0, pytest_out="", merge_rc=0, conflicts="", tool_rc=None):
        self.calls, self.pytest_rc, self.pytest_out = [], pytest_rc, pytest_out
        self.merge_rc, self.conflicts, self.tool_rc = merge_rc, conflicts, tool_rc or {}

    def run(self, argv, cwd, env=None, stream=False, low=False, timeout=None):
        self.calls.append({"argv": list(argv), "cwd": str(cwd), "env": env or {}, "low": low})
        a = " ".join(argv)
        if "rev-parse" in a:
            return 0, ("b" * 40 if "origin/platform" in a else "a" * 40) + "\n"
        if " merge " in a and "--abort" not in a:
            return self.merge_rc, "CONFLICT" if self.merge_rc else ""
        if "diff --name-only --diff-filter=U" in a:
            return 0, self.conflicts
        if "diff --name-only" in a:
            return 0, "backend/helpers/h.py\nbackend/modules/case/api/a.py\n"
        if "status --porcelain" in a:
            return 0, " M docs/platform/dep_graph.json\n"
        if "-m pytest" in a:
            return self.pytest_rc, self.pytest_out
        for key, rc in self.tool_rc.items():
            if key in a:
                return rc, key + " failed"
        return 0, ""


def _run(tmp_path, **kw):
    runner = kw.pop("runner")
    lines = []
    code, rep = PT.run_check({"branch": "wip/x", "base": "origin/platform"}, runner=runner, root_repo=REPO,
                             scratch_root=tmp_path, python="py", out=lines.append, fetch=False, **kw)
    return code, rep, lines


def _cmds(runner):
    return [" ".join(c["argv"]) for c in runner.calls]


def test_flow_order_env_priority_and_cleanup(tmp_path):
    fr = FakeRunner(pytest_out="2 passed in 1s\n")
    code, rep, _ = _run(tmp_path, runner=fr)
    assert code == 0 and "結果：無紅" in rep
    cmds = _cmds(fr)
    order = [next(i for i, c in enumerate(cmds) if n in c) for n in
             ("worktree add --detach", " merge ", "setup_merge_drivers.py", "train_number.py assign", "train_number.py --check",
              "dep_scan.py", "unit_index.py", "test_map.py", "-m pytest", "worktree remove --force")]
    assert order == sorted(order), "步驟順序不對：%s" % order
    py = next(c for c in fr.calls if "-m pytest" in " ".join(c["argv"]))
    assert py["env"].get("MOTRIX_TRAIN") == "1", "沒有設 MOTRIX_TRAIN=1 ⇒ 產生檔／版號守門會 skip，等於沒預演"
    assert py["low"] is True and py["cwd"].endswith("backend")
    assert py["argv"][py["argv"].index("-n") + 1] == "2"
    assert not any(" push" in c for c in cmds)
    assert all("rerere.enabled=false" in c for c in cmds if " merge " in c and "--abort" not in c)


def test_flow_groups_reds_and_exits_1(tmp_path):
    fr = FakeRunner(pytest_rc=1, pytest_out=PYTEST_OUT)
    code, rep, _ = _run(tmp_path, runner=fr)
    assert code == 1
    assert "歸屬 core" in rep and "歸屬 case" in rep and "page_paths 棘輪" in rep
    assert "backend/helpers/h.py" in rep, "沒有印出本分支動到的相關檔"


def test_flow_red_exit_without_identifiable_test_is_still_red(tmp_path):
    code, rep, _ = _run(tmp_path, runner=FakeRunner(pytest_rc=2, pytest_out="INTERNALERROR\n"))
    assert code == 1 and "認不出是哪一題" in rep, "pytest 非 0 而沒有 FAILED 行被當成綠"
    assert "✘ pytest" in rep, "pytest 這一步本身要標紅（不能只靠附加的那一條）"


def test_flow_merge_conflict_exits_2_and_never_runs_tests(tmp_path):
    fr = FakeRunner(merge_rc=1, conflicts="backend/core/registry.py\n")
    code, rep, _ = _run(tmp_path, runner=fr)
    assert code == 2 and "衝突 1 檔" in rep and "registry.py" in rep
    assert not any("-m pytest" in c for c in _cmds(fr)) and any("merge --abort" in c for c in _cmds(fr))
    assert any("worktree remove --force" in c for c in _cmds(fr)), "衝突離開時沒有移除拋棄式樹"


def test_flow_train_number_failure_is_red(tmp_path):
    code, rep, _ = _run(tmp_path, runner=FakeRunner(tool_rc={"train_number.py assign": 1}), skip_tests=True)
    assert code == 1 and "✘ train_number assign" in rep


def test_flow_train_number_check_failure_is_red_even_when_assign_succeeds(tmp_path):
    code, rep, _ = _run(tmp_path, runner=FakeRunner(tool_rc={"train_number.py --check": 1}), skip_tests=True)
    assert code == 1 and "✘ train_number assign＋--check" in rep, "assign 過但 --check 紅（撞號／殘留佔位）被放過"


def test_flow_skip_tests_and_keep(tmp_path):
    fr = FakeRunner()
    code, _, _ = _run(tmp_path, runner=fr, skip_tests=True, keep=True)
    assert code == 0 and not any("-m pytest" in c for c in _cmds(fr))
    assert not any("worktree remove" in c for c in _cmds(fr)), "--keep 卻移除了樹"


def test_flow_unknown_branch_exits_2_without_creating_a_tree(tmp_path):
    class NoRef(FakeRunner):
        def run(self, argv, cwd, **kw):
            if "rev-parse" in " ".join(argv):
                return 1, ""
            return super().run(argv, cwd, **kw)
    fr = NoRef()
    code, rep, _ = _run(tmp_path, runner=fr)
    assert code == 2 and "找不到" in rep and not any("worktree add" in c for c in _cmds(fr))


def test_flow_removes_only_its_own_tree(tmp_path):
    fr = FakeRunner()
    _run(tmp_path, runner=fr, skip_tests=True)
    removes = [c for c in fr.calls if "worktree remove" in " ".join(c["argv"])]
    assert len(removes) == 1
    target = Path(removes[0]["argv"][-1])
    assert target.parent == tmp_path and target.name.startswith("pre-train-wip-x-")
