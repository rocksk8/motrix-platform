# -*- coding: utf-8 -*-
"""hichan-1 對抗式審查（feat/external-login-hardening 7697699c8；證明測試 h1/attack-extlogin-review 6848f8b92）的修補後版本。

原檔每題是「攻擊成功＝assert 成立」；這裡全部翻成「攻擊失敗」（防線成立）。對照：
  A1＝F1 QR 密碼核准繞過 TOTP（已拿掉密碼核准）      A2＝F2 本機直連（loopback 無標頭）被當內網（預設改判外網）
  A3＝F4 併發猜測超過門檻（預占計數）                A4＝F5 塞表洗掉受害帳號計數（清表保留高計數列）
  A6＝F6 稽核／log 含攻擊者可控字串（去控制字元、不存在帳號不落明文）   A7＝F7 auth_alert 缺失（error 層級）
  A5＝F3、A8＝F8：**維持原取捨**（外網持續 DoS、403 可當密碼探針）——這兩題改成「記錄現狀」的測試，風險已寫在交付說明與 docs/quick/security.md §3.3d，交使用者決定。
"""
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pyotp
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from helpers import account_lock, external_access
from helpers import settings_groups  # noqa: F401

PW = "Test-Pass-123"


def _tunnel(client, ip="198.51.100.10"):
    c = TestClient(client.app, client=("127.0.0.1", 50000))
    c.headers.update({"CF-Connecting-IP": ip, "CF-Ray": "abc123-TPE"})
    return c


def _login(c, username, password=PW):
    return c.post("/api/auth/login", json={"username": username, "password": password})


def _enable_totp(client, username):
    tok = _login(client, username).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    secret = client.post("/api/auth/totp/setup", headers=h).json()["secret"]
    assert client.post("/api/auth/totp/enable", headers=h, json={"code": pyotp.TOTP(secret).now()}).status_code == 200
    return secret


def _audit_rows(action):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT * FROM audit_log WHERE action=? ORDER BY id", (action,)).fetchall()
    finally:
        conn.close()


