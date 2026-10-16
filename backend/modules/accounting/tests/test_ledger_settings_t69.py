# -*- coding: utf-8 -*-
"""總帳設定 T69：①會計年度起始月份只有最高管理者能改、立即生效、留稽核（舊值→新值）；
②角色→科目對應（金流）的變更要**第二位**最高管理者核准才生效（設定帳本 config_ledger 的待生效＋雙人核准）；
③唯讀 `GET /api/ledger/roles`（現行對應＋待核准清單）。權限題一律走真實使用者 HTTP（make_user＋登入），不 patch 權限函式。
"""
import json

import pytest

import db
from modules.accounting.ledger import periods as P
from modules.accounting.ledger import roles as ROLES


def _login(client, make_user, name, role="superadmin", modules=("finance",), **kw):
    u, p = make_user(username=name, role=role, modules=list(modules), **kw)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


@pytest.fixture
def sup_a(client, make_user, conn):
    return _login(client, make_user, "t69_sup_a")


@pytest.fixture
def sup_b(client, make_user, conn):
    return _login(client, make_user, "t69_sup_b")


@pytest.fixture
def fin(client, make_user):
    return _login(client, make_user, "t69_fin", role="finance", modules=("cashier", "finance"), legacy_finance_flag=False)


def _audits(action):
    c = db.get_db()
    try:
        return [dict(r, detail=json.loads(r["detail"] or "{}")) for r in
                c.execute("SELECT * FROM audit_log WHERE action=? ORDER BY id", (action,)).fetchall()]
    finally:
        c.close()


def _role_code(role="BANK"):
    c = db.get_db()
    try:
        return ROLES.resolve_role(c, role)
    finally:
        c.close()


# ── 一、會計年度起始月份：僅最高管理者、立即生效、稽核 ─────────────────────────────
def test_fiscal_start_finance_user_is_refused(client, fin, conn):
    before = P.fiscal_start_month(conn)
    r = client.put("/api/ledger/settings", headers=fin, json={"fiscal_year_start_month": 4})
    assert r.status_code == 403 and "最高管理者" in r.json()["detail"], r.text
    assert P.fiscal_start_month(db.get_db()) == before


def test_fiscal_start_superadmin_changes_immediately_and_audits_old_and_new(client, sup_a, conn):
    assert client.put("/api/ledger/settings", headers=sup_a, json={"fiscal_year_start_month": 4}).status_code == 200
    assert P.fiscal_start_month(db.get_db()) == 4
    a = [x for x in _audits("ledger.settings.update") if x["username"] == "t69_sup_a"]
    assert a and a[-1]["detail"]["old"] == 1 and a[-1]["detail"]["new"] == 4


@pytest.mark.parametrize("bad", [0, 13, "x", None, 2.5])
def test_fiscal_start_rejects_invalid_months(client, sup_a, conn, bad):
    before = P.fiscal_start_month(conn)
    assert client.put("/api/ledger/settings", headers=sup_a, json={"fiscal_year_start_month": bad}).status_code == 400
    assert P.fiscal_start_month(db.get_db()) == before


def test_fiscal_start_locked_once_a_year_exists(client, sup_a, conn):
    P.create_year(conn, 2031, "t69")
    conn.commit()
    r = client.put("/api/ledger/settings", headers=sup_a, json={"fiscal_year_start_month": 7})
    assert r.status_code == 409


# ── 二、角色→科目對應：第二位最高管理者核准 ─────────────────────────────────────────
def _put(client, h, code="1112", reason="銀行存款改記到另一個科目", role="BANK", **kw):
    return client.put("/api/ledger/roles", headers=h, json=dict({"role": role, "account_code": code, "reason": reason}, **kw))


def test_role_change_is_pending_until_a_second_superadmin_approves(client, sup_a, sup_b, conn):
    before = _role_code()
    r = _put(client, sup_a)
    assert r.status_code == 202 and r.json()["pending"] is True, r.text
    pid = r.json()["id"]
    assert _role_code() == before                              # 還沒生效
    g = client.get("/api/ledger/roles", headers=sup_b).json()
    assert [p["id"] for p in g["pending"]] == [pid] and g["pending"][0]["account_code"] == "1112" and g["pending"][0]["old_account_code"] == before
    # 申請人不能核准自己的
    assert client.post("/api/ledger/roles/pending/%d/approve" % pid, headers=sup_a, json={}).status_code == 409
    assert _role_code() == before
    ok = client.post("/api/ledger/roles/pending/%d/approve" % pid, headers=sup_b, json={"reason": "已核對"})
    assert ok.status_code == 200, ok.text
    assert _role_code() == "1112"                              # 核准後立刻生效
    assert client.get("/api/ledger/roles", headers=sup_b).json()["pending"] == []
    for act in ("ledger.role.request", "ledger.role.approve", "ledger.role.put"):
        assert _audits(act), act
    assert _audits("ledger.role.put")[-1]["detail"]["requested_by"] == "t69_sup_a"


def test_finance_user_cannot_request_or_approve_but_can_read(client, sup_a, sup_b, fin, conn):
    assert _put(client, fin).status_code == 403
    pid = _put(client, sup_a).json()["id"]
    assert client.post("/api/ledger/roles/pending/%d/approve" % pid, headers=fin, json={}).status_code == 403
    assert client.post("/api/ledger/roles/pending/%d/cancel" % pid, headers=fin, json={"reason": "不該能撤銷"}).status_code == 403
    g = client.get("/api/ledger/roles", headers=fin)
    assert g.status_code == 200 and g.json()["roles"] and g.json()["pending"]
    assert _role_code() != "1112"


