# -*- coding: utf-8 -*-
"""MONEY-FLOWS §9 L5：經匯款單付款的勞報單，營運報表（現金口徑）支出不可雙計。

匯款單（個人外包人員，R12）的實付金額＝勞報單實付（net，已扣代扣）；現金口徑的承攬商支出讀匯款單 `remit_actual`（net），
而勞報單付款後又以 gross 列入 expense.entries（payslip）⇒ 原本 net 被算兩次（net＋gross）。
修正：`paid_via_remit` 的勞報單在報表只列「代扣部分」（gross − net：所得稅＋補充保費，匯款單沒有付的那一塊），
於是匯款單 net ＋ 勞報單代扣 ＝ gross，剛好一次。"""
import json

import pytest

import db
from modules.accounting.ledger import roles as ROLES
from modules.analytics.api import reports as R

_N = [0]
DAY = "2174-02-20"


def _auth(t):
    return {"Authorization": "Bearer " + t}


@pytest.fixture
def tok(client, make_user):
    u, p = make_user(username="l5_admin%d" % id(client), role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    c.close()
    return r.json()["token"]


def _slip(cid, gross=10000, tax=1000, nhi=211):
    _N[0] += 1
    no = "LB-L5-%d-%d" % (id(_N), _N[0])
    c = db.get_db()
    try:
        c.execute("INSERT INTO payslips(slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, "
                  "slip_date, status, signed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (no, cid, "李外包", "9A", gross, tax, nhi, gross - tax - nhi, "2174-02-10", "已簽回", "2174-02-11T00:00:00"))
        c.commit()
    finally:
        c.close()
    return no


def _expense_total(month="2174-02"):
    d = R._collect_expenses(2174, basis="cash")
    m = d["monthly"][month]
    return round(sum(m.values())), d


def _remit_paid_payslip(client, tok):
    c = db.get_db()
    try:
        cid = c.execute("INSERT INTO contractors(name, id_number) VALUES (?,?)", ("李外包", "B234567890")).lastrowid
        c.commit()
    finally:
        c.close()
    slip = _slip(cid)
    net = 10000 - 1000 - 211
    _N[0] += 1
    r = client.post("/api/contractor-dispatches", headers=_auth(tok), json={
        "quote_no": "MQ-L5-%d" % _N[0], "items_json": [], "status": "completed",
        "personnel_json": [{"id": cid, "name": "李外包", "amount": net}]})
    assert r.status_code == 201, r.text
    cv = client.post("/api/contractor-vouchers", headers=_auth(tok), json={"dispatch_id": r.json()["id"]})
    assert cv.status_code == 201, cv.text
    vno = cv.json()["voucher_no"]
    c = db.get_db()
    try:
        c.execute("UPDATE contractor_payment_vouchers SET status='已核准' WHERE voucher_no=?", (vno,))
        c.commit()
    finally:
        c.close()
    assert client.post("/api/contractor-vouchers/%s/personnel-link" % vno, headers=_auth(tok),
                       json={"personId": cid, "payslipNo": slip}).status_code == 200
    assert client.post("/api/contractor-vouchers/%s/paid-toggle" % vno, headers=_auth(tok),
                       json={"action": "pay", "paid_at": DAY}).status_code == 200
    return slip, vno, net


def test_remit_paid_payslip_is_counted_once_in_cash_expenses(client, tok):
    before, _ = _expense_total()
    slip, vno, net = _remit_paid_payslip(client, tok)
    after, _d = _expense_total()
    assert after - before == 10000, (after - before, "應為 gross 一次（匯款 net 8789＋代扣 1211）；雙計會是 18789")


def test_payslip_paid_directly_still_counts_gross(client, tok):
    """對照：沒有經匯款單付款的勞報單維持 gross（行為不變）。"""
    before, _ = _expense_total()
    slip = _slip(None)
    c = db.get_db()
    try:
        c.execute("UPDATE payslips SET status='已付款', payment_date=? WHERE slip_no=?", (DAY, slip))
        c.commit()
    finally:
        c.close()
    after, _ = _expense_total()
    assert after - before == 10000
