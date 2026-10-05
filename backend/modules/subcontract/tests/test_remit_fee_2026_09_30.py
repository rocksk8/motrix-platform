"""W1（2026-09-30）：承攬商匯款單標記已匯款——實付金額、手續費（公司自付）、差額待審核、核可／退回、報表支出、T100、案件成本。

契約：`modules/subcontract/remit.py`、IP-102 `remit.reviews`（出納頁 `/api/cashier/remit-reviews`）、IP-9 `expense.entries`。"""
import json

import pytest

from modules.subcontract.tests.test_contractor_voucher_paid_date_2026_08_31 import (
    _auth, _login, _make_approved_voucher)
from modules.subcontract import remit


_MAKE_USER_DEFAULT_ROLE = "superadmin"      # 第42班：財務／出納不再有 admin 直通；舊題的「預設 admin 操作者」改用 superadmin（見 conftest.make_user）


def _pay(client, token, vno, **body):
    return client.post(f"/api/contractor-vouchers/{vno}/paid-toggle", headers=_auth(token),
                       json={"action": "pay", "paid_at": "2026-09-20", **body})


def _row(vno):
    import db
    conn = db.get_db()
    try:
        return dict(conn.execute("SELECT * FROM contractor_payment_vouchers WHERE voucher_no=?", (vno,)).fetchone())
    finally:
        conn.close()


def _payable(vno):
    return float(json.loads(_row(vno)["snapshot_json"])["grandTotal"])


# ── 純函式 ────────────────────────────────────────────────────────────────

def test_parse_remit_rules():
    p = remit.parse_remit({}, 1000)
    assert (p["actual"], p["fee"], p["review"]) == (1000, 0, "")                   # 不帶＝等於應付
    p = remit.parse_remit({"actualAmount": 985, "hasFee": True, "fee": 15}, 1000)
    assert (p["actual"], p["fee"], p["diff"], p["review"]) == (985, 15, -15, "pending")
    # 手續費不參與比對：實付＝應付、有手續費 ⇒ 不送審
    assert remit.parse_remit({"hasFee": True, "fee": 15}, 1000)["review"] == ""
    # 沒勾有手續費 ⇒ 帶了金額也當 0
    assert remit.parse_remit({"fee": 15}, 1000)["fee"] == 0
    # 實付大於應付也算差額
    assert remit.parse_remit({"actualAmount": 1001}, 1000)["review"] == "pending"
    for bad in ({"actualAmount": 0}, {"actualAmount": -5}, {"actualAmount": "abc"}, {"actualAmount": float("nan")},
                {"actualAmount": True}, {"hasFee": True}, {"hasFee": True, "fee": -1}, {"hasFee": True, "fee": "x"}):
        with pytest.raises(ValueError):
            remit.parse_remit(bad, 1000)


# ── paid-toggle ───────────────────────────────────────────────────────────

def test_pay_equal_amount_with_fee_is_recorded_without_review(client, make_user):
    u, pw = make_user(role="superadmin")
    t = _login(client, u, pw)
    vno = _make_approved_voucher(client, t, "MQ-REMIT-001")
    r = _pay(client, t, vno, hasFee=True, fee=15)
    assert r.status_code == 200, r.text
    assert r.json()["remitReview"] == ""
    row = _row(vno)
    assert row["remit_fee"] == 15 and row["remit_review"] == "" and row["is_paid"] == 1
    d = client.get(f"/api/contractor-vouchers/{vno}", headers=_auth(t)).json()
    assert d["remitFee"] == 15 and d["remitActual"] == d["payableAmount"] and d["remitDiff"] == 0


def test_pay_with_diff_goes_pending_and_unpay_clears_everything(client, make_user):
    u, pw = make_user(role="superadmin")
    t = _login(client, u, pw)
    vno = _make_approved_voucher(client, t, "MQ-REMIT-002")
    payable = _payable(vno)
    r = _pay(client, t, vno, actualAmount=payable - 15, hasFee=True, fee=15)
    assert r.status_code == 200, r.text
    assert r.json()["remitReview"] == "pending" and r.json()["diff"] == -15
    row = _row(vno)
    assert row["remit_review"] == "pending" and row["remit_actual"] == payable - 15
    log = json.loads(row["paid_log"])[-1]
    assert log["actual"] == payable - 15 and log["fee"] == 15 and log["diff"] == -15
    # 取消匯款：新欄位與審核狀態一併清空
    r = client.post(f"/api/contractor-vouchers/{vno}/paid-toggle", headers=_auth(t), json={"action": "unpay"})
    assert r.status_code == 200
    row = _row(vno)
    assert (row["is_paid"], row["remit_actual"], row["remit_fee"], row["remit_review"]) == (0, None, 0, "")


def test_pay_rejects_bad_amounts_without_marking_paid(client, make_user):
    u, pw = make_user(role="superadmin")
    t = _login(client, u, pw)
    vno = _make_approved_voucher(client, t, "MQ-REMIT-003")
    for body in ({"actualAmount": 0}, {"actualAmount": "x"}, {"hasFee": True}, {"hasFee": True, "fee": -3}):
        assert _pay(client, t, vno, **body).status_code == 400
    assert _row(vno)["is_paid"] == 0


# ── 出納審核端點（IP-102）─────────────────────────────────────────────────

def _review_list(client, t):
    r = client.get("/api/cashier/remit-reviews", headers=_auth(t))
    assert r.status_code == 200, r.text
    return r.json()


