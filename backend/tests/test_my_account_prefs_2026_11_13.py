"""「我的帳號」個人偏好（2026-11-13）：存伺服器端、換 session 仍在、只能動自己的、只收白名單。"""
import pytest


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_defaults_then_save_then_new_session_still_has_it(client, make_user):
    u, p = make_user(username="pref_a", role="sales")
    h1 = _login(client, u, p)
    d = client.get("/api/auth/preferences", headers=h1).json()
    assert d["prefs"]["login_greeting"] == "follow_company" and d["prefs"]["font_size"] == "normal"
    assert {c["value"] for c in d["options"]["login_greeting"]["choices"]} == {"follow_company", "humor", "formal", "off"}
    r = client.put("/api/auth/preferences", json={"login_greeting": "off", "font_size": "large", "home_page": "quotations.html"}, headers=h1)
    assert r.status_code == 200 and r.json()["prefs"]["font_size"] == "large"
    h2 = _login(client, u, p)                                  # 另一個 session（等同換裝置）
    assert client.get("/api/auth/preferences", headers=h2).json()["prefs"]["login_greeting"] == "off"


def test_only_whitelisted_keys_and_values(client, make_user):
    u, p = make_user(username="pref_b", role="viewer")
    h = _login(client, u, p)
    for bad in ({"nope": "x"}, {"font_size": "huge"}, {"home_page": "../../etc/passwd"}, {"theme": 1}, {}):
        assert client.put("/api/auth/preferences", json=bad, headers=h).status_code == 422, bad
    assert client.get("/api/auth/preferences", headers=h).json()["prefs"]["font_size"] == "normal"


def test_each_user_sees_only_their_own(client, make_user):
    ua, pa = make_user(username="pref_c1", role="sales")
    ub, pb = make_user(username="pref_c2", role="admin")
    ha, hb = _login(client, ua, pa), _login(client, ub, pb)
    client.put("/api/auth/preferences", json={"theme": "dark"}, headers=ha)
    assert client.get("/api/auth/preferences", headers=hb).json()["prefs"]["theme"] == "light"
    assert client.get("/api/auth/preferences", headers=ha).json()["prefs"]["theme"] == "dark"


def test_requires_login(client):
    assert client.get("/api/auth/preferences").status_code == 401
    assert client.put("/api/auth/preferences", json={"theme": "dark"}).status_code == 401


def test_helper_for_greeting_reads_the_same_value(client, make_user):
    from helpers import user_prefs as UP
    from db import get_db
    u, p = make_user(username="pref_d", role="sales")
    h = _login(client, u, p)
    conn = get_db(); uid = conn.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()["id"]; conn.close()
    assert UP.get(uid, "login_greeting", default="follow_company") == "follow_company"
    client.put("/api/auth/preferences", json={"login_greeting": "humor"}, headers=h)
    assert UP.get(uid, "login_greeting") == "humor"
    with pytest.raises(KeyError):
        UP.get(uid, "not_a_key")
