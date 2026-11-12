# -*- coding: utf-8 -*-
"""hichan-1 對抗式審查 feat/external-login-hardening (7697699c8) 的證明用測試。放在審查者自己的 worktree，不屬於該分支。
每一題是「攻擊成功＝assert 成立」，斷言通過＝漏洞存在。"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pyotp
import pytest
from fastapi.testclient import TestClient

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


# ── A1：只知道密碼，從外網繞過 TOTP（QR 密碼核准）────────────────────────────
def test_A1_external_totp_enabled_admin_bypassed_with_password_only_via_qr_approve(client, make_user):
    make_user(username="bossA1", password=PW, role="superadmin")
    _enable_totp(client, "bossA1")                       # 內網啟用 TOTP（正規流程）
    ext = _tunnel(client, "203.0.113.50")                # 攻擊者：外網，只有密碼、沒有驗證碼
    r = _login(ext, "bossA1")
    assert r.status_code == 200 and r.json().get("totpRequired") is True
    chal = r.json()["challengeToken"]
    # 不需要手機：qr-approve 的「密碼核准」分支，同一個密碼就能核准自己的登入
    r2 = ext.post("/api/auth/login/qr-approve", json={"challenge_token": chal, "password": PW})
    assert r2.status_code == 200, r2.text
    r3 = ext.get("/api/auth/login/qr-status", headers={"X-Login-Challenge": chal})
    assert r3.status_code == 200 and r3.json().get("token"), r3.text      # ← 拿到真 session，全程沒有 TOTP 碼
    me = ext.get("/api/auth/me", headers={"Authorization": "Bearer " + r3.json()["token"]})
    assert me.status_code == 200 and me.json().get("username") == "bossA1"


# ── A2：本機／同機非 Cloudflare 代理（對端 loopback、無任何標頭）＝內網，免 TOTP、免帳號鎖 ─────────────
def test_A2_loopback_peer_without_markers_is_internal(client, make_user):
    make_user(username="adminA2", password=PW, role="admin")
    c = TestClient(client.app, client=("127.0.0.1", 50001))      # 例如 netsh portproxy／frp／同機 nginx 去掉標頭後轉進來
    assert external_access.classify(type("R", (), {"client": type("C", (), {"host": "127.0.0.1"})(), "headers": {}})())[0] is False
    r = _login(c, "adminA2")                                     # 角色 admin、沒啟用 TOTP：外網會 403，這裡直接 200
    assert r.status_code == 200 and r.json().get("token")


# ── A3：同一時間大量併發 → 鎖定門檻是「軟」的 ──────────────────────────────
def test_A3_concurrent_guesses_overshoot_the_threshold(client, make_user, monkeypatch):
    make_user(username="victimA3", password=PW, role="sales")
    import routers.auth as A
    calls = {"n": 0}
    lk = threading.Lock()

    def slow_verify(pw, h):
        with lk:
            calls["n"] += 1
        time.sleep(0.4)                                          # 模擬 pbkdf2 的耗時
        return False

    monkeypatch.setattr(A, "_verify_pw", slow_verify)
    app = client.app

    def one(i):
        c = TestClient(app, client=("127.0.0.1", 50100 + i))
        c.headers.update({"CF-Connecting-IP": "198.51.100.%d" % (i + 1), "CF-Ray": "x"})     # 每個請求不同 IP：避開每 IP 鎖
        return c.post("/api/auth/login", json={"username": "victimA3", "password": "guess%d" % i}).status_code

    with ThreadPoolExecutor(max_workers=40) as ex:
        codes = list(ex.map(one, range(40)))
    # 門檻是 10；一輪鎖定前實際驗證了幾次密碼？
    print("A3 verify_calls=%d codes=%s" % (calls["n"], sorted(set(codes)))); assert calls["n"] > 10, (calls, codes)


# ── A4：塞爆 _fails 表（10_000 筆）把受害帳號的計數洗掉 ─────────────────────
def test_A4_flooding_unique_names_evicts_a_targets_failure_counter():
    account_lock.reset_for_tests()
    for i in range(9):
        assert account_lock.record_failure("bossA4", "203.0.113.1", True) == "counted"
    for i in range(account_lock._MAX_ENTRIES + 5):
        account_lock.record_failure("junk%06d" % i, "203.0.113.2", True)
    # 計數被洗掉：第 10 次失敗不再觸發鎖定（回 counted 而不是 locked）
    assert account_lock.record_failure("bossA4", "203.0.113.1", True) == "counted"
    account_lock.reset_for_tests()


# ── A5：外網攻擊者讓任一帳號從外網無法登入（持續性 DoS），且可在鎖到期後立刻續鎖 ──────────
def test_A5_attacker_can_lock_out_the_real_user_from_outside(client, make_user):
    make_user(username="travelerA5", password=PW, role="admin")
    for i in range(10):
        _login(_tunnel(client, "198.51.100.%d" % (100 + i)), "travelerA5", "wrong")
    r = _login(_tunnel(client, "203.0.113.77"), "travelerA5", PW)     # 本人、密碼正確、不同 IP
    assert r.status_code == 429


# ── A6：稽核／log 含攻擊者可控字串（換行 → log 偽造；任何文字進 audit 與 LINE）─────────────
def test_A6_attacker_controlled_name_lands_in_log_and_audit(caplog):
    account_lock.reset_for_tests()
    evil = "x\nWARNING FAKE: admin password reset by system"
    import logging
    caplog.set_level(logging.WARNING)
    for _ in range(10):
        account_lock.record_failure(evil, "203.0.113.9", True)
    assert any("\nwarning fake" in m for m in caplog.messages), caplog.messages     # 名稱被轉小寫，但換行仍原樣進 log
    account_lock.reset_for_tests()


# ── A7：auth_alert 模組在這個分支不存在 ⇒ 鎖定告警是空動作（只記 log）─────────────────────
def test_A7_auth_alert_module_missing_on_this_branch():
    with pytest.raises(ImportError):
        from helpers import auth_alert  # noqa: F401


# ── A8：被 403 拒絕的外網登入不計入失敗 ⇒ 成為「密碼是否正確」的免費探針（不會鎖）─────────────
def test_A8_403_is_a_free_password_oracle_and_never_counts(client, make_user):
    make_user(username="noTotpA8", password=PW, role="admin")
    ext = _tunnel(client, "203.0.113.88")
    for _ in range(30):
        assert _login(ext, "noTotpA8").status_code == 403          # 正確密碼：30 次都是 403，不鎖、不計
    assert account_lock.is_locked("noTotpA8", True) == 0
    assert _login(ext, "noTotpA8", "wrong").status_code == 401     # 錯密碼：401 ⇒ 兩者可區分
