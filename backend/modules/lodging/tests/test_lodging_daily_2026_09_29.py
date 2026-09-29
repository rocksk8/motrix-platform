# -*- coding: utf-8 -*-
"""旅宿檔案更新（2026-09-29 使用者：「旅宿檔案更新改到系統內，並且每天自動更新」）。

- 每日自動更新：開關、展示模式、當天已更新過都不連線；3 點後當天沒成功過才下載；
  固定鐘點的檢查不會被前一天的成功時間卡住（自動更新用 20 小時間隔，不是手動的 24 小時）。
- 排程：啟動立即返回（背景 Timer）、丟例外照樣排下一輪。
- 選單：側欄「系統」群組、標籤「旅宿檔案更新」。
觀測點是 `fetch_raw` 的**呼叫次數**（同 test_lodging_source）。
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from modules.lodging import source as ls
from modules.lodging.tests import _fixtures as fx

DAY1_0305 = datetime(2026, 9, 29, 3, 5, 0)


@pytest.fixture()
def net(client, monkeypatch):
    calls = []
    box = {"blob": fx.good_zip(), "now": DAY1_0305}

    def fake_fetch(url=ls.DATASET_URL):
        calls.append(url)
        return box["blob"]

    monkeypatch.setattr(ls, "fetch_raw", fake_fetch)
    monkeypatch.setattr(ls, "_now", lambda: box["now"])
    monkeypatch.setenv(ls.FETCH_ENV, "1")
    box["calls"] = calls
    return box


# ── 判定 ──────────────────────────────────────────────────────────────────────

def test_daily_due_rules():
    d = datetime(2026, 9, 29, ls.DAILY_REFRESH_HOUR, 0, 0)
    assert ls.daily_due({}, d) is True                                              # 從沒更新過
    assert ls.daily_due({}, d - timedelta(minutes=1)) is False                      # 還沒到鐘點
    assert ls.daily_due({"last_success_at": "2026-09-28T03:00:00"}, d) is True       # 昨天成功 ⇒ 今天要
    assert ls.daily_due({"last_success_at": "2026-09-29T03:00:00"}, d + timedelta(hours=5)) is False


# ── 一輪排程 ──────────────────────────────────────────────────────────────────

def test_daily_run_downloads_once_per_day(net):
    r = ls.run_daily_refresh()
    assert r and r["ok"] is True and len(net["calls"]) == 1
    net["now"] = DAY1_0305 + timedelta(hours=1)
    assert ls.run_daily_refresh() is None and len(net["calls"]) == 1                # 同一天不再抓
    net["now"] = DAY1_0305 + timedelta(days=1)
    assert ls.run_daily_refresh()["ok"] and len(net["calls"]) == 2                  # 隔天再抓


def test_daily_run_not_blocked_by_yesterdays_later_success(net):
    """昨天 03:59 成功、今天 03:05 檢查：手動的 24 小時間隔會擋住並讓時間每天往後漂；自動更新的 20 小時不會。"""
    net["now"] = DAY1_0305.replace(minute=59)
    assert ls.run_daily_refresh()["ok"]
    net["now"] = DAY1_0305 + timedelta(days=1)
    r = ls.run_daily_refresh()
    assert r["ok"] is True and len(net["calls"]) == 2, r
    # 反向控制：手動按鈕仍是 24 小時
    net["now"] = (DAY1_0305 + timedelta(days=2)).replace(minute=0)                 # 距上次成功 23 小時 55 分
    assert ls.refresh()["reason"] == "rate_limited"


@pytest.mark.parametrize("case", ["switch_off", "demo", "before_hour"])
def test_daily_run_never_connects_when_not_allowed(net, monkeypatch, case):
    if case == "switch_off":
        monkeypatch.delenv(ls.FETCH_ENV, raising=False)
    elif case == "demo":
        monkeypatch.setattr(ls, "is_demo_mode", lambda: True)
    else:
        net["now"] = DAY1_0305.replace(hour=ls.DAILY_REFRESH_HOUR - 1)
    assert ls.run_daily_refresh() is None
    assert net["calls"] == []


# ── 排程殼 ────────────────────────────────────────────────────────────────────

class _FakeTimer:
    made = []

    def __init__(self, delay, fn):
        self.delay, self.fn, self.daemon, self.started = delay, fn, False, False
        _FakeTimer.made.append(self)

    def start(self):
        self.started = True


def test_schedule_returns_immediately_and_tick_always_reschedules(monkeypatch):
    _FakeTimer.made = []
    monkeypatch.setattr(ls.threading, "Timer", _FakeTimer)
    ran = []
    monkeypatch.setattr(ls, "run_daily_refresh", lambda: ran.append(1))
    ls.schedule_daily_refresh()
    assert ran == []                                                                # 啟動路徑不下載
    first = _FakeTimer.made[-1]
    assert first.daemon and first.started and first.delay == ls._DAILY_FIRST_DELAY_SECONDS

    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(ls, "run_daily_refresh", boom)
    first.fn()                                                                      # 丟例外也要排下一輪
    nxt = _FakeTimer.made[-1]
    assert nxt is not first and nxt.started and nxt.daemon and nxt.delay == ls._DAILY_CHECK_SECONDS


def test_module_registers_the_daily_scheduler(monkeypatch):
    import modules.lodging as mod
    called = []
    monkeypatch.setattr(ls, "schedule_daily_refresh", lambda: called.append(1))
    for s in mod.MODULE.schedulers:
        s()
    assert called == [1]


# ── 選單 ──────────────────────────────────────────────────────────────────────

def test_menu_is_system_group_named_lodging_file_update():
    spec = json.loads((Path(ls.__file__).parent / "module.json").read_text(encoding="utf-8"))
    menu = spec["pages"][0]["menu"]
    assert menu["group"] == "system" and menu["label"] == "旅宿檔案更新"


def test_status_reports_daily_hour(client, make_user):
    h = fx.token(client, make_user, "lod_daily", "sales", modules=["lodging"])
    r = client.get("/api/lodging/status", headers=h)
    assert r.status_code == 200 and r.json()["dailyRefreshHour"] == ls.DAILY_REFRESH_HOUR
