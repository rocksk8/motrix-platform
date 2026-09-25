# -*- coding: utf-8 -*-
"""背景 job 的收尾（C 稽核 S-P01、S-U01）：歷史真的寫得進去、掛住的 job 會被中止。
用本機 python 子行程代替 PowerShell／WinRM，不連正式機。"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import deploy_dashboard as dd  # noqa: E402


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(dd, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(dd, "DEPLOY_LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(dd, "_active_job_id", None)
    return tmp_path


def _hist(tmp):
    p = tmp / "history.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def test_deploy_job_writes_history_even_when_it_fails(env):
    """S-P01：原本 `success` 未賦值 ⇒ NameError ⇒ 部署／回滾的歷史從來沒寫。"""
    job = "j-deploy"
    dd._try_acquire_job_lock(job)
    dd._run_job(job, "deploy", [sys.executable, "-c", "print('no protocol line')"])
    h = _hist(env)
    assert h and h[0]["action"] == "deploy" and h[0]["success"] is False
    assert dd._active_job_id is None


def test_recent_failure_warning_now_fires(env):
    """S-P01 的下游：歷史寫得進去之後，「15 分鐘內剛失敗」的警告才會出現。"""
    dd._run_job("j2", "rollback", [sys.executable, "-c", "raise SystemExit(1)"])
    assert "失敗" in dd._recent_failure_warning()


def test_hung_upgrade_job_is_killed_and_reported(env, monkeypatch):
    """S-U01：WinRM 掛住不回 ⇒ 超過上限就中止、狀態 failed、鎖釋放、訊息說明正式機狀態不明。"""
    monkeypatch.setitem(dd._JOB_TIMEOUT_MIN, "upgrade-verify", 0.03)     # ≈ 2 秒
    job = "j-hang"
    dd._try_acquire_job_lock(job)
    t0 = time.monotonic()
    dd._run_upgrade_job(job, "upgrade-verify", [sys.executable, "-c", "import time; time.sleep(60)"], "pw\n")
    assert time.monotonic() - t0 < 30
    j = dd._jobs[job]
    assert j["status"] == "failed"
    assert any("逾時" in l and "正式機上的動作可能仍在進行" in l for l in j["lines"])
    assert dd._active_job_id is None
    assert _hist(env)[0]["success"] is False
