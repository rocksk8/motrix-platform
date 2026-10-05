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


def test_global_switch_off_upsert_is_silent_too(monkeypatch, caplog):
    """全域總開關關閉 + 事件種類開 ⇒ upsert 早退（同 delete），不打 Google、不記 WARNING。"""
    gc = _gc()
    cal = _setup(monkeypatch, {"receivable_due": True}, enabled=False)
    with caplog.at_level("WARNING"):
        gc.push_event_upsert_for_module("receivable_due", "a", "a", "2031-06-01", "K1")
    assert cal.calls == [] and not [r for r in caplog.records if "push_event_upsert_for_module" in r.getMessage()]


def test_upsert_recreates_with_merge_key_when_event_was_deleted_in_google(monkeypatch):
    """找到事件、更新時 404（使用者剛在 Google 手動刪掉）⇒ 重建**帶 merge key**，下一次 upsert 才找得回同一筆（不重複建）。"""
    gc = _gc()
    cal = _setup(monkeypatch, {"receivable_due": True})
    gc.push_event_upsert_for_module("receivable_due", "舊", "舊", "2031-06-01", "K1")
    (old_id,) = cal.events.keys()
    real = gc._update_all_day_event

    def vanish(event_id, *a, **k):
        cal.events.pop(event_id, None)                       # Google 端已被手動刪掉
        raise RuntimeError("Google API 錯誤 404：not found")
    monkeypatch.setattr(gc, "_update_all_day_event", vanish)
    gc.push_event_upsert_for_module("receivable_due", "新", "新", "2031-07-01", "K1")
    monkeypatch.setattr(gc, "_update_all_day_event", real)
    (ev,) = cal.events.values()
    assert ev["summary"] == "新" and ev["id"] != old_id
    assert ev["extendedProperties"]["private"]["motrixMergeKey"] == "receivable_due#K1", "重建的事件要找得回來"
    gc.push_event_upsert_for_module("receivable_due", "再改", "再改", "2031-07-09", "K1")
    assert len(cal.events) == 1 and list(cal.events.values())[0]["summary"] == "再改"
