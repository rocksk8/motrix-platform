# -*- coding: utf-8 -*-
"""W1（2026-09-30）：請款待付款（IP-100，案件額外支出）登錄付款時的實付／手續費／差額審核（IP-102 `remit.reviews`）。

- 實付≠應付 ⇒ 差額待審核（remit_review=pending），付款日照寫、從待付款消失；手續費（勾 hasFee）不參與比對。
- admin+ 核可（留紀錄）或退回（＝回待付款，付款日／實付／手續費清空）；出納自己不能決定。
- 手續費以付款日進 IP-9 `expense.entries`、現金口徑金額用實付、付款日被清除時新欄位一併清空。
"""
import json

from tests._requires import requires_module

NEEDS_CASE = requires_module("case", "請款的提供者是 M01 案件額外支出")
NO = "MQ-RF-001"


_MAKE_USER_DEFAULT_ROLE = "superadmin"      # 第42班：財務／出納不再有 admin 直通；舊題的「預設 admin 操作者」改用 superadmin（見 conftest.make_user）


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur
    finally:
        conn.close()


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _h(client, make_user, name, role, modules=None):
    u, p = make_user(username=name, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed(cost=1000):
    _x("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
       " deal_tag, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "手續費客", "手續費專案", 1, 1, "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "", "[]"))
    cur = _x("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, expense_date,"
             " files_json, created_by, created_by_name, payer_name, created_at, updated_at, status, paid_date)"
             " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (NO, "材料", "線材", 1, "", cost, cost, "2031-05-01", "[]", "rf_eng", "工程師甲", "", "2031-05-01", "2031-05-01", "已核准", ""))
    return str(cur.lastrowid)


def _pay(client, h, key, **body):
    return client.post("/api/cashier/pending-payables/case/%s/pay" % key, headers=h, json={"paidDate": "2031-05-09", **body})


def _row(key):
    return _q("SELECT * FROM case_extra_expenses WHERE id=?", (key,))[0]


@NEEDS_CASE
def test_pay_equal_with_fee_no_review_and_fee_expense_entry(client, make_user):
    cash = _h(client, make_user, "rf_cash", "user", ["cashier"])
    key = _seed()
    r = _pay(client, cash, key, hasFee=True, fee=15)
    assert r.status_code == 200, r.text
    assert (r.json()["remitReview"], r.json()["fee"], r.json()["actual"]) == ("", 15, 1000)
    row = _row(key)
    assert row["paid_date"] == "2031-05-09" and row["remit_fee"] == 15 and row["remit_review"] == ""
    import db
    from modules.case import payables
    conn = db.get_db()
    try:
        fee = [f for f in payables._expense_entries(conn, "2031-05-01", "2031-05-31") if f["quoteNo"] == NO]
        assert [(f["amount"], f["category"]) for f in fee] == [(15.0, "匯款手續費")]
        assert payables._expense_entries(conn, "2031-06-01", "2031-06-30") == []
        assert [i["actual"] for i in payables._Payables.paid(conn, "2031-05-01", "2031-05-31") if i["key"] == key] == [1000.0]
    finally:
        conn.close()
    # 案件成本：額外支出清單回應帶手續費合計（不併入 totalAmount）
    adm = _h(client, make_user, "rf_admin0", "superadmin")
    d = client.get("/api/quotations/%s/extra-expenses" % NO, headers=adm).json()
    assert d["remitFeeTotal"] == 15 and d["totalAmount"] == 1000


@NEEDS_CASE
def test_diff_goes_pending_then_approve_and_reject(client, make_user):
    cash = _h(client, make_user, "rf_cash", "user", ["cashier"])
    adm = _h(client, make_user, "rf_admin", "superadmin")
    k1, k2 = _seed(), _seed()
    for k in (k1, k2):
        r = _pay(client, cash, k, actualAmount=985, hasFee=True, fee=15)
        assert r.status_code == 200, r.text
        assert r.json()["remitReview"] == "pending" and r.json()["diff"] == -15
    # 付款日照寫、已不在待付款
    assert _row(k1)["paid_date"] == "2031-05-09"
    pend = client.get("/api/cashier/pending-payables", headers=cash).json()["items"]
    assert not [i for i in pend if i["key"] in (k1, k2)]
    lst = client.get("/api/cashier/remit-reviews", headers=cash).json()
    it = next(i for i in lst["items"] if i["source"] == "case" and i["key"] == k1)
    assert (it["payable"], it["actual"], it["diff"], it["fee"]) == (1000.0, 985.0, -15.0, 15.0) and lst["canDecide"] is True          # 第42班：出納與財務合併為財務角色，「出納唯讀／不可核可」的分工不再存在（自核風險已列入 FINANCE-ROLE-GOLIVE 後續）
    url = "/api/cashier/remit-reviews/case/%s/decision"
    r = client.post(url % k1, headers=adm, json={"decision": "approve", "note": "短收已確認"})
    assert r.status_code == 200, r.text
    row = _row(k1)
    assert row["remit_review"] == "approved" and row["remit_review_note"] == "短收已確認" and row["paid_date"] == "2031-05-09"
    assert client.post(url % k1, headers=adm, json={"decision": "approve"}).status_code == 409
    assert client.post(url % k2, headers=adm, json={"decision": "reject"}).status_code == 400        # 退回必填原因
    r = client.post(url % k2, headers=adm, json={"decision": "reject", "note": "金額有誤"})
    assert r.status_code == 200, r.text
    row = _row(k2)
    assert (row["paid_date"], row["remit_actual"], row["remit_fee"], row["remit_review"]) == ("", None, 0, "")
    back = client.get("/api/cashier/pending-payables", headers=cash).json()["items"]
    assert [i for i in back if i["key"] == k2]                                                          # 退回＝回待付款
    acts = {r["action"]: r["target_label"] for r in _q("SELECT action, target_label FROM audit_log WHERE action LIKE 'cashier.remit_review_%'")}
    assert "核可" in acts["cashier.remit_review_approve"] and "退回" in acts["cashier.remit_review_reject"]


@NEEDS_CASE
def test_bad_amounts_rejected_and_nothing_paid(client, make_user):
    cash = _h(client, make_user, "rf_cash", "user", ["cashier"])
    key = _seed()
    for body in ({"actualAmount": 0}, {"actualAmount": "x"}, {"hasFee": True}, {"hasFee": True, "fee": -1}):
        r = _pay(client, cash, key, **body)
        assert r.status_code == 400 or r.status_code == 409 or r.status_code == 422, (body, r.status_code, r.text)
    assert _row(key)["paid_date"] == ""


@NEEDS_CASE
def test_cash_basis_uses_actual_and_clearing_paid_date_clears_remit(client, make_user):
    cash = _h(client, make_user, "rf_cash", "user", ["cashier"])
    adm = _h(client, make_user, "rf_admin2", "superadmin")
    key = _seed()
    assert _pay(client, cash, key, actualAmount=985, hasFee=True, fee=15).status_code == 200
    import db
    from modules.case import recognition as rec
    conn = db.get_db()
    try:
        e = [x for x in rec.extra_entries(conn, "cash") if x["expenseId"] == int(key)][0]
        assert e["amount"] == 985 and e["date"] == "2031-05-09"
        assert [x for x in rec.extra_entries(conn, "accrual") if x["expenseId"] == int(key)][0]["amount"] == 1000
    finally:
        conn.close()
    r = client.patch("/api/quotations/%s/extra-expenses/%s/dates" % (NO, key), headers=adm, json={"paidDate": ""})
    assert r.status_code == 200, r.text
    row = _row(key)
    assert (row["paid_date"], row["remit_actual"], row["remit_fee"], row["remit_review"]) == ("", None, 0, "")


@NEEDS_CASE
def test_execution_history_lists_payreq_paid(client, make_user):
    adm = _h(client, make_user, "rf_admin3", "superadmin")
    key = _seed()
    assert _pay(client, adm, key, actualAmount=985, hasFee=True, fee=15).status_code == 200
    d = client.get("/api/cashier/execution-history?start=2031-05-01&end=2031-05-31", headers=adm).json()
    it = [i for i in d["payreqPaid"] if i["key"] == key][0]
    assert (it["payable"], it["actual"], it["fee"], it["review"]) == (1000.0, 985.0, 15.0, "pending")
    assert d["payreqFeeTotal"] >= 15
    x = client.get("/api/cashier/export?start=2031-05-01&end=2031-05-31", headers=adm)
    assert x.status_code == 200 and x.content[:2] == b"PK"


@NEEDS_CASE
def test_payreq_pay_requires_date_and_payer_cannot_decide_own_diff(client, make_user):
    """M2：不帶 paidDate ⇒ 400；M4：登錄付款的人不能自己核可自己的差額（反向控制：另一位可以）。"""
    a1 = _h(client, make_user, "rf_a1", "superadmin")
    a2 = _h(client, make_user, "rf_a2", "superadmin")
    key = _seed()
    r = client.post("/api/cashier/pending-payables/case/%s/pay" % key, headers=a1, json={"actualAmount": 985})
    assert r.status_code == 400 and "付款日" in r.text
    assert _row(key)["paid_date"] == ""
    assert _pay(client, a1, key, actualAmount=985).status_code == 200
    url = "/api/cashier/remit-reviews/case/%s/decision" % key
    assert client.post(url, headers=a1, json={"decision": "approve"}).status_code == 403
    assert client.post(url, headers=a1, json={"decision": "reject", "note": "x"}).status_code == 403
    assert _row(key)["remit_review"] == "pending"
    assert client.post(url, headers=a2, json={"decision": "approve"}).status_code == 200            # 反向控制


@NEEDS_CASE
def test_pending_diff_extra_fee_entry_is_flagged_and_finance_summary_has_fee(client, make_user):
    """M3：手續費 entry 標 pending（核可前）；S1：案件財務總覽帶已匯款手續費。"""
    a1 = _h(client, make_user, "rf_b1", "superadmin")
    a2 = _h(client, make_user, "rf_b2", "superadmin")
    key = _seed()
    assert _pay(client, a1, key, actualAmount=985, hasFee=True, fee=15).status_code == 200
    import db
    from modules.case import payables

    def fee_entry():
        conn = db.get_db()
        try:
            return [x for x in payables._expense_entries(conn, "2031-05-01", "2031-05-31") if x["quoteNo"] == NO][0]
        finally:
            conn.close()
    assert fee_entry()["pending"] is True
    fs = client.get("/api/quotations/%s/finance-summary" % NO, headers=a1).json()
    assert fs["settlementExtras"]["remitFeeTotal"] == 15 and fs["payable"]["remitFeeTotal"] == 0
    assert client.post("/api/cashier/remit-reviews/case/%s/decision" % key, headers=a2,
                       json={"decision": "approve"}).status_code == 200
    assert fee_entry()["pending"] is False
