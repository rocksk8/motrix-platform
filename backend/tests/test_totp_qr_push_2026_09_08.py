"""手機掃 QR 核准登入測試（2026-09-08 新增，與既有 6 位數驗證碼並行）。
見 routers/auth.py 的 login_qr_info() / login_qr_approve() / login_qr_status()。
以下三個 helper 複製自 test_totp_2026_09_07.py（此專案測試慣例是各檔各自複製
小 helper，不跨檔案 import，避免 pytest 的 rootdir/import-mode 找不到模組）。"""
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

    code = pyotp.TOTP(secret).now()
    r2 = client.post("/api/auth/totp/enable", headers=_auth(token), json={"code": code})
    assert r2.status_code == 200, r2.text
    return secret, r2.json()["recoveryCodes"]


def test_login_returns_qr_code_when_totp_enabled(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)

    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["totpRequired"] is True
    assert data["challengeToken"]
    assert data["qrCodePng"].startswith("data:image/png;base64,")


def test_qr_info_returns_masked_username(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)
    challenge = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["challengeToken"]

    r = client.get(f"/api/auth/login/qr-info?challenge={challenge}")
    assert r.status_code == 200, r.text
    masked = r.json()["maskedUsername"]
    assert masked != username
    assert "*" in masked


def test_qr_info_invalid_challenge_400(client):
    r = client.get("/api/auth/login/qr-info?challenge=not-a-real-token")
    assert r.status_code == 400, r.text


def test_qr_status_pending_before_approval(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)
    challenge = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["challengeToken"]

    r = client.get(f"/api/auth/login/qr-status?challenge={challenge}")
    assert r.status_code == 200, r.text
    assert r.json() == {"pending": True}


def test_qr_approve_wrong_password_then_lockout_after_max_fails(client, make_user):
    # 比照既有 test_login_totp_wrong_code_rejected_and_lockout_after_max_fails
    # 的隔離慣例，用專屬假 IP 避免跟同批次其他測試的 per-IP 鎖定互相干擾。
    headers = {"X-Forwarded-For": "203.0.113.201"}
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)
    challenge = client.post(
        "/api/auth/login", json={"username": username, "password": password}, headers=headers
    ).json()["challengeToken"]

    for _ in range(4):
        bad = client.post(
            "/api/auth/login/qr-approve",
            json={"challenge_token": challenge, "password": "wrong-password"},
            headers=headers,
        )
        assert bad.status_code == 401, bad.text

    # 第 5 次錯誤：challenge 直接作廢
    last = client.post(
        "/api/auth/login/qr-approve",
        json={"challenge_token": challenge, "password": "wrong-password"},
        headers=headers,
    )
    assert last.status_code == 401, last.text

    again = client.post(
        "/api/auth/login/qr-approve",
        json={"challenge_token": challenge, "password": password},
        headers=headers,
    )
    assert again.status_code == 400, again.text  # 逾時/工作階段無效，不是密碼錯誤


def test_qr_approve_and_manual_code_share_fail_counter(client, make_user):
    # qr-approve 錯密碼跟手動輸入驗證碼錯誤，共用同一組 pending["fails"]
    # 上限（不是各自獨立 5 次、變相可猜 10 次）。
    headers = {"X-Forwarded-For": "203.0.113.202"}
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)
    challenge = client.post(
        "/api/auth/login", json={"username": username, "password": password}, headers=headers
    ).json()["challengeToken"]

    # 2 次錯密碼 + 2 次錯驗證碼
    for _ in range(2):
        r = client.post(
            "/api/auth/login/qr-approve",
            json={"challenge_token": challenge, "password": "wrong-password"},
            headers=headers,
        )
        assert r.status_code == 401, r.text
    for _ in range(2):
        r = client.post(
            "/api/auth/login/totp",
            json={"challenge_token": challenge, "code": "000000"},
            headers=headers,
        )
        assert r.status_code == 401, r.text

    # 累計第 5 次錯誤（不論從哪條路徑）：challenge 整個作廢
    last = client.post(
        "/api/auth/login/qr-approve",
        json={"challenge_token": challenge, "password": "wrong-password"},
        headers=headers,
    )
    assert last.status_code == 401, last.text

    again = client.get(f"/api/auth/login/qr-status?challenge={challenge}")
    assert again.status_code == 400, again.text


def test_qr_approve_correct_password_then_status_issues_session_once(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)
    challenge = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["challengeToken"]

    approve = client.post(
        "/api/auth/login/qr-approve",
        json={"challenge_token": challenge, "password": password},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json() == {"ok": True}

    status = client.get(f"/api/auth/login/qr-status?challenge={challenge}")
    assert status.status_code == 200, status.text
    session = status.json()
    assert session["token"]
    assert session["username"] == username

    # 單次有效：同一個 challenge 再打一次要回 400，不能再拿到 session
    again = client.get(f"/api/auth/login/qr-status?challenge={challenge}")
    assert again.status_code == 400, again.text
