"""superadmin（及任何角色）自助啟用 TOTP 兩步驟驗證測試（2026-09-07 新增）。
見 db.py::_m072_totp() 與 routers/auth.py 的 totp_* / auth_login_totp() docstring。
架構地圖 §6.2 建議事項——自助啟用而非強制，理由見 db.py migration docstring。"""
import pyotp


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _enable_totp(client, token):
    """走完 setup→enable 流程，回傳 (secret, recovery_codes)。"""
    r = client.post("/api/auth/totp/setup", headers=_auth(token))
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    assert r.json()["qrCodePng"].startswith("data:image/png;base64,")

    code = pyotp.TOTP(secret).now()
    r2 = client.post("/api/auth/totp/enable", headers=_auth(token), json={"code": code})
    assert r2.status_code == 200, r2.text
    recovery_codes = r2.json()["recoveryCodes"]
    assert len(recovery_codes) == 10
    return secret, recovery_codes


def test_status_defaults_to_disabled(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    r = client.get("/api/auth/totp/status", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False


def test_setup_does_not_enable_until_confirmed(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    r = client.post("/api/auth/totp/setup", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["secret"]
    status = client.get("/api/auth/totp/status", headers=_auth(token)).json()
    assert status["enabled"] is False

    # 登入不受影響（尚未 enable，密碼登入直接成功，不會被要求 TOTP）
    r2 = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r2.status_code == 200, r2.text
    assert "totpRequired" not in r2.json()


def test_enable_rejects_wrong_code(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    client.post("/api/auth/totp/setup", headers=_auth(token))
    r = client.post("/api/auth/totp/enable", headers=_auth(token), json={"code": "000000"})
    assert r.status_code == 400, r.text
    assert client.get("/api/auth/totp/status", headers=_auth(token)).json()["enabled"] is False


def test_enable_success_flips_status_and_returns_recovery_codes(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    secret, recovery_codes = _enable_totp(client, token)
    assert len(set(recovery_codes)) == 10  # 十組彼此不重複
    assert client.get("/api/auth/totp/status", headers=_auth(token)).json()["enabled"] is True


def test_login_requires_second_step_once_enabled(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)

    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["totpRequired"] is True
    assert data["challengeToken"]
    assert "token" not in data  # 尚未核發真正的 session token


def test_login_totp_verify_success_issues_real_session(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    secret, _ = _enable_totp(client, token)

    r = client.post("/api/auth/login", json={"username": username, "password": password})
    challenge = r.json()["challengeToken"]

    code = pyotp.TOTP(secret).now()
    r2 = client.post("/api/auth/login/totp", json={"challenge_token": challenge, "code": code})
    assert r2.status_code == 200, r2.text
    data = r2.json()
    assert data["token"]
    assert data["username"] == username

    # 新 session token 可正常使用
    r3 = client.get("/api/auth/me", headers=_auth(data["token"]))
    assert r3.status_code == 200, r3.text

    # challenge_token 用過即失效，不能重放
    r4 = client.post("/api/auth/login/totp", json={"challenge_token": challenge, "code": code})
    assert r4.status_code == 400, r4.text


def test_login_totp_wrong_code_rejected_and_lockout_after_max_fails(client, make_user):
    # 這支測試會刻意連續 5 次驗證碼錯誤，觸發 auth_login_totp() 內共用的
    # per-IP 登入失敗鎖定（routers/auth.py _rl_state，process-global dict）。
    # 比照 test_api_integration.py::test_login_locks_out_after_repeated_failures
    # 既有慣例，用專屬 X-Forwarded-For 假 IP 隔離，避免鎖定殘留影響同一批次
    # 裡其他共用 TestClient 預設 IP 的測試。
    headers = {"X-Forwarded-For": "203.0.113.88"}
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)

    r = client.post("/api/auth/login", json={"username": username, "password": password}, headers=headers)
    challenge = r.json()["challengeToken"]

    for _ in range(4):
        bad = client.post("/api/auth/login/totp", json={"challenge_token": challenge, "code": "000000"}, headers=headers)
        assert bad.status_code == 401, bad.text

    # 第 5 次錯誤：challenge 直接作廢
    last = client.post("/api/auth/login/totp", json={"challenge_token": challenge, "code": "000000"}, headers=headers)
    assert last.status_code == 401, last.text

    again = client.post("/api/auth/login/totp", json={"challenge_token": challenge, "code": "000000"}, headers=headers)
    assert again.status_code == 400, again.text  # 逾時/工作階段無效，不是驗證碼錯誤


def test_login_totp_recovery_code_works_once(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _, recovery_codes = _enable_totp(client, token)
    recovery = recovery_codes[0]

    r = client.post("/api/auth/login", json={"username": username, "password": password})
    challenge = r.json()["challengeToken"]
    r2 = client.post("/api/auth/login/totp", json={"challenge_token": challenge, "code": recovery})
    assert r2.status_code == 200, r2.text

    # 同一組救援碼用過即失效
    r3 = client.post("/api/auth/login", json={"username": username, "password": password})
    challenge2 = r3.json()["challengeToken"]
    r4 = client.post("/api/auth/login/totp", json={"challenge_token": challenge2, "code": recovery})
    assert r4.status_code == 401, r4.text


def test_disable_requires_correct_password(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)

    r = client.post("/api/auth/totp/disable", headers=_auth(token), json={"password": "wrong-password"})
    assert r.status_code == 400, r.text
    assert client.get("/api/auth/totp/status", headers=_auth(token)).json()["enabled"] is True


def test_disable_success_removes_login_requirement(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)

    r = client.post("/api/auth/totp/disable", headers=_auth(token), json={"password": password})
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/totp/status", headers=_auth(token)).json()["enabled"] is False

    r2 = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r2.status_code == 200, r2.text
    assert "totpRequired" not in r2.json()


def test_setup_and_enable_require_auth(client):
    r = client.post("/api/auth/totp/setup")
    assert r.status_code in (401, 403), r.text
    r2 = client.post("/api/auth/totp/enable", json={"code": "123456"})
    assert r2.status_code in (401, 403), r2.text