# ── F1／A1：只知道密碼，從外網繞過 TOTP（QR 密碼核准）→ 攻擊失敗 ───────────────
def test_A1_password_only_attacker_cannot_get_a_session_via_qr_approve(client, make_user):
    make_user(username="bossA1", password=PW, role="superadmin")
    secret = _enable_totp(client, "bossA1")
    ext = _tunnel(client, "203.0.113.50")
    r = _login(ext, "bossA1")
    assert r.status_code == 200 and r.json().get("totpRequired") is True
    chal = r.json()["challengeToken"]
    r2 = ext.post("/api/auth/login/qr-approve", json={"challenge_token": chal, "password": PW})
    assert r2.status_code == 400 and "先登入同一個帳號" in r2.json()["detail"]
    r3 = ext.get("/api/auth/login/qr-status", headers={"X-Login-Challenge": chal})
    assert r3.status_code == 200 and r3.json() == {"pending": True} and "token" not in r3.text
    # 正規路徑照常：真正的驗證碼仍可登入
    ok = ext.post("/api/auth/login/totp", json={"challenge_token": chal, "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200 and ok.json()["token"]


def test_A1b_qr_approve_with_a_session_from_the_same_account_still_works_from_outside(client, make_user):
    make_user(username="bossA1b", password=PW, role="superadmin")
    secret = _enable_totp(client, "bossA1b")
    phone = _login(client, "bossA1b")                                       # 手機先在內網登入過（有 totp ⇒ 要碼）
    code = client.post("/api/auth/login/totp", json={"challenge_token": phone.json()["challengeToken"], "code": pyotp.TOTP(secret).now()})
    phone_token = code.json()["token"]
    ext = _tunnel(client, "203.0.113.51")
    chal = _login(ext, "bossA1b").json()["challengeToken"]
    assert ext.post("/api/auth/login/qr-approve", json={"challenge_token": chal, "session_token": phone_token}).status_code == 200
    st = ext.get("/api/auth/login/qr-status", headers={"X-Login-Challenge": chal})
    assert st.status_code == 200 and st.json()["username"] == "bossA1b"


def test_A1c_qr_status_applies_the_account_lock(client, make_user):
    """qr-status 是發 session 的最後一步：帳號鎖定中不發。"""
    make_user(username="bossA1c", password=PW, role="superadmin")
    secret = _enable_totp(client, "bossA1c")
    phone_token = client.post("/api/auth/login/totp", json={"challenge_token": _login(client, "bossA1c").json()["challengeToken"],
                                                            "code": pyotp.TOTP(secret).now()}).json()["token"]
    ext = _tunnel(client, "203.0.113.52")
    chal = _login(ext, "bossA1c").json()["challengeToken"]
    assert ext.post("/api/auth/login/qr-approve", json={"challenge_token": chal, "session_token": phone_token}).status_code == 200
    for i in range(10):                                                    # 此時帳號被外網打鎖
        account_lock.record_failure("bossA1c", "198.51.100.%d" % i, True)
    assert account_lock.is_locked("bossA1c", True) > 0
    st = ext.get("/api/auth/login/qr-status", headers={"X-Login-Challenge": chal})
    assert st.status_code == 429 and "token" not in st.text


# ── F2／A2：本機直連（loopback、無任何標頭）→ 預設不再當內網 ─────────────────────
def test_A2_loopback_without_markers_is_external_by_default(client, make_user, monkeypatch):
    monkeypatch.setattr(external_access, "INTERNAL_PEER_NAMES", frozenset())          # 正式規則（conftest 的測試特例拿掉）
    req = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers=Headers({}))
    assert external_access.classify(req) == (True, "loopback")
    assert external_access.classify(SimpleNamespace(client=SimpleNamespace(host="::1"), headers=Headers({}))) == (True, "loopback")
    assert external_access.classify(SimpleNamespace(client=SimpleNamespace(host="::ffff:127.0.0.1"), headers=Headers({}))) == (True, "loopback")
    make_user(username="adminA2", password=PW, role="admin")
    c = TestClient(client.app, client=("127.0.0.1", 50001))
    r = _login(c, "adminA2")                                                           # admin 沒啟用 TOTP：不再免除
    assert r.status_code == 403 and "token" not in r.text


def test_A2b_loopback_counts_toward_the_account_lock(client, make_user, monkeypatch):
    monkeypatch.setattr(external_access, "INTERNAL_PEER_NAMES", frozenset())
    make_user(username="salesA2", password=PW, role="sales")
    c = TestClient(client.app, client=("127.0.0.1", 50002))
    for _i in range(5):
        _login(c, "salesA2", "wrong")
    assert account_lock.is_locked("salesA2", True) == 0                                # 5 次（IP 鎖才 5 次）還沒到帳號門檻
    # 帳號鎖對 loopback 也適用（以前被當內網就完全不計）
    for i in range(10):
        account_lock.record_failure("salesA2b", "127.0.0.1", external_access.classify(SimpleNamespace(
            client=SimpleNamespace(host="127.0.0.1"), headers=Headers({})))[0])
    assert account_lock.is_locked("salesA2b", True) > 0


def test_A2c_loopback_is_internal_only_with_the_explicit_setting(monkeypatch):
    monkeypatch.setattr(external_access, "INTERNAL_PEER_NAMES", frozenset())
    real = external_access._get
    monkeypatch.setattr(external_access, "_get", lambda k, d: 1 if k == "loopback_is_internal" else real(k, d))
    assert external_access.classify(SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers=Headers({})))[0] is False
    # 即使打開，帶 Cloudflare／代理標頭的 loopback 仍是外網（隧道同機的情況）
    assert external_access.classify(SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers=Headers({"CF-Ray": "x"})))[0] is True
    assert external_access.classify(SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers=Headers({"X-Forwarded-For": "1.2.3.4"})))[0] is True


def test_A2d_internal_networks_setting_cannot_add_loopback(monkeypatch):
    monkeypatch.setattr(external_access, "_get", lambda k, d: "127.0.0.0/8, ::1/128, 192.168.0.0/16" if k == "internal_networks" else d)
    assert [str(n) for n in external_access.internal_networks()] == ["192.168.0.0/16"]


