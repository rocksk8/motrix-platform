"""IP-10 `daily.check`：模組的每日檢查登記給 L1 執行器（M12 搬遷前置，2026-09-26）。

原本九種檢查寄生在 M12 的排程裡 ⇒ 停用每日任務會連帶停掉備份與磁碟告警。
① 兩個提供者（daily_tasks、case_deadlines）都已登記
② 反向控制：拿掉所有提供者 ⇒ 系統健康檢查兩種模式都照跑
③ 一支提供者丟例外 ⇒ 其他提供者與系統檢查照跑
④ 每日任務的啟動補跑：依 dt_overdue_last_check 逐日補，guard 前進
"""
from datetime import date, timedelta

import pytest

from core import registry
from helpers import daily_checks, system_checks

SYS = ("_check_backup_freshness", "_check_disk_space", "_check_temp_bloat", "_check_cert_expiry",
       "_check_approval_reminders", "_prune_request_log")


def _only(monkeypatch, fake):
    """daily.check 的提供者換成 fake（其他能力不動）：legacy 與已載入模組的 ModuleSpec.providers 兩處都要處理。"""
    orig = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: dict(fake) if cap == "daily.check" else orig(cap))


@pytest.fixture
def sys_calls(monkeypatch):
    called = []
    for n in SYS:
        monkeypatch.setattr(system_checks, n, (lambda *a, n=n, **k: called.append(n)))
    return called


def test_both_providers_are_registered(client):
    names = set(registry.providers("daily.check"))
    assert {"daily_tasks", "case_deadlines"} <= names, names


def test_reverse_without_module_providers_system_checks_still_run(monkeypatch, sys_calls):
    _only(monkeypatch, {})
    assert not registry.providers("daily.check")
    for mode in ("startup", "daily"):
        del sys_calls[:]
        assert daily_checks.run_once(mode) == []
        assert set(SYS) - {"_prune_request_log"} <= set(sys_calls), (mode, sys_calls)
        assert ("_prune_request_log" in sys_calls) == (mode == "daily")


def test_one_failing_provider_does_not_stop_the_others(monkeypatch, sys_calls):
    ran = []

    def boom(mode):
        raise RuntimeError("x")
    _only(monkeypatch, {"aa_boom": boom, "zz_ok": lambda mode: ran.append(mode)})
    assert daily_checks.run_once("daily") == ["aa_boom", "zz_ok"]
    assert ran == ["daily"] and "_check_backup_freshness" in sys_calls


def test_daily_tasks_startup_catchup_advances_the_guard(client, monkeypatch):
    import modules.daily_tasks.api as dt
    days = []
    monkeypatch.setattr(dt, "_check_overdue_and_notify", lambda d=None: days.append(d))
    monkeypatch.setattr(dt, "_check_range_task_deadline", lambda: None)
    y = date.today() - timedelta(days=1)
    dt._set_setting("dt_overdue_last_check", (y - timedelta(days=3)).isoformat())
    dt.run_daily_checks("startup")
    assert days == [(y - timedelta(days=i)).isoformat() for i in (2, 1, 0)]
    assert dt._get_setting("dt_overdue_last_check") == y.isoformat()
    del days[:]
    dt.run_daily_checks("daily")
    assert days == [None]


def test_reminder_failures_endpoint_lives_in_l1(client, make_user, monkeypatch):
    """簽核催辦的失敗落點（端點）跟著催辦下沉 L1：停用每日任務不可以讓它消失。
    這一題也真的呼叫端點——搬移時它曾經引用一個已經不在本檔的函式（執行才會 NameError）。"""
    from helpers import system_checks
    monkeypatch.setattr(system_checks, "reminder_send_failures", lambda: [{"doc_no": "A"}, {"doc_no": "B"}])
    name, pw = make_user(username="rsf_sa", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": name, "password": pw}).json()["token"]
    r = client.get("/api/settings/reminder-send-failures", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200 and r.json() == {"items": [{"doc_no": "B"}, {"doc_no": "A"}]}, r.text
    import routers.system as rs
    assert any(getattr(rt, "path", "") == "/api/settings/reminder-send-failures" for rt in rs.router.routes)
