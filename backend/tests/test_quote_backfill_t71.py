# -*- coding: utf-8 -*-
"""補登歷史報價單 T71：D1（caseRecord 為 null 時新增階段 500）、自動關閉排程。真實使用者 HTTP。"""
import json
from datetime import datetime, timedelta

import pytest

import db


def _login(client, make_user, name, role="superadmin"):
    u, p = make_user(name, "Lay-Pass-123", role=role)[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@pytest.fixture
def boss(client, make_user):
    return _login(client, make_user, "t71_boss")


@pytest.fixture
def flag_on():
    from helpers import settings_registry as SR

    def _set(**vals):
        conn = db.get_db()
        try:
            SR.publish("quote_backfill", dict({"enabled": 1, "auto_off_hours": 24}, **vals), reason="測試", user="t71_test", conn=conn)
            conn.commit()
            SR.invalidate("quote_backfill")
        finally:
            conn.close()
    _set()
    yield _set
    _set(enabled=0, auto_off_hours=24)


def _data_json(no):
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
    finally:
        c.close()


@pytest.mark.parametrize("variant", ["null", "absent", "list"])
def test_backfill_then_add_stage_works_whatever_the_client_sent_for_caseRecord(client, boss, flag_on, variant):
    """D1：畫面新增頁送 caseRecord:null ⇒ 補登單存成 null ⇒ 新增階段曾 500。"""
    d = {"customerName": "D1 客戶", "items": [], "quoteDate": "2026-07-15"}
    if variant == "null":
        d["caseRecord"] = None
    elif variant == "list":
        d["caseRecord"] = []
    r = client.post("/api/quotations/historical", headers=boss, json={"data": d, "reason": "D1 補登測試案件"})
    assert r.status_code == 201, r.text
    no = r.json()["quote_no"]
    assert isinstance(_data_json(no)["caseRecord"], dict), "補登建立時就把 caseRecord 補成 dict"
    s = client.post("/api/quotations/%s/stages" % no, headers=boss, json={"label": "施工"})
    assert s.status_code in (200, 201), s.text
    assert [x["label"] for x in _data_json(no)["caseRecord"]["stages"]] == ["施工"]


def test_add_stage_tolerates_a_null_caseRecord_already_in_the_database(client, boss):
    """舊資料／其他路徑留下的 caseRecord:null 也不可讓新增階段 500（不只補登單）。"""
    r = client.post("/api/quotations", headers=boss, json={"status": "草稿", "data": {"customerName": "舊資料", "items": []}})
    assert r.status_code in (200, 201), r.text
    no = r.json()["quote_no"]
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
        d["caseRecord"] = None
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), no))
        c.commit()
    finally:
        c.close()
    s = client.post("/api/quotations/%s/stages" % no, headers=boss, json={"label": "A"})
    assert s.status_code in (200, 201), s.text


def _backfilled_with_null_case_record(client, boss):
    r = client.post("/api/quotations/historical", headers=boss, json={
        "data": {"customerName": "D1 全端點", "items": [], "quoteDate": "2026-07-15", "caseRecord": None}, "reason": "D1 全端點補登測試"})
    assert r.status_code == 201, r.text
    no = r.json()["quote_no"]
    c = db.get_db()
    try:                                                       # 模擬「畫面建立、之後被別條路徑寫成 null」：直接把 caseRecord 改回 null（最壞情形）
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
        d["caseRecord"] = None
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), no))
        c.commit()
    finally:
        c.close()
    return no


STAGE_OPS = [
    # (名稱, 方法, 路徑樣板, body, 成功狀態)
    ("add-stage", "post", "/api/quotations/{no}/stages", {"label": "新階段"}, (200, 201)),
    ("update-stage", "put", "/api/quotations/{no}/stages/{s1}", {"label": "改名"}, (200,)),
    ("reorder", "patch", "/api/quotations/{no}/stages/reorder", "REORDER", (200,)),
    ("assignee-add", "post", "/api/quotations/{no}/stages/{s1}/assignees", {"username": "t71_boss"}, (200, 201)),
    ("assignee-remove", "delete", "/api/quotations/{no}/stages/{s1}/assignees/t71_boss", None, (200,)),
    ("depends-on", "post", "/api/quotations/{no}/stages/{s1}/depends-on/{s2}", None, (200, 201)),
    ("visit-add", "post", "/api/quotations/{no}/stages/{s1}/visits", {"visitDate": "2026-07-20", "visitPeople": "2", "note": "n"}, (200, 201)),
    ("delete-stage", "delete", "/api/quotations/{no}/stages/{s2}", None, (200,)),
]


