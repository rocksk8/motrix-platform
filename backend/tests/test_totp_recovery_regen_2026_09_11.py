"""救援碼剩餘組數顯示 ＋ 重新產生端點（2026-09-11 新增）。

**這批補的是什麼缺口**：救援碼是一次性的，用一組少一組，但在此之前
①沒有任何地方看得到還剩幾組 ②用完之後唯一的補救方式是停用 TOTP 再重跑一輪
setup/enable——那會連帶換掉密鑰、要重掃一次 QR code，成本高到沒人會主動做。
結果就是用到剩最後一組也不處理，等哪天驗證 App 不在手邊才發現被鎖在外面，
而那時已經來不及自助補救（重產端點本身要先登入）。

見 `routers/auth.py::totp_regenerate_recovery_codes()` 與 `totp_status()` docstring。
"""
import pyotp


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _enable_totp(client, token):
    """走完 setup→enable，回傳 (secret, recovery_codes)。比照 test_totp_2026_09_07.py。"""
    secret = client.post("/api/auth/totp/setup", headers=_auth(token)).json()["secret"]
    r = client.post("/api/auth/totp/enable", headers=_auth(token),
                    json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    return secret, r.json()["recoveryCodes"]


def _totp_login(client, username, password, code):
    """走兩段式登入，回傳第二段的 response。"""
    r1 = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r1.json().get("totpRequired") is True, r1.text
    return client.post("/api/auth/login/totp",
                       json={"challenge_token": r1.json()["challengeToken"], "code": code})


# ── 剩餘組數 ────────────────────────────────────────────────────────────────

def test_status_reports_remaining_count(client, make_user):
    username, password = make_user(role="admin")
    token = _login(client, username, password)["token"]

    # 還沒啟用：0 組
    assert client.get("/api/auth/totp/status", headers=_auth(token)).json()["recoveryCodesRemaining"] == 0

    _enable_totp(client, token)
    r = client.get("/api/auth/totp/status", headers=_auth(token))
    assert r.json()["enabled"] is True
    assert r.json()["recoveryCodesRemaining"] == 10


def test_remaining_count_drops_after_using_one(client, make_user):
    """用掉一組之後，狀態端點與登入回應都要看得到少了一組。"""
    username, password = make_user(username="totp_rem", role="admin")
    token = _login(client, username, password)["token"]
    _secret, codes = _enable_totp(client, token)

    r = _totp_login(client, username, password, codes[0])
    assert r.status_code == 200, r.text
    # 登入當下就講剩幾組——使用者最可能注意到的時機就是這一刻
    assert r.json()["recoveryCodesRemaining"] == 9

    new_token = r.json()["token"]
    assert client.get("/api/auth/totp/status",
                      headers=_auth(new_token)).json()["recoveryCodesRemaining"] == 9


def test_normal_totp_login_does_not_report_remaining(client, make_user):
    """用一般 6 位數驗證碼登入時不該出現這個欄位——沒有消耗救援碼，
    講「剩餘 10 組」只會讓人以為剛剛用掉了一組。"""
    username, password = make_user(username="totp_norm", role="admin")
    token = _login(client, username, password)["token"]
    secret, _codes = _enable_totp(client, token)

    r = _totp_login(client, username, password, pyotp.TOTP(secret).now())
    assert r.status_code == 200, r.text
    assert "recoveryCodesRemaining" not in r.json()


# ── 重新產生 ────────────────────────────────────────────────────────────────

def test_regenerate_requires_correct_password(client, make_user):
    username, password = make_user(username="totp_rg1", role="admin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)

    r = client.post("/api/auth/totp/recovery-codes/regenerate",
                    headers=_auth(token), json={"password": "wrong-password"})
    assert r.status_code == 400, r.text
    assert "密碼" in r.json()["detail"]


def test_regenerate_requires_totp_enabled(client, make_user):
    """沒啟用 TOTP 時回 400，而不是默默產生一組永遠用不到的碼。"""
    username, password = make_user(username="totp_rg2", role="admin")
    token = _login(client, username, password)["token"]

    r = client.post("/api/auth/totp/recovery-codes/regenerate",
                    headers=_auth(token), json={"password": password})
    assert r.status_code == 400, r.text
    assert "尚未啟用" in r.json()["detail"]


def test_regenerate_returns_ten_new_codes_and_resets_count(client, make_user):
    username, password = make_user(username="totp_rg3", role="admin")
    token = _login(client, username, password)["token"]
    _secret, old_codes = _enable_totp(client, token)

    # 先用掉三組，剩 7
    for c in old_codes[:3]:
        assert _totp_login(client, username, password, c).status_code == 200
    assert client.get("/api/auth/totp/status", headers=_auth(token)).json()["recoveryCodesRemaining"] == 7

    r = client.post("/api/auth/totp/recovery-codes/regenerate",
                    headers=_auth(token), json={"password": password})
    assert r.status_code == 200, r.text
    new_codes = r.json()["recoveryCodes"]
    assert len(new_codes) == 10
    assert len(set(new_codes)) == 10, "十組必須各不相同"
    assert not (set(new_codes) & set(old_codes)), "新碼不該跟舊碼重複"
    assert r.json()["replacedPrevious"] is True
    assert client.get("/api/auth/totp/status", headers=_auth(token)).json()["recoveryCodesRemaining"] == 10


def test_regenerate_invalidates_all_old_codes(client, make_user):
    """語意是「整組換掉」不是「補到 10 組」——沒用過的舊碼也必須失效。

    這是這支端點最重要的一條：若舊碼還能用，使用者手上那張列印的舊清單會
    變成「其中某幾組還有效但不知道是哪幾組」，比全部失效更難處理。
    """
    username, password = make_user(username="totp_rg4", role="admin")
    token = _login(client, username, password)["token"]
    _secret, old_codes = _enable_totp(client, token)

    r = client.post("/api/auth/totp/recovery-codes/regenerate",
                    headers=_auth(token), json={"password": password})
    new_codes = r.json()["recoveryCodes"]

    # 一組都沒用過的舊碼，現在應該被拒絕
    assert _totp_login(client, username, password, old_codes[0]).status_code == 401
    assert _totp_login(client, username, password, old_codes[9]).status_code == 401
    # 新碼可以用
    assert _totp_login(client, username, password, new_codes[0]).status_code == 200


def test_regenerate_requires_auth(client):
    r = client.post("/api/auth/totp/recovery-codes/regenerate", json={"password": "x"})
    assert r.status_code in (401, 403), r.text


def test_regenerate_is_audit_logged(client, make_user):
    username, password = make_user(username="totp_rg5", role="admin")
    token = _login(client, username, password)["token"]
    _enable_totp(client, token)

    client.post("/api/auth/totp/recovery-codes/regenerate",
                headers=_auth(token), json={"password": password})

    items = client.get("/api/audit-log", headers=_auth(token)).json()["items"]
    assert any(it["action"] == "auth.totp_recovery_regenerated" for it in items), \
        [it["action"] for it in items[:10]]
