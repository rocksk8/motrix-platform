# -*- coding: utf-8 -*-
"""行事曆「支出付款」（2026-09-30 使用者裁示，預設關）：出納登錄請款（案件額外支出）付款 ⇒ 以付款日建立事件；
名目／金額取 IP-100 提供者回傳（出納不讀別的模組的表）。勞報單付款走自己的端點，不在此列。Google 用假行事曆。"""
from tests import _fake_gcal
from tests._requires import requires_module

pytestmark = requires_module("case", "請款的提供者是 M01 案件額外支出")
NO = "MQ-CALEXP-001"


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur
    finally:
        conn.close()


def _seed():
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "支出客", "支出專案", 1, 1, "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "", "[]"))
    cur = _x("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, expense_date,"
             " files_json, created_by, created_by_name, payer_name, created_at, updated_at, status, paid_date)"
             " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (NO, "材料", "線材", 1, "", 1200, 1200, "2031-05-01", "[]", "ce_eng", "工程師甲", "材料行", "2031-05-01",
              "2031-05-01", "已核准", ""))
    return str(cur.lastrowid)


def _setup(client, make_user, monkeypatch, events):
    from modules.arap.api import cashier
    cal = _fake_gcal.install(monkeypatch)
    _fake_gcal.sync_spawn(monkeypatch, cashier)
    _fake_gcal.set_events(events=events)
    u, p = make_user(username="ce_cash", role="user", modules=["cashier"])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    return cal, {"Authorization": "Bearer " + r.json()["token"]}, _seed()


def _pay(client, h, key):
    r = client.post("/api/cashier/pending-payables/case/%s/pay" % key, headers=h, json={"paidDate": "2031-05-09"})
    assert r.status_code == 200, r.text
    return r.json()


def test_off_by_default(client, make_user, monkeypatch):
    cal, h, key = _setup(client, make_user, monkeypatch, None)
    _pay(client, h, key)
    assert cal.calls == []


def test_on_creates_event_on_paid_date(client, make_user, monkeypatch):
    cal, h, key = _setup(client, make_user, monkeypatch, {"expense_payout": True})
    res = _pay(client, h, key)
    assert res["title"] == "材料｜線材" and res["payee"] == "材料行"
    assert cal.methods() == ["POST"]
    ev = list(cal.events.values())[0]
    assert ev["summary"] == "支出付款 — 材料｜線材"
    assert ev["start"] == {"date": "2031-05-09"}
    assert "金額：NT$ 1,200" in ev["description"] and NO in ev["description"]
