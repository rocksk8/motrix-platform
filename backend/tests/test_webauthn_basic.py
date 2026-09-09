"""2026-09-09：WebAuthn/Passkey 裝置綁定登入端點基本測試。"""
import json
import base64
from datetime import datetime


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


def test_webauthn_register_begin_returns_options_and_challenge_token(client, make_user):
    """已登入時，register/begin 回傳 registration options 與 challenge_token。"""
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


def test_webauthn_login_begin_rejects_nonexistent_user(client):
    """帳號不存在時，login/begin 應得到 404。"""
    r = client.post("/api/auth/webauthn/login/begin", json={"username": "nonexistent_user"})
    assert r.status_code == 404, r.text


def test_webauthn_login_begin_rejects_no_passkeys(client, make_user):
    """帳號存在但未設定任何 Passkey 時，login/begin 應得到 404。"""
    username, _ = make_user(role="staff")
    r = client.post("/api/auth/webauthn/login/begin", json={"username": username})
    assert r.status_code == 404, r.text


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