def test_review_list_approve_and_reject_flow(client, make_user):
    admin, apw = make_user(username="w1admin", role="superadmin")
    ta = _login(client, admin, apw)
    cashier, cpw = make_user(username="w1cash", role="user", modules=["cashier"])
    tc = _login(client, cashier, cpw)
    v1 = _make_approved_voucher(client, ta, "MQ-REMIT-004")
    v2 = _make_approved_voucher(client, ta, "MQ-REMIT-005")
    for v in (v1, v2):
        assert _pay(client, tc, v, actualAmount=_payable(v) - 15, hasFee=True, fee=15).status_code == 200
    data = _review_list(client, tc)
    assert {v1, v2} <= {i["key"] for i in data["items"]} and data["canDecide"] is True          # 第42班：出納與財務合併為財務角色，「出納唯讀／不可核可」的分工不再存在（自核風險已列入 FINANCE-ROLE-GOLIVE 後續）
    it = next(i for i in data["items"] if i["key"] == v1)
    assert it["source"] == "contractor_voucher" and it["diff"] == -15 and it["fee"] == 15
    # 核可
    r = client.post(f"/api/cashier/remit-reviews/contractor_voucher/{v1}/decision", headers=_auth(ta),
                    json={"decision": "approve", "note": "銀行短收"})
    assert r.status_code == 200, r.text
    row = _row(v1)
    assert row["remit_review"] == "approved" and row["is_paid"] == 1 and row["remit_review_note"] == "銀行短收"
    # 已處理再按 ⇒ 409
    assert client.post(f"/api/cashier/remit-reviews/contractor_voucher/{v1}/decision", headers=_auth(ta),
                       json={"decision": "approve"}).status_code == 409
    # 退回必填原因；退回＝回未匯款
    assert client.post(f"/api/cashier/remit-reviews/contractor_voucher/{v2}/decision", headers=_auth(ta),
                       json={"decision": "reject"}).status_code == 400
    r = client.post(f"/api/cashier/remit-reviews/contractor_voucher/{v2}/decision", headers=_auth(ta),
                    json={"decision": "reject", "note": "金額不對"})
    assert r.status_code == 200, r.text
    row = _row(v2)
    assert (row["is_paid"], row["remit_actual"], row["remit_fee"], row["remit_review"], row["paid_at"]) == (0, None, 0, "", "")
    assert "remit_review_rejected" in row["paid_log"]
    assert v1 not in {i["key"] for i in _review_list(client, ta)["items"]}
    assert client.post("/api/cashier/remit-reviews/nope/x/decision", headers=_auth(ta),
                       json={"decision": "approve"}).status_code == 404


def test_execution_history_shows_actual_fee_and_review(client, make_user):
    u, pw = make_user(role="superadmin")
    t = _login(client, u, pw)
    vno = _make_approved_voucher(client, t, "MQ-REMIT-009")
    assert _pay(client, t, vno, actualAmount=_payable(vno) - 15, hasFee=True, fee=15).status_code == 200
    r = client.get("/api/cashier/execution-history?start=2026-09-01&end=2026-09-30", headers=_auth(t))
    assert r.status_code == 200, r.text
    v = next(x for x in r.json()["outgoing"] if x["voucherNo"] == vno)
    assert v["remitActual"] == _payable(vno) - 15 and v["remitFee"] == 15 and v["remitReview"] == "pending"
    assert r.json()["outgoingFeeTotal"] >= 15
    x = client.get("/api/cashier/export?start=2026-09-01&end=2026-09-30", headers=_auth(t))
    assert x.status_code == 200 and x.content[:2] == b"PK"


# ── 報表支出：實付＋手續費 ────────────────────────────────────────────────

def test_report_sources_actual_plus_fee(client, make_user):
    import db
    from modules.case import recognition as rec
    u, pw = make_user(role="superadmin")
    t = _login(client, u, pw)
    vno = _make_approved_voucher(client, t, "MQ-REMIT-006")
    payable = _payable(vno)
    assert _pay(client, t, vno, actualAmount=payable - 15, hasFee=True, fee=15).status_code == 200
    conn = db.get_db()
    try:
        fees = [f for f in remit._expense_entries(conn, "2026-09-01", "2026-09-30") if f["quoteNo"] == "MQ-REMIT-006"]
        assert [(f["amount"], f["category"], f["date"]) for f in fees] == [(15.0, "匯款手續費", "2026-09-20")]
        assert remit._expense_entries(conn, "2026-10-01", "2026-10-31") == []
        cash = [e for e in rec.dispatch_entries(conn, "cash") if e["quoteNo"] == "MQ-REMIT-006"]
        assert cash and cash[0]["amount"] == payable - 15          # 現金口徑＝實付（手續費另列）
    finally:
        conn.close()


def test_fee_total_endpoint_for_case_cost(client, make_user):
    u, pw = make_user(role="superadmin")
    t = _login(client, u, pw)
    vno = _make_approved_voucher(client, t, "MQ-REMIT-007")
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                     " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     ("MQ-REMIT-007", "已送出", "測客", "測專", 210000, 200000, "{}", "2026-01-01T00:00:00",
                      "2026-01-01T00:00:00", "已成案", "2026-06-01"))
        conn.commit()
    finally:
        conn.close()
    url = "/api/contractor-vouchers/remit-fee-total?quote_no=MQ-REMIT-007"
    r0 = client.get(url, headers=_auth(t)); assert r0.status_code == 200, r0.text; assert r0.json()["feeTotal"] == 0
    assert _pay(client, t, vno, hasFee=True, fee=15).status_code == 200
    assert client.get(url, headers=_auth(t)).json()["feeTotal"] == 15