# ── F4／A3：併發猜測不可超過門檻 → 預占計數 ─────────────────────────────────
def test_A3_concurrent_guesses_never_exceed_the_threshold(client, make_user, monkeypatch):
    make_user(username="victimA3", password=PW, role="sales")
    import routers.auth as A
    calls = {"n": 0}
    lk = threading.Lock()

    def slow_verify(pw, h):
        with lk:
            calls["n"] += 1
        time.sleep(0.3)                                                    # 模擬 pbkdf2 的耗時
        return False

    monkeypatch.setattr(A, "_verify_pw", slow_verify)
    app = client.app

    def one(i):
        c = TestClient(app, client=("127.0.0.1", 50100 + i))
        c.headers.update({"CF-Connecting-IP": "198.51.100.%d" % (i + 1), "CF-Ray": "x"})     # 每個請求不同 IP：避開每 IP 鎖
        return c.post("/api/auth/login", json={"username": "victimA3", "password": "guess%d" % i}).status_code

    with ThreadPoolExecutor(max_workers=40) as ex:
        codes = list(ex.map(one, range(40)))
    assert calls["n"] <= 10, (calls, sorted(set(codes)))                  # 門檻 10：最多放行 10 次密碼驗證
    assert codes.count(429) >= 30 and set(codes) <= {401, 429}


