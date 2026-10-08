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
