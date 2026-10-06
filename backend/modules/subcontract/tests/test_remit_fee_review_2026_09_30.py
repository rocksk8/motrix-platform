"""W1 稽核補題（2026-09-30）：M2 匯款日期必填、M3 待審核差額的報表標示與 T100 排除、M4 自己標記的匯款不能自己核可。"""
from modules.subcontract import remit
from modules.subcontract.tests.test_contractor_voucher_paid_date_2026_08_31 import (
    _auth, _login, _make_approved_voucher)
from modules.subcontract.tests.test_remit_fee_2026_09_30 import _payable, _pay, _row


def test_t100_excludes_pending_then_uses_actual_and_fee_after_approval(client, make_user):
    """M3：待審核差額不進 T100 傳票，核可後才進（實付＋手續費、借貸相等）。"""
    from modules.accounting.api import accounting_export as ax
    cashier, cpw = make_user(username="t100_cash", role="user", modules=["cashier"])
    boss, bpw = make_user(username="t100_boss", role="superadmin")
    tc, tb = _login(client, cashier, cpw), _login(client, boss, bpw)
    vno = _make_approved_voucher(client, tb, "MQ-REMIT-008")
    payable = _payable(vno)
    assert _pay(client, tc, vno, actualAmount=payable - 15, hasFee=True, fee=15).status_code == 200

    def events():
        return [e for e in ax._collect_t100_events("2026-09-01", "2026-09-30", exclude_confirmed=False)
                if e["sourceKey"] == vno]
    assert events() == []                                                     # 待審核 ⇒ 不進
    r = client.post(f"/api/cashier/remit-reviews/contractor_voucher/{vno}/decision", headers=_auth(tb),
                    json={"decision": "approve"})
    assert r.status_code == 200, r.text
    ev = events()[0]
    assert sum(l["debit"] for l in ev["lines"]) == sum(l["credit"] for l in ev["lines"])
    by = {l["acctName"]: l for l in ev["lines"]}
    assert by["承攬商費用"]["debit"] == round(payable - 15) and by["匯款手續費支出"]["debit"] == 15
    assert [l["credit"] for l in ev["lines"] if l["credit"]] == [round(payable)]


def test_t100_includes_equal_amount_voucher_immediately(client, make_user):
    """反向控制：實付＝應付（不需審核）的匯款單，標記後 T100 立即可匯（排除的只有 pending）。"""
    from modules.accounting.api import accounting_export as ax
    u, pw = make_user(username="t100_eq", role="superadmin")
    t = _login(client, u, pw)
    vno = _make_approved_voucher(client, t, "MQ-REMIT-013")
    assert _pay(client, t, vno, hasFee=True, fee=15).status_code == 200
    assert [e for e in ax._collect_t100_events("2026-09-01", "2026-09-30", exclude_confirmed=False)
            if e["sourceKey"] == vno]


def test_pending_shows_in_reports_but_is_flagged(client, make_user):
    """M3：報表現金口徑照計（已記錄）但標「差額待審核」；核可後不再標；手續費同。"""
    import db
    from modules.case import recognition as rec
    cashier, cpw = make_user(username="rp_cash", role="user", modules=["cashier"])
    boss, bpw = make_user(username="rp_boss", role="superadmin")
    tc, tb = _login(client, cashier, cpw), _login(client, boss, bpw)
    vno = _make_approved_voucher(client, tb, "MQ-REMIT-010")
    payable = _payable(vno)
    assert _pay(client, tc, vno, actualAmount=payable - 15, hasFee=True, fee=15).status_code == 200

    def cash():
        conn = db.get_db()
        try:
            e = [x for x in rec.dispatch_entries(conn, "cash") if x["quoteNo"] == "MQ-REMIT-010"][0]
            f = [x for x in remit._expense_entries(conn, "2026-09-01", "2026-09-30") if x["quoteNo"] == "MQ-REMIT-010"][0]
            return e, f
        finally:
            conn.close()
    e, f = cash()
    assert e["amount"] == payable - 15 and e["remitPending"] is True and f["pending"] is True
    r = client.get("/api/reports/expenses-monthly?year=2026&basis=cash", headers=_auth(tb))
    assert r.status_code == 200, r.text
    d = [x for x in r.json()["expenses"]["details"]["contractor"] if x["quoteNo"] == "MQ-REMIT-010"]
    assert d and d[0]["pending"] is True and "差額待審核" in d[0]["taxNote"]
    o = [x for x in r.json()["expenses"]["details"]["other"] if x["quoteNo"] == "MQ-REMIT-010"]
    assert o and o[0]["pending"] is True and o[0]["amount"] == 15
    assert client.post(f"/api/cashier/remit-reviews/contractor_voucher/{vno}/decision", headers=_auth(tb),
                       json={"decision": "approve"}).status_code == 200
    e, f = cash()
    assert e["remitPending"] is False and f["pending"] is False


def test_paid_by_cannot_decide_own_diff(client, make_user):
    """M4：標記匯款的人不能自己核可／退回自己的差額（即使是最高管理者）；反向控制：另一位管理員可以。"""
    boss, bpw = make_user(username="own_boss", role="superadmin")
    other, opw = make_user(username="own_other", role="superadmin")
    tb, to = _login(client, boss, bpw), _login(client, other, opw)
    vno = _make_approved_voucher(client, tb, "MQ-REMIT-011")
    assert _pay(client, tb, vno, actualAmount=_payable(vno) - 5).status_code == 200
    url = f"/api/cashier/remit-reviews/contractor_voucher/{vno}/decision"
    r = client.post(url, headers=_auth(tb), json={"decision": "approve"})
    assert r.status_code == 403
    assert "其他財務角色成員或最高管理者" in r.text and "其他管理員" not in r.text, r.text      # 第44班稽核 c3：訊息指向可審核的人
    assert client.post(url, headers=_auth(tb), json={"decision": "reject", "note": "x"}).status_code == 403
    assert _row(vno)["remit_review"] == "pending" and _row(vno)["is_paid"] == 1
    assert client.post(url, headers=_auth(to), json={"decision": "approve"}).status_code == 200      # 反向控制


def test_toggle_requires_date_for_pay_only(client, make_user):
    """M2：pay 不帶日期 ⇒ 400；unpay 不需要日期。"""
    u, pw = make_user(role="superadmin")
    t = _login(client, u, pw)
    vno = _make_approved_voucher(client, t, "MQ-REMIT-012")
    r = client.post(f"/api/contractor-vouchers/{vno}/paid-toggle", headers=_auth(t), json={"action": "pay"})
    assert r.status_code == 400 and "匯款日期" in r.text
    assert _pay(client, t, vno).status_code == 200
    assert client.post(f"/api/contractor-vouchers/{vno}/paid-toggle", headers=_auth(t),
                       json={"action": "unpay"}).status_code == 200
