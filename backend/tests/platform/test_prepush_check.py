"""tools/platform/prepush_check.py＋setup_prepush.py＋integ_watch.py＋.githooks（SPEEDUP-PREPUSH-T50，第 51 班）。

全部用注入／暫存 repo／假的 PY，不跑真的守門測試、不打 app：輕量（秒級）。
重點（使用者規則：不削弱閘門）：
  · pre-push 紅 ⇒ 擋；未完成與整合分支只警告；不是 HEAD 的推送略過；刪除分支略過。
  · integ_watch 只寫自己的狀態目錄，從不寫任何綠燈紀錄。
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load(name):
    sys.path.insert(0, str(REPO / "tools" / "platform"))
    spec = importlib.util.spec_from_file_location("_t_" + name, REPO / "tools" / "platform" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PP = _load("prepush_check")
_FE = "frontend"          # git diff 的 repo 相對路徑前綴（合成輸入，不讀頁面檔）
SETUP = _load("setup_prepush")
IW = _load("integ_watch")
TP = PP.TP
ZERO = "0" * 40


def _no_static(monkeypatch):
    for n in ("check_changelogs", "check_ip_registry", "check_global_tests", "check_doc_types", "check_begin_sites",
              "check_golden", "check_db_version_literals", "check_bare_get_db", "check_generated"):
        monkeypatch.setattr(TP, n, lambda *a, **k: [])


# ── 靜態 ──────────────────────────────────────────────

def test_branch_carrying_generated_files_is_red_but_integration_mode_is_not(monkeypatch):
    _no_static(monkeypatch)
    changed = ["docs/platform/test_map.json", "backend/modules/case/api/x.py"]
    wip = PP.static_findings(REPO, changed, "base", integration=False)
    assert [f.code for f in wip] == ["P0"] and "test_map.json" in wip[0].where
    assert PP.static_findings(REPO, changed, "base", integration=True) == []      # 整合分支本來就要帶產生檔（只要求最新）


def test_integration_mode_asks_for_fresh_generated_files_check_only(monkeypatch):
    _no_static(monkeypatch)
    monkeypatch.setattr(TP, "check_generated", lambda repo: [TP.Finding("A0", "產生檔", "過期", "regen")])
    assert [f.code for f in PP.static_findings(REPO, [], "base", integration=True)] == ["A0"]
    assert PP.static_findings(REPO, [], "base", integration=False) == []          # wip：不要求重產


def test_warning_only_for_user_visible_changes_without_a_manifest_entry():
    assert PP.warnings([_FE + "/pages/x.html"])
    assert PP.warnings(["backend/modules/case/api/a.py"])
    assert not PP.warnings([_FE + "/pages/x.html", "backend/version_manifest.json"])
    assert not PP.warnings(["backend/modules/case/tests/test_a.py", "docs/x.md"])


def test_touched_modules():
    assert PP.touched_modules(["backend/modules/case/api/a.py", "backend/modules/arap/x.py", "docs/a.md", "backend/core/x.py"]) == ["arap", "case"]


def test_select_tests_adds_slow_guards_only_when_the_paths_say_so():
    base = {t for t, _ in PP.select_tests(REPO, ["docs/readme.md"])}
    assert "tests/test_version_manifest_2026_09_22.py" in base
    assert "tests/platform/test_ship_tier_2026_09_28.py" not in base
    api = {t for t, _ in PP.select_tests(REPO, ["backend/modules/case/api/a.py"])}
    assert "tests/platform/test_ship_tier_2026_09_28.py" in api
    assert sum(s for t, s in PP.TIER1) < 60, "必跑集合的量測秒數合計要 < 60（單進程預算）"


# ── run()／main()：結束碼語意 ─────────────────────────────

def _run(monkeypatch, rc, out="", findings=None, integration=False):
    monkeypatch.setattr(PP, "changed_files", lambda repo, base: ["backend/modules/case/api/a.py"])
    monkeypatch.setattr(PP, "static_findings", lambda *a, **k: list(findings or []))
    monkeypatch.setattr(PP, "changelog_findings", lambda *a, **k: [])
    monkeypatch.setattr(PP, "form_version_findings", lambda *a, **k: [])
    return PP.run(REPO, "base", 55, False, integration, runner=lambda repo, tests, timeout: (rc, out, 1.0))


def test_exit_codes(monkeypatch):
    assert _run(monkeypatch, 0)[0] == 0
    code, text, data = _run(monkeypatch, 1, "FAILED tests/a.py::t - x\n")
    assert code == 1 and "tests/a.py::t" in text and data["fails"] == ["tests/a.py::t"]
    assert _run(monkeypatch, PP.INCOMPLETE)[0] == PP.INCOMPLETE
    assert _run(monkeypatch, 0, findings=[TP.Finding("P0", "x", "m", "f")])[0] == 1
    assert _run(monkeypatch, 0, findings=[TP.Unchecked("A?", "boom")])[0] == 0      # 工具出錯顯示 ⚠ 但不擋（不冤枉作者）


def test_incomplete_is_never_reported_as_green(monkeypatch):
    code, text, _ = _run(monkeypatch, PP.INCOMPLETE)
    assert "不可當綠" in text and "結果：未完成" in text


def test_hook_mode_blocks_only_on_real_reds(monkeypatch):
    for ret, integ, want in ((1, False, 1), (3, False, 0), (0, False, 0), (1, True, 0)):
        monkeypatch.setattr(PP, "run", lambda *a, _r=ret, **k: (_r, "x", {}))
        argv = ["--hook"] + (["--integration"] if integ else [])
        assert PP.main(argv) == want, (ret, integ)


def test_tool_crash_is_exit_2_not_a_silent_pass(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(PP, "run", boom)
    assert PP.main(["--hook"]) == 2


def _code_only(path):
    """原始碼去掉所有 docstring 與註解（ast.unparse）——只檢查『會執行的碼』。"""
    import ast
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            f = n.body[0]
            if isinstance(f, ast.Expr) and isinstance(f.value, ast.Constant) and isinstance(f.value.value, str):
                n.body = n.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_the_tool_never_sets_train_mode_or_calls_numbering_or_regen():
    body = _code_only(REPO / "tools" / "platform" / "prepush_check.py")
    assert body.count("MOTRIX_TRAIN") == 1 and "k != 'MOTRIX_TRAIN'" in body          # 唯一出現＝把它從環境拿掉
    for bad in ("train_number", "regen_all", "git commit", "git push", "'commit'", "'push'", "'checkout'"):
        assert bad not in body, bad
    assert body.count(".write_text(") == 1, "唯一的寫檔是使用者指定的 --json-out"


# ── setup_prepush／hook 檔 ──────────────────────────────

def _bash():
    """Git Bash（不是 PATH 上的 WSL bash.exe）：從 git 的位置推出來；找不到 ⇒ None（相關題 skip）。"""
    g = shutil.which("git")
    if not g:
        return None
    for parent in Path(g).resolve().parents:
        for sub in (("bin", "bash.exe"), ("usr", "bin", "bash.exe")):
            cand = parent.joinpath(*sub)
            if cand.is_file():
                return str(cand)
    return shutil.which("bash") if os.name != "nt" else None


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")


@pytest.fixture()
def tmp_repo(tmp_path):
    r = tmp_path / "r"
    (r / ".githooks").mkdir(parents=True)
    _git(r, "init", "-q")
    for n in SETUP.NEEDED:
        shutil.copy(REPO / ".githooks" / n, r / ".githooks" / n)
    return r


def test_setup_install_check_remove(tmp_repo):
    assert SETUP.problems(tmp_repo)                                              # 還沒登記
    SETUP.install(tmp_repo)
    assert SETUP.problems(tmp_repo) == []
    (tmp_repo / ".githooks" / "pre-push").unlink()
    assert any("pre-push" in p for p in SETUP.problems(tmp_repo))
    SETUP.remove(tmp_repo)
    assert any("core.hooksPath" in p for p in SETUP.problems(tmp_repo))


@pytest.mark.skipif(_bash() is None, reason="沒有 Git Bash")
@pytest.mark.parametrize("hook", ["pre-push", "post-commit"])
def test_hook_files_parse(hook):
    r = subprocess.run([_bash(), "-n", (REPO / ".githooks" / hook).as_posix()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.fixture()
def hook_env(tmp_path):
    """暫存 repo＋假的 prepush_check.py（照環境變數決定結束碼、把參數記下來）＋真的 pre-push。"""
    if _bash() is None:
        pytest.skip("沒有 Git Bash")
    r = tmp_path / "h"
    (r / "tools" / "platform").mkdir(parents=True)
    (r / ".githooks").mkdir()
    shutil.copy(REPO / ".githooks" / "pre-push", r / ".githooks" / "pre-push")
    (r / "tools" / "platform" / "prepush_check.py").write_text(
        "import os, sys\nopen(os.environ['ARGS_OUT'], 'a').write(' '.join(sys.argv[1:]) + '\\n')\nsys.exit(int(os.environ.get('STUB_RC', '0')))\n",
        encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    (r / "f.txt").write_text("x", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "c")
    head = _git(r, "rev-parse", "HEAD").stdout.strip()

    def push(lsha, rref, rc=0):
        env = dict(os.environ, MOTRIX_PY=sys.executable, STUB_RC=str(rc), ARGS_OUT=str(tmp_path / "args.txt"))
        p = subprocess.run([_bash(), (r / ".githooks" / "pre-push").as_posix()], cwd=str(r), env=env, capture_output=True, text=True, encoding="utf-8",
                           input="refs/heads/x %s %s %s\n" % (lsha, rref, ZERO))
        return p.returncode, p.stdout
    return push, head, tmp_path / "args.txt"


def test_pre_push_hook_blocks_red_and_skips_deletes_and_non_head(hook_env):
    push, head, args = hook_env
    assert push(head, "refs/heads/wip/x", rc=1)[0] == 1                          # 紅 ⇒ 擋
    assert push(head, "refs/heads/wip/x", rc=0)[0] == 0
    assert push(ZERO, "refs/heads/wip/x", rc=1)[0] == 0                          # 刪除遠端分支 ⇒ 略過
    rc, out = push("a" * 40, "refs/heads/wip/x", rc=1)
    assert rc == 0 and "略過" in out                                              # 推的不是 HEAD ⇒ 略過（不誤判）


def test_pre_push_hook_uses_integration_mode_for_train_and_platform(hook_env):
    push, head, args = hook_env
    push(head, "refs/heads/train/t99-int")
    push(head, "refs/heads/platform")
    push(head, "refs/heads/wip/a")
    lines = args.read_text(encoding="utf-8").splitlines()
    assert lines[0].endswith("--hook --integration") and lines[1].endswith("--hook --integration")
    assert lines[2].endswith("--hook") and "--integration" not in lines[2]


# ── integ_watch：只寫自己的狀態目錄 ─────────────────────────

def _watch_env(monkeypatch, tmp_path, busy=False, gb=16.0):
    monkeypatch.setattr(IW, "OUT", tmp_path / "integ_watch")
    monkeypatch.setattr(IW, "head_sha", lambda: "abcdef1234567890" * 2 + "abcdefgh")
    monkeypatch.setattr(IW, "other_pytest_running", lambda: busy)
    monkeypatch.setattr(IW, "free_gb", lambda: gb)
    import prepush_check as real_pp                                              # integ_watch.once 以名稱匯入的那一份（不是上面 spec 載入的副本）
    monkeypatch.setattr(real_pp, "run", lambda *a, **k: (1, "x\n結果：有紅", {"findings": [{"code": "A1", "msg": "壞了", "where": "w", "fix": "f"}],
                                                                         "warnings": [], "fails": [], "tests": ["t"], "exit": 1}))


def test_integ_watch_writes_status_only_in_its_own_dir(monkeypatch, tmp_path):
    _watch_env(monkeypatch, tmp_path)
    before = {p for p in tmp_path.rglob("*")}
    d = IW.once(wait=False)
    assert d["state"] == "done" and d["exit"] == 1 and d["reds"][0]["code"] == "A1"
    new = {p for p in tmp_path.rglob("*")} - before
    assert new and all(IW.OUT in p.parents or p == IW.OUT for p in new), new
    assert (IW.OUT / "status.json").is_file()
    assert "閘門以官方 run-stage 為準" in d["note"]


def test_integ_watch_skips_when_machine_is_busy_or_low_on_memory(monkeypatch, tmp_path):
    _watch_env(monkeypatch, tmp_path, busy=True)
    assert IW.once(wait=False)["state"] == "skipped"
    _watch_env(monkeypatch, tmp_path, busy=False, gb=2.0)
    d = IW.once(wait=False)
    assert d["state"] == "skipped" and "記憶體" in d["note"]


def test_integ_watch_never_touches_gate_records():
    body = _code_only(REPO / "tools" / "platform" / "integ_watch.py")
    for bad in ("record-stage", "record_stage", "build_test_reuse", "train_number", "regen_all", "git commit", "git push", "stage_record"):
        assert bad not in body, bad


# ── 第 52 班後續（1d 稽核兩個 nit）：預算與實測相符、背景檢查逐檔讓出 ─────────────────────────

def test_default_budget_is_90_for_wip_and_300_for_integration_and_explicit_wins(monkeypatch):
    def run(integration, budget=None):
        monkeypatch.setattr(PP, "changed_files", lambda repo, base: [])
        monkeypatch.setattr(PP, "static_findings", lambda *a, **k: [])
        monkeypatch.setattr(PP, "changelog_findings", lambda *a, **k: [])
        monkeypatch.setattr(PP, "form_version_findings", lambda *a, **k: [])
        return PP.run(REPO, "base", budget, True, integration)[2]
    assert run(False)["budget_sec"] == PP.WIP_BUDGET_SEC == 90
    assert run(True)["budget_sec"] == PP.INTEGRATION_BUDGET_SEC == 300
    assert run(True, 45)["budget_sec"] == 45 and run(False, 200)["budget_sec"] == 200
    assert "static_secs" in run(False)


def test_report_line_shows_static_seconds_and_budget(monkeypatch):
    monkeypatch.setattr(PP, "changed_files", lambda repo, base: [])
    monkeypatch.setattr(PP, "static_findings", lambda *a, **k: [])
    monkeypatch.setattr(PP, "changelog_findings", lambda *a, **k: [])
    monkeypatch.setattr(PP, "form_version_findings", lambda *a, **k: [])
    text = PP.run(REPO, "base", None, True, True)[1]
    assert "預算 300 秒" in text


def _polite_env(monkeypatch, busy_seq, gb=16.0):
    import prepush_check as real_pp                                             # integ_watch 以名稱匯入的那一份
    calls = []
    seq = list(busy_seq)
    monkeypatch.setattr(IW, "other_pytest_running", lambda: seq.pop(0) if seq else seq_default[0])
    monkeypatch.setattr(IW, "free_gb", lambda: gb)
    monkeypatch.setattr(real_pp, "run_tests", lambda repo, tests, timeout: (calls.append(tests[0][0]) or (0, "ok " + tests[0][0], 0.1)))
    return real_pp, calls


seq_default = [False]


def test_polite_run_yields_between_files_when_another_pytest_appears(monkeypatch):
    real_pp, calls = _polite_env(monkeypatch, [False, True])
    IW.polite_run.reason = ""
    rc, out, _s = IW.polite_run(REPO, [("a.py", 1), ("b.py", 1), ("c.py", 1)], 100)
    assert rc == real_pp.INCOMPLETE and calls == ["a.py"], calls                  # 第二檔開跑前偵測到 ⇒ 只跑了第一檔
    assert "讓出" in IW.polite_run.reason and "1／3" in IW.polite_run.reason
    assert "ok a.py" in out


def test_polite_run_runs_everything_when_the_machine_stays_free(monkeypatch):
    real_pp, calls = _polite_env(monkeypatch, [])
    IW.polite_run.reason = ""
    rc, out, _s = IW.polite_run(REPO, [("a.py", 1), ("b.py", 1), ("c.py", 1)], 100)
    assert rc == 0 and calls == ["a.py", "b.py", "c.py"] and IW.polite_run.reason == ""


def test_polite_run_yields_on_low_memory_midway(monkeypatch):
    real_pp, calls = _polite_env(monkeypatch, [], gb=1.0)
    IW.polite_run.reason = ""
    rc, _o, _s = IW.polite_run(REPO, [("a.py", 1), ("b.py", 1)], 100)
    assert rc == real_pp.INCOMPLETE and calls == [] and "記憶體" in IW.polite_run.reason


def test_polite_run_reports_the_first_real_red(monkeypatch):
    import prepush_check as real_pp
    monkeypatch.setattr(IW, "other_pytest_running", lambda: False)
    monkeypatch.setattr(IW, "free_gb", lambda: 16.0)
    monkeypatch.setattr(real_pp, "run_tests", lambda repo, tests, timeout: (1 if tests[0][0] == "b.py" else 0, "x", 0.1))
    rc, _o, _s = IW.polite_run(REPO, [("a.py", 1), ("b.py", 1), ("c.py", 1)], 100)
    assert rc == 1


def test_once_records_a_yielded_state_and_never_green(monkeypatch, tmp_path):
    import prepush_check as real_pp
    monkeypatch.setattr(IW, "OUT", tmp_path / "integ_watch")
    monkeypatch.setattr(IW, "head_sha", lambda: "abcdef1234567890" * 2 + "abcdefgh")
    monkeypatch.setattr(real_pp, "changed_files", lambda repo, base: [])
    monkeypatch.setattr(real_pp, "static_findings", lambda *a, **k: [])
    monkeypatch.setattr(real_pp, "changelog_findings", lambda *a, **k: [])
    monkeypatch.setattr(real_pp, "form_version_findings", lambda *a, **k: [])
    monkeypatch.setattr(real_pp, "select_tests", lambda repo, changed: [("a.py", 1), ("b.py", 1), ("c.py", 1)])
    calls = []
    monkeypatch.setattr(real_pp, "run_tests", lambda repo, tests, timeout: (calls.append(tests[0][0]) or (0, "ok", 0.1)))
    seq = [False, False, True]                                                   # 開始時閒；第一檔前閒；第二檔前有別人
    monkeypatch.setattr(IW, "other_pytest_running", lambda: seq.pop(0) if seq else True)
    monkeypatch.setattr(IW, "free_gb", lambda: 16.0)
    d = IW.once(wait=False)
    assert d["state"] == "yielded" and d["exit"] == real_pp.INCOMPLETE and calls == ["a.py"], (d, calls)
    assert "讓出" in d["note"]
