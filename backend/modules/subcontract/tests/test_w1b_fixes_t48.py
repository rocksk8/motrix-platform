# -*- coding: utf-8 -*-
"""第 48 班 W1b 端點稽核修補（subcontract）：last-paid-bank-account 只給財務角色（原本任何登入者都讀得到公司付款帳戶）。"""
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _auth, _login

URL = "/api/contractor-vouchers/last-paid-bank-account"


def _h(client, make_user, name, **kw):
    u, p = make_user(username=name, **kw)
    return _auth(_login(client, u, p))


def test_last_paid_bank_account_needs_a_finance_role(client, make_user):
    plain = _h(client, make_user, "w1b_plain", role="user", modules=[], legacy_finance_flag=False)
    staff = _h(client, make_user, "w1b_staff", role="user", modules=["case_manage", "procurement", "contractor_list"], legacy_finance_flag=False)
    fin = _h(client, make_user, "w1b_fin", role="finance")
    sa = _h(client, make_user, "w1b_sa", role="superadmin")
    assert client.get(URL + "?vendor_id=1", headers=plain).status_code == 403
    assert client.get(URL + "?vendor_id=1", headers=staff).status_code == 403
    assert client.get(URL, headers={}).status_code in (401, 403)
    for h in (fin, sa):
        r = client.get(URL + "?vendor_id=1", headers=h)
        assert r.status_code == 200 and r.json() == {"name": "", "acctCode": ""}
