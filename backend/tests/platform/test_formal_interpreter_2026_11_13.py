# -*- coding: utf-8 -*-
"""預跑與正式閘門必須用同一個直譯器（2026-11-13，T82 閘門抓到的流程漏洞）。

事故：預跑（modtest --full）用 `.venv`、閘門（run-stage／建包）用 `.venv312` ⇒ test_merge_drivers 兩題
（假設 sys.executable 不在 .venv312 之下）預跑綠、閘門紅。修法：`project_env.interpreter_mismatch` 是單一判定；
modtest --full（真的跑時）與 run_stage（真的跑時）直譯器不是 `.venv312` 就**拒跑**（modtest 回 2；run-stage 回 2、不寫紀錄），
明知要用別的才 `--allow-other-python`／MOTRIX_ALLOW_OTHER_PYTHON=1。預跑守門題組（preflight_guards.python_exe）本來就固定 .venv312。
"""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
sys.path.insert(0, str(REPO / "backend" / "tools"))
import project_env as PE  # noqa: E402


@pytest.fixture
def fake_formal(tmp_path, monkeypatch):
    """假的「正式」環境：<tmp>/.venv312/Scripts/python.exe。"""
    root = tmp_path / ".venv312" / "Scripts"
    root.mkdir(parents=True)
    py = root / "python.exe"
    py.write_text("", encoding="utf-8")
    monkeypatch.setattr(PE, "formal_python", lambda: py)
    monkeypatch.delenv(PE.ALLOW_OTHER_PYTHON_ENV, raising=False)
    return py


def test_same_venv_passes_and_other_python_is_refused(fake_formal, tmp_path):
    assert PE.interpreter_mismatch(fake_formal, {}) is None
    assert PE.interpreter_mismatch(str(fake_formal).upper(), {}) is None, "Windows 路徑大小寫不拘"
    other = tmp_path / ".venv" / "Scripts" / "python.exe"
    msg = PE.interpreter_mismatch(other, {})
    assert msg and ".venv312" in msg and "test_merge_drivers" in msg and PE.ALLOW_OTHER_PYTHON_ENV in msg, msg
    assert PE.interpreter_mismatch(r"C:\Python312\python.exe", {}), "系統 python 也不是正式環境"
    assert PE.interpreter_mismatch(tmp_path / ".venv312-old" / "Scripts" / "python.exe", {}), "前綴相似不算同一個 venv"


def test_explicit_allow_and_missing_formal_env_do_not_block(fake_formal, tmp_path, monkeypatch):
    other = tmp_path / ".venv" / "Scripts" / "python.exe"
    assert PE.interpreter_mismatch(other, {PE.ALLOW_OTHER_PYTHON_ENV: "1"}) is None, "明確放行"
    assert PE.interpreter_mismatch(other, {PE.ALLOW_OTHER_PYTHON_ENV: "0"}), "0 不是放行"
    monkeypatch.setattr(PE, "formal_python", lambda: None)
    assert PE.interpreter_mismatch(other, {}) is None, "沒有正式環境可比對（例：別台機器）⇒ 不擋"


def test_modtest_full_refuses_a_different_interpreter_and_has_the_escape_flag():
    src = (REPO / "tools" / "platform" / "modtest.py").read_text(encoding="utf-8")
    m = re.search(r'if a\.full and not a\.dry_run and "PYTEST_CURRENT_TEST" not in os\.environ:\n'
                  r'\s+bad = project_env\.interpreter_mismatch\(PYEXE,.*\n'
                  r'\s+if bad:.*\n\s+print\(.*\n\s+return 2', src)
    assert m, "modtest --full 沒有「直譯器不一致就拒跑（回 2）」"
    assert m.start() > src.index("PYEXE = resolve_python(a.python)"), "檢查要在 resolve_python 之後"
    assert m.start() < src.index("return run_full(extra, a)"), "檢查要在 run_full 之前"
    assert '"--allow-other-python"' in src


def test_run_stage_refuses_before_running_anything(tmp_path, monkeypatch):
    import build_test_reuse as btr
    called = []
    monkeypatch.setattr(btr, "_interpreter_mismatch", lambda python, repo: "不是正式環境")
    monkeypatch.setattr(btr, "fingerprint", lambda repo: called.append("fp") or "x")
    notes = []
    rc, wrote, why = btr.run_stage(tmp_path, "not_e2e", tmp_path / "rec.jsonl", python="whatever", note=notes.append)
    assert (rc, wrote) == (2, False) and not called, (rc, wrote, called)
    assert any("拒跑" in n for n in notes), notes
    # 注入 runner（測試用）時不查：既有的 run-stage 測試照常
    monkeypatch.setattr(btr, "_interpreter_mismatch", lambda python, repo: (_ for _ in ()).throw(AssertionError("不該被呼叫")))
    assert btr._interpreter_mismatch is not None


def test_build_side_uses_the_same_single_judgement(tmp_path):
    """run_stage 用的 _interpreter_mismatch 就是 project_env.interpreter_mismatch（同一份判定；不是另寫一套）。"""
    import build_test_reuse as btr
    assert btr._interpreter_mismatch(sys.executable, REPO) == PE.interpreter_mismatch(sys.executable)
    assert btr._interpreter_mismatch(sys.executable, tmp_path) is None, "載不到 project_env ⇒ fail-open（不擋）"


def test_preflight_runs_on_the_formal_interpreter():
    src = (REPO / "tools" / "platform" / "preflight_guards.py").read_text(encoding="utf-8")
    assert 'D:/MOTRIX-PLATFORM/.venv312/Scripts/python.exe' in src and "def python_exe" in src
