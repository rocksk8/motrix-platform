# -*- coding: utf-8 -*-
"""總帳設定（T69）的權限補測（T70 衛生；審查 audit-t69-ledger-r1 的補洞）：
非最高管理者——包含只勾『出納』的人、勾了『財務』『出納』模組的管理員、業務——不能申請／核准／撤銷角色對應、不能改會計年度起始月份。
出納／財務『模組勾選』不算數（這幾個能力由角色決定，不看勾選），所以連唯讀 GET 也是 403；只有財務『角色』與最高管理者能讀。
全部走真實使用者 HTTP（make_user＋登入），`legacy_finance_flag=False` 避免被舊旗標升級；不 patch 任何權限函式。
正對照：同一個請求由最高管理者送出得 202／200，確認 403 不是請求內容造成。
"""
import pytest

import db
from modules.accounting.ledger import periods as P
from modules.accounting.ledger import roles as ROLES


def _login(client, make_user, name, role, modules):
    u, p = make_user(username=name, role=role, modules=list(modules), legacy_finance_flag=False)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def seeded(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


@pytest.fixture
def pending(client, make_user, seeded):
    """最高管理者甲先送出一筆待核准申請，給下面的核准／撤銷題用。"""
    sup = _login(client, make_user, "t70_sup_a", "superadmin", ())
    _login(client, make_user, "t70_sup_b", "superadmin", ())          # 第二位在職最高管理者（沒有它申請會 409）
    r = client.put("/api/ledger/roles", headers=sup, json={"role": "BANK", "account_code": "1112", "reason": "權限補測的申請"})
    assert r.status_code == 202, r.text                                  # 正對照
    return r.json()["id"]


UNPRIVILEGED = [
    pytest.param("user", ("cashier",), id="cashier-tick-only"),
    pytest.param("admin", ("finance", "cashier"), id="admin-with-finance-and-cashier-ticks"),
    pytest.param("sales", (), id="sales-no-modules"),
]


@pytest.mark.parametrize("role,modules", UNPRIVILEGED)
def test_unprivileged_users_cannot_request_approve_or_cancel_role_changes(client, make_user, pending, role, modules):
    h = _login(client, make_user, "t70_low_" + role, role, modules)
    assert client.put("/api/ledger/roles", headers=h,
                      json={"role": "BANK", "account_code": "1111", "reason": "不該成功"}).status_code == 403
    assert client.post("/api/ledger/roles/pending/%d/approve" % pending, headers=h, json={"reason": "不該成功"}).status_code == 403
    assert client.post("/api/ledger/roles/pending/%d/cancel" % pending, headers=h, json={"reason": "不該成功"}).status_code == 403
    # 什麼都沒變：待核准項仍在、對應表沒動
    sup = _login(client, make_user, "t70_check_" + role, "superadmin", ())
    g = client.get("/api/ledger/roles", headers=sup).json()
    assert [p["id"] for p in g["pending"]] == [pending]


@pytest.mark.parametrize("role,modules", UNPRIVILEGED)
def test_unprivileged_users_cannot_change_the_fiscal_year_start_and_cannot_read_roles(client, make_user, seeded, role, modules):
    before = P.fiscal_start_month(seeded)
    h = _login(client, make_user, "t70_fs_" + role, role, modules)
    assert client.put("/api/ledger/settings", headers=h, json={"fiscal_year_start_month": 4}).status_code == 403
    assert P.fiscal_start_month(db.get_db()) == before
    assert client.get("/api/ledger/roles", headers=h).status_code == 403          # 模組勾選不算數
    sup = _login(client, make_user, "t70_fs_sup_" + role, "superadmin", ())
    assert client.put("/api/ledger/settings", headers=sup, json={"fiscal_year_start_month": 4}).status_code == 200   # 正對照


def test_finance_role_can_read_but_not_write(client, make_user, pending):
    fin = _login(client, make_user, "t70_fin", "finance", ("cashier", "finance"))
    assert client.get("/api/ledger/roles", headers=fin).status_code == 200
    assert client.put("/api/ledger/roles", headers=fin, json={"role": "BANK", "account_code": "1111", "reason": "不該成功"}).status_code == 403
    assert client.post("/api/ledger/roles/pending/%d/approve" % pending, headers=fin, json={}).status_code == 403
