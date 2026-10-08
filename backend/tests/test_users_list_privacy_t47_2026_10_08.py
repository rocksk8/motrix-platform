# -*- coding: utf-8 -*-
"""GET /api/users 的敏感欄位收緊（第 47 班；使用者裁示）：一般人員（非 admin／superadmin）看別人時拿不到 email／phone／modules／notificationMuted；
自己那一列照舊；admin／superadmin 拿到完整列。其餘欄位（id、帳號、顯示名稱、角色、在職、部門）不變，頁面的人員下拉照常運作。"""
import pytest

_MAKE_USER_DEFAULT_ROLE = "superadmin"
SENSITIVE = ("email", "phone", "modules", "notificationMuted")
KEPT = ("id", "username", "displayName", "role", "active", "departmentId", "departmentName", "divisionId", "divisionName", "createdAt", "builtinAdmin")


def _db():
    import db
    return db.get_db()


@pytest.fixture
def people(client, make_user):
    out = {}
    for name, role in (("pl_sales", "sales"), ("pl_eng", "engineer"), ("pl_view", "viewer"), ("pl_admin", "admin"), ("pl_super", "superadmin")):
        u, p = make_user(username=name, role=role)
        out[name] = (u, p)
    c = _db()
    try:
        for name in out:
            c.execute("UPDATE users SET email=?, phone=?, notification_muted=? WHERE username=?",
                      (name + "@example.test", "09" + str(abs(hash(name)))[:8].ljust(8, "0"), '["quote_sent"]', name))
        c.commit()
    finally:
        c.close()
    return out


def _get(client, creds):
    tok = client.post("/api/auth/login", json={"username": creds[0], "password": creds[1]}).json()["token"]
    r = client.get("/api/users", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200, r.text
    return {u["username"]: u for u in r.json()}


@pytest.mark.parametrize("who", ["pl_sales", "pl_eng", "pl_view"])
def test_plain_users_do_not_get_other_peoples_sensitive_fields(client, people, who):
    rows = _get(client, people[who])
    assert set(people) <= set(rows), "清單仍然列出所有人（人員下拉要用）"
    for name, row in rows.items():
        if name == who:
            continue
        for k in SENSITIVE:
            assert k not in row, (who, name, k)
        for k in KEPT:
            assert k in row, (who, name, k)
    other = rows["pl_admin"]
    assert other["role"] == "admin" and other["active"] in (1, True) and other["displayName"]


@pytest.mark.parametrize("who", ["pl_sales", "pl_eng", "pl_view", "pl_admin", "pl_super"])
def test_everyone_still_gets_their_own_full_row(client, people, who):
    me = _get(client, people[who])[who]
    assert me["email"] == who + "@example.test" and me["phone"].startswith("09")
    assert me["notificationMuted"] == ["quote_sent"] and isinstance(me["modules"], list)


@pytest.mark.parametrize("who", ["pl_admin", "pl_super"])
def test_admin_and_superadmin_keep_the_full_rows(client, people, who):
    rows = _get(client, people[who])
    for name in people:
        for k in SENSITIVE + KEPT:
            assert k in rows[name], (who, name, k)
        assert rows[name]["email"] == name + "@example.test"


def test_unauthenticated_is_still_rejected(client):
    assert client.get("/api/users").status_code in (401, 403)


def test_the_selectable_endpoint_is_unchanged(client, people):
    tok = client.post("/api/auth/login", json={"username": "pl_sales", "password": people["pl_sales"][1]}).json()["token"]
    r = client.get("/api/users/selectable", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200 and {"id", "username", "display_name", "role"} <= set(r.json()[0])
    assert not any(k in r.json()[0] for k in SENSITIVE)


# ── 報價人聯絡資料（GET /api/users/sales-contact）：改選『報價人』時帶入電話／Email，不經過收緊後的使用者清單 ──────────

def _tok(client, creds):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": creds[0], "password": creds[1]}).json()["token"]}


def test_sales_contact_returns_exactly_four_fields_for_a_quotation_editor(client, people):
    h = _tok(client, people["pl_sales"])
    r = client.get("/api/users/sales-contact", params={"username": "pl_admin"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"id", "displayName", "phone", "email"} and body["email"] == "pl_admin@example.test" and body["phone"].startswith("09")
    assert client.get("/api/users/sales-contact", params={"username": "pl_super"}, headers=_tok(client, people["pl_super"])).status_code == 200


def test_sales_contact_needs_the_quotation_module(client, make_user, people):
    u, p = make_user(username="pl_nomod", role="viewer", modules=["dashboard"], legacy_finance_flag=False)
    r = client.get("/api/users/sales-contact", params={"username": "pl_admin"}, headers=_tok(client, (u, p)))
    assert r.status_code == 403 and "pl_admin@example.test" not in r.text
    assert client.get("/api/users/sales-contact", params={"username": "pl_admin"}).status_code in (401, 403)


def test_sales_contact_only_for_active_existing_users(client, people):
    c = _db()
    try:
        c.execute("UPDATE users SET active=0 WHERE username='pl_eng'")
        c.commit()
    finally:
        c.close()
    h = _tok(client, people["pl_sales"])
    assert client.get("/api/users/sales-contact", params={"username": "pl_eng"}, headers=h).status_code == 404
    assert client.get("/api/users/sales-contact", params={"username": "nobody_here"}, headers=h).status_code == 404
    assert client.get("/api/users/sales-contact", headers=h).status_code == 422
