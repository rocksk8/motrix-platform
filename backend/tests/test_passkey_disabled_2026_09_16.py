"""Passkey 功能暫緩（2026-09-16 使用者裁示）——驗證「停用」本身真的生效。

這一檔**刻意不被 PASSKEY_ENABLED skip**，其他五個 Passkey 測試檔則整檔 skip。
理由是假綠燈：那五檔全部 skip 之後，端點是真的被開關擋成 404、還是路由被改壞
／打錯字而不存在，沒有任何一題分得出來——兩種情況在測試報告上長得一模一樣。

所以這裡每一題停用態的斷言，都配一題把開關 monkeypatch 回 True 的反向斷言：
404 必須在開關打開後消失。只驗「回 404」是驗不出東西的，路由拼錯也會 404。

停用的語意是**暫停**，不是移除：webauthn_credentials 資料表與既有憑證列原樣
保留，也仍然留在每日 JSON 備份清單裡——最後兩題守這件事，避免日後有人把
「功能關掉了」誤讀成「資料可以不用備份了」。
"""
from datetime import datetime

import pytest

from helpers.auth import PASSKEY_ENABLED

_DISABLED_ONLY = pytest.mark.skipif(
    PASSKEY_ENABLED, reason="Passkey 功能目前是啟用的，停用態不適用")


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def su(client, make_user):
    """superadmin 的 token 與 user_id（插憑證列要用 user_id）。"""
    username, password = make_user("pk_off_su", role="superadmin")
    token = _login(client, username, password)
    import db
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()
    return {"token": token, "id": uid}


