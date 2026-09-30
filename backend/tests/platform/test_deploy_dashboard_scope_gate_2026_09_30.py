"""部署儀表板 /api/build-gate 的範圍驗證分支（PLAYBOOK §D-1a；判定本體的題在 test_scope_gate_2026_09_30.py）。
絕不觸發真的打包或對正式機連線。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import deploy_dashboard as dd  # noqa: E402

C = "c" * 40


@pytest.fixture
def gate_env(monkeypatch, tmp_path):
    monkeypatch.setattr(dd, "FULL_RESULTS_DIR", tmp_path / "full_results")
    monkeypatch.setattr(dd, "_head_full_sha", lambda: C)
    return tmp_path


def _ok(commit=C):
    return lambda h: {"accepted": True, "mode": "scoped", "commit": commit, "record_present": True, "detail": "範圍 ok"}


def test_gate_accepts_scoped_only_when_scope_gate_accepts(monkeypatch, gate_env):
    monkeypatch.setattr(dd, "_scoped_gate", _ok())
    g = dd.build_gate()
    assert (g["state"], g["mode"]) == ("ok", "scoped")
    monkeypatch.setattr(dd, "_scoped_gate", lambda h: {"accepted": False, "record_present": True, "detail": "動到底層"})
    g = dd.build_gate()
    assert g["state"] == "missing" and g["mode"] is None and "動到底層" in g["detail"]


def _scoped_for_other_commit_is_blocked(mod, monkeypatch):
    monkeypatch.setattr(mod, "_scoped_gate", _ok("d" * 40))
    g = mod.build_gate()
    return g["state"] != "ok" and g["mode"] is None


def test_scoped_verdict_for_another_commit_is_blocked(monkeypatch, gate_env):
    """稽核 W4 S2：判定的 commit 不是 HEAD ⇒ 不放行。"""
    assert _scoped_for_other_commit_is_blocked(dd, monkeypatch)


def test_reverse_control_without_the_commit_check_it_would_pass(monkeypatch, gate_env):
    src = Path(dd.__file__).read_text(encoding="utf-8")
    old = ' and sc.get("commit") == head:\n'
    assert src.count(old) == 1
    body = src.replace(old, ":\n", 1)
    fn = body[body.index("@app.get(\"/api/build-gate\")"):]
    fn = fn[fn.index("def build_gate"):fn.index("\n\n\n")]
    ns = dict(dd.__dict__)
    exec(compile(fn, "build_gate_mutant", "exec"), ns)          # 只換 build_gate，其餘沿用真實模組
    ns["_scoped_gate"] = _ok("d" * 40)
    assert ns["build_gate"]()["state"] == "ok", "拿掉 commit 比對後應該放行（證明上一題守得住）"


def test_green_full_wins_and_does_not_consult_scope_gate(monkeypatch, gate_env):
    (gate_env / "full_results").mkdir()
    (gate_env / "full_results" / (C + ".json")).write_text(json.dumps({"commit": C, "ok": True}), encoding="utf-8")
    monkeypatch.setattr(dd, "_scoped_gate", lambda h: pytest.fail("全量綠時不可以再判範圍驗證"))
    g = dd.build_gate()
    assert (g["state"], g["mode"]) == ("ok", "full")


def test_scoped_gate_errors_fail_closed(gate_env):
    """真的 _scoped_gate：repo 裡沒有 c…c 這個 commit ⇒ scope_gate 丟例外 ⇒ 不放行。"""
    g = dd.build_gate()
    assert g["state"] != "ok" and g["mode"] is None
    r = dd._scoped_gate(C)
    assert r["accepted"] is False and "範圍驗證判定失敗" in r["detail"]
