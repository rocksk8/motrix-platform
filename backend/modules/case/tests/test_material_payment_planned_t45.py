# -*- coding: utf-8 -*-
"""第 45 班 S3：叫料匯款申請的預定付款日（case v8）：申請人建立／草稿期修改、IP-100 項目帶出、出納端點、付款後與結清後的規則。"""
import json

import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "叫料匯款申請在 M01")

NO = "MQ-MPP-001"
ITEM = "L1"
BODY = {"bankCode": "812", "bankName": "台新", "bankAccountName": "甲供應商有限公司", "bankAccountNumber": "28881234567890"}
_MAKE_USER_DEFAULT_ROLE = "superadmin"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def world(client, make_user):
    sa, sp = make_user(username="mpp_sa", role="superadmin")
    fin, fp = make_user(username="mpp_fin", role="finance")
    order = {"itemId": ITEM, "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 5000, "totalPrice": 10000,
             "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": ""}
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "匯款客", "匯款專案", 1, 1, json.dumps({"dealTag": "已成案", "caseRecord": {"materialOrders": [order]}}),
        "2031-01-01T00:00:00", "2031-01-01T00:00:00", "已成案", "", "[]"))
    _x("INSERT INTO case_material_approvals (quote_no, item_id, doc_code, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
       (NO, ITEM, "MO-20310101-0001", "已核准", "2031-01-01", "2031-01-01"))
    _x("INSERT INTO suppliers (name, code, created_at, updated_at) VALUES (?,?,?,?)", ("甲供應商", "S-001", "2031-01-01", "2031-01-01"))
    sid = _q("SELECT id FROM suppliers WHERE name='甲供應商'")[0]["id"]
    _x("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
       ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
    return {"sa": _login(client, sa, sp), "fin": _login(client, fin, fp), "sid": sid}


def _create(client, w, **kw):
    body = dict(BODY, supplierId=w["sid"], payeeNoticeAcked=True, amount=6000, **kw)
    return client.post("/api/quotations/%s/material-orders/%s/payments" % (NO, ITEM), json=body, headers=w["sa"])


def _approve(client, w, pid):
    s = client.post("/api/material-payments/%d/submit" % pid, headers=w["sa"])
    assert s.status_code == 200 and s.json()["status"] == "已核准", s.text


def _planned(pid):
    return _q("SELECT planned_pay_date FROM case_material_payments WHERE id=?", (pid,))[0][0]


def _url(pid):
    return "/api/cashier/pending-payables/case_material/%s/planned-pay-date" % pid


def test_create_with_planned_date_and_public_shape(client, world):
    r = _create(client, world, plannedPayDate="2031-06-10")
    assert r.status_code == 200, r.text
    p = r.json()["payment"]
    assert p["plannedPayDate"] == "2031-06-10" and _planned(p["id"]) == "2031-06-10"
    lst = client.get("/api/quotations/%s/material-payments" % NO, headers=world["sa"]).json()
    assert lst["orders"][ITEM]["payments"][0]["plannedPayDate"] == "2031-06-10"


def test_create_without_date_and_bad_date(client, world):
    r = _create(client, world)
    assert r.status_code == 200 and r.json()["payment"]["plannedPayDate"] == ""
    pid = r.json()["payment"]["id"]
    _x("UPDATE case_material_payments SET status='作廢' WHERE id=?", (pid,))
    bad = _create(client, world, plannedPayDate="2031-02-30")
    assert bad.status_code == 400 and "預定付款日" in str(bad.json())


def test_draft_edit_keeps_or_changes_date_and_approved_is_locked(client, world):
    pid = _create(client, world, plannedPayDate="2031-06-10").json()["payment"]["id"]
    assert client.patch("/api/material-payments/%d" % pid, json={"amount": 5000}, headers=world["sa"]).status_code == 200
    assert _planned(pid) == "2031-06-10", "沒帶 plannedPayDate ⇒ 保留"
    assert client.patch("/api/material-payments/%d" % pid, json={"plannedPayDate": "2031-06-20"}, headers=world["sa"]).status_code == 200
    assert _planned(pid) == "2031-06-20"
    assert client.patch("/api/material-payments/%d" % pid, json={"plannedPayDate": ""}, headers=world["sa"]).status_code == 200
    assert _planned(pid) == ""
    _approve(client, world, pid)
    assert client.patch("/api/material-payments/%d" % pid, json={"plannedPayDate": "2031-07-01"}, headers=world["sa"]).status_code == 409
    assert _planned(pid) == ""


def test_pending_item_carries_date_and_cashier_endpoint_edits_it(client, world):
    pid = _create(client, world, plannedPayDate="2031-06-10").json()["payment"]["id"]
    _approve(client, world, pid)
    items = client.get("/api/cashier/pending-payables", headers=world["fin"]).json()["items"]
    mine = [i for i in items if i["source"] == "case_material" and i["key"] == str(pid)]
    assert len(mine) == 1 and mine[0]["plannedPayDate"] == "2031-06-10"
    r = client.patch(_url(pid), json={"plannedPayDate": "2031-06-30"}, headers=world["fin"])
    assert r.status_code == 200 and _planned(pid) == "2031-06-30", r.text
    assert client.patch(_url(pid), json={"plannedPayDate": ""}, headers=world["fin"]).status_code == 200 and _planned(pid) == ""


def test_cashier_endpoint_rejects_draft_nonfinance_and_settled(client, world, make_user):
    pid = _create(client, world, plannedPayDate="2031-06-10").json()["payment"]["id"]
    assert client.patch(_url(pid), json={"plannedPayDate": "2031-06-30"}, headers=world["fin"]).status_code == 404     # 草稿不在待付款清單
    _approve(client, world, pid)
    u, p = make_user(username="mpp_user", role="user")
    assert client.patch(_url(pid), json={"plannedPayDate": "2031-06-30"}, headers=_login(client, u, p)).status_code == 403
    assert _planned(pid) == "2031-06-10"
    pay = client.post("/api/cashier/pending-payables/case_material/%s/pay" % pid, json={"paidDate": "2031-06-11", "actualAmount": 6000}, headers=world["fin"])
    assert pay.status_code == 200, pay.text                                                                              # 結清
    r = client.patch(_url(pid), json={"plannedPayDate": "2031-06-30"}, headers=world["fin"])
    assert r.status_code in (404, 409) and _planned(pid) == "2031-06-10", "結清後預定日保留為歷史"


def test_partial_payment_keeps_date_editable(client, world):
    pid = _create(client, world, plannedPayDate="2031-06-10").json()["payment"]["id"]
    _approve(client, world, pid)
    pay = client.post("/api/cashier/pending-payables/case_material/%s/pay" % pid, json={"paidDate": "2031-06-11", "actualAmount": 2500}, headers=world["fin"])
    assert pay.status_code == 200, pay.text
    assert client.patch(_url(pid), json={"plannedPayDate": "2031-07-10"}, headers=world["fin"]).status_code == 200      # 分次付款：改下一次預定日
    assert _planned(pid) == "2031-07-10"
