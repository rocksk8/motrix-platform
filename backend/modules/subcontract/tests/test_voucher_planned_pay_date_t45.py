# -*- coding: utf-8 -*-
"""第 45 班 S4：承攬商匯款預定付款日（subcontract v6）：欄位／migration、建立時選填、IP-14 形狀、出納端點（權限、已匯款、未核准）、與合約應付款日分開。"""
import sqlite3

import pytest

from tests._requires import requires_module

pytestmark = [requires_module("case", "用案件編號建派發／匯款單"), requires_module("arap", "出納端點在 M05")]

Q = "MQ-VPP-001"
_N = __import__("itertools").count(1)


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _voucher(client, h, planned=None, payable="2031-08-01", approve=True):
    r = client.post("/api/vendor-contractors", headers=h, json={"name": "廠商VPP%d" % next(_N), "data": {}})
    assert r.status_code == 201, r.text
    body = {"quote_no": Q, "vendor_id": r.json()["id"], "status": "completed", "payable_date": payable,
            "items_json": [{"description": "測試品項", "qty": 1, "unit": "式", "unitPrice": 10000, "amount": 10000}]}
    r = client.post("/api/contractor-dispatches", headers=h, json=body)
    assert r.status_code == 201, r.text
    cv = {"dispatch_id": r.json()["id"]}
    if planned is not None:
        cv["planned_pay_date"] = planned
    r = client.post("/api/contractor-vouchers", headers=h, json=cv)
    return r, (r.json().get("voucher_no") if r.status_code == 201 else None)


def _approve(no):
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no=?", (no,))
        c.commit()
    finally:
        c.close()


def _col(no, name="planned_pay_date"):
    import db
    c = db.get_db()
    try:
        return c.execute("SELECT %s FROM contractor_payment_vouchers WHERE voucher_no=?" % name, (no,)).fetchone()[0]
    finally:
        c.close()


@pytest.fixture
def world(client, make_user):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
                  " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (Q, "已送出", "客", "案", 1, 1, "{}", "2031-01-01T00:00:00", "2031-01-01T00:00:00", "已成案", "", "[]"))
        c.commit()
    finally:
        c.close()
    sa, sp = make_user(username="vpp_sa", role="superadmin")
    fin, fp = make_user(username="vpp_fin", role="finance")
    usr, up = make_user(username="vpp_usr", role="user")
    return {"sa": _login(client, sa, sp), "fin": _login(client, fin, fp), "usr": _login(client, usr, up)}


def _url(no):
    return "/api/cashier/payable-queue/%s/planned-pay-date" % no


def test_migration_adds_column_idempotently_and_reports_missing_table():
    import importlib
    m = importlib.import_module("modules.subcontract.migrations.0006_voucher_planned_pay_date")
    c = sqlite3.connect(":memory:")
    assert "不存在" in m.up(c)
    c.execute("CREATE TABLE contractor_payment_vouchers (id INTEGER PRIMARY KEY, voucher_no TEXT)")
    c.execute("INSERT INTO contractor_payment_vouchers (voucher_no) VALUES ('舊')")
    assert m.up(c) is None and m.up(c) is None
    assert c.execute("SELECT planned_pay_date FROM contractor_payment_vouchers").fetchone()[0] == ""
    c.execute("INSERT INTO contractor_payment_vouchers (voucher_no) VALUES ('舊程式不帶欄位')")


def test_registered_migration_and_real_table_has_column(client):
    import db
    c = db.get_db()
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(contractor_payment_vouchers)")}
    finally:
        c.close()
    assert "planned_pay_date" in cols, "之後任何重建 contractor_payment_vouchers 的遷移都必須帶這一欄"


def test_create_with_and_without_planned_and_it_is_separate_from_payable_date(client, world):
    r, no = _voucher(client, world["sa"], planned="2031-07-20", payable="2031-08-01")
    assert r.status_code == 201, r.text
    assert _col(no) == "2031-07-20"
    snap = __import__("json").loads(_col(no, "snapshot_json"))
    assert snap["payableDate"] == "2031-08-01" and "plannedPayDate" not in snap and "planned_pay_date" not in snap, "合約應付款日在快照，預定日不混進去"
    r2, no2 = _voucher(client, world["sa"], payable="2031-08-02")
    assert r2.status_code == 201 and _col(no2) == "", "沒帶＝空白，不自動複製應付款日"
    r3, _ = _voucher(client, world["sa"], planned="2031-02-30")
    assert r3.status_code == 400


def test_queue_shape_and_cashier_endpoint(client, world):
    _, no = _voucher(client, world["sa"], payable="2031-08-01")
    _approve(no)
    q = client.get("/api/cashier/payable-queue", headers=world["fin"]).json()
    row = [v for v in q if v["voucherNo"] == no][0]
    assert row["plannedPayDate"] == "" and row["payableDate"] == "2031-08-01"
    r = client.patch(_url(no), json={"plannedPayDate": "2031-07-25"}, headers=world["fin"])
    assert r.status_code == 200 and _col(no) == "2031-07-25", r.text
    q = client.get("/api/cashier/payable-queue", headers=world["fin"]).json()
    assert [v["plannedPayDate"] for v in q if v["voucherNo"] == no] == ["2031-07-25"]
    assert client.patch(_url(no), json={"plannedPayDate": ""}, headers=world["fin"]).status_code == 200 and _col(no) == ""


def test_permissions_validation_and_state_rules(client, world):
    _, no = _voucher(client, world["sa"], planned="2031-07-20")
    h = world["fin"]
    assert client.patch(_url(no), json={"plannedPayDate": "2031-07-25"}, headers=h).status_code == 404        # 未核准不在待付款清單
    _approve(no)
    assert client.patch(_url(no), json={"plannedPayDate": "2031-07-25"}, headers=world["usr"]).status_code == 403
    assert client.patch(_url(no), json={"plannedPayDate": "2031-07-25"}).status_code in (401, 403)
    assert _col(no) == "2031-07-20"
    for bad in ("2031/07/25", "2031-02-30"):
        assert client.patch(_url(no), json={"plannedPayDate": bad}, headers=h).status_code == 400
    assert client.patch(_url(no), json={}, headers=h).status_code == 400
    assert client.patch(_url("NOPE-1"), json={"plannedPayDate": "2031-07-25"}, headers=h).status_code == 404
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE contractor_payment_vouchers SET is_paid=1 WHERE voucher_no=?", (no,))
        c.commit()
    finally:
        c.close()
    r = client.patch(_url(no), json={"plannedPayDate": "2031-07-25"}, headers=h)
    assert r.status_code == 409 and "歷史" in r.json()["detail"] and _col(no) == "2031-07-20"