def test_A3b_begin_attempt_is_atomic_check_and_count():
    account_lock.reset_for_tests()
    results = []

    def go():
        results.append(account_lock.begin_attempt("raceA3b", "203.0.113.1", True))

    ts = [threading.Thread(target=go) for _ in range(50)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results.count(0) == 10 and sum(1 for r in results if r > 0) == 40
    account_lock.reset_for_tests()


def test_A3c_correct_password_does_not_consume_the_budget(client, make_user):
    """密碼正確（走 TOTP 第二步或直接登入）退回預占：連續成功登入 30 次不會把帳號鎖掉。"""
    make_user(username="legitA3c", password=PW, role="sales")
    for i in range(30):
        assert _login(_tunnel(client, "198.51.100.%d" % (i + 1)), "legitA3c").status_code == 200
    assert account_lock.is_locked("legitA3c", True) == 0


# ── F5／A4：塞滿表洗掉受害帳號的計數 → 保留接近門檻的列 ───────────────────────
def test_A4_flooding_unique_names_cannot_evict_a_near_threshold_target():
    account_lock.reset_for_tests()
    for _i in range(9):
        assert account_lock.record_failure("bossA4", "203.0.113.1", True) == "counted"
    for i in range(account_lock._MAX_ENTRIES + 5):
        account_lock.record_failure("junk%06d" % i, "203.0.113.2", True)
    assert len(account_lock._fails) <= account_lock._MAX_ENTRIES + 1
    assert account_lock.record_failure("bossA4", "203.0.113.1", True) == "locked"      # 第 10 次仍然觸發鎖定
    account_lock.reset_for_tests()


# ── F3／A5：外網攻擊者讓帳號無法從外網登入 → **維持原取捨**（記錄現狀；內網不受影響）──────────
def test_A5_accepted_risk_attacker_can_lock_external_login_but_internal_still_works(client, make_user):
    make_user(username="travelerA5", password=PW, role="sales")
    for i in range(10):
        _login(_tunnel(client, "198.51.100.%d" % (100 + i)), "travelerA5", "wrong")
    assert _login(_tunnel(client, "203.0.113.77"), "travelerA5").status_code == 429       # 已知殘留：本人從外網也進不來
    assert _login(client, "travelerA5").status_code == 200                                # 緩解：內網照常登入（並解除鎖）
    assert _login(_tunnel(client, "203.0.113.78"), "travelerA5").status_code == 200


# ── F6／A6：稽核／log 的攻擊者可控字串 ─────────────────────────────────────
def test_A6_attacker_controlled_name_never_reaches_log_or_audit_in_plaintext(client, caplog):
    account_lock.reset_for_tests()
    caplog.set_level(logging.WARNING)
    evil = "x\nWARNING FAKE: admin password reset by system"
    for _ in range(10):
        account_lock.record_failure(evil, "203.0.113.9\nFAKE", True)
    text = "\n".join(caplog.messages)
    assert "FAKE" not in text.upper().replace("FAKE", "FAKE") or "\n" not in "".join(m for m in caplog.messages if "Account lockout" in m)
    lock_msgs = [m for m in caplog.messages if "Account lockout" in m]
    assert lock_msgs and all("\n" not in m and "admin password reset" not in m.lower() for m in lock_msgs)
    rows = _audit_rows("auth.account_locked")
    assert rows
    blob = " ".join(str(dict(r)) for r in rows)
    assert "admin password reset" not in blob.lower() and "\\nWARNING" not in blob
    assert "不存在的帳號 #" in rows[-1]["username"]


def test_A6b_a_password_pasted_into_the_username_field_is_never_stored_or_alerted(client, monkeypatch):
    account_lock.reset_for_tests()
    sent = []
    mod = SimpleNamespace(on_lockout=lambda key, ip, names, fails, secs, **kw: sent.append((key, list(names), kw)))
    monkeypatch.setitem(sys.modules, "helpers.auth_alert", mod)
    import helpers
    monkeypatch.setattr(helpers, "auth_alert", mod, raising=False)
    secret_like = "Hunter2!Real-Password-9"
    for i in range(11):                                                    # 第 11 次嘗試當場鎖
        _login(_tunnel(client, "198.51.100.%d" % (i + 1)), secret_like, "whatever")
    assert account_lock.is_locked(secret_like, True) > 0
    assert sent, "告警應該送出（帶不含明文的標記）"
    import db
    conn = db.get_db()
    try:
        dumps = [str(dict(r)) for r in conn.execute("SELECT * FROM audit_log WHERE action='auth.account_locked'").fetchall()]
        dumps += [str(dict(r)) for r in conn.execute("SELECT * FROM login_rate_limit").fetchall()]
    finally:
        conn.close()
    assert not any(secret_like in d or secret_like.lower() in d.lower() for d in dumps)
    assert not any(secret_like.lower() in str(s).lower() for s in sent)
    assert "不存在的帳號 #" in sent[-1][1][0]


def test_A6c_known_account_shown_by_name_and_sanitised(client, make_user):
    make_user(username="realA6", password=PW, role="sales")
    assert account_lock.safe_label("REALA6") == "realA6"
    assert account_lock.safe_label("") == "（空白）"
    assert "\n" not in account_lock.safe_label("ghost\nname") and "ghost" not in account_lock.safe_label("ghost\nname")


# ── F7／A7：auth_alert 缺失 → error 層級的 log ────────────────────────────
def test_A7_missing_auth_alert_module_logs_at_error_level(caplog, monkeypatch):
    account_lock.reset_for_tests()
    import helpers
    monkeypatch.setitem(sys.modules, "helpers.auth_alert", None)           # 讓 import 丟 ImportError（等同模組不存在）
    monkeypatch.delattr(helpers, "auth_alert", raising=False)              # 套件屬性已存在時 `from helpers import x` 不查 sys.modules
    caplog.set_level(logging.WARNING)
    for i in range(10):
        account_lock.record_failure("alertless", "203.0.113.5", True)
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR and "auth_alert" in r.getMessage()]
    assert errs, [(r.levelname, r.getMessage()) for r in caplog.records]
    assert account_lock.is_locked("alertless", True) > 0                   # 鎖定本身照常生效
    account_lock.reset_for_tests()


# ── F8／A8：403 可當密碼探針 → **維持原取捨**（記錄現狀）──────────────────────
def test_A8_accepted_risk_403_distinguishes_right_from_wrong_password(client, make_user):
    make_user(username="noTotpA8", password=PW, role="admin")
    ext = _tunnel(client, "203.0.113.88")
    for _ in range(30):
        assert _login(ext, "noTotpA8").status_code == 403
    assert account_lock.is_locked("noTotpA8", True) == 0                   # 密碼對的 403 不計入（已知殘留，見 security.md §3.3d）
    assert _login(ext, "noTotpA8", "wrong").status_code == 401
