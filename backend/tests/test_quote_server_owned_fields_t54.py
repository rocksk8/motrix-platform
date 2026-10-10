# -*- coding: utf-8 -*-
"""第 54 班：報價存檔路徑的伺服器自有欄位（單號、編輯紀錄、已結案利潤欄位）不採用用戶端的值。"""
import json

import pytest

import db


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def who(client, make_user):
    su, sp = make_user(username="pq_su", role="superadmin")
    ad, ap = make_user(username="pq_admin", role="admin")
    return _login(client, su, sp), _login(client, ad, ap)


def _q(**over):
    d = {"customerName": "探針客", "projectName": "探針案", "salesPerson": "", "quoteDate": "2026-10-11",
         "items": [{"type": "item", "qty": 1, "unitPrice": 100000, "amount": 100000, "cost": 60000}],
         "tot": {"subtotal": 100000, "pretax": 100000, "tax": 5000, "total": 105000, "totalCost": 60000, "inputVat": 3000,
                 "directProfit": 37000, "directMarginPct": 37.0, "adminCost": 10000, "charityDonation": 370, "totalIndirect": 10370,
                 "netProfit": 26630, "netMarginPct": 26.6}}
    d.update(over)
    return d


def _stored(no):
    cn = db.get_db()
    try:
        r = cn.execute("SELECT data_json, status, updated_at FROM quotations WHERE quote_no=?", (no,)).fetchone()
        return json.loads(r["data_json"]), r["status"], r["updated_at"]
    finally:
        cn.close()


def _mk(client, h):
    r = client.post("/api/quotations", json={"status": "草稿", "data": _q()}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["quote_no"]


def test_put_forces_quote_no_to_url_number(client, who):
    su, ad = who
    a, b = _mk(client, ad), _mk(client, ad)
    r = client.put("/api/quotations/%s" % a, json={"status": "草稿", "data": _q(quoteNo=b)}, headers=ad)
    assert r.status_code == 200, r.text
    assert _stored(a)[0].get("quoteNo") == a
    assert _stored(b)[0].get("quoteNo") in (b, None), "B 自己的單不受影響"
    assert client.get("/api/quotations/%s" % a, headers=ad).json()["data"]["quoteNo"] == a


def test_put_ignores_client_edit_history(client, who):
    su, ad = who
    a = _mk(client, ad)
    for i in range(2):
        client.put("/api/quotations/%s" % a, json={"status": "草稿", "data": _q(customerName="改%d" % i)}, headers=ad)
    real = _stored(a)[0].get("editHistory") or []
    assert len(real) >= 1
    forged = [{"rev": 1, "at": "2020-01-01T00:00:00", "by": "boss", "byDisplay": "老闆", "type": "quote_update"}]
    client.put("/api/quotations/%s" % a, json={"status": "草稿", "data": _q(customerName="偽造", editHistory=forged)}, headers=ad)
    h = _stored(a)[0].get("editHistory") or []
    assert all(x.get("by") != "boss" for x in h) and len(h) >= len(real)
    client.put("/api/quotations/%s" % a, json={"status": "草稿", "data": _q(customerName="清空", editHistory=[])}, headers=ad)
    assert len(_stored(a)[0].get("editHistory") or []) >= len(real), "清空編輯紀錄不可生效"


def _settled_unlock(client, who, tot_patch, items=None):
    su, ad = who
    a = _mk(client, ad)
    cn = db.get_db()
    cn.execute("UPDATE quotations SET status='已成案', deal_tag='已成案', settle_status='finalized' WHERE quote_no=?", (a,))
    cn.commit()
    cn.close()
    cn = db.get_db()
    try:
        dep = cn.execute("SELECT id FROM departments LIMIT 1").fetchone()
        if dep is None:
            cn.execute("INSERT INTO divisions (name, created_at) VALUES ('探針處', '2026-10-11')")
            dv = cn.execute("SELECT id FROM divisions LIMIT 1").fetchone()[0]
            cn.execute("INSERT INTO departments (division_id, name, created_at) VALUES (?, '探針部', '2026-10-11')", (dv,))
            dep = cn.execute("SELECT id FROM departments LIMIT 1").fetchone()
        cn.execute("UPDATE users SET department_id=? WHERE username IN ('pq_su','pq_admin')", (dep[0],))
        cn.execute("UPDATE departments SET manager_user_id=(SELECT id FROM users WHERE username='pq_admin') WHERE id=?", (dep[0],))
        cn.commit()
    finally:
        cn.close()
    body = _q()
    if items:
        body["items"] = items
    body["tot"] = dict(body["tot"], **tot_patch)
    body["_isUnlockEdit"] = True
    r = client.put("/api/quotations/%s" % a, json={"status": "已成案", "data": body}, headers=su)
    assert r.status_code == 200, r.text
    return _stored(a)[0]["tot"]


def test_unlock_edit_on_settled_quote_keeps_db_profit_fields(client, who):
    keys = ("netProfit", "adminCost", "netMarginPct", "charityDonation", "totalIndirect")
    forged = dict(netProfit=999999, adminCost=1, netMarginPct=99.9, charityDonation=0, totalIndirect=1)
    t = _settled_unlock(client, who, forged)
    assert t["netProfit"] == 26630 and t["adminCost"] == 10000 and t["charityDonation"] == 370 and t["totalIndirect"] == 10370
    assert t["netMarginPct"] == 26.6


def test_unlock_edit_price_change_keeps_profit_until_resettled(client, who):
    """已知取捨（PM 裁示維持）：改價後利潤欄位維持舊值；價格欄位本身可改。"""
    items = [{"type": "item", "qty": 1, "unitPrice": 200000, "amount": 200000, "cost": 60000}]
    t = _settled_unlock(client, who, dict(netProfit=999999, pretax=200000), items=items)
    assert t["pretax"] == 200000 and t["netProfit"] == 26630


def test_create_discards_client_edit_history(client, who):
    su, ad = who
    forged = [{"rev": 1, "at": "2020-01-01T00:00:00", "by": "boss", "byDisplay": "老闆", "type": "quote_update"}]
    r = client.post("/api/quotations", json={"status": "草稿", "data": _q(editHistory=forged)}, headers=ad)
    assert r.status_code == 201, r.text
    assert (_stored(r.json()["quote_no"])[0].get("editHistory") or []) == []