@pytest.mark.parametrize("op", STAGE_OPS, ids=[o[0] for o in STAGE_OPS])
def test_every_stage_changing_endpoint_works_on_a_backfilled_quote_with_null_case_record(client, boss, flag_on, op):
    """稽核 8f：_sync_stages_to_json 是 17 個階段寫入端點共用的尾巴；補登單的 caseRecord 為 null 時全部會 500。"""
    name, method, path, body, ok = op
    no = _backfilled_with_null_case_record(client, boss)
    s1 = client.post("/api/quotations/%s/stages" % no, headers=boss, json={"label": "一"})
    assert s1.status_code in (200, 201), s1.text
    s2 = client.post("/api/quotations/%s/stages" % no, headers=boss, json={"label": "二"})
    assert s2.status_code in (200, 201), s2.text
    ids = {"s1": s1.json()["id"], "s2": s2.json()["id"]}
    if body == "REORDER":
        body = {"order": [ids["s2"], ids["s1"]]}
    # 再弄回 null：前面的新增階段會把它補成 dict，這裡要測的是「每個端點自己遇到 null」
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
        d["caseRecord"] = None
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), no))
        c.commit()
    finally:
        c.close()
    r = getattr(client, method)(path.format(no=no, **ids), headers=boss, **({"json": body} if body is not None else {}))
    assert r.status_code in ok, "%s → %s %s" % (name, r.status_code, r.text[:200])
    assert isinstance(_data_json(no)["caseRecord"], dict)


# ── 自動關閉排程：真的把設定翻回關並留紀錄 ───────────────────────────────────
def _enabled():
    from helpers import settings_registry as SR
    SR.invalidate("quote_backfill")
    return int(SR.get("quote_backfill", "enabled"))


def _audit_rows():
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM audit_log WHERE action LIKE 'settings.quote_backfill%' ORDER BY id").fetchall()]
    finally:
        c.close()


def test_daily_expiry_really_turns_the_flag_off_and_leaves_a_trail(client, boss, flag_on, monkeypatch):
    from modules.case.api import quotations as Q
    assert Q.expire_backfill_if_due() is False and _enabled() == 1, "未過期不動"
    before = len(_audit_rows())
    monkeypatch.setattr(Q, "_backfill_now", lambda: datetime.now() + timedelta(hours=25))
    assert Q.expire_backfill_if_due() is True
    assert _enabled() == 0, "設定值真的翻回關（不是只在讀取時算出關）"
    assert len(_audit_rows()) > before, "稽核有留下紀錄"
    from helpers import config_ledger as L
    c = db.get_db()
    try:
        rows = L.history(c, "setting:quote_backfill", "quote_backfill", limit=5)
    finally:
        c.close()
    assert any(r["field"] == "enabled" and r["new"] in (0, "0", False) and "自動關閉" in (r.get("reason") or r.get("note") or "") for r in rows), rows[:2]
    assert Q.expire_backfill_if_due() is False, "已關閉就不再重複寫紀錄"
    j = client.get("/api/quotations/historical/config", headers=boss).json()
    assert j["available"] is False and j.get("auto_off") is False


def test_expiry_never_fires_when_hours_is_zero(client, boss, flag_on, monkeypatch):
    from modules.case.api import quotations as Q
    flag_on(auto_off_hours=0)
    monkeypatch.setattr(Q, "_backfill_now", lambda: datetime.now() + timedelta(days=400))
    assert Q.expire_backfill_if_due() is False and _enabled() == 1


def test_daily_check_provider_runs_the_expiry(client, boss, flag_on, monkeypatch):
    """排程接線：case 的 daily.check（case_deadlines.run_daily_checks）會呼叫自動關閉；其他每日檢查換成空函式免得寄信。"""
    from modules.case import case_deadlines as CD
    from modules.case.api import quotations as Q
    for n in ("_check_warranty_expiry", "_check_case_stage_deadline", "_check_case_project_timeline_deadline",
              "_check_project_deadline", "_sync_warranty_calendar", "_sync_project_end_calendar"):
        monkeypatch.setattr(CD, n, lambda *a, **k: None)
    monkeypatch.setattr(CD.payable_reminders, "run", lambda *a, **k: None)
    monkeypatch.setattr(Q, "_backfill_now", lambda: datetime.now() + timedelta(hours=25))
    CD.run_daily_checks("daily")
    assert _enabled() == 0


def test_material_orders_get_works_on_a_backfilled_quote_with_null_case_record(client, boss, flag_on):
    """稽核 S1：GET /api/quotations/{no}/material-orders 在 caseRecord 為 null 時曾 500。"""
    no = _backfilled_with_null_case_record(client, boss)
    assert _data_json(no)["caseRecord"] is None
    r = client.get("/api/quotations/%s/material-orders" % no, headers=boss)
    assert r.status_code == 200, r.text
    assert r.json()["materialOrders"] == []


def test_daily_checks_run_the_expiry_before_everything_else(client, boss, flag_on, monkeypatch):
    """後面的檢查出例外也不能讓自動關閉被跳過：它排在最前面。"""
    from modules.case import case_deadlines as CD
    from modules.case.api import quotations as Q

    def boom(*a, **k):
        raise RuntimeError("後面的檢查壞了")
    for n in ("_check_warranty_expiry", "_check_case_stage_deadline"):
        monkeypatch.setattr(CD, n, boom)
    monkeypatch.setattr(Q, "_backfill_now", lambda: datetime.now() + timedelta(hours=25))
    with pytest.raises(RuntimeError):
        CD.run_daily_checks("daily")
    assert _enabled() == 0
