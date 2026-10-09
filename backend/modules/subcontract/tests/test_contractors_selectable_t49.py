# -*- coding: utf-8 -*-
"""第 49 班（使用者裁示）：GET /api/contractors/selectable（外包名冊 id／姓名／電話）不再是「所有登入者皆可讀」。

允許：最高管理者、財務角色，或持有 procurement／case_manage／contractor_list／payslip 任一模組者；其他 403。只回 id／name／phone（無銀行、證號）。
"""
import pytest

from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _auth, _login

URL = "/api/contractors/selectable"


def _h(client, make_user, name, **kw):
    u, p = make_user(username=name, **kw)
    return _auth(_login(client, u, p))


def _seed():
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO contractors (name, id_number, phone, bank_account_number, active, created_at, updated_at) VALUES ('名冊甲','A123456789','0912000111','123456789012',1,'t','t')")
        c.commit()
    finally:
        c.close()


@pytest.mark.parametrize("who,kw,ok", [
    ("sa", dict(role="superadmin"), True),
    ("fin", dict(role="finance"), True),
    ("proc", dict(role="user", modules=["procurement"], legacy_finance_flag=False), True),
    ("cm", dict(role="user", modules=["case_manage"], legacy_finance_flag=False), True),
    ("roster", dict(role="user", modules=["contractor_list"], legacy_finance_flag=False), True),
    ("slip", dict(role="user", modules=["payslip"], legacy_finance_flag=False), True),
    ("quo", dict(role="user", modules=["quotation"], legacy_finance_flag=False), False),
    ("none", dict(role="user", modules=[], legacy_finance_flag=False), False),
    ("daily", dict(role="user", modules=["daily_task", "dashboard"], legacy_finance_flag=False), False),
])
def test_selectable_roster_is_limited_to_dispatch_payslip_roster_or_finance(client, make_user, who, kw, ok):
    _seed()
    h = _h(client, make_user, "sel_" + who, **kw)
    r = client.get(URL, headers=h)
    if ok:
        assert r.status_code == 200, r.text
        assert r.json() == [{"id": r.json()[0]["id"], "name": "名冊甲", "phone": "0912000111"}]
        assert "A123456789" not in r.text and "123456789012" not in r.text
    else:
        assert r.status_code == 403, r.text
        assert "名冊甲" not in r.text and "0912000111" not in r.text


def test_anonymous_is_refused(client):
    assert client.get(URL).status_code in (401, 403)
