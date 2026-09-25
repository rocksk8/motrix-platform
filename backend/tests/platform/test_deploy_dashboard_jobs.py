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
    assert j["status"] == "timeout"                     # B-3：逾時與失敗分開
    assert any("逾時" in l and "不改正式機" in l for l in j["lines"])
    assert dd._active_job_id is None
    assert _hist(env)[0]["success"] is False


def test_rollback_timeouts_are_longer_than_convert():
    """稽核 A-1：回滾比轉換慢，上限不可以比轉換短。"""
    t = dd._JOB_TIMEOUT_MIN
    assert t["upgrade-rollback-code"] > t["upgrade-convert"] and t["upgrade-rollback-full"] > t["upgrade-convert"]
    assert t["rollback"] >= t["deploy"]


def test_deploy_timeout_does_not_kill_and_needs_release_with_reason(env, monkeypatch):
    """稽核 A-1／B-1：deploy 逾時不自動中止（中止會讓正式機停在一半），鎖不放，由人寫原因解除。"""
    from fastapi.testclient import TestClient
    monkeypatch.setitem(dd._JOB_TIMEOUT_MIN, "deploy", 0.03)
    job = "j-deploy-hang"
    dd._try_acquire_job_lock(job)
    import threading
    th = threading.Thread(target=dd._run_job, args=(job, "deploy", [sys.executable, "-c", "import time; time.sleep(60)"]))
    th.start()
    for _ in range(100):
        if dd._jobs.get(job, {}).get("timedOut"):
            break
        time.sleep(0.1)
    j = dd._jobs[job]
    assert j.get("timedOut") and j["status"] == "running"          # 沒有被中止
    assert any("仍在等待" in l for l in j["lines"])
    assert dd._active_job_id == job                                 # 鎖沒放
    c = TestClient(dd.app, client=("127.0.0.1", 1))
    assert c.post(f"/api/jobs/{job}/release", json={"reason": "短"}).status_code == 400
    assert c.post(f"/api/jobs/{job}/release", json={"reason": "已從 log 確認正式機已停止"}).status_code == 200
    th.join(timeout=30)
    assert not th.is_alive()
    assert dd._jobs[job]["status"] == "timeout" and dd._active_job_id is None
    assert any("解除鎖定" in h["action"] for h in _hist(env))


def test_release_refuses_jobs_that_did_not_time_out(env):
    from fastapi.testclient import TestClient
    dd._run_job("j-ok", "rollback", [sys.executable, "-c", "print(1)"])
    c = TestClient(dd.app, client=("127.0.0.1", 1))
    assert c.post("/api/jobs/j-ok/release", json={"reason": "隨便解除看看不行"}).status_code == 409


def test_deploy_success_path_writes_success(env):
    """稽核 B-1：成功路徑也要有題（v2 協定結果行）。"""
    out = "print('::PROTOCOL:: v=2'); print('::RESULT:: v=2 status=success rolled_back=applied service=up exit=0')"
    dd._run_job("j-deploy-ok", "deploy", [sys.executable, "-c", out])
    assert dd._jobs["j-deploy-ok"]["status"] == "succeeded"
    assert _hist(env)[0]["success"] is True
