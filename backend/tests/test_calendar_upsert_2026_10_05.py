# -*- coding: utf-8 -*-
"""L1 行事曆「一個對象一個事件」（2026-10-05）：push_event_upsert_for_module／push_event_delete_for_module。
以（代碼, key）找回同一筆（與日期無關）；開關關閉＝零流量；未知代碼不推；刪除找不到＝安靜。Google 用假行事曆。"""
import pytest

from tests import _fake_gcal


@pytest.fixture(autouse=True)
def _calendar_app(client):
    """設定表要有資料庫（client 夾具會建好測試用的 app／DB）。"""
    return client


def _gc():
    from helpers import google_calendar as gc
    return gc


def _setup(monkeypatch, events, enabled=True):
    cal = _fake_gcal.install(monkeypatch)
    _fake_gcal.set_events(events=events, enabled=enabled)
    return cal


def test_upsert_creates_then_moves_same_event(monkeypatch):
    gc = _gc()
    cal = _setup(monkeypatch, {"receivable_due": True})
    gc.push_event_upsert_for_module("receivable_due", "標題一", "說明一", "2031-06-01", "K1")
    gc.push_event_upsert_for_module("receivable_due", "標題二", "說明二", "2031-07-15", "K1")
    (ev,) = cal.events.values()
    assert ev["summary"] == "標題二" and ev["start"] == {"date": "2031-07-15"} and ev["end"] == {"date": "2031-07-16"}
    assert ev["extendedProperties"]["private"]["motrixMergeKey"] == "receivable_due#K1"
    gc.push_event_upsert_for_module("receivable_due", "別的對象", "x", "2031-06-01", "K2")
    assert len(cal.events) == 2


def test_delete_removes_only_that_key_and_missing_is_quiet(monkeypatch):
    gc = _gc()
    cal = _setup(monkeypatch, {"receivable_due": True})
    gc.push_event_upsert_for_module("receivable_due", "a", "a", "2031-06-01", "K1")
    gc.push_event_upsert_for_module("receivable_due", "b", "b", "2031-06-01", "K2")
    gc.push_event_delete_for_module("receivable_due", "K1")
    assert [e["summary"] for e in cal.events.values()] == ["b"]
    gc.push_event_delete_for_module("receivable_due", "K1")            # 已經沒有 ⇒ 不報錯
    assert len(cal.events) == 1


def test_switch_off_means_zero_traffic_for_upsert_and_delete(monkeypatch):
    gc = _gc()
    cal = _setup(monkeypatch, None)                                     # 預設關
    gc.push_event_upsert_for_module("receivable_due", "a", "a", "2031-06-01", "K1")
    gc.push_event_delete_for_module("receivable_due", "K1")
    assert cal.calls == []


def test_global_switch_off_blocks_delete_lookup(monkeypatch):
    """全域總開關關閉：delete 自己先擋（不做查詢）；upsert 靠真正的 _events_call 拒絕（假行事曆不模擬那一層）。"""
    gc = _gc()
    cal = _setup(monkeypatch, {"receivable_due": True}, enabled=False)
    gc.push_event_delete_for_module("receivable_due", "K1")
    assert cal.calls == []


def test_unknown_code_and_empty_key_are_never_pushed(monkeypatch):
    gc = _gc()
    cal = _setup(monkeypatch, {"receivable_due": True})
    gc.push_event_upsert_for_module("not_a_type", "a", "a", "2031-06-01", "K1")
    gc.push_event_delete_for_module("not_a_type", "K1")
    gc.push_event_upsert_for_module("receivable_due", "a", "a", "2031-06-01", "")
    assert cal.calls == []


def test_google_failure_is_swallowed(monkeypatch):
    gc = _gc()
    _setup(monkeypatch, {"receivable_due": True})

    def boom(*a, **k):
        raise RuntimeError("Google 掛了")
    monkeypatch.setattr(gc, "_events_call", boom)
    gc.push_event_upsert_for_module("receivable_due", "a", "a", "2031-06-01", "K1")
    gc.push_event_delete_for_module("receivable_due", "K1")             # 不拋出即可
