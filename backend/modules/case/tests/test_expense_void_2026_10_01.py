# -*- coding: utf-8 -*-
"""A2 作廢路徑（S1）：僅 superadmin、僅「已核准且未付款」、理由必填；列保留（申請人清單／稽核／案件列表照列，標已作廢），
但不進任何合計／出納待付款／營運報表／佇列／總帳來源；已付款 ⇒ 409；作廢後不可再改附件／日期／付款。
GL 端（引擎自動沖轉）的證明在 modules/accounting/tests/test_ledger_void_extra_expense_2026_10_01.py。"""
import json
from datetime import date

import pytest

SENT = "/api/quotations/-/extra-expenses"
TODAY = date.today().isoformat()


_MAKE_USER_DEFAULT_ROLE = "superadmin"      # 第42班：財務／出納不再有 admin 直通；舊題的「預設 admin 操作者」改用 superadmin（見 conftest.make_user）


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _no_tiers():
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        c.commit()
    finally:
        c.close()


@pytest.fixture
def H(client, make_user):
    out = {}
    for u, role, mods in (("vd_form", "sales", ["expense_forms"]), ("vd_cash", "engineer", ["cashier", "finance"]),
                          ("vd_admin", "admin", None), ("vd_sa", "superadmin", None)):
        name, pw = make_user(username=u, role=role, modules=mods)
        out[u] = _login(client, name, pw)
    return out


def _approved(client, H, kind="travel", amount=3000):
    r = client.post(SENT, headers=H["vd_form"], json={"kind": kind, "lines": [{"category": "交通費", "summary": "車資", "amount": amount}],
                                                       "payeeName": "王小明", "payeeType": "employee", "data": {"applicant": "vd_form"}})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    _no_tiers()
    s = client.post("%s/%d/submit" % (SENT, eid), headers=H["vd_form"])
    assert s.status_code == 200 and s.json()["status"] == "已核准", s.text
    return eid


def _void(client, h, eid, reason="重複請款", path=SENT):
    return client.post("%s/%d/void" % (path, eid), headers=h, json={"reason": reason} if reason is not None else {})


# ── 權限與前置條件 ─────────────────────────────────────────────────────────

def test_only_superadmin_can_void_admin_and_owner_are_refused(client, H):
    eid = _approved(client, H)
    for who in ("vd_admin", "vd_form", "vd_cash"):
        r = _void(client, H[who], eid)
        assert r.status_code == 403, (who, r.status_code, r.text)
    assert _q("SELECT status FROM case_extra_expenses WHERE id=?", (eid,))[0]["status"] == "已核准"          # 一個都沒動
    r = _void(client, H["vd_sa"], eid)
    assert r.status_code == 200 and r.json()["status"] == "已作廢", r.text
    row = _q("SELECT * FROM case_extra_expenses WHERE id=?", (eid,))[0]
    assert row["status"] == "已作廢" and row["void_reason"] == "重複請款" and row["voided_by"] == "vd_sa" and row["voided_at"]


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_reason_is_required(client, H, reason):
    eid = _approved(client, H)
    r = _void(client, H["vd_sa"], eid, reason=reason)
    assert r.status_code == 400
    assert _q("SELECT status FROM case_extra_expenses WHERE id=?", (eid,))[0]["status"] == "已核准"


def test_only_approved_unpaid_rows_can_be_voided(client, H):
    draft = client.post(SENT, headers=H["vd_form"], json={"kind": "travel", "lines": [{"category": "交通費", "summary": "x", "amount": 10}]}).json()["id"]
    assert _void(client, H["vd_sa"], draft).status_code == 409                       # 草稿請直接刪除
    eid = _approved(client, H)
    assert client.post("/api/cashier/pending-payables/case/%d/pay" % eid, headers=H["vd_cash"], json={"paidDate": TODAY, "payMethod": "transfer"}).status_code == 200
    r = _void(client, H["vd_sa"], eid)
    assert r.status_code == 409 and "更正付款日" in r.text                              # 已付款不可直接作廢（前置檢查的訊息，不是搶先付款的那句）
    assert _q("SELECT status FROM case_extra_expenses WHERE id=?", (eid,))[0]["status"] == "已核准"
    # 付款日被管理員更正清除（退回待付款）後才可作廢
    c = client.patch("%s/%d/dates" % (SENT, eid), headers=H["vd_sa"], json={"paidDate": ""})
    assert c.status_code == 200, c.text
    assert _void(client, H["vd_sa"], eid).status_code == 200
    assert _void(client, H["vd_sa"], eid).status_code == 409                          # 重複作廢


