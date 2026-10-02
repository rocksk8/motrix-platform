# -*- coding: utf-8 -*-
"""MONEY-FLOWS §9 L12（更換已登錄發票號碼要權限＋稽核）、L11（已付款額外支出經變更申請改金額 ⇒ 強制重走差額審核）。

L12 下游：已過帳 E01 的鍵＝案件::發票號碼，換號碼＝舊號 orphan＋新號新草稿；所以「更換」要 admin＋／出納／財務，第一次登錄維持開放。
L11 下游：已付款後金額被改而不回審核 ⇒ E11b 用新 total／舊 remit_actual；改成沿用既有差額審核（`remit_review='pending'`）。"""
import json
from datetime import datetime

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "打 M01（案件）的端點")

Q = "MQ-MG-001"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed(invoice_no):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, deal_tag)"
                  " VALUES (?,?,?,?,?,?,?,?)",
                  (Q, "已送出", "客戶", "專案", json.dumps({"caseRecord": {"payment": {"items": [
                      {"id": "it1", "type": "訂金款", "pct": 30, "amount": 30000, "received": False, "invoiceNo": invoice_no}]}}}),
                   "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        c.commit()
    finally:
        c.close()


def _inv():
    import db
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (Q,)).fetchone()["data_json"])
        return d["caseRecord"]["payment"]["items"][0]["invoiceNo"]
    finally:
        c.close()


def _audits():
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM audit_log WHERE action='payment.invoice_no_change'").fetchall()]
    finally:
        c.close()


@pytest.mark.parametrize("role,mods,allowed", [("sales", [], False), ("viewer", [], False), ("sales", ["cashier"], True),
                                                ("sales", ["finance"], True), ("admin", None, True), ("superadmin", [], True)])
def test_changing_an_existing_invoice_number_needs_permission(client, make_user, role, mods, allowed):
    """**反向控制**：拿掉 `_invoice_no_change_allowed` 檢查 ⇒ 不允許的角色那幾列紅。"""
    _seed("AB12345678")
    u, p = make_user(username="mg_%s_%s" % (role, "_".join(mods or ["none"])), role=role, modules=mods)
    h = _login(client, u, p)
    r = client.patch("/api/quotations/%s/payment/0" % Q, headers=h, json={"invoiceNo": "CD87654321"})
    if allowed:
        assert r.status_code == 200, r.text
        assert _inv() == "CD87654321" and len(_audits()) == 1 and "AB12345678" in _audits()[0]["target_label"]
    else:
        assert r.status_code == 403, r.text
        assert _inv() == "AB12345678" and _audits() == []


def test_first_registration_and_unchanged_number_stay_open(client, make_user):
    _seed("")
    u, p = make_user(username="mg_plain", role="sales", modules=[])
    h = _login(client, u, p)
    assert client.patch("/api/quotations/%s/payment/0" % Q, headers=h, json={"invoiceNo": "AB12345678"}).status_code == 200
    assert _inv() == "AB12345678" and _audits() == []                                   # 第一次登錄：不算更換、不記更換稽核
    assert client.patch("/api/quotations/%s/payment/0" % Q, headers=h, json={"invoiceNo": "AB12345678"}).status_code == 200
    assert client.patch("/api/quotations/%s/payment/0" % Q, headers=h, json={"invoiceNo": "CD87654321"}).status_code == 403


def test_case_record_bulk_save_denied_for_a_plain_case_member(client, make_user):
    """**反向控制（G2）**：案件成員（業務本人、沒有 cashier／finance）用整包存更換已登錄號碼 ⇒ 403、什麼都沒寫；
    拿掉整包存路徑的檢查 ⇒ 這題紅。"""
    import db
    u, p = make_user(username="mg_member", role="sales", modules=[])
    h = _login(client, u, p)
    _seed("AB12345678")
    c = db.get_db()
    try:
        uid = c.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()["id"]
        c.execute("UPDATE quotations SET sales_person_id=?, sales_person=? WHERE quote_no=?", (uid, u, Q))
        c.commit()
    finally:
        c.close()
    item = {"id": "it1", "type": "訂金款", "pct": 30, "amount": 30000, "received": False, "invoiceNo": "CD87654321"}
    r = client.patch("/api/quotations/%s/case-record" % Q, headers=h, json={"case_record": {"payment": {"items": [item]}}})
    assert r.status_code == 403, r.text
    assert _inv() == "AB12345678" and _audits() == []


def test_case_record_bulk_save_path_has_the_same_rule(client, make_user):
    """整包存（案件管理財務 Tab 實際走的路徑）也一樣：非授權者更換已登錄號碼 ⇒ 403，什麼都沒寫。"""
    _seed("AB12345678")
    u, p = make_user(username="mg_bulk", role="admin", modules=None)            # admin 是案件成員，可通過成員檢查
    ha = _login(client, u, p)
    item = {"id": "it1", "type": "訂金款", "pct": 30, "amount": 30000, "received": False, "invoiceNo": "CD87654321"}
    ok = client.patch("/api/quotations/%s/case-record" % Q, headers=ha, json={"case_record": {"payment": {"items": [item]}}})
    assert ok.status_code == 200, ok.text
    assert _inv() == "CD87654321" and len(_audits()) == 1


# ── L11 ────────────────────────────────────────────────────────────────────

def _expense(paid, actual, total=1000.0):
    import db
    c = db.get_db()
    try:
        _seed("")
        cur = c.execute(
            "INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, status, expense_date,"
            " paid_date, remit_actual, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (Q, "其他", "測試", 1, "式", total, total, "已核准", "2026-09-01", "2026-09-05" if paid else "", actual,
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _apply(exp_id, new_unit_cost):
    import db
    from modules.case.api import case_extra_expenses as X
    c = db.get_db()
    try:
        row = X._load(c, Q, exp_id)
        X._apply_change(c, row, {"description": "測試", "qty": 1, "unit": "式", "unitCost": new_unit_cost, "category": "其他",
                                 "expenseDate": "2026-09-01"}, "tester", datetime.now().isoformat())
        c.commit()
        return dict(c.execute("SELECT remit_review, remit_review_note, total_cost FROM case_extra_expenses WHERE id=?", (exp_id,)).fetchone())
    finally:
        c.close()


def test_paid_expense_amount_change_forces_remit_re_review(client):
    """**反向控制**：拿掉 `_apply_change` 結尾那段 ⇒ 這題紅（已付款金額被悄悄改掉）。"""
    eid = _expense(paid=True, actual=1000.0)
    got = _apply(eid, 1500)
    assert got["total_cost"] == 1500 and got["remit_review"] == "pending" and "1500" in got["remit_review_note"]


def test_unpaid_or_same_amount_change_is_not_forced(client):
    assert _apply(_expense(paid=False, actual=None), 1500)["remit_review"] in ("", None)       # 未付款：照舊
    assert _apply(_expense(paid=True, actual=1000.0), 1000)["remit_review"] in ("", None)       # 金額沒變（只改其他欄位）：照舊
