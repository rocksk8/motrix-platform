"""2026-09-11（DB v74）：`webauthn_credentials.rp_id` —— 讓「RP ID 變更導致
Passkey 全滅」這件事變成可見、可通知、可清理。

背景：Passkey 憑證被瀏覽器綁在「註冊當下那個 RP ID」上。v73 建表時沒存 rp_id，
於是 RP ID 一變更，系統**查不出**哪幾張失效——只能對使用者說「全部都可能不能
用了」，而使用者在裝置清單看到的是一張外觀完全正常、實際上永遠驗不過的殭屍憑證，
登入失敗也只回一句概括的「認證失敗」。

⚠️ 這個欄位**救不回**已經簽發的憑證（綁定在瀏覽器端，不在我們手上）。本檔釘住
的是「失效之後系統講不講得清楚」，不是「失效可不可逆」——別把這兩件事搞混。

釘住五件事：
  1. 註冊時會記下當下的 RP ID
  2. login/begin 不把舊 RP ID 的憑證交給瀏覽器；且**對外錯誤訊息維持統一**
     （不能因為「有失效的憑證」就洩漏帳號存在——`0527524` 修掉的就是這種枚舉）
  3. login/complete 對失效憑證回**明確原因**，不再是籠統的「認證失敗」
  4. 裝置清單標得出 stale
  5. 設定端點回報的是**精準張數與人數**，不是全表張數
"""
from datetime import datetime

import pytest

# ── 2026-09-16：Passkey 功能暫緩使用（使用者裁示）───────────────────────────
# 整檔 skip，**不是刪掉、也不是 xfail**：程式碼與資料表都原樣留著，開關一開
# 這些測試就要立刻跟著回來把關。xfail 會讓功能恢復後的真實失敗被當成預期失敗
# 而靜靜吞掉，刪掉則是恢復時沒有任何東西守著。
#
# 開關在 backend/helpers/auth.py::PASSKEY_ENABLED。
# ⚠️ 「停用本身有沒有生效」由 tests/test_passkey_disabled_2026_09_16.py 驗，
# 那一檔**不會**被這個開關 skip——否則整組 Passkey 測試全 skip 時，端點是真的
# 回 404 還是路由根本壞了，沒有任何一題分得出來。
from helpers.auth import PASSKEY_ENABLED

pytestmark = pytest.mark.skipif(
    not PASSKEY_ENABLED,
    reason="Passkey 功能暫緩（backend/helpers/auth.py::PASSKEY_ENABLED=False）")



def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _set_rp(rp_id, origin=None):
    from helpers.settings import _set_setting
    _set_setting("webauthn_rp_id", rp_id)
    _set_setting("webauthn_origin", origin or f"https://{rp_id}")


def _user_id(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _seed_cred(username, rp_id, cred_id=b"\x01\x02\x03", name="測試裝置"):
    """直接種一張憑證——真的跑完 WebAuthn 註冊需要認證器，那是 e2e 的事
    （`test_e2e_passkey_2026_09_11.py`）。這裡要驗的是 rp_id 欄位的行為。"""
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO webauthn_credentials "
            "(user_id, credential_id, public_key, name, created_at, rp_id) "
            "VALUES (?,?,?,?,?,?)",
            (_user_id(username), cred_id, b"fake-public-key", name,
             datetime.now().isoformat(), rp_id),
        )
        conn.commit()
    finally:
        conn.close()


# ── 1. schema 與註冊路徑 ─────────────────────────────────────────────────────

def test_column_exists_and_defaults_empty(client):
    """v74 欄位存在，且預設空字串（不是 NULL——查詢端一律用 != '' 判斷）。"""
    import db
    conn = db.get_db()
    try:
        cols = {r["name"]: r for r in conn.execute(
            "PRAGMA table_info(webauthn_credentials)").fetchall()}
    finally:
        conn.close()
    assert "rp_id" in cols, "DB v74 應新增 rp_id 欄位"
    assert cols["rp_id"]["notnull"] == 1
    assert cols["rp_id"]["dflt_value"] in ("''", '""')


def test_schema_version_is_at_least_74(client):
    import db
    assert db.CURRENT_VERSION >= 74