def test_void_loses_the_race_against_a_payment_that_lands_after_the_precheck(client, H, monkeypatch):
    """前置檢查讀到的是舊資料（付款在檢查之後才寫入）⇒ 帶條件的 UPDATE 擋下（rowcount 0 ⇒ 409），付款日與狀態不被蓋掉。"""
    eid = _approved(client, H)
    assert client.post("/api/cashier/pending-payables/case/%d/pay" % eid, headers=H["vd_cash"], json={"paidDate": TODAY}).status_code == 200
    from modules.case.api import case_extra_expenses as X
    real = X._load

    def stale(conn, quote_no, exp_id, user=None):
        d = dict(real(conn, quote_no, exp_id, user))
        d["paid_date"] = ""                                   # 檢查當下還沒付款
        return d
    monkeypatch.setattr(X, "_load", stale)
    r = _void(client, H["vd_sa"], eid)
    assert r.status_code == 409, r.text
    row = _q("SELECT status, paid_date, void_reason FROM case_extra_expenses WHERE id=?", (eid,))[0]
    assert row["status"] == "已核准" and row["paid_date"] == TODAY and row["void_reason"] == ""


def test_void_not_found_and_caseless_visibility(client, H):
    assert _void(client, H["vd_sa"], 999999).status_code == 404


# ── 排除：金流／清單／佇列 ───────────────────────────────────────────────────

def test_voided_row_leaves_cashier_recognition_gl_and_totals_but_stays_in_owner_list(client, H):
    keep = _approved(client, H, amount=1000)
    gone = _approved(client, H, amount=2000)
    pend0 = {i["key"] for i in client.get("/api/cashier/pending-payables", headers=H["vd_cash"]).json()["items"]}
    assert {str(keep), str(gone)} <= pend0
    assert _void(client, H["vd_sa"], gone).status_code == 200
    # 出納待付款：只剩 keep；對已作廢的列付款 ⇒ 不可
    pend = {i["key"] for i in client.get("/api/cashier/pending-payables", headers=H["vd_cash"]).json()["items"]}
    assert str(keep) in pend and str(gone) not in pend
    pr = client.post("/api/cashier/pending-payables/case/%d/pay" % gone, headers=H["vd_cash"], json={"paidDate": TODAY, "payMethod": "transfer"})
    assert pr.status_code == 409
    assert _q("SELECT paid_date FROM case_extra_expenses WHERE id=?", (gone,))[0]["paid_date"] == ""
    # 營運報表認列（權責／現金）與總帳來源
    import db
    from modules.case import gl_events as G
    from modules.case import recognition as R
    c = db.get_db()
    try:
        for basis in ("accrual", "cash"):
            ids = {str(e.get("id") or e.get("key")) for e in R.extra_entries(c, basis)}
            assert str(gone) not in ids, basis
    finally:
        c.close()
    assert str(gone) not in {e["source_key"] for e in G.gl_events("2000-01-01", "2999-12-31")["events"] if e["source_type"].startswith("case_extra_expense")}
    assert str(keep) in {e["source_key"] for e in G.gl_events("2000-01-01", "2999-12-31")["events"] if e["source_type"] == "case_extra_expense"}   # 正對照
    # 申請人自己的清單與詳細列表仍看得到（標已作廢）；合計不含
    mine = {i["id"]: i for i in client.get("/api/extra-expenses/mine", headers=H["vd_form"]).json()}
    assert mine[gone]["status"] == "已作廢" and mine[gone]["voidReason"] == "重複請款" and mine[keep]["status"] == "已核准"
    lst = client.get(SENT, headers=H["vd_form"]).json()
    assert {i["id"]: i["status"] for i in lst["items"]}[gone] == "已作廢"
    assert lst["totalAmount"] == 1000 and lst["totalPending"] == 0


