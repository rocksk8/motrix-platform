# -*- coding: utf-8 -*-
"""行事曆推送可選（2026-09-30 使用者裁示；提案 D:\\開發測試檔\\proposal-calendar-events.md）。

L1 `helpers.google_calendar`：事件種類開關（`system_settings.google_calendar.events`）、預設（既有 9 種開、新 4 種關）、
關閉不刪既有事件、通用推送 `push_event_for_module`（同一案件同一天合併）、設定端點只限最高管理者＋每個變更記稽核。
Google API 一律用 `tests/_fake_gcal.py` 的假行事曆，不連外。
"""
import json

import pytest

from tests import _fake_gcal

EXISTING = ["invoice_voucher", "payment_request", "shipping_note", "quotation_won", "stage_due", "stage_done",
            "important_comment", "dev_case_converted", "dev_case_stale"]
NEW = ["case_update", "dev_case_update", "contractor_payout", "expense_payout"]


def _gc():
    from helpers import google_calendar as gc
    return gc


def _hdr(client, make_user, name, role):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


# ── 預設 ──────────────────────────────────────────────────────────────────

def test_catalog_is_nine_existing_on_and_four_new_off():
    gc = _gc()
    assert list(gc.EVENT_CODES) == [t["code"] for t in gc.event_types()]
    assert sorted(gc.EVENT_CODES) == sorted(EXISTING + NEW)
    sw = gc.event_switches({})                      # 升級後第一次讀：沒有 events ⇒ 全部取預設
    assert [c for c in EXISTING if not sw[c]] == []
    assert [c for c in NEW if sw[c]] == []
    # 存了非 bool 的垃圾 ⇒ 取預設，不當真
    assert gc.event_switches({"events": {"case_update": "yes", "invoice_voucher": 0}})["case_update"] is False
    assert gc.event_switches({"events": {"invoice_voucher": 0}})["invoice_voucher"] is True
    assert gc.event_enabled("no_such_event") is False


def test_get_endpoint_returns_defaults_and_catalog(client, make_user):
    h = _hdr(client, make_user, "gct_sa", "superadmin")
    d = client.get("/api/settings/google-calendar", headers=h).json()
    assert {c for c, v in d["events"].items() if v} == set(EXISTING)
    assert [t["code"] for t in d["eventTypes"]] == list(_gc().EVENT_CODES)
    assert all({"label", "group", "description", "default"} <= set(t) for t in d["eventTypes"])


# ── 既有 9 種：每一種都聽自己的開關 ─────────────────────────────────────────

class _Row(dict):
    def __missing__(self, k):
        return ""


_ROW = _Row(data_json="{}", snapshot_json="{}", amount=100, total=100, customer_name="客", project_name="案",
            quote_no="MQ-1", ship_date="2031-01-02", case_name="開發案", converted_quote_no="MQ-1", id=1, label="驗收",
            due_date="2031-01-03", google_calendar_event_id="", done=1, done_at="2031-01-04",
            google_calendar_done_event_id="")


class _Conn:
    def execute(self, *a, **k):
        return self

    def fetchone(self):
        return _ROW

    def fetchall(self):
        return [_ROW]

    def close(self):
        pass


_CALLS = {
    "invoice_voucher":    lambda gc: gc.push_event_for_invoice_voucher("IV-1"),
    "payment_request":    lambda gc: gc.push_event_for_payment_request("PR-1"),
    "shipping_note":      lambda gc: gc.push_event_for_shipping_note("SN-1"),
    "quotation_won":      lambda gc: gc.push_event_for_quotation_won("MQ-1"),
    "stage_due":          lambda gc: gc.push_event_for_case_stage_due(1),
    "stage_done":         lambda gc: gc.push_event_for_case_stage_done(1),
    "important_comment":  lambda gc: gc.push_event_for_important_comment(1, "MQ-1", "內容", "甲"),
    "dev_case_converted": lambda gc: gc.push_event_for_dev_case_converted(1),
    "dev_case_stale":     lambda gc: gc.push_event_for_dev_case_stale(1, "開發案", "客", 31),
}


