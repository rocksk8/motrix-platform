"""IP-10 `daily.check`：M12 自己的那一支（逾期、區間到期；啟動補跑逐日補）。

2026-09-26 自 tests/platform/test_daily_checks_connector.py 移入本模組：拿掉 M12 時一起消失。
"""
from datetime import date, timedelta

from core import registry


def test_daily_tasks_provider_is_registered(client):
    assert "daily_tasks" in registry.providers("daily.check")
    assert registry.single_provider("daily_task.external") is not None


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
