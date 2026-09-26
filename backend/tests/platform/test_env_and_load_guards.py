"""稽核 AUDIT-D-B-env-guards 的修正（2026-09-26）：§C-13 負載上限、專案環境不覆寫、全量 dirty 判定、同 commit 歷次紀錄。

每一題都對應稽核的一個突變（B05／B06／B07）或發現（B-M1～M3、B-S3、B-S4），且都是反向控制：修正拿掉就紅。
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))


def _load(name):
    spec = importlib.util.spec_from_file_location("_audit_" + name, REPO / "tools" / "platform" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MT = _load("modtest")
PE = _load("project_env")


# ── B-M1：cap_workers（突變 B05）──────────────────────────────────────────────

@pytest.mark.parametrize("given,expected", [
    (["-n", "8"], ["-n", "2"]),
    (["-n8"], ["-n2"]),
    (["-n=8"], ["-n=2"]),
    (["--numprocesses", "8"], ["--numprocesses", "2"]),
    (["--numprocesses=8"], ["--numprocesses=2"]),
    (["-n", "-1"], ["-n", "2"]),
    (["-n", "auto"], ["-n", "2"]),          # 稽核 B-M1：原本原樣放行
    (["-nauto"], ["-n2"]),
    (["-n", "logical"], ["-n", "2"]),
    (["--numprocesses=auto"], ["--numprocesses=2"]),
    (["-n", "2"], ["-n", "2"]),             # 正對照：不超過就不動
    (["-n", "1", "-q"], ["-n", "1", "-q"]),
    (["-q", "-x"], ["-q", "-x"]),
])
def test_cap_workers_every_spelling(given, expected, capsys):
    assert MT.cap_workers(given, 2) == expected


def test_cap_workers_message_survives_a_legacy_console(monkeypatch):
    """稽核 B-M1 附帶：被 import 呼叫、主控台是 cp932 時不可以 UnicodeEncodeError。"""
    import io
    buf = io.BytesIO()
    fake = io.TextIOWrapper(buf, encoding="cp932", errors="strict")
    monkeypatch.setattr(sys, "stdout", fake)
    assert MT.cap_workers(["-n", "auto"], 2) == ["-n", "2"]
    fake.flush()
    assert buf.getvalue(), "要說出來（改寫了哪個參數）"


# ── B-S3：低優先權（突變 B06）─────────────────────────────────────────────────

@pytest.mark.skipif(os.name != "nt", reason="BELOW_NORMAL_PRIORITY_CLASS 只在 Windows")
def test_low_priority_flag_is_below_normal():
    assert MT._low_priority_flags() == subprocess.BELOW_NORMAL_PRIORITY_CLASS != 0


# ── B-M3：dirty 判定（突變 B07）──────────────────────────────────────────────

@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(r), *args], check=True)
    (r / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (r / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-q", "-m", "init"], check=True)
    return r


def test_clean_tree_is_not_dirty(repo):
    s = MT.tree_state(repo)
    assert MT.run_dirty(s, s) is False


def test_rc_untracked_file_makes_the_run_dirty(repo):
    """稽核 B-M3：未追蹤的檔（忘了 git add 的產品檔、測試、conftest 外掛）會影響一輪全量。"""
    (repo / "new_module.py").write_text("y = 2\n", encoding="utf-8")
    s = MT.tree_state(repo)
    assert MT.run_dirty(s, s) is True


def test_ignored_files_do_not_make_it_dirty(repo):
    """正對照：gitignored 的（測試產生的 uploads 等）照樣排除，否則每一輪都 dirty、閘門永遠過不了。"""
    (repo / "ignored").mkdir()
    (repo / "ignored" / "x.txt").write_text("", encoding="utf-8")
    s = MT.tree_state(repo)
    assert MT.run_dirty(s, s) is False


def test_rc_head_moved_during_the_run_is_dirty(repo):
    start = MT.tree_state(repo)
    (repo / "a.py").write_text("x = 3\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-am", "mid-run"], check=True)
    assert MT.run_dirty(start, MT.tree_state(repo)) is True


def test_rc_tree_modified_during_the_run_is_dirty(repo):
    start = MT.tree_state(repo)
    (repo / "a.py").write_text("x = 4\n", encoding="utf-8")
    assert MT.run_dirty(start, MT.tree_state(repo)) is True


def _run_full_record(monkeypatch, states):
    """實際呼叫 run_full（pytest 本身換掉），回傳寫出去的那一筆紀錄。states：tree_state 依序回傳的值。"""
    import types
    seq = iter(states)
    written = []
    monkeypatch.setattr(MT, "tree_state", lambda repo=None: next(seq))
    monkeypatch.setattr(MT, "run_pytest", lambda *a, **k: (0, "== 5 passed in 1.0s =="))
    monkeypatch.setattr(MT, "write_last_full", lambda r, root=None: written.append(dict(r)) or Path("x"))
    MT.run_full([], types.SimpleNamespace(workers=2, e2e_workers=2, window="t"))
    return written[-1]


def test_run_full_records_clean_when_nothing_changed(monkeypatch):
    rec = _run_full_record(monkeypatch, [("a" * 40, ""), ("a" * 40, "")])
    assert rec["dirty"] is False and rec["commit"] == "a" * 40


def test_rc_run_full_records_dirty_when_head_moves_mid_run(monkeypatch):
    """突變 B07（dirty 寫死）存活過 ⇒ 驗寫出去的紀錄，不驗程式碼長相。"""
    rec = _run_full_record(monkeypatch, [("a" * 40, ""), ("b" * 40, "")])
    assert rec["dirty"] is True and rec["head_at_end"] == "b" * 40


def test_rc_run_full_records_dirty_when_untracked_at_start(monkeypatch):
    rec = _run_full_record(monkeypatch, [("a" * 40, "?? x.py\n"), ("a" * 40, "?? x.py\n")])
    assert rec["dirty"] is True



# ── worker 上限可用環境變數覆寫（主持派工 2026-09-26：全速期間不改程式，使用者回來後拿掉即恢復）──────

@pytest.fixture
def _no_cap_env(monkeypatch):
    """跑這幾題的人自己可能正設著覆寫（全速期間）⇒ 先清掉，否則「預設」那題會量到環境。"""
    monkeypatch.delenv(MT.FULL_ENV, raising=False)
    monkeypatch.delenv(MT.PARTIAL_ENV, raising=False)


def test_caps_default_when_env_unset(_no_cap_env):
    assert MT.full_max_workers() == MT.FULL_MAX_WORKERS == 4
    assert MT.partial_max_workers() == MT.PARTIAL_MAX_WORKERS == 2


def test_caps_follow_env(_no_cap_env, monkeypatch):
    monkeypatch.setenv(MT.FULL_ENV, "3")
    monkeypatch.setenv(MT.PARTIAL_ENV, "1")
    assert MT.full_max_workers() == 3 and MT.partial_max_workers() == 1


@pytest.mark.parametrize("raw", ["0", "-2", "abc", "4.5", str((os.cpu_count() or 1) + 1)])
def test_rc_invalid_env_is_not_used_and_is_said(_no_cap_env, monkeypatch, capsys, raw):
    """不合法 ⇒ 不猜、用預設、說出來（〈版本適配：算不出來就什麼都不做別猜〉）。"""
    monkeypatch.setenv(MT.FULL_ENV, raw)
    assert MT.full_max_workers() == MT.FULL_MAX_WORKERS
    assert MT.FULL_ENV in capsys.readouterr().out


def test_run_full_uses_the_env_cap(_no_cap_env, monkeypatch):
    """行為題：全量把 -n 壓到環境變數給的上限（不是寫死的常數）。突變：run_full 改回常數 ⇒ 紅。"""
    import types
    monkeypatch.setenv(MT.FULL_ENV, "3")
    seen = []
    monkeypatch.setattr(MT, "tree_state", lambda repo=None: ("a" * 40, ""))
    monkeypatch.setattr(MT, "run_pytest", lambda roots, args, *a, **k: seen.append(list(args)) or (0, "== 1 passed in 1.0s =="))
    monkeypatch.setattr(MT, "write_last_full", lambda r, root=None: Path("x"))
    MT.run_full([], types.SimpleNamespace(workers=4, e2e_workers=4, window="t"))
    ns = [args[args.index("-n") + 1] for args in seen if "-n" in args]
    assert ns and all(n == "3" for n in ns), seen


def test_no_call_site_caps_with_the_bare_constant():
    """差異題那條路（main 內）不好在單元題裡跑到 ⇒ 另守：cap_workers 的上限一律經函式（常數只當預設）。"""
    src = (REPO / "tools" / "platform" / "modtest.py").read_text(encoding="utf-8")
    import re
    assert not re.search(r"cap_workers\([^)]*,\s*(FULL|PARTIAL)_MAX_WORKERS\)", src)
    assert "cap_workers(extra, partial_max_workers())" in src

# ── B-S4：同一個 commit 的歷次紀錄 ─────────────────────────────────────────────

def test_rerun_keeps_history_and_gate_reports_earlier_reds(tmp_path):
    sys.path.insert(0, str(REPO / "backend" / "tools"))
    import deploy_insights as di
    sha = "a" * 40
    MT.write_last_full({"commit": sha, "dirty": False, "ok": False, "failed": 3}, root=tmp_path)
    per = MT.write_last_full({"commit": sha, "dirty": False, "ok": True, "failed": 0}, root=tmp_path)
    rec = json.loads(per.read_text(encoding="utf-8"))
    assert rec["ok"] is True and [h["ok"] for h in rec["history"]] == [False]
    g = di.last_full(per, sha)
    assert g["state"] == "ok" and g["red_runs"] == 1 and "紅過 1 次" in g["detail"]


# ── B-M2：project_env create 不覆寫（突變：拿掉存在檢查）───────────────────────

def test_venv_dir_follows_python_version(monkeypatch):
    monkeypatch.delenv("MOTRIX_PROJECT_VENV", raising=False)
    assert PE.venv_dir_for("3.13") == ".venv313" and PE.venv_dir_for("3.12") == ".venv312"


def test_rc_create_refuses_an_existing_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MOTRIX_PROJECT_VENV", raising=False)
    (tmp_path / ".venv313").mkdir()
    monkeypatch.setattr(PE, "main_worktree_root", lambda: tmp_path)
    monkeypatch.setattr(PE, "holders", lambda p: [])
    calls = []
    monkeypatch.setattr(PE.subprocess, "run", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("不可以執行")))
    assert PE.cmd_create("3.13") == 2
    assert calls == [], "資料夾已存在時不可以呼叫 venv／pip"
    assert "不覆寫" in capsys.readouterr().out


# ── B-S3：project_env 的純函式 ─────────────────────────────────────────────────

@pytest.mark.parametrize("v,ok", [("3.11.0", True), ("3.12.10", True), ("3.14.1", True), ("4.0", True),
                                  ("3.10.9", False), ("", False), (None, False), ("abc", False)])
def test_supported_range_has_only_a_lower_bound(v, ok):
    assert PE.in_supported_range(v) is ok


def test_parse_prod_env_accepts_freeze_text_and_dict():
    a = PE.parse_prod_env({"pythonVersion": "Python 3.12.10", "pipFreeze": "FastAPI==0.1\npydantic_core==2.0 ; x\n# c"})
    assert a == {"python": "3.12.10", "packages": {"fastapi": "0.1", "pydantic-core": "2.0"}}
    assert PE.parse_prod_env({"python": "3.12", "packages": {"Starlette": "1"}})["packages"] == {"starlette": "1"}


def test_compare_only_warns_on_range_and_lists_package_diffs():
    venv = {"python": "3.13.1", "packages": {"fastapi": "1"}}
    assert any("fastapi" in d for d in PE.compare(venv, {"python": "3.12.10", "packages": {"fastapi": "2"}}))
    assert not any("Python" in d for d in PE.compare(venv, {"python": "3.12.10", "packages": {}}))   # 範圍內不比 Python
    assert any("不在支援範圍" in d for d in PE.compare(venv, {"python": "3.10.1", "packages": {}}))


# ── B-S2：建包的 pytest worker 數 ─────────────────────────────────────────────

def test_build_script_workers_within_full_limit():
    """建包也在同一台開發機上跑 ⇒ 上限同 §C-13 全量（modtest.FULL_MAX_WORKERS）。"""
    import re
    src = (REPO / "backend" / "tools" / "build_deploy_package.ps1").read_text(encoding="utf-8-sig")
    caps = re.findall(r"\$workers\s*=\s*\[Math\]::Max\(\s*\d+\s*,\s*\[Math\]::Min\(\s*\$physCores\s*,\s*(\d+)\s*\)\s*\)", src)
    assert caps, "找不到建包的 worker 計算式（改寫了就要一起改這題）"
    assert all(int(c) <= MT.FULL_MAX_WORKERS for c in caps), caps