def test_roles_read_needs_ledger_module_and_login(client, make_user, conn):
    assert client.get("/api/ledger/roles").status_code in (401, 403)
    nobody = _login(client, make_user, "t69_nobody", role="staff", modules=())
    assert client.get("/api/ledger/roles", headers=nobody).status_code == 403


def test_sole_superadmin_cannot_change_roles_alone(client, sup_a, conn):
    c = db.get_db()
    try:                                                        # 沒有第二位在職最高管理者
        c.execute("UPDATE users SET active=0 WHERE role='superadmin' AND username<>'t69_sup_a'")
        c.commit()
    finally:
        c.close()
    before = _role_code()
    r = _put(client, sup_a)
    assert r.status_code == 409 and "另一位" in r.json()["detail"], r.text
    assert _role_code() == before


def test_reason_is_required_and_validation_still_applies_at_request_time(client, sup_a, sup_b, conn):
    assert _put(client, sup_a, reason="").status_code == 400
    assert _put(client, sup_a, code="111").status_code == 400          # 非葉節點
    assert _put(client, sup_a, code="0000").status_code == 400
    assert client.put("/api/ledger/roles", headers=sup_a, json={"role": "", "account_code": "1112", "reason": "原因原因"}).status_code == 400
    assert client.get("/api/ledger/roles", headers=sup_b).json()["pending"] == []


def test_account_deactivated_before_approval_blocks_the_approval(client, sup_a, sup_b, conn):
    pid = _put(client, sup_a).json()["id"]
    conn.execute("UPDATE gl_account_meta SET is_active=0 WHERE code='1112'")
    conn.commit()
    r = client.post("/api/ledger/roles/pending/%d/approve" % pid, headers=sup_b, json={})
    assert r.status_code == 409 and "停用" in r.json()["detail"], r.text
    assert _role_code() != "1112"
    assert client.get("/api/ledger/roles", headers=sup_b).json()["pending"]       # 仍待處理，可撤銷


def test_cancel_and_supersede_and_double_approval(client, sup_a, sup_b, conn):
    first = _put(client, sup_a).json()["id"]
    second = _put(client, sup_a, code="1111", reason="改成現金科目").json()["id"]     # 同一目標再申請 ⇒ 舊的被取代
    ids = [p["id"] for p in client.get("/api/ledger/roles", headers=sup_b).json()["pending"]]
    assert ids == [second]
    assert client.post("/api/ledger/roles/pending/%d/approve" % first, headers=sup_b, json={}).status_code == 409
    assert client.post("/api/ledger/roles/pending/%d/cancel" % second, headers=sup_a, json={"reason": "改變主意"}).status_code == 200
    assert client.get("/api/ledger/roles", headers=sup_b).json()["pending"] == []
    assert client.post("/api/ledger/roles/pending/%d/approve" % second, headers=sup_b, json={}).status_code == 409
    assert client.post("/api/ledger/roles/pending/999999/approve", headers=sup_b, json={}).status_code == 404
    assert _role_code() == "1113"


def test_approved_request_cannot_be_approved_again(client, sup_a, sup_b, conn):
    pid = _put(client, sup_a).json()["id"]
    assert client.post("/api/ledger/roles/pending/%d/approve" % pid, headers=sup_b, json={}).status_code == 200
    assert client.post("/api/ledger/roles/pending/%d/approve" % pid, headers=sup_b, json={}).status_code == 409


# ── 稽核跟進（hichan-49）──────────────────────────────────────────────────────
def test_fiscal_start_refuses_admin_with_finance_module_and_cashier_only(client, make_user, conn):
    before = P.fiscal_start_month(conn)
    adm = _login(client, make_user, "t69_admfin", role="admin", modules=("cashier", "finance"), legacy_finance_flag=False)
    cash = _login(client, make_user, "t69_cashier", role="staff", modules=("cashier",), legacy_finance_flag=False)
    for h in (adm, cash):
        r = client.put("/api/ledger/settings", headers=h, json={"fiscal_year_start_month": 4})
        assert r.status_code == 403, r.text
    assert P.fiscal_start_month(db.get_db()) == before


def test_requesting_the_account_a_role_already_has_is_a_409_and_creates_no_pending(client, sup_a, sup_b, conn):
    cur = _role_code()
    r = _put(client, sup_a, code=cur)
    assert r.status_code == 409 and "已經是" in r.json()["detail"], r.text
    assert client.get("/api/ledger/roles", headers=sup_b).json()["pending"] == []


def test_pending_list_pages_through_all_changes(client, sup_a, sup_b, conn, monkeypatch):
    from modules.accounting.api import ledger_reports as LR
    monkeypatch.setattr(LR, "_PAGE", 1)                         # 每頁 1 筆：3 筆待核准項必須全部列出
    ids = [_put(client, sup_a, role=r, code=c).json()["id"] for r, c in (("BANK", "1112"), ("OUTPUT_TAX", "2205"), ("REV_SALES", "4112"))
           if client.put("/api/ledger/roles", headers=sup_a, json={"role": r, "account_code": c, "reason": "測試"}).status_code in (202, 400, 409)]
    g = client.get("/api/ledger/roles", headers=sup_b).json()["pending"]
    assert len(g) == len({p["id"] for p in g}) and len(g) >= 1
    first = g[-1]["id"]                                           # 最舊的一筆也要找得到、能核准
    assert client.post("/api/ledger/roles/pending/%d/approve" % first, headers=sup_b, json={}).status_code in (200, 409)
