# -*- coding: utf-8 -*-
"""全新安裝的預設值（2026-09-27 H10，主持裁示）。

1. 預設管理員：全新安裝（users 表是空的）建 `admin`；既有安裝（包括本公司正式機、V9 升級）的 `jeff` 完全不動
   （不改名、不補姓名與 email）。不可刪除／停用的「預設管理員」跟著安裝資訊走。
2. 版本紀錄：全新安裝只顯示安裝基準版本之後的系統紀錄；沒有安裝基準的既有安裝照舊全部顯示；
   判定在後端（routers/module_versions.py），使用者自己新增的紀錄一律顯示。
觀測點：users 表、system_settings 的 install_info、API 回應的列（不是頁面）。
"""
import pytest


@pytest.fixture()
def no_cred_file(monkeypatch):
    """初始憑證檔寫到真的 backend/ ⇒ 換成記錄呼叫。"""
    import helpers.startup as st
    calls = []
    monkeypatch.setattr(st, "_write_initial_credentials", lambda u, p, path=None: calls.append(u) or "<test>")
    return calls


def _users():
    import db
    conn = db.get_db()
    try:
        return {r["username"]: dict(r) for r in conn.execute(
            "SELECT username, display_name, email, role, active FROM users")}
    finally:
        conn.close()


def _exec(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _hdr(client, make_user, username, role="superadmin"):
    u = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u[0], "password": u[1]})
    return {"Authorization": "Bearer " + r.json()["token"]}


# ── 1. 預設管理員 ──────────────────────────────────────────────────────────

def test_fresh_install_creates_admin_not_jeff(client, no_cred_file):
    import helpers.startup as st
    _exec("DELETE FROM users")
    st.init_default_admin()
    users = _users()
    assert set(users) == {"admin"}, users
    assert users["admin"]["role"] == "superadmin"
    assert users["admin"]["display_name"] == "系統管理員" and users["admin"]["email"] == ""
    info = st.install_info()
    assert info["adminUsername"] == "admin"
    versions = [e["version"] for e in st._manifest_entries()]
    assert info["baselineVersion"] == max(versions, key=st.version_sort_key)
    assert no_cred_file == ["admin"]
    # 重啟：不重建、不改安裝資訊
    st.init_default_admin()
    assert set(_users()) == {"admin"} and st.install_info() == info
    # admin 不見了 ⇒ 補回的是 admin，不是 jeff
    _exec("DELETE FROM users")
    st.init_default_admin()
    assert set(_users()) == {"admin"}


def test_existing_install_keeps_jeff_untouched(client, no_cred_file):
    """既有安裝（已有帳號、沒有安裝資訊）：jeff 在 ⇒ 什麼都不做；姓名與 email 空著也不補；不寫安裝資訊。"""
    import helpers.startup as st
    _exec("DELETE FROM users")
    _exec("INSERT INTO users (username, password_hash, display_name, role, email, modules, active, created_at) "
          "VALUES ('jeff', 'x', '', 'superadmin', '', '[]', 1, '2026-01-01'), "
          "('someone', 'x', '某人', 'admin', '', '[]', 1, '2026-01-01')")
    before = _users()
    st.init_default_admin()
    assert _users() == before
    assert st.install_info() == {} and st.builtin_admin_username() == "jeff"
    assert st.install_baseline_version() == ""
    assert no_cred_file == []


def test_existing_install_without_jeff_behaves_as_before(client, no_cred_file):
    """反向：已有帳號、沒有安裝資訊、jeff 不在 ⇒ 照舊補 jeff（不因為這次改版變成建 admin）。"""
    import helpers.startup as st
    _exec("DELETE FROM users")
    _exec("INSERT INTO users (username, password_hash, display_name, role, email, modules, active, created_at) "
          "VALUES ('someone', 'x', '某人', 'admin', '', '[]', 1, '2026-01-01')")
    st.init_default_admin()
    assert set(_users()) == {"someone", "jeff"}
    assert st.install_info() == {}


def test_builtin_admin_protection_follows_install_info(client, make_user):
    from helpers.settings import _set_setting
    sa = _hdr(client, make_user, "ida_sa")
    for name in ("jeff", "admin"):
        _exec("INSERT INTO users (username, password_hash, display_name, role, email, modules, active, created_at) "
              "VALUES (?, 'x', ?, 'superadmin', '', '[]', 1, '2026-01-01')", (name, name))
    ids = {u["username"]: u for u in client.get("/api/users", headers=sa).json()}
    # 既有安裝：jeff 受保護，名叫 admin 的一般帳號不受保護
    assert ids["jeff"]["builtinAdmin"] is True and ids["admin"]["builtinAdmin"] is False
    assert client.patch("/api/users/%d/active" % ids["jeff"]["id"], headers=sa).status_code == 400
    assert client.patch("/api/users/%d/active" % ids["admin"]["id"], headers=sa).status_code == 200
    # 全新安裝：admin 受保護
    _set_setting("install_info", {"adminUsername": "admin", "baselineVersion": "2026-09-27b"})
    ids = {u["username"]: u for u in client.get("/api/users", headers=sa).json()}
    assert ids["admin"]["builtinAdmin"] is True and ids["jeff"]["builtinAdmin"] is False
    assert client.delete("/api/users/%d" % ids["admin"]["id"], headers=sa).status_code == 400
    assert client.patch("/api/users/%d/active" % ids["admin"]["id"], headers=sa).status_code == 400


# ── 2. 版本紀錄的安裝基準 ──────────────────────────────────────────────────

def _seed_versions():
    rows = [("H10測試", "2026-09-20a", "system"), ("H10測試", "2026-09-27b", "system"),
            ("H10測試", "2026-09-28a", "system"), ("H10測試", "2026-01-01a", "someone"),
            ("H10測試", "v1.2", "someone")]
    for m, v, by in rows:
        _exec("INSERT INTO module_versions (module, version, updated_at, content, updated_by) VALUES (?,?,?,?,?)",
              (m, v, v[:10] if v[0].isdigit() else "2026-09-29", "x", by))


def _visible(client, hdr):
    r = client.get("/api/module-versions", headers=hdr)
    assert r.status_code == 200, r.text
    g = next((x for x in r.json() if x["module"] == "H10測試"), {"history": []})
    return sorted(h["version"] for h in g["history"])


def test_existing_install_shows_every_version_entry(client, make_user):
    _seed_versions()
    hdr = _hdr(client, make_user, "idv_all")
    assert _visible(client, hdr) == ["2026-01-01a", "2026-09-20a", "2026-09-27b", "2026-09-28a", "v1.2"]


def test_fresh_install_hides_system_entries_up_to_the_baseline(client, make_user):
    from helpers.settings import _set_setting
    _seed_versions()
    _set_setting("install_info", {"adminUsername": "admin", "baselineVersion": "2026-09-27b"})
    hdr = _hdr(client, make_user, "idv_fresh")
    # 基準（含）之前的系統紀錄不顯示；之後的與使用者自己新增的照常顯示
    assert _visible(client, hdr) == ["2026-01-01a", "2026-09-28a", "v1.2"]
    # 已出貨的條目本身沒有被改寫或刪除（只是不列）
    import db
    conn = db.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) FROM module_versions WHERE module='H10測試'").fetchone()[0]
    finally:
        conn.close()
    assert n == 5


def test_version_sort_key_handles_multi_letter_suffix():
    from helpers.startup import version_sort_key as k
    assert k("2026-09-27aa") > k("2026-09-27z") > k("2026-09-27a") > k("2026-09-26zz")
    assert k("v1.2") == ("", 0, "")
