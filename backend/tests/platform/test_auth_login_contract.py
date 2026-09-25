"""登入契約（modtest 每次必跑）。

test_map 把「只為取得登入狀態而打 /api/auth/login」視為 fixture，不算依賴 router:auth（主持裁示 2026-09-25）。
代價是：改到登入流程時，modtest 不會再把 200 多支「順便登入」的測試挑進來。
這支就是那道保護——登入流程壞了，這裡先紅。
"""
import pytest

LOGIN = "/api/auth/login"
PROTECTED = "/api/auth/me"


@pytest.fixture()
def user(make_user):
    return make_user("contract_login", "Contract-Pass-123", role="admin")


def test_login_success_returns_token(client, user):
    r = client.post(LOGIN, json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    token = r.json().get("token")
    assert isinstance(token, str) and token


def test_login_wrong_password_is_rejected(client, user):
    r = client.post(LOGIN, json={"username": user[0], "password": "wrong-password"})
    assert r.status_code in (400, 401, 403), r.text
    assert not r.json().get("token")


def test_login_unknown_user_is_rejected(client):
    r = client.post(LOGIN, json={"username": "no_such_user_contract", "password": "whatever-123"})
    assert r.status_code in (400, 401, 403), r.text
    assert not r.json().get("token")


def test_token_opens_protected_endpoint(client, user):
    token = client.post(LOGIN, json={"username": user[0], "password": user[1]}).json()["token"]
    r = client.get(PROTECTED, headers={"Authorization": "Bearer %s" % token})
    assert r.status_code == 200, r.text
    assert r.json().get("username") == user[0]


def test_protected_endpoint_without_token_is_rejected(client):
    assert client.get(PROTECTED).status_code == 401
    assert client.get(PROTECTED, headers={"Authorization": "Bearer not-a-real-token"}).status_code == 401
