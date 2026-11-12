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


# ── 個人資料（唯讀）與頁面結構 ────────────────────────────────────────────────

def _set_contact(username, email, phone):
    from db import get_db
    conn = get_db()
    conn.execute("UPDATE users SET email=?, phone=? WHERE username=?", (email, phone, username))
    conn.commit(); conn.close()


def test_profile_returns_only_own_data_and_has_no_write_endpoint(client, make_user):
    ua, pa = make_user(username="prof_a", role="sales")
    ub, pb = make_user(username="prof_b", role="admin")
    _set_contact(ua, "a@x.test", "02-1111")
    _set_contact(ub, "b@x.test", "02-2222")
    ha, hb = _login(client, ua, pa), _login(client, ub, pb)
    da = client.get("/api/auth/profile", headers=ha).json()
    assert da["username"] == "prof_a" and da["email"] == "a@x.test" and da["phone"] == "02-1111" and da["role"] == "sales"
    assert client.get("/api/auth/profile", headers=hb).json()["email"] == "b@x.test"
    assert set(da) == {"username", "displayName", "role", "department", "email", "phone", "quoteEmail", "quoteEmailEffective", "quoteEmailSource"}     # 不洩漏密碼雜湊、權限勾選等
    for m in ("put", "patch", "post"):                                                         # 唯讀：沒有任何寫入端點
        assert getattr(client, m)("/api/auth/profile", json={"email": "evil@x.test"}, headers=ha).status_code in (404, 405)
    assert client.get("/api/auth/profile", headers=ha).json()["email"] == "a@x.test"
    assert client.get("/api/auth/profile").status_code == 401


def test_avatar_color_is_a_pref_and_validated(client, make_user):
    u, p = make_user(username="prof_c", role="viewer")
    h = _login(client, u, p)
    assert client.get("/api/auth/preferences", headers=h).json()["prefs"]["avatar_color"] == "auto"
    assert client.put("/api/auth/preferences", json={"avatar_color": "purple"}, headers=h).status_code == 200
    assert client.put("/api/auth/preferences", json={"avatar_color": "#ff0000"}, headers=h).status_code == 422
    assert client.get("/api/auth/preferences", headers=_login(client, u, p)).json()["prefs"]["avatar_color"] == "purple"


def test_old_change_password_url_redirects_to_my_account_security_tab():
    from core import source_tree
    stub = source_tree.page_file("change-password.html").read_text(encoding="utf-8")
    assert "my-account.html" in stub and "location.replace" in stub and "'security'" in stub
    assert "forced" in stub or "URLSearchParams" in stub          # 帶著 forced／wizard 參數轉過去
    assert len(stub) < 2000                                        # 只是轉址殼，不再放功能


def test_my_account_page_structure():
    from core import source_tree
    src = source_tree.page_file("my-account.html").read_text(encoding="utf-8")
    for tid in ("tab-profile", "tab-security", "tab-notify", "tab-prefs"):
        assert f'data-testid="{tid}"' in src, tid
    assert "此資料由管理者維護，會顯示在報價單上" in src
    assert "id=\"line-bind-card\"" in src and "lineBindCard()" in src     # LINE 卡原樣搬到通知分頁
    # 個人資料分頁沒有任何可編輯的聯絡欄位（顯示名稱／Email／電話全 disabled）
    prof = src[src.index('data-testid="tab-profile"'):src.index('data-testid="tab-prefs"')]
    for m in __import__("re").finditer(r"<input[^>]*>", prof):
        assert "disabled" in m.group(0), m.group(0)[:100]
