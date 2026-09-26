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
    monkeypatch.setattr(dd, "HISTORY_PENDING_PATH", tmp_path / "history.pending.jsonl")
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


def test_history_concurrent_appends_keep_valid_json_and_every_entry(env):
    """解除鎖定端點與 job 收尾會同時寫歷史：不可以留下殘字、不可以掉筆（2026-09-26 反向控制時出現「…]_deploy_timeout」）。"""
    import threading
    n = 40
    go = threading.Event()

    def w(i):
        go.wait()
        dd._append_history(("x" * (i % 7) * 20) + f"a{i}", f"j{i}", i % 2 == 0)

    ths = [threading.Thread(target=w, args=(i,)) for i in range(n)]
    for th in ths:
        th.start()
    go.set()
    for th in ths:
        th.join(timeout=30)
    h = _hist(env)                                               # 殘字 ⇒ 這裡 JSONDecodeError
    assert sorted(e["action"].lstrip("x") for e in h) == sorted(f"a{i}" for i in range(n))
    assert not list(env.glob("history.json.*.tmp"))


def test_history_writes_survive_a_concurrent_reader(env):
    """D 稽核：只鎖寫入端時，儀表板輪詢 /api/history 會讓 os.replace 在 Windows 丟 PermissionError ⇒ 那一筆掉了。
    讀與寫同時進行：寫入不可以丟例外、不可以掉筆。"""
    import threading
    stop = threading.Event()
    reads = []

    def poll():
        while not stop.is_set():
            reads.append(len(dd.get_history()))

    rd = threading.Thread(target=poll)
    rd.start()
    errors = []
    try:
        for i in range(150):
            try:
                dd._append_history("r%d" % i, "j", True)
            except Exception as e:                       # noqa: BLE001 — 任何例外都算掉筆
                errors.append(repr(e))
    finally:
        stop.set()
        rd.join(timeout=30)
    assert not errors, errors[:3]
    assert len(_hist(env)) == 150
    assert reads, "前提：讀取端真的有在跑"


def test_unreadable_history_is_reported_not_treated_as_no_failure(env):
    """讀不到歷史 ≠ 上一次沒有失敗：警告要說出來。"""
    (env / "history.json").write_text("{殘字", encoding="utf-8")
    assert "讀不到" in dd._recent_failure_warning()
    assert dd.get_history() == []


def test_busy_history_is_not_overwritten_as_empty(env, monkeypatch):
    """D 稽核 H-S1：讀檔被占用（PermissionError）時，不可以當成空清單寫回蓋掉既有紀錄；那一筆另存、警告說出來。"""
    for i in range(20):
        dd._append_history("old%d" % i, "j", True)
    real = type(dd.HISTORY_PATH).read_text

    def busy(self, *a, **k):
        if self == dd.HISTORY_PATH:
            raise PermissionError("locked by another process")
        return real(self, *a, **k)

    monkeypatch.setattr(type(dd.HISTORY_PATH), "read_text", busy)
    monkeypatch.setattr(dd.time, "sleep", lambda s: None)
    dd._append_history("new", "j", False)
    monkeypatch.undo()
    monkeypatch.setattr(dd, "HISTORY_PATH", env / "history.json")
    monkeypatch.setattr(dd, "HISTORY_PENDING_PATH", env / "history.pending.jsonl")
    assert len(_hist(env)) == 20, "既有 20 筆不可以被蓋掉"
    pending = (env / "history.pending.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(l)["action"] for l in pending] == ["new"]
    assert dd.get_history()[0]["action"] == "new", "還沒併回之前，畫面也要看得到那一筆"
    assert "上一次new" in dd._recent_failure_warning(), "那一筆是失敗 ⇒ 15 分鐘警告照常"


def test_pending_is_merged_back_on_the_next_write_and_warning_returns_to_normal(env, monkeypatch):
    """D 稽核 H-S2：pending 要有落點——主檔恢復後的下一次寫入把它依時間併回並刪檔；警告回到一般判斷。"""
    dd._append_history("old", "j", True)
    real = type(dd.HISTORY_PATH).read_text

    def busy(self, *a, **k):
        if self == dd.HISTORY_PATH:
            raise PermissionError("locked")
        return real(self, *a, **k)

    with monkeypatch.context() as m:
        m.setattr(type(dd.HISTORY_PATH), "read_text", busy)
        m.setattr(dd.time, "sleep", lambda s: None)
        dd._append_history("while-busy", "j", False)
    assert (env / "history.pending.jsonl").exists()
    for i in range(3):
        dd._append_history("after%d" % i, "j", True)
    assert not (env / "history.pending.jsonl").exists(), "併回之後 pending 要刪掉"
    actions = [e["action"] for e in _hist(env)]
    assert actions == ["after2", "after1", "after0", "while-busy", "old"], actions
    assert dd._recent_failure_warning() == "", "最近一筆是成功 ⇒ 沒有警告（不會卡在「尚未併回」）"


def test_corrupt_history_is_archived_before_starting_over(env):
    """讀得到但不是合法 JSON：先封存壞檔（不丟內容），新檔第一筆說明發生什麼事。"""
    (env / "history.json").write_text('[{"action": "a"}]殘字', encoding="utf-8")
    dd._append_history("new", "j", True)
    archived = list(env.glob("history.json.corrupt-*"))
    assert len(archived) == 1 and archived[0].read_text(encoding="utf-8") == '[{"action": "a"}]殘字'
    h = _hist(env)
    assert h[0]["action"] == "new" and "封存" in h[1]["action"]