@pytest.fixture()
def cred_id(su):
    """插一筆真實憑證列，讓 /credentials/{id} 那兩支端點有東西可以操作。

    **沒有它，反向驗證會退化成假綠燈**：`DELETE /api/auth/webauthn/credentials/1`
    在功能開啟時也回 404（查無此憑證），跟「功能被關掉」的 404 完全一樣，
    那一題就永遠是綠的、卻什麼都沒驗到。用真的存在的 id，開關打開時才會走到
    業務邏輯並回 200。
    """
    import db
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO webauthn_credentials "
            "(user_id, credential_id, public_key, name, sign_count, created_at, rp_id) "
            "VALUES (?, ?, ?, ?, 0, ?, '')",
            (su["id"], b"\x01\x02\x03\x04", b"\xa5" * 32, "測試金鑰",
             datetime.now().isoformat()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


@pytest.fixture()
def enabled(monkeypatch):
    """把開關暫時打開——驗證 404 是開關造成的，不是路由不存在。

    patch 的是 `helpers.auth` 的模組屬性，不是 router 裡的名稱：守門是在呼叫
    當下讀 `_auth_helpers.PASSKEY_ENABLED`，就是為了讓這件事測得到。
    """
    import helpers.auth
    monkeypatch.setattr(helpers.auth, "PASSKEY_ENABLED", True)


# 停用期間必須回 404 的端點。body 一律送 {}（不合格）是**刻意的**：
# 見下面 test_disabled_endpoints_do_not_leak_schema_via_422。
_WEBAUTHN_ENDPOINTS = [
    ("post",   "/api/auth/webauthn/register/begin",     True),
    ("post",   "/api/auth/webauthn/register/complete",  True),
    ("post",   "/api/auth/webauthn/login/begin",        False),
    ("post",   "/api/auth/webauthn/login/complete",     False),
    ("get",    "/api/auth/webauthn/credentials",        True),
]


def _call(client, method, path, token=None, json_body=None):
    kwargs = {"headers": _auth(token)} if token else {}
    if method in ("post", "patch"):
        kwargs["json"] = json_body if json_body is not None else {}
    return getattr(client, method)(path, **kwargs)


# ── 停用態 ────────────────────────────────────────────────────────────────────

@_DISABLED_ONLY
@pytest.mark.parametrize("method,path,needs_auth", _WEBAUTHN_ENDPOINTS)
def test_webauthn_endpoints_are_404_while_disabled(client, su, method, path, needs_auth):
    """/api/auth/webauthn/* 在停用期間一律 404。

    404 而不是 403/503 是刻意的：503「尚未設定」會讓前端顯示「請聯繫管理員設定
    WebAuthn 網域」，把使用者引去要一個現在不該開的功能。
    """
    r = _call(client, method, path, su["token"] if needs_auth else None)
    assert r.status_code == 404, f"{method.upper()} {path} 回 {r.status_code}，應為 404"


@_DISABLED_ONLY
@pytest.mark.parametrize("method,path,needs_auth", _WEBAUTHN_ENDPOINTS)
def test_disabled_endpoints_do_not_leak_schema_via_422(client, su, method, path, needs_auth):
    """停用的端點不可以用 422 洩漏自己的存在與欄位結構。

    **這題是實際踩到才補的**：守門原本寫在路由函式的第一行，但 FastAPI 先解
    dependencies、**之後**才驗 Pydantic body——帶 body 的端點在 body 不合格時
    直接回 422，連函式都沒進去，守門形同不存在。而那個 422 會把欄位名一併列出：

        {"loc": ["body", "challengeToken"], "msg": "Field required"}, ...

    等於在功能已經關掉的情況下，對外確認端點存在並公布它的介面。
    修法是把守門掛成 route dependency，這題守著不讓它退回去。
    """
    r = _call(client, method, path, su["token"] if needs_auth else None)
    assert r.status_code != 422, (
        f"{method.upper()} {path} 回 422 而不是 404——守門沒有掛成 route "
        f"dependency，body 驗證搶先執行了。回應內容：{r.text}")


@_DISABLED_ONLY
def test_credential_id_endpoints_are_404_while_disabled(client, su, cred_id):
    """改名／刪除單張憑證同樣 404——而且用的是**真的存在**的憑證 id。

    用真 id 才分得出「功能被關掉」與「查無此憑證」：兩者都是 404，但後者代表
    守門根本沒生效、只是剛好資源不存在。搭配下面的反向驗證（同一個 id 在開關
    打開後回 200）才構成一組有鑑別力的斷言。
    """
    r = client.patch(f"/api/auth/webauthn/credentials/{cred_id}",
                     headers=_auth(su["token"]), json={"name": "改個名字"})
    assert r.status_code == 404, r.text
    r = client.delete(f"/api/auth/webauthn/credentials/{cred_id}",
                      headers=_auth(su["token"]))
    assert r.status_code == 404, r.text


@_DISABLED_ONLY
def test_webauthn_settings_endpoints_are_404_while_disabled(client, su):
    """管理員的網域設定端點同樣關掉——留著會讓管理員填了存不進去。"""
    r = client.get("/api/settings/webauthn-config", headers=_auth(su["token"]))
    assert r.status_code == 404, r.text
    r = client.patch("/api/settings/webauthn-config", headers=_auth(su["token"]),
                     json={"rp_id": "erp.example.local",
                           "origin": "https://erp.example.local:666"})
    assert r.status_code == 404, r.text


@_DISABLED_ONLY
def test_config_status_reports_disabled(client):
    """前端三個頁面共用的公開端點：停用時回 200，兩個旗標都是 false。

    這支**不能**回 404——login.html / change-password.html /
    company-profile-settings.html 都靠它決定要不要畫出 Passkey 區塊，
    要回得了 200 才能同時關掉按鈕（configured）與整張卡片（enabled）。

    `configured` 一併壓成 false 是給舊版前端的保險：舊頁面只認得 configured，
    壓成 false 才能保證按鈕不會冒出來。
    """
    r = client.get("/api/system/webauthn-config-status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["configured"] is False, "停用時 configured 必須一併壓成 false（舊前端只認得它）"


# ── 反向驗證：開關打開後，上面每一個 404 都要消失 ──────────────────────────────

@pytest.mark.parametrize("method,path,needs_auth", _WEBAUTHN_ENDPOINTS)
def test_webauthn_endpoints_exist_when_enabled(client, su, enabled, method, path, needs_auth):
    """開關打開後，這些端點不可以再回 404。

    沒有這一題，停用態那幾題就是假綠燈——把路由路徑打錯、或整個 router 沒註冊，
    停用態照樣全綠。這裡不管業務結果對不對（空 body 本來就會 400/422），
    只管「這支端點存在」。
    """
    r = _call(client, method, path, su["token"] if needs_auth else None)
    assert r.status_code != 404, (
        f"{method.upper()} {path} 在開關打開後仍是 404——"
        f"這代表路由本身有問題，不是停用開關的效果")


def test_credential_id_endpoints_work_when_enabled(client, su, cred_id, enabled):
    """反向驗證：同一個憑證 id，開關打開後改名與刪除都要真的成功。"""
    r = client.patch(f"/api/auth/webauthn/credentials/{cred_id}",
                     headers=_auth(su["token"]), json={"name": "改個名字"})
    assert r.status_code == 200, r.text
    r = client.delete(f"/api/auth/webauthn/credentials/{cred_id}",
                      headers=_auth(su["token"]))
    assert r.status_code == 200, r.text


def test_webauthn_settings_endpoints_exist_when_enabled(client, su, enabled):
    """反向驗證：設定端點在開關打開後回得來（不驗業務結果）。"""
    r = client.get("/api/settings/webauthn-config", headers=_auth(su["token"]))
    assert r.status_code != 404, r.text


def test_config_status_reports_enabled_when_on(client, enabled):
    """反向驗證：開關打開後 enabled 要變回 true。"""
    r = client.get("/api/system/webauthn-config-status")
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True


# ── 停用 ≠ 清除 ───────────────────────────────────────────────────────────────

def test_credentials_table_survives_disabling(client):
    """停用是暫停、不是清除——資料表必須還在。

    恢復開關後既有憑證要能原樣回到清單裡（前提是這段期間沒有改過 RP ID，
    見 db.py::_m074_webauthn_rp_id）。
    """
    import db
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='webauthn_credentials'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "webauthn_credentials 資料表不見了——停用不該刪表"


def test_credentials_still_in_daily_json_backup(client):
    """功能關掉了，這張表仍然要每天備份。

    「功能暫緩」很容易被順手讀成「資料不用備份了」，但表裡記的是「誰原本綁過
    Passkey」——恢復功能時要靠它通知誰重綁，那份名單反而是停用期間唯一的線索。
    """
    import archive
    tables = archive._daily_backup_tables()
    assert "通行金鑰" in tables, "通行金鑰被移出每日 JSON 匯出了"
    assert "webauthn_credentials" in tables["通行金鑰"]
