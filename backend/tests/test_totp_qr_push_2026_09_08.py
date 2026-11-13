# 2026-11-13 chore/test-prune：刪 test_qr_approve_via_session_token_same_account_succeeds——它的步驟與斷言（核准 200＋{"ok": True}、qr-status 200、username 相同）全部包含在 test_qr_approve_with_phone_session_then_status_issues_session_once（另外還驗 token、單次有效）裡
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

    r = client.get("/api/auth/login/qr-info",
                      headers={"X-Login-Challenge": challenge})
    assert r.status_code == 200, r.text
    masked = r.json()["maskedUsername"]
    assert masked != username
    assert "*" in masked


def test_qr_info_invalid_challenge_400(client):
    """無效的 challenge ⇒ 400。

    ⚠️ 2026-09-22 §8 FX22：challenge 改走 `X-Login-Challenge` header。
    📌 這一題原本把它放在 query string ——
    ☠️ 而**那條路現在回 422（格式拒絕）而不是 400（內容無效）**
    ⇒ 若照舊不改，它會紅在一個**與這一題無關**的理由上。
    🔑 而那個紅是對的：〈FX22c〉就是要讓舊的呼叫方式被明著拒絕。
    """
    r = client.get("/api/auth/login/qr-info",
                   headers={"X-Login-Challenge": "not-a-real-token"})
    assert r.status_code == 400, r.text


def test_qr_status_pending_before_approval(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)
    challenge = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["challengeToken"]

    r = client.get("/api/auth/login/qr-status",
                      headers={"X-Login-Challenge": challenge})
    assert r.status_code == 200, r.text
    assert r.json() == {"pending": True}


def test_qr_approve_password_branch_is_gone(client, make_user):
    """2026-11-12（F1 hotfix，hichan-1 審查）：手機核准**不再接受輸入密碼**。以前只驗密碼就把 challenge 標成 approved、
    qr-status 接著發 session ⇒ 只知道密碼的人自己呼叫就繞過 TOTP。現在密碼（對或錯）一律 400＋白話訊息，challenge 不被核准、不被消耗。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)
    challenge = client.post("/api/auth/login", json={"username": username, "password": password}).json()["challengeToken"]
    for pw in (password, "wrong-password", ""):
        r = client.post("/api/auth/login/qr-approve", json={"challenge_token": challenge, "password": pw})
        assert r.status_code == 400, r.text
        assert "先登入同一個帳號" in r.json()["detail"]
    status = client.get("/api/auth/login/qr-status", headers={"X-Login-Challenge": challenge})
    assert status.status_code == 200 and status.json() == {"pending": True}        # 沒被核准、也沒被消耗


def test_manual_code_path_unaffected_by_qr_password_removal(client, make_user):
    """手動輸入驗證碼的路徑照舊：QR 密碼嘗試不佔用 challenge 的失敗次數，正確驗證碼仍可登入。"""
    import pyotp
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    secret, _ = _enable_totp(client, token)
    challenge = client.post("/api/auth/login", json={"username": username, "password": password}).json()["challengeToken"]
    for _ in range(8):                                                      # 反覆打密碼核准：不計 fails、不作廢 challenge
        assert client.post("/api/auth/login/qr-approve", json={"challenge_token": challenge, "password": password}).status_code == 400
    ok = client.post("/api/auth/login/totp", json={"challenge_token": challenge, "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200 and ok.json()["token"]


def test_qr_approve_via_session_token_different_account_rejected(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)
    challenge = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["challengeToken"]

    other_username, other_password = make_user(username="other_tester", role="viewer")
    other_session_token = _login(client, other_username, other_password)["token"]

    r = client.post(
        "/api/auth/login/qr-approve",
        json={"challenge_token": challenge, "session_token": other_session_token},
    )
    assert r.status_code == 401, r.text

    # 沒有真的核准掉——challenge 仍然 pending，不因為錯的 session 就被消耗掉
    status = client.get("/api/auth/login/qr-status",
                      headers={"X-Login-Challenge": challenge})
    assert status.status_code == 200, status.text
    assert status.json() == {"pending": True}


def test_qr_approve_via_bogus_session_token_rejected(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)
    challenge = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["challengeToken"]

    r = client.post(
        "/api/auth/login/qr-approve",
        json={"challenge_token": challenge, "session_token": "not-a-real-session-token"},
    )
    assert r.status_code == 401, r.text


def test_qr_approve_without_password_or_session_token_400(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)
    challenge = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["challengeToken"]

    r = client.post("/api/auth/login/qr-approve", json={"challenge_token": challenge})
    assert r.status_code == 400, r.text


def test_qr_approve_via_session_token_does_not_consume_shared_fail_counter(client, make_user):
    # session token 不是「猜測型」憑證，錯的 session token 不該計入跟密碼/
    # 驗證碼共用的 fails 上限——連續打錯 session token 很多次，之後改用
    # 正確的手機 session 仍然要能核准成功（2026-11-12：密碼核准已移除，改用同帳號的手機 session）。
    headers = {"X-Forwarded-For": "203.0.113.203"}
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)
    challenge = client.post(
        "/api/auth/login", json={"username": username, "password": password}, headers=headers
    ).json()["challengeToken"]

    for _ in range(6):
        r = client.post(
            "/api/auth/login/qr-approve",
            json={"challenge_token": challenge, "session_token": "not-a-real-session-token"},
            headers=headers,
        )
        assert r.status_code == 401, r.text

    approve = client.post(
        "/api/auth/login/qr-approve",
        json={"challenge_token": challenge, "session_token": token},
        headers=headers,
    )
    assert approve.status_code == 200, approve.text


def test_qr_approve_with_phone_session_then_status_issues_session_once(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)
    challenge = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    ).json()["challengeToken"]

    approve = client.post(
        "/api/auth/login/qr-approve",
        json={"challenge_token": challenge, "session_token": token},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json() == {"ok": True}

    status = client.get("/api/auth/login/qr-status",
                      headers={"X-Login-Challenge": challenge})
    assert status.status_code == 200, status.text
    session = status.json()
    assert session["token"]
    assert session["username"] == username

    # 單次有效：同一個 challenge 再打一次要回 400，不能再拿到 session
    again = client.get("/api/auth/login/qr-status",
                      headers={"X-Login-Challenge": challenge})
    assert again.status_code == 400, again.text