@pytest.fixture
def fake(monkeypatch, client):
    import db
    gc = _gc()
    cal = _fake_gcal.install(monkeypatch)
    monkeypatch.setattr(db, "get_db", lambda *a, **k: _Conn())
    monkeypatch.setattr(gc, "_write_back", lambda *a, **k: True)
    monkeypatch.setattr(gc, "_get_setting", lambda key, default=None: dict(_SETTING))
    _SETTING.clear()
    _SETTING.update({"enabled": True})
    return cal


_SETTING = {}


@pytest.mark.parametrize("code", EXISTING)
def test_existing_event_respects_its_switch(fake, code):
    gc = _gc()
    _CALLS[code](gc)                                  # 預設（沒有 events）＝開 ⇒ 建立（升級後行為不變）
    assert fake.methods() == ["POST"], (code, fake.calls)
    fake.calls.clear()
    _SETTING["events"] = {code: False}
    _CALLS[code](gc)
    assert fake.calls == [], code                     # 關 ⇒ 不打 Google
    # 關掉別種不影響這一種
    _SETTING["events"] = {c: False for c in gc.EVENT_CODES if c != code}
    _CALLS[code](gc)
    assert fake.methods() == ["POST"], code


@pytest.mark.parametrize("code,field,clear", [("stage_due", "google_calendar_event_id", "due_date"),
                                              ("stage_done", "google_calendar_done_event_id", "done")])
def test_switch_off_keeps_existing_events(fake, monkeypatch, code, field, clear):
    """關閉後：清空到期日／取消勾選也不刪既有事件（開著時才會刪，現況行為）。"""
    gc = _gc()
    monkeypatch.setitem(_ROW, field, "evt-old")
    monkeypatch.setitem(_ROW, clear, "" if clear == "due_date" else 0)
    _SETTING["events"] = {code: False}
    _CALLS[code](gc)
    assert fake.calls == []
    _SETTING["events"] = {code: True}
    _CALLS[code](gc)
    assert fake.methods() == ["DELETE"]


# ── 通用推送：開關、合併 ────────────────────────────────────────────────────

@pytest.mark.parametrize("code", NEW)
def test_new_events_only_when_enabled(fake, code):
    gc = _gc()
    gc.push_event_for_module(code, "標題", "說明", "2031-02-03")
    assert fake.calls == []                           # 預設關
    _SETTING["events"] = {code: True}
    gc.push_event_for_module(code, "標題", "說明", "2031-02-03")
    assert fake.methods() == ["POST"]
    ev = list(fake.events.values())[0]
    assert ev["start"] == {"date": "2031-02-03"} and ev["summary"] == "標題"


def test_unknown_code_never_pushes(fake):
    _gc().push_event_for_module("nope", "t", "d")
    assert fake.calls == []


def test_same_key_same_day_merges_into_one_event(fake):
    gc = _gc()
    _SETTING["events"] = {"case_update": True}
    gc.push_event_for_module("case_update", "甲案案件更新", "[09:00] 第一則", "2031-03-01", merge_key="MQ-1")
    gc.push_event_for_module("case_update", "甲案案件更新", "[10:00] 第二則", "2031-03-01", merge_key="MQ-1")
    assert len(fake.events) == 1
    ev = list(fake.events.values())[0]
    assert ev["summary"] == "甲案案件更新"
    assert ev["description"] == "[09:00] 第一則\n\n[10:00] 第二則"
    # 隔天、或別的案件 ⇒ 另一個事件
    gc.push_event_for_module("case_update", "甲案案件更新", "[09:00] 隔天", "2031-03-02", merge_key="MQ-1")
    gc.push_event_for_module("case_update", "乙案案件更新", "[09:00] 乙", "2031-03-01", merge_key="MQ-2")
    assert len(fake.events) == 3
    # 同一個 key、不同事件種類不合併
    _SETTING["events"] = {"case_update": True, "dev_case_update": True}
    gc.push_event_for_module("dev_case_update", "甲案案件更新", "x", "2031-03-01", merge_key="MQ-1")
    assert len(fake.events) == 4