def test_voiding_clears_a_pending_change_request_and_queue_items(client, H):
    eid = _approved(client, H, amount=1000)
    r = client.put("%s/%d/change-request" % (SENT, eid), headers=H["vd_form"],
                   json={"description": "改", "lines": [{"category": "交通費", "summary": "改", "amount": 5000}]})
    assert r.status_code == 200, r.text
    assert _void(client, H["vd_sa"], eid).status_code == 200
    row = _q("SELECT status, change_status, change_json FROM case_extra_expenses WHERE id=?", (eid,))[0]
    assert row["status"] == "已作廢" and row["change_status"] == "" and row["change_json"] == "{}"
    import db
    from modules.case.api import quotations as Q
    c = db.get_db()
    try:
        assert not [i for i in Q.approval_queue_items(c) if i.get("extraExpenseId") == eid]
    finally:
        c.close()


# ── 作廢後不可再動 ──────────────────────────────────────────────────────────

def test_voided_row_is_frozen(client, H):
    eid = _approved(client, H)
    assert _void(client, H["vd_sa"], eid).status_code == 200
    assert client.patch("%s/%d" % (SENT, eid), headers=H["vd_form"], json={"kind": "travel", "lines": [{"category": "交通費", "summary": "x", "amount": 1}]}).status_code == 409
    assert client.delete("%s/%d" % (SENT, eid), headers=H["vd_form"]).status_code == 409
    assert client.post("%s/%d/submit" % (SENT, eid), headers=H["vd_form"]).status_code == 409
    assert client.put("%s/%d/change-request" % (SENT, eid), headers=H["vd_form"], json={"description": "x"}).status_code == 409
    assert client.patch("%s/%d/dates" % (SENT, eid), headers=H["vd_sa"], json={"invoiceNo": "AB12345678"}).status_code == 409          # 第42班：admin 看不到別人的無案件額外支出；改用 superadmin 驗「作廢列凍結」
    assert client.patch("%s/%d/dates" % (SENT, eid), headers=H["vd_cash"], json={"paidDate": TODAY}).status_code == 409
    up = client.post("%s/%d/files" % (SENT, eid), headers=H["vd_form"], files={"files": ("a.txt", b"hello", "text/plain")}, data={"kind": "invoice"})
    assert up.status_code == 409, up.text


# ── 稽核 ────────────────────────────────────────────────────────────────────

def test_void_is_audited_with_reason_and_target(client, H):
    eid = _approved(client, H)
    assert _void(client, H["vd_sa"], eid, reason="廠商取消").status_code == 200
    rows = _q("SELECT action, target_type, target_id, target_label, detail FROM audit_log WHERE action='extra_expense.void'")
    assert len(rows) == 1 and rows[0]["target_type"] == "case_extra_expense" and rows[0]["target_id"] == str(eid)
    assert "廠商取消" in rows[0]["target_label"] and json.loads(rows[0]["detail"])["reason"] == "廠商取消"


# ── 案件綁定列：案件財務總覽的合計 ───────────────────────────────────────────

def test_case_bound_settlement_extras_excludes_voided_total_but_lists_it(client, H, seed_extra_expense):
    import db
    qn = "MQ-VOID-1"
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (qn, "已送出", "客", "案", 0, 0, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-01-01"))
        c.commit()
    finally:
        c.close()
    a = seed_extra_expense(qn, total_cost=700, description="留", expense_date="2026-03-01", created_by_name="x")
    b = seed_extra_expense(qn, total_cost=900, description="廢", expense_date="2026-03-02", created_by_name="x")
    r = _void(client, H["vd_sa"], b, path="/api/quotations/%s/extra-expenses" % qn)
    assert r.status_code == 200, r.text
    fs = client.get("/api/quotations/%s/finance-summary" % qn, headers=H["vd_sa"]).json()["settlementExtras"]
    assert fs["total"] == 700 and {i["id"]: i["voided"] for i in fs["items"]} == {a: False, b: True}
    lst = client.get("/api/quotations/%s/extra-expenses" % qn, headers=H["vd_sa"]).json()
    assert lst["totalAmount"] == 700 and {i["id"]: i["status"] for i in lst["items"]}[b] == "已作廢"
    from modules.case import quotations as CQ
    c = db.get_db()
    try:
        assert [e["desc"] for e in CQ.case_extra_expenses(c, qn)] == ["留"]
    finally:
        c.close()
