"""2026-09-09：WebAuthn/Passkey 裝置綁定登入端點基本測試。

2026-09-10：`f8198e9` 把 RP ID / Origin 從環境變數改成 `system_settings` 可動態
設定，並讓四個端點在「尚未設定」時回 503——本檔案原本三題假設端點永遠可用，
該次改動沒有同步更新測試就部署上線（打包測試關卡當時因其他原因已經全紅，沒有
擋下來）。現在改成：需要 RP 的題目先用 `webauthn_config` fixture 設好網域，另外
補一題正面驗證「沒設定就是 503」這個新行為。
"""
import json
import base64
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



@pytest.fixture()
def webauthn_config():
    """設定 WebAuthn 網域，模擬 superadmin 已在公司資料設定頁填過的正式機狀態。"""
    from helpers.settings import _set_setting
    _set_setting("webauthn_rp_id", "localhost")
    _set_setting("webauthn_origin", "http://localhost")


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_webauthn_register_begin_requires_auth(client, make_user):
    """未登入時呼叫 register/begin 應得到 401。"""
    r = client.post("/api/auth/webauthn/register/begin")
    assert r.status_code == 401


def test_webauthn_register_begin_returns_options_and_challenge_token(client, make_user, webauthn_config):
    """已登入且網域已設定時，register/begin 回傳 registration options 與 challenge_token。"""
    username, password = make_user(role="staff")
    token = _login(client, username, password)

    r = client.post("/api/auth/webauthn/register/begin", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert "challengeToken" in data, "缺少 challengeToken"
    assert "options" in data, "缺少 options"
    assert isinstance(data["options"], dict), "options 應是 dict"
    assert "challenge" in data["options"], "options 缺少 challenge"
    assert "rp" in data["options"], "options 缺少 rp"
    assert "user" in data["options"], "options 缺少 user"
    assert "pubKeyCredParams" in data["options"], "options 缺少 pubKeyCredParams"


def test_webauthn_login_begin_rejects_nonexistent_user(client, webauthn_config):
    """帳號不存在時，login/begin 應得到 404。"""
    r = client.post("/api/auth/webauthn/login/begin", json={"username": "nonexistent_user"})
    assert r.status_code == 404, r.text


def test_webauthn_login_begin_rejects_no_passkeys(client, make_user, webauthn_config):
    """帳號存在但未設定任何 Passkey 時，login/begin 應得到 404。"""
    username, _ = make_user(role="staff")
    r = client.post("/api/auth/webauthn/login/begin", json={"username": username})
    assert r.status_code == 404, r.text


def test_webauthn_endpoints_return_503_when_domain_unconfigured(client, make_user):
    """2026-09-10 新行為：RP ID / Origin 尚未設定時，四個 WebAuthn 端點一律回 503
    而不是用 localhost 預設值硬跑——正式機用 IP 服務時，錯的 RP ID 會讓瀏覽器
    丟出看起來像前端壞掉的 invalid domain 錯誤。這題同時是「正式機部署後
    Passkey 還不能用」的規格說明：要有人先去設定頁填網域。"""
    username, password = make_user(role="staff")
    token = _login(client, username, password)

    r = client.post("/api/auth/webauthn/register/begin", headers=_auth(token))
    assert r.status_code == 503, r.text
    assert "WebAuthn" in r.json()["detail"]

    r = client.post("/api/auth/webauthn/login/begin", json={"username": username})
    assert r.status_code == 503, r.text


def test_webauthn_credentials_list_empty_initially(client, make_user):
    """新登入使用者的 Passkey 清單應初始為空。"""
    username, password = make_user(role="staff")
    token = _login(client, username, password)

    r = client.get("/api/auth/webauthn/credentials", headers=_auth(token))
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 0, "初始清單應為空"


def test_webauthn_credential_delete_not_found(client, make_user):
    """刪除不存在的 credential 應得到 404。"""
    username, password = make_user(role="staff")
    token = _login(client, username, password)

    r = client.delete("/api/auth/webauthn/credentials/999", headers=_auth(token))
    assert r.status_code == 404, r.text


def test_webauthn_credential_rename_not_found(client, make_user):
    """改名不存在的 credential 應得到 404。"""
    username, password = make_user(role="staff")
    token = _login(client, username, password)

    r = client.patch(
        "/api/auth/webauthn/credentials/999",
        json={"name": "新名稱"},
        headers=_auth(token)
    )
    assert r.status_code == 404, r.text
