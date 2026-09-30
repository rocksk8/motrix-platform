# -*- coding: utf-8 -*-
"""R12（使用者 2026-09-30 裁示 (b)）：個人外包人員匯款前須關聯勞報單，匯款金額＝勞報單實付；匯款標記時勞報單一併記為已付款；
總帳：E05 對該行借『其他應付款』（勞報單負債）而非應付帳款，勞報單不再另產生 E06b，也不產生 E05b。
反向控制：未關聯（設定開啟）／金額不符／勞報單未簽回／受款人不符 ⇒ 擋下；取消匯款一併退回；勞報單自己的 unpay 被擋；設定關閉時舊行為不變。
"""
import json
from datetime import datetime

import pytest

import db
from helpers.settings import _set_setting
from modules.accounting.ledger import contract as C
from modules.accounting.ledger import engine as E
from modules.accounting.ledger import roles as ROLES
from modules.payroll import gl_events as PG
from modules.subcontract import gl_events as SG

_N = [0]


def _auth(t):
    return {"Authorization": "Bearer " + t}


@pytest.fixture
def tok(client, make_user):
    u, p = make_user(username="r12_admin%d" % id(client), role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    c.close()
    yield r.json()["token"]
    _set_setting("remit_require_payslip", "1")               # 還原成預設（開啟）


def _contractor(name="李外包"):
    c = db.get_db()
    try:
        cid = c.execute("INSERT INTO contractors(name, id_number) VALUES (?,?)", (name, "B234567890")).lastrowid
        c.commit()
        return cid
    finally:
        c.close()


def _slip(cid, name, gross=10000, tax=1000, nhi=211, status="已簽回"):
    _N[0] += 1
    no = "LB-R12-%d-%d" % (id(_N), _N[0])
    c = db.get_db()
    try:
        c.execute("INSERT INTO payslips(slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, "
                  "slip_date, status, signed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (no, cid, name, "9A", gross, tax, nhi, gross - tax - nhi, "2174-02-10", status, "2174-02-11T00:00:00"))
        c.commit()
    finally:
        c.close()
    return no


def _voucher(client, tok, cid, name, amount, extra_vendor=True):
    """一張只含一位個人外包人員的已核准匯款單。"""
    _N[0] += 1
    body = {"quote_no": "MQ-R12-%d" % _N[0], "items_json": [], "status": "completed",
            "personnel_json": [{"id": cid, "name": name, "amount": amount}]}
    r = client.post("/api/contractor-dispatches", headers=_auth(tok), json=body)
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
    return vno


def _pay(client, tok, vno):
    return client.post("/api/contractor-vouchers/%s/paid-toggle" % vno, headers=_auth(tok), json={"action": "pay", "paid_at": "2174-02-20"})


def _link(client, tok, vno, cid, slip):
    return client.post("/api/contractor-vouchers/%s/personnel-link" % vno, headers=_auth(tok), json={"personId": cid, "payslipNo": slip})


def _status(slip):
    c = db.get_db()
    try:
        return c.execute("SELECT status, data_json FROM payslips WHERE slip_no=?", (slip,)).fetchone()
    finally:
        c.close()


def test_link_validates_amount_status_and_payee(client, tok):
    cid = _contractor()
    net = 10000 - 1000 - 211
    vno = _voucher(client, tok, cid, "李外包", net)
    assert _link(client, tok, vno, cid, "LB-NOPE").status_code == 409                                     # 查無
    assert _link(client, tok, vno, cid, _slip(cid, "李外包", status="已匯出")).status_code == 409            # 未簽回
    assert _link(client, tok, vno, cid, _slip(cid, "李外包", gross=20000)).status_code == 409              # 金額不符
    other = _contractor("別人")
    assert _link(client, tok, vno, cid, _slip(other, "別人")).status_code == 409                          # 受款人不符
    ok = _slip(cid, "李外包")
    assert _link(client, tok, vno, cid, ok).status_code == 200
    assert _link(client, tok, vno, cid, "").status_code == 200                                           # 解除


def test_pay_requires_link_by_default_and_marks_payslip_paid(client, tok):
    cid = _contractor()
    net = 8789
    slip = _slip(cid, "李外包")
    vno = _voucher(client, tok, cid, "李外包", net)
    r = _pay(client, tok, vno)
    assert r.status_code == 409 and "尚未關聯勞報單" in r.text                                             # 未關聯 ⇒ 擋
    assert _link(client, tok, vno, cid, slip).status_code == 200
    assert _pay(client, tok, vno).status_code == 200
    row = _status(slip)
    assert row["status"] == "已付款" and json.loads(row["data_json"])["paid_via_remit"] == vno
    # 勞報單自己的 unpay 被擋，要回匯款單取消
    r = client.post("/api/payslips/%s/unpay" % slip, headers=_auth(tok))
    assert r.status_code == 409 and vno in r.text
    # 取消匯款 ⇒ 勞報單一併退回
    assert client.post("/api/contractor-vouchers/%s/paid-toggle" % vno, headers=_auth(tok), json={"action": "unpay"}).status_code == 200
    row = _status(slip)
    assert row["status"] == "已簽回" and "paid_via_remit" not in json.loads(row["data_json"])


def test_setting_off_keeps_old_behaviour_but_linked_lines_still_validated(client, tok):
    _set_setting("remit_require_payslip", "0")
    cid = _contractor()
    vno = _voucher(client, tok, cid, "李外包", 8789)
    assert _pay(client, tok, vno).status_code == 200                                                     # 設定關閉、沒關聯 ⇒ 照舊可匯款
    cid2 = _contractor("王二")
    vno2 = _voucher(client, tok, cid2, "王二", 8789)
    slip = _slip(cid2, "王二")
    assert _link(client, tok, vno2, cid2, slip).status_code == 200
    c = db.get_db()
    try:                                                                                                   # 關聯後勞報單被別的方式改成已付款 ⇒ 匯款被擋（避免重複付款）
        c.execute("UPDATE payslips SET status='已付款' WHERE slip_no=?", (slip,))
        c.commit()
    finally:
        c.close()
    assert _pay(client, tok, vno2).status_code == 409


def test_ledger_e05_uses_other_payable_and_no_double_payment(client, tok):
    cid = _contractor()
    slip = _slip(cid, "李外包")
    vno = _voucher(client, tok, cid, "李外包", 8789)
    assert _link(client, tok, vno, cid, slip).status_code == 200
    assert _pay(client, tok, vno).status_code == 200
    sub = SG.gl_events("2174-02-01", "2174-02-28")
    (e05,) = [e for e in sub["events"] if e["event_code"] == "E05" and e["source_key"] == vno]
    got = [(l["role"], l["side"], l["amount"]) for l in e05["lines"]]
    assert got == [("OTHER_PAYABLE", "D", 8789), ("BANK", "C", 8789)] and C.validate_event(e05) == []
    assert not [e for e in sub["events"] if e["event_code"] == "E05b" and e["source_key"] == vno]          # 已關聯 ⇒ 不再有未扣繳補列
    pay = PG.gl_events("2174-02-01", "2174-02-28")
    assert [e for e in pay["events"] if e["event_code"] == "E06" and e["source_key"] == slip]              # 應付照常
    assert not [e for e in pay["events"] if e["event_code"] == "E06b" and e["source_key"] == slip]         # 付款分錄只有匯款單那一筆


def test_unlinked_legacy_personnel_still_get_e05b(client, tok):
    _set_setting("remit_require_payslip", "0")
    cid = _contractor()
    vno = _voucher(client, tok, cid, "李外包", 5000)
    assert _pay(client, tok, vno).status_code == 200                                                     # 設定關閉、未關聯
    sub = SG.gl_events("2174-02-01", "2174-02-28")
    assert [e for e in sub["events"] if e["event_code"] == "E05b" and e["source_key"] == vno]
    (e05,) = [e for e in sub["events"] if e["event_code"] == "E05" and e["source_key"] == vno]
    assert [l["role"] for l in e05["lines"]] == ["AP", "BANK"]


def test_links_endpoint_lists_candidates_and_blocks(client, tok):
    cid = _contractor()
    good, wrong = _slip(cid, "李外包"), _slip(cid, "李外包", gross=20000)
    vno = _voucher(client, tok, cid, "李外包", 8789)
    r = client.get("/api/contractor-vouchers/%s/personnel-links" % vno, headers=_auth(tok))
    d = r.json()
    assert r.status_code == 200 and d["required"] is True and d["canPay"] is False
    (line,) = d["lines"]
    assert {c["slipNo"] for c in line["candidates"]} >= {good, wrong} and "尚未關聯" in line["error"]
    assert _link(client, tok, vno, cid, good).status_code == 200
    d = client.get("/api/contractor-vouchers/%s/personnel-links" % vno, headers=_auth(tok)).json()
    assert d["canPay"] is True and d["lines"][0]["payslipNo"] == good and d["lines"][0]["ok"] is True


def test_emergency_switch_is_superadmin_only_and_audited(client, tok, make_user):
    u, p = make_user(username="r12_plain%d" % id(client), role="admin")
    other = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    url = "/api/contractor-vouchers/settings/remit-require-payslip"
    assert client.get(url, headers=_auth(tok)).json() == {"enabled": True}                                # 預設開啟
    assert client.put(url, headers=_auth(other), json={"enabled": False}).status_code == 403
    assert client.put(url, headers=_auth(tok), json={"enabled": False, "reason": "演練"}).json() == {"enabled": False}
    cid = _contractor()
    vno = _voucher(client, tok, cid, "李外包", 8789)
    assert _pay(client, tok, vno).status_code == 200                                                     # 關閉後未關聯也可匯款
    c = db.get_db()
    try:
        n = c.execute("SELECT COUNT(*) FROM audit_log WHERE action='contractor_voucher.remit_require_payslip'").fetchone()[0]
    finally:
        c.close()
    assert n >= 1
