# -*- coding: utf-8 -*-
"""A29 稽核探針 R1：員工收款帳號（W3，payroll bank_account）角色矩陣、reveal、稽核不含全碼（包 47db5613；不進倉庫）。"""
import json

import pytest

FULL = "12345678901234"
BODY = {"bankCode": "700", "bankName": "中華郵政", "bankBranch": "台中", "accountName": "王小明", "accountNumber": FULL}


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def world(client, make_user):
    import db
    users = {"me": make_user(username="b1_me", role="user", modules=[]),
             "other": make_user(username="b1_other", role="user", modules=[]),
             "admin": make_user(username="b1_admin", role="admin", modules=[]),
             "fin": make_user(username="b1_fin", role="user", modules=["finance"]),
             "cash": make_user(username="b1_cash", role="user", modules=["cashier"]),
             "sa": make_user(username="b1_sa", role="superadmin")}
    h = {k: _login(client, v[0], v[1]) for k, v in users.items()}
    r = client.put("/api/me/bank-account", headers=h["me"], json=BODY)
    assert r.status_code == 200, r.text
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='b1_me'").fetchone()[0]
    finally:
        conn.close()
    return client, h, uid


def _audit_text():
    import db
    conn = db.get_db()
    try:
        return json.dumps([dict(r) for r in conn.execute("SELECT * FROM audit_log").fetchall()], ensure_ascii=False, default=str)
    finally:
        conn.close()


def test_self_full_others_denied_or_masked(world):
    client, h, uid = world
    mine = client.get("/api/me/bank-account", headers=h["me"]).json()["account"]
    assert mine["accountNumber"] == FULL                                                  # 本人完整
    for who in ("other", "admin"):                                                         # 無資格（含沒有財務模組的 admin）⇒ 404，不洩漏有沒有帳號
        assert client.get("/api/bank-accounts/%d" % uid, headers=h[who]).status_code == 404, who
        assert client.get("/api/bank-accounts", headers=h[who]).status_code == 404, who
        assert client.get("/api/bank-accounts/%d/history" % uid, headers=h[who]).status_code == 404, who
        assert client.put("/api/bank-accounts/%d" % uid, headers=h[who], json=BODY).status_code == 404, who
    for who in ("fin", "cash", "sa"):                                                      # 有資格者：預設遮蔽
        r = client.get("/api/bank-accounts/%d" % uid, headers=h[who])
        assert r.status_code == 200, (who, r.text)
        assert FULL not in r.text, (who, "預設就回了完整帳號")
        assert r.json()["account"]["last4"] == FULL[-4:]


def test_reveal_requires_qualification_and_is_audited_without_full_number(world):
    client, h, uid = world
    for who in ("fin", "cash", "sa"):
        r = client.get("/api/bank-accounts/%d?reveal=1" % uid, headers=h[who])
        assert r.status_code == 200 and FULL in r.text, (who, "有資格者 reveal 應回完整")
    assert client.get("/api/bank-accounts/%d?reveal=1" % uid, headers=h["admin"]).status_code == 404
    assert client.get("/api/bank-accounts/%d?reveal=1" % uid, headers=h["other"]).status_code == 404
    import db
    conn = db.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action LIKE '%bank%reveal%' OR action LIKE '%bank_account%reveal%'").fetchone()[0]
    finally:
        conn.close()
    assert n >= 3, "reveal 沒有每次寫稽核（找到 %d 筆）" % n
    assert FULL not in _audit_text(), "稽核表裡出現帳號全碼"


def test_edit_others_only_superadmin_or_finance_and_audit_has_last4_only(world):
    client, h, uid = world
    new = dict(BODY, accountNumber="99998888777766")
    assert client.put("/api/bank-accounts/%d" % uid, headers=h["cash"], json=new).status_code == 404       # 出納只能看、不能改
    assert client.put("/api/bank-accounts/%d" % uid, headers=h["fin"], json=new).status_code == 200
    assert client.put("/api/bank-accounts/%d" % uid, headers=h["sa"], json=BODY).status_code == 200
    hist = client.get("/api/bank-accounts/%d/history" % uid, headers=h["fin"])
    assert hist.status_code == 200
    for full in (FULL, "99998888777766"):
        assert full not in hist.text, "歷史回了帳號全碼"
        assert full not in _audit_text(), "稽核含全碼"
    bad = dict(BODY, accountNumber="12ab")
    assert client.put("/api/me/bank-account", headers=h["me"], json=bad).status_code == 400                  # 驗證