def test_merge_survives_restart_by_looking_up_google(fake):
    """合併靠 Google 事件上的 private extendedProperty 找回（不靠記憶體）：清掉行程內狀態後照樣合併。"""
    gc = _gc()
    _SETTING["events"] = {"case_update": True}
    gc.push_event_for_module("case_update", "甲", "一", "2031-03-01", merge_key="MQ-1")
    gc._merge_locks.clear()
    gc.push_event_for_module("case_update", "甲", "二", "2031-03-01", merge_key="MQ-1")
    assert len(fake.events) == 1 and list(fake.events.values())[0]["description"] == "一\n\n二"


def test_push_never_raises(fake, monkeypatch):
    gc = _gc()
    _SETTING["events"] = {"case_update": True}

    def boom(*a, **k):
        raise RuntimeError("Google API 錯誤 500")
    monkeypatch.setattr(gc, "_events_call", boom)
    monkeypatch.setattr(gc, "_notify_push_failure", lambda *a: None)
    gc.push_event_for_module("case_update", "t", "d", merge_key="k")
    gc.push_event_for_module("case_update", "t", "d")


# ── 設定端點：只限最高管理者、驗代碼、每個變更一筆稽核 ─────────────────────────

def _audits(action):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM audit_log WHERE action=? ORDER BY id", (action,)).fetchall()]
    finally:
        conn.close()


def test_only_superadmin_can_change_and_each_change_is_audited(client, make_user):
    admin = _hdr(client, make_user, "gct_admin", "admin")
    sa = _hdr(client, make_user, "gct_sa2", "superadmin")
    r = client.put("/api/settings/google-calendar", headers=admin, json={"events": {"case_update": True}})
    assert r.status_code == 403
    assert client.get("/api/settings/google-calendar", headers=admin).status_code == 403
    assert _gc().event_switches()["case_update"] is False

    r = client.put("/api/settings/google-calendar", headers=sa,
                   json={"events": {"case_update": True, "invoice_voucher": False, "stage_due": True}})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["changed"]) == ["case_update", "invoice_voucher"]      # stage_due 本來就開，不算變更
    sw = _gc().event_switches()
    assert sw["case_update"] is True and sw["invoice_voucher"] is False and sw["payment_request"] is True
    rows = _audits("settings.google_calendar.event_toggle")
    got = sorted((json.loads(x["detail"] or "{}")["event"], json.loads(x["detail"] or "{}")["to"]) for x in rows)
    assert got == [("case_update", True), ("invoice_voucher", False)]
    assert all(x["username"] == "gct_sa2" for x in rows)

    # 只改 OAuth 欄位 ⇒ 開關不動、不多記事件稽核
    r = client.put("/api/settings/google-calendar", headers=sa, json={"calendar_id": "x@group.calendar.google.com"})
    assert r.status_code == 200
    assert _gc().event_switches()["case_update"] is True
    assert len(_audits("settings.google_calendar.event_toggle")) == 2


@pytest.mark.parametrize("bad", [{"nope": True}, {"case_update": "true"}, {"case_update": 1}, ["case_update"]])
def test_put_rejects_unknown_codes_and_non_bool(client, make_user, bad):
    sa = _hdr(client, make_user, "gct_sa3", "superadmin")
    r = client.put("/api/settings/google-calendar", headers=sa, json={"events": bad})
    assert r.status_code == 400, r.text
    assert _gc().event_switches()["case_update"] is False


# ── 寫鎖守門：新呼叫點都在 commit 之後（全 repo 掃描＝tests/test_approval_no_freeze_2026_09_30.py） ─────

def test_write_txn_scan_catches_push_event_for_module():
    """反向控制：寫鎖區塊內呼叫 push_event_for_module 必須被掃到（名稱符合 push_event_* 規則）。"""
    import importlib.util
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("_wts", repo / "tools" / "platform" / "write_txn_scan.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert any(p.match("push_event_for_module") for p in m.DENY)