def _v73_shaped_db(path):
    """建一個 v74 之前形狀的資料庫（webauthn_credentials 沒有 rp_id）。"""
    import sqlite3
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE system_settings (
            key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT);
        CREATE TABLE webauthn_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            credential_id BLOB NOT NULL UNIQUE,
            public_key BLOB NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            sign_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_used_at TEXT);
    """)
    conn.commit()
    return conn


def test_migration_backfills_existing_rows(tmp_path):
    """⭐ 升級路徑：正式機跑的是這條，不是全新建庫。

    既有那幾張憑證都是在目前這組設定下註冊的，回填成當前 RP ID 才是事實；
    留空的話它們會被永遠當成「與現行相符」，等於這個欄位對既有資料完全沒作用
    ——而既有資料正是唯一真的存在的資料。
    """
    import db
    conn = _v73_shaped_db(tmp_path / "v73.db")
    conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)",
                 ("webauthn_rp_id", '"motrix.internal"', "2026-09-11T00:00:00"))
    conn.execute("INSERT INTO webauthn_credentials "
                 "(user_id, credential_id, public_key, name, created_at) VALUES (?,?,?,?,?)",
                 (1, b"\x01", b"k", "既有裝置", "2026-09-11T00:10:00"))
    conn.commit()

    db._m074_webauthn_rp_id(conn)

    row = conn.execute("SELECT rp_id FROM webauthn_credentials").fetchone()
    assert row["rp_id"] == "motrix.internal", "既有憑證未回填成當前 RP ID"
    conn.close()


def test_migration_leaves_blank_when_rp_unconfigured(tmp_path):
    """RP ID 還沒設定過就升級 → 留空（不明），不能亂填一個值進去。"""
    import db
    conn = _v73_shaped_db(tmp_path / "v73b.db")
    conn.execute("INSERT INTO webauthn_credentials "
                 "(user_id, credential_id, public_key, name, created_at) VALUES (?,?,?,?,?)",
                 (1, b"\x02", b"k", "裝置", "2026-09-11T00:10:00"))
    conn.commit()

    db._m074_webauthn_rp_id(conn)

    assert conn.execute("SELECT rp_id FROM webauthn_credentials").fetchone()["rp_id"] == ""
    conn.close()


def test_migration_is_idempotent(tmp_path):
    """重跑不能炸（ALTER TABLE ADD COLUMN 對已存在的欄位會直接報錯）。"""
    import db
    conn = _v73_shaped_db(tmp_path / "v73c.db")
    conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)",
                 ("webauthn_rp_id", '"a.example"', "2026-09-11T00:00:00"))
    conn.commit()
    db._m074_webauthn_rp_id(conn)
    db._m074_webauthn_rp_id(conn)      # 第二次不能爆
    conn.close()


def test_migration_does_not_overwrite_known_rp_id(tmp_path):
    """已經有值的列不能被回填蓋掉（只補 rp_id='' 的）。"""
    import db
    conn = _v73_shaped_db(tmp_path / "v73d.db")
    conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)",
                 ("webauthn_rp_id", '"new.example"', "2026-09-11T00:00:00"))
    conn.execute("ALTER TABLE webauthn_credentials ADD COLUMN rp_id TEXT NOT NULL DEFAULT ''")
    conn.execute("INSERT INTO webauthn_credentials "
                 "(user_id, credential_id, public_key, name, created_at, rp_id) VALUES (?,?,?,?,?,?)",
                 (1, b"\x03", b"k", "裝置", "2026-09-11T00:10:00", "old.example"))
    conn.commit()

    db._m074_webauthn_rp_id(conn)

    assert conn.execute("SELECT rp_id FROM webauthn_credentials").fetchone()["rp_id"] == "old.example"
    conn.close()


def test_registration_records_current_rp_id(client, make_user):
    """註冊時記下當下的 RP ID。

    這一題刻意不走真的 WebAuthn 註冊（需要認證器），改成直接驗 INSERT 語句
    有沒有帶 rp_id——漏帶的話欄位會靜靜留空，而空值被視為「與現行相符」，
    症狀是「換了 RP ID 卻沒有任何憑證被標成失效」，非常難察覺。
    """
    import inspect
    import routers.auth as auth
    src = inspect.getsource(auth.webauthn_register_complete)
    assert "rp_id" in src, "register/complete 的 INSERT 沒有帶 rp_id"
    assert "_webauthn_rp_id()" in src


# ── 2. login/begin：擋掉失效憑證，但不洩漏帳號存在 ──────────────────────────

def test_login_begin_ignores_stale_credentials(client, make_user):
    """帳號只有舊 RP ID 的憑證 → 不能把它交給瀏覽器（交了也一定驗不過）。"""
    username, _ = make_user(role="staff")
    _set_rp("old.internal")
    _seed_cred(username, "old.internal")
    _set_rp("erp.miactw.com")

    r = client.post("/api/auth/webauthn/login/begin", json={"username": username})
    assert r.status_code == 404, r.text


def test_login_begin_error_is_indistinguishable_from_unknown_user(client, make_user):
    """⭐ 「憑證全部失效」與「帳號根本不存在」對外必須是**同一個**回應。

    這裡若照實說「你的 Passkey 已失效」，等於確認了這個帳號存在、而且註冊過
    Passkey——正是 `0527524` 修掉的用戶枚舉漏洞。真相要留給登入後的裝置清單。
    """
    username, _ = make_user(role="staff")
    _set_rp("old.internal")
    _seed_cred(username, "old.internal")
    _set_rp("erp.miactw.com")

    stale = client.post("/api/auth/webauthn/login/begin", json={"username": username})
    unknown = client.post("/api/auth/webauthn/login/begin",
                          json={"username": "no_such_user_at_all"})
    assert stale.status_code == unknown.status_code
    assert stale.json() == unknown.json(), "回應內容不同 → 可用來判斷帳號是否存在"


def test_login_begin_still_works_for_current_rp(client, make_user):
    """同一個 RP ID 下註冊的憑證照常可用（別把好的一起擋掉）。"""
    username, _ = make_user(role="staff")
    _set_rp("erp.miactw.com")
    _seed_cred(username, "erp.miactw.com")

    r = client.post("/api/auth/webauthn/login/begin", json={"username": username})
    assert r.status_code == 200, r.text
    assert len(r.json()["options"]["allowCredentials"]) == 1


def test_legacy_blank_rp_id_is_treated_as_current(client, make_user):
    """v74 之前留下的 rp_id='' 來源不明 → 一律當成相符，不能擋掉還能用的憑證。"""
    username, _ = make_user(role="staff")
    _set_rp("erp.miactw.com")
    _seed_cred(username, "")

    r = client.post("/api/auth/webauthn/login/begin", json={"username": username})
    assert r.status_code == 200, r.text


def test_login_begin_offers_only_the_current_rp_credential(client, make_user):
    """同時有舊、新兩張時，只交出新的那張。"""
    username, _ = make_user(role="staff")
    _set_rp("erp.miactw.com")
    _seed_cred(username, "old.internal", cred_id=b"\xAA\xAA")
    _seed_cred(username, "erp.miactw.com", cred_id=b"\xBB\xBB")

    r = client.post("/api/auth/webauthn/login/begin", json={"username": username})
    assert r.status_code == 200, r.text
    assert len(r.json()["options"]["allowCredentials"]) == 1


# ── 3. login/complete：失效要講清楚 ─────────────────────────────────────────

def test_login_complete_explains_stale_credential(client, make_user):
    """走到 complete 代表對方握有真實的 credential_id，不是枚舉探測 → 可以講原因。

    少了這段，py_webauthn 會丟一個 rpIdHash 不符的例外，被概括的 except 收斂成
    一句「認證失敗」——2026-09-11 那四個根因全都是被這種籠統錯誤蓋掉才拖了那麼久。
    """
    import base64
    username, password = make_user(role="staff")
    _set_rp("old.internal")
    _seed_cred(username, "old.internal", cred_id=b"\x11\x22\x33")
    _set_rp("erp.miactw.com")

    # 先合法取得一個 challenge token（用另一張現行 RP 的憑證讓 begin 過關）
    _seed_cred(username, "erp.miactw.com", cred_id=b"\x99\x99")
    begin = client.post("/api/auth/webauthn/login/begin", json={"username": username})
    assert begin.status_code == 200, begin.text
    token = begin.json()["challengeToken"]

    raw_id = base64.urlsafe_b64encode(b"\x11\x22\x33").decode().rstrip("=")
    r = client.post("/api/auth/webauthn/login/complete", json={
        "username": username, "challengeToken": token,
        "id": raw_id, "rawId": raw_id, "type": "public-key",
        "response": {"clientDataJSON": "", "authenticatorData": "", "signature": ""},
    })
    assert r.status_code == 401
    detail = r.json()["detail"]
    assert "舊" in detail and "重新註冊" in detail, f"錯誤訊息沒說清楚原因：{detail}"
    assert detail != "認證失敗"


# ── 4. 裝置清單標記 ──────────────────────────────────────────────────────────

def test_credentials_list_marks_stale(client, make_user):
    username, password = make_user(role="staff")
    _set_rp("old.internal")
    _seed_cred(username, "old.internal", cred_id=b"\xAA", name="舊筆電")
    _set_rp("erp.miactw.com")
    _seed_cred(username, "erp.miactw.com", cred_id=b"\xBB", name="新筆電")

    token = _login(client, username, password)
    rows = client.get("/api/auth/webauthn/credentials", headers=_auth(token)).json()
    by_name = {r["name"]: r for r in rows}
    assert by_name["舊筆電"]["stale"] is True
    assert by_name["新筆電"]["stale"] is False


def test_credentials_list_not_stale_when_rp_unconfigured(client, make_user):
    """RP ID 清空（Passkey 停用中）時不要把憑證標成失效——那是停用，不是失效。"""
    username, password = make_user(role="staff")
    _set_rp("erp.miactw.com")
    _seed_cred(username, "erp.miactw.com")
    _set_rp("", "")

    token = _login(client, username, password)
    rows = client.get("/api/auth/webauthn/credentials", headers=_auth(token)).json()
    assert all(r["stale"] is False for r in rows)


# ── 5. 設定端點回報精準張數 ──────────────────────────────────────────────────

def test_config_change_reports_exact_counts(client, make_user):
    """⭐ 回報的是「真正會失效的那幾張」，不是全表張數。

    改成精準計算之前，這裡是 `SELECT COUNT(*) FROM webauthn_credentials`——
    只有一種 RP ID 時剛好等於正確答案，一旦出現兩種以上就會高估，而且說不出是誰。
    """
    su, su_pw = make_user(username="rp_su", role="superadmin")
    other, _ = make_user(username="rp_other", role="staff")

    _set_rp("old.internal")
    _seed_cred(su, "old.internal", cred_id=b"\x01")
    _seed_cred(other, "old.internal", cred_id=b"\x02")
    _seed_cred(other, "erp.miactw.com", cred_id=b"\x03")   # 已經在新網域註冊過

    token = _login(client, su, su_pw)
    r = client.patch("/api/settings/webauthn-config",
                     json={"rp_id": "erp.miactw.com", "origin": "https://erp.miactw.com:666"},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["invalidatedCredentials"] == 2, "應只算舊 RP 的兩張，不是全表三張"
    assert body["affectedUsers"] == 2


def test_config_change_excludes_unknown_provenance(client, make_user):
    """`rp_id=''`（來源不明）不列入失效張數——這是刻意的，不是漏算。

    理由：v74 的回填會把「RP ID 已設定」環境裡的既有憑證全部填好，而 RP ID
    沒設定時根本註冊不了（四個端點回 503）。所以正式環境不會有 '' 的列；
    真的出現就代表來源不明，此時**寧可少報也不要謊報「已失效、無法復原」**
    ——那句話會讓人去刪掉可能還能用的憑證。

    對稱地看另一邊：登入路徑（login/begin／stale 標記）把 '' 當成「相符」，
    也是同一個原則的另一面——不確定時不要把人鎖在門外。
    """
    su, su_pw = make_user(username="rp_su2", role="superadmin")
    _set_rp("old.internal")
    _seed_cred(su, "", cred_id=b"\x77")          # 來源不明

    token = _login(client, su, su_pw)
    r = client.patch("/api/settings/webauthn-config",
                     json={"rp_id": "erp.miactw.com", "origin": "https://erp.miactw.com:666"},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["invalidatedCredentials"] == 0


def test_config_change_counts_zero_when_rp_unchanged(client, make_user):
    su, su_pw = make_user(role="superadmin")
    _set_rp("erp.miactw.com", "https://erp.miactw.com:666")
    _seed_cred(su, "erp.miactw.com")

    token = _login(client, su, su_pw)
    r = client.patch("/api/settings/webauthn-config",
                     json={"rp_id": "erp.miactw.com", "origin": "https://erp.miactw.com:666"},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["invalidatedCredentials"] == 0
