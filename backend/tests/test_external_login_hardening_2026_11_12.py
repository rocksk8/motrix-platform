# -*- coding: utf-8 -*-
"""外網登入強化（2026-11-12）：外網來源判定、外網強制 TOTP、單一帳號鎖定。

背景：motrix-platform.miactw.com 經 Cloudflare Tunnel 對外開放；正式機風險評估（20261112_外網開放風險評估.md）指出
登入保護只有「每個來源 IP 錯 5 次鎖 15 分鐘」，換很多 IP 就能持續猜密碼；TOTP 只有 2 位最高管理者啟用。
本檔涵蓋：內外網判定（含偽造標頭）、三種角色的強制 TOTP、內網不受影響、帳號鎖定（門檻／窗口／解鎖／DoS 防護／持久化）、稽核與告警。

模擬外網：Cloudflare Tunnel 與本程式同機 ⇒ TCP 對端是 127.0.0.1，真實 IP 在 `CF-Connecting-IP`；每次換一個 IP＝「換很多 IP 猜密碼」。
模擬內網：預設的 `client` 夾具（對端 "testclient"，conftest 讓它視為內網對端）。
"""
import sys
import time
from types import SimpleNamespace

import pyotp
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from helpers import account_lock, external_access
from helpers import settings_groups  # noqa: F401  登錄設定群組
from helpers import settings_registry as SR

PW = "Test-Pass-123"


def _req(peer, **headers):
    return SimpleNamespace(client=(SimpleNamespace(host=peer) if peer is not None else None), headers=Headers(headers))


@pytest.fixture()
def real_peers(monkeypatch):
    """關掉 conftest 給 "testclient" 的內網特例：回到正式規則（對端不是 IP ⇒ 外網）。"""
    monkeypatch.setattr(external_access, "INTERNAL_PEER_NAMES", frozenset())


def _tunnel(client, ip="198.51.100.10"):
    """cloudflared 同機：對端 127.0.0.1，真實來源 IP 放 CF-Connecting-IP。"""
    c = TestClient(client.app, client=("127.0.0.1", 50000))
    c.headers.update({"CF-Connecting-IP": ip, "CF-Ray": "abc123-TPE"})
    return c


def _login(c, username, password=PW, ip=None):
    h = {"CF-Connecting-IP": ip} if ip else None
    return c.post("/api/auth/login", json={"username": username, "password": password}, headers=h)


def _enable_totp(client, username):
    tok = _login(client, username).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    secret = client.post("/api/auth/totp/setup", headers=h).json()["secret"]
    r = client.post("/api/auth/totp/enable", headers=h, json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    return secret


def _audit_rows(action):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT * FROM audit_log WHERE action=? ORDER BY id", (action,)).fetchall()
    finally:
        conn.close()


# ═══ 一、來源判定 ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("peer,headers,external,why", [
    ("192.168.1.20", {}, False, "internal_network"),
    ("10.1.2.3", {}, False, "internal_network"),
    ("172.20.0.5", {}, False, "internal_network"),
    ("127.0.0.1", {}, True, "loopback"),          # 本機直連預設不算內網（F2）
    ("::1", {}, True, "loopback"),
    ("::ffff:192.168.1.20", {}, False, "internal_network"),
    ("203.0.113.9", {}, True, "public_ip"),
    ("2001:db8::1", {}, True, "public_ip"),
    ("testclient", {}, True, "unknown_ip"),          # 判斷不出來 ⇒ 外網（保守預設）
    ("unknown", {}, True, "unknown_ip"),
    (None, {}, True, "unknown_ip"),
    ("192.168.1.20", {"CF-Ray": "x"}, True, "cloudflare_header"),
    ("127.0.0.1", {"CF-Connecting-IP": "198.51.100.7"}, True, "cloudflare_header"),
    ("192.168.1.20", {"Host": "motrix-platform.miactw.com"}, True, "external_host"),
    ("192.168.1.20", {"Host": "MOTRIX-Platform.MIACTW.com:443"}, True, "external_host"),
    ("192.168.1.20", {"X-Forwarded-For": "10.0.0.9"}, True, "proxy_header"),
    ("192.168.1.20", {"Forwarded": "for=10.0.0.9"}, True, "proxy_header"),
    ("192.168.1.20", {"X-Real-IP": "10.0.0.9"}, True, "proxy_header"),
    ("192.168.1.20", {"Host": "192.168.1.5:666"}, False, "internal_network"),
])
def test_classify(peer, headers, external, why):
    assert external_access.classify(_req(peer, **headers)) == (external, why)


def test_forged_internal_claims_never_make_an_external_request_internal():
    """外網使用者能控制的東西（XFF、Host、自填 CF 標頭）都只會讓判定更嚴；對端是公網 IP 就是外網，不管他宣稱什麼。"""
    for hdr in ({"X-Forwarded-For": "192.168.1.5"}, {"CF-Connecting-IP": "192.168.1.5"}, {"X-Real-IP": "10.0.0.1"},
                {"Host": "192.168.1.5"}, {"Host": "localhost"}):
        assert external_access.classify(_req("203.0.113.9", **hdr))[0] is True


def test_tunnel_request_with_a_private_looking_connecting_ip_is_still_external():
    # 即使 CF-Connecting-IP 填了私有位址（client_ip 會採信它），Cloudflare 標頭本身就足以判成外網
    assert external_access.classify(_req("127.0.0.1", **{"CF-Connecting-IP": "192.168.1.5", "CF-Ray": "r"}))[0] is True


def test_internal_networks_setting_only_accepts_private_ranges(monkeypatch):
    monkeypatch.setattr(external_access, "_get", lambda k, d: "0.0.0.0/0, 8.8.8.0/24, 192.168.50.0/24, bogus" if k == "internal_networks" else d)
    nets = [str(n) for n in external_access.internal_networks()]
    assert nets == ["192.168.50.0/24"]
    assert external_access.classify(_req("203.0.113.9"))[0] is True          # 公網網段不可能被當成內網
    assert external_access.classify(_req("192.168.50.7"))[0] is False
    assert external_access.classify(_req("192.168.1.7"))[0] is True          # 設定改窄了，原本的內網不在清單 ⇒ 外網


def test_internal_networks_all_invalid_falls_back_to_defaults(monkeypatch):
    monkeypatch.setattr(external_access, "_get", lambda k, d: "0.0.0.0/0" if k == "internal_networks" else d)
    assert external_access.classify(_req("192.168.1.7"))[0] is False
    assert external_access.classify(_req("203.0.113.9"))[0] is True


def test_external_hosts_setting_is_configurable(monkeypatch):
    monkeypatch.setattr(external_access, "_get", lambda k, d: "erp.example.com" if k == "external_hosts" else d)
    assert external_access.classify(_req("192.168.1.20", Host="erp.example.com"))[0] is True
    assert external_access.classify(_req("192.168.1.20", Host="motrix-platform.miactw.com"))[0] is False


def test_classify_never_raises_and_defaults_to_external():
    assert external_access.classify(object())[0] is True


def test_default_enforced_roles_and_master_switch(monkeypatch):
    assert external_access.enforced_roles() == frozenset({"superadmin", "admin", "finance"})
    assert external_access.totp_required_for("finance") and not external_access.totp_required_for("sales")
    assert not external_access.totp_required_for("admin", "demo")            # 示範帳號不適用
    monkeypatch.setattr(external_access, "_get", lambda k, d: 0 if k == "ext_totp_enabled" else d)
    assert external_access.enforced_roles() == frozenset()


def test_settings_group_registered_with_the_agreed_defaults():
    g = SR.groups()["external_login"]
    d = {f["key"]: f["default"] for f in g["fields"]}
    assert d["ext_totp_enabled"] == 1
    assert [r for r in external_access.ENFORCEABLE_ROLES if d["ext_totp_role_" + r] == 1] == ["superadmin", "admin", "finance"]
    assert (d["lock_threshold"], d["lock_window_min"], d["lock_minutes"], d["lock_scope"]) == (10, 30, 30, 1)
    assert d["external_hosts"] == "motrix-platform.miactw.com"
    # 放寬方向一律走確認期間（loosen／requires_pending）
    by = {f["key"]: f for f in g["fields"]}
    assert by["ext_totp_enabled"]["loosen"] == "down" and by["lock_threshold"]["loosen"] == "up"
    assert by["internal_networks"]["requiresPending"] and by["external_hosts"]["requiresPending"]


# ═══ 二、外網強制 TOTP ═══════════════════════════════════════════════════════════

@pytest.mark.parametrize("role", ["superadmin", "admin", "finance"])
def test_external_login_without_totp_is_refused_for_the_three_roles(client, make_user, role):
    u, _ = make_user(username="u_" + role, password=PW, role=role)
    r = _login(_tunnel(client), u)
    assert r.status_code == 403, r.text
    assert "公司內網" in r.json()["detail"] and "兩步驟驗證" in r.json()["detail"]
    assert "token" not in r.text
    rows = _audit_rows("auth.login_refused_external_totp")
    assert rows and rows[-1]["username"] == u and rows[-1]["reason_code"] == "ext_totp_required"


def test_refusal_does_not_issue_a_session_and_is_not_counted_as_a_password_failure(client, make_user):
    u, _ = make_user(username="adm1", password=PW, role="admin")
    c = _tunnel(client)
    for _ in range(12):                                       # 密碼是對的：不算失敗，不會觸發 IP 鎖定或帳號鎖定
        assert _login(c, u).status_code == 403
    assert account_lock.is_locked(u, True) == 0
    assert _login(client, u).status_code == 200               # 內網照常


@pytest.mark.parametrize("role", ["superadmin", "admin", "finance"])
def test_internal_login_is_unchanged_for_the_enforced_roles(client, make_user, role):
    u, _ = make_user(username="in_" + role, password=PW, role=role)
    r = _login(client, u)
    assert r.status_code == 200 and r.json()["token"]


@pytest.mark.parametrize("role", ["sales", "engineer", "viewer"])
def test_other_roles_can_log_in_from_outside_without_totp_by_default(client, make_user, role):
    u, _ = make_user(username="o_" + role, password=PW, role=role)
    assert _login(_tunnel(client), u).status_code == 200


@pytest.mark.parametrize("role", ["superadmin", "admin", "finance"])
def test_external_login_with_totp_goes_through_the_normal_challenge(client, make_user, role):
    u, _ = make_user(username="t_" + role, password=PW, role=role)
    secret = _enable_totp(client, u)                          # 先在內網啟用
    c = _tunnel(client)
    r = _login(c, u)
    assert r.status_code == 200 and r.json()["totpRequired"] is True
    ok = c.post("/api/auth/login/totp", json={"challenge_token": r.json()["challengeToken"], "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200 and ok.json()["token"]


def test_wrong_password_from_outside_is_still_the_generic_401_not_the_totp_message(client, make_user):
    """帳號存在與否、密碼對錯都不能被『請先啟用兩步驟驗證』的訊息洩漏：只有密碼正確才會看到它。"""
    u, _ = make_user(username="adm2", password=PW, role="admin")
    c = _tunnel(client)
    assert _login(c, u, "wrong-password").status_code == 401
    assert _login(c, "ghost-user", PW).status_code == 401


def test_forged_xff_from_the_lan_is_treated_as_external(client, make_user, real_peers):
    """區網（內網對端）帶了 X-Forwarded-For 宣稱自己是 10.x ⇒ 有代理痕跡 ⇒ 外網。偽造只會更嚴。"""
    u, _ = make_user(username="adm3", password=PW, role="admin")
    lan = TestClient(client.app, client=("192.168.1.20", 50000))
    assert _login(lan, u).status_code == 200                                  # 真正的區網直連＝內網
    r = lan.post("/api/auth/login", json={"username": u, "password": PW}, headers={"X-Forwarded-For": "192.168.1.99"})
    assert r.status_code == 403


def test_external_peer_cannot_pretend_to_be_internal(client, make_user, real_peers):
    u, _ = make_user(username="adm4", password=PW, role="admin")
    ext = TestClient(client.app, client=("203.0.113.50", 50000))
    for h in ({"X-Forwarded-For": "192.168.1.5"}, {"CF-Connecting-IP": "192.168.1.5"}, {"Host": "localhost"}):
        assert ext.post("/api/auth/login", json={"username": u, "password": PW}, headers=h).status_code == 403


def test_master_switch_off_lets_external_login_through(client, make_user, monkeypatch):
    u, _ = make_user(username="adm5", password=PW, role="admin")
    assert _login(_tunnel(client), u).status_code == 403
    real = external_access._get
    monkeypatch.setattr(external_access, "_get", lambda k, d: 0 if k == "ext_totp_enabled" else real(k, d))
    assert _login(_tunnel(client), u).status_code == 200


def test_role_list_is_adjustable_in_settings(client, make_user):
    """收緊（加一個角色）立即生效：業務也必須有 TOTP 才能從外網登入。"""
    u, _ = make_user(username="sal1", password=PW, role="sales")
    assert _login(_tunnel(client), u).status_code == 200
    SR.publish("external_login", {"ext_totp_role_sales": 1}, user="tester")
    assert "sales" in external_access.enforced_roles()
    assert _login(_tunnel(client), u).status_code == 403


def test_relaxing_the_master_switch_is_not_immediate(client):
    """放寬（關總開關）走確認期間：提交後不會立刻生效。"""
    r = SR.publish("external_login", {"ext_totp_enabled": 0}, user="tester")
    assert r["pending"], "放寬應寫成待生效項"
    assert external_access.enforced_roles() == frozenset({"superadmin", "admin", "finance"})


# ═══ 三、單一帳號鎖定 ═══════════════════════════════════════════════════════════

def _fail_from_many_ips(client, username, n, start=1):
    """每次換一個來源 IP（經隧道）猜錯密碼＝『換很多 IP』的攻擊。回最後一次的回應。"""
    r = None
    for i in range(start, start + n):
        r = _login(_tunnel(client, f"198.51.100.{i}"), username, "wrong-password")
    return r


def test_account_locks_after_threshold_failures_across_many_ips(client, make_user):
    u, _ = make_user(username="victim", password=PW, role="sales")
    last = _fail_from_many_ips(client, u, 10)
    assert last.status_code == 401                            # 第 10 次還是 401（鎖是從第 11 次起擋）
    r = _login(_tunnel(client, "198.51.100.200"), u, PW)      # 全新 IP、連正確密碼也擋
    assert r.status_code == 429 and "暫時鎖定" in r.json()["detail"]
    assert "token" not in r.text


def test_nine_failures_do_not_lock(client, make_user):
    u, _ = make_user(username="victim2", password=PW, role="sales")
    _fail_from_many_ips(client, u, 9)
    assert _login(_tunnel(client, "198.51.100.201"), u, PW).status_code == 200


def test_success_resets_the_failure_counter(client, make_user):
    u, _ = make_user(username="victim3", password=PW, role="sales")
    _fail_from_many_ips(client, u, 9)
    assert _login(_tunnel(client, "198.51.100.202"), u, PW).status_code == 200
    _fail_from_many_ips(client, u, 9, start=20)               # 再 9 次仍未達門檻
    assert _login(_tunnel(client, "198.51.100.203"), u, PW).status_code == 200


def test_lock_response_is_identical_for_unknown_accounts(client, make_user):
    u, _ = make_user(username="real1", password=PW, role="sales")
    _fail_from_many_ips(client, u, 10)
    _fail_from_many_ips(client, "ghost-acct", 10, start=50)
    a = _login(_tunnel(client, "198.51.100.210"), u, PW)
    b = _login(_tunnel(client, "198.51.100.211"), "ghost-acct", PW)
    assert a.status_code == b.status_code == 429
    assert a.json()["detail"].split("約")[0] == b.json()["detail"].split("約")[0]


def test_internal_login_still_works_while_locked_and_clears_the_lock(client, make_user):
    """DoS 防護的核心：攻擊者從外網把帳號鎖住，本人在公司內網仍可登入，且內網登入成功會解除鎖。"""
    u, _ = make_user(username="victim4", password=PW, role="sales")
    _fail_from_many_ips(client, u, 10)
    assert _login(_tunnel(client, "198.51.100.220"), u, PW).status_code == 429
    assert _login(client, u).status_code == 200                           # 內網
    assert account_lock.is_locked(u, True) == 0
    assert _login(_tunnel(client, "198.51.100.221"), u, PW).status_code == 200
    assert _audit_rows("auth.account_unlocked")


def test_internal_failures_do_not_count_toward_the_account_lock(client, make_user):
    u, _ = make_user(username="victim5", password=PW, role="sales")
    for _i in range(4):                                       # 內網（同一 IP，未達 IP 鎖定 5 次）
        assert _login(client, u, "wrong-password").status_code == 401
    assert account_lock.record_failure(u, "192.168.1.5", external=False) == "ignored"
    _fail_from_many_ips(client, u, 9)
    assert _login(_tunnel(client, "198.51.100.230"), u, PW).status_code == 200


def test_attacker_cannot_extend_the_lock_by_hammering(client, make_user):
    u, _ = make_user(username="victim6", password=PW, role="sales")
    _fail_from_many_ips(client, u, 11)                        # 第 11 次嘗試當場鎖
    before = account_lock.is_locked(u, True)
    assert before > 0
    _fail_from_many_ips(client, u, 30, start=100)             # 鎖定期間持續送請求
    after = account_lock.is_locked(u, True)
    assert after <= before                                    # 沒有被延長
    assert account_lock.record_failure(u, "198.51.100.1", True) == "already"


def test_lock_expires_by_itself():
    account_lock.reset_for_tests()
    t0 = 1000.0
    for i in range(10):
        st = account_lock.record_failure("someone", "198.51.100.%d" % i, True, now=t0 + i)
    assert st == "locked"
    assert account_lock.is_locked("someone", True, now=t0 + 60) > 0
    assert account_lock.is_locked("someone", True, now=t0 + 9 + 1800 + 1) == 0     # 30 分鐘後自動解除


def test_failures_outside_the_window_do_not_accumulate():
    account_lock.reset_for_tests()
    t = 1000.0
    for i in range(30):                                       # 每 4 分鐘一次：任一 30 分鐘窗內只有 ≤8 次
        assert account_lock.record_failure("slow", "198.51.100.5", True, now=t + i * 240) == "counted"


def test_threshold_window_and_lock_time_are_settings(client, make_user):
    SR.publish("external_login", {"lock_threshold": 3}, user="tester")      # 調低＝收緊，立即生效
    assert account_lock.config()["threshold"] == 3
    u, _ = make_user(username="victim7", password=PW, role="sales")
    _fail_from_many_ips(client, u, 3)
    assert _login(_tunnel(client, "198.51.100.240"), u, PW).status_code == 429


def test_scope_2_blocks_internal_too_and_counts_internal_failures(client, make_user):
    SR.publish("external_login", {"lock_scope": 2}, user="tester")           # 收緊，立即生效
    u, _ = make_user(username="victim8", password=PW, role="sales")
    assert account_lock.record_failure(u, "192.168.1.5", external=False) == "counted"
    _fail_from_many_ips(client, u, 9, start=1)
    assert _login(client, u).status_code == 429                              # 內網也被擋
    assert account_lock.check(u, external=False) > 0


def test_lock_is_persisted_and_reloaded(client, make_user):
    u, _ = make_user(username="victim9", password=PW, role="sales")
    _fail_from_many_ips(client, u, 11)
    account_lock.reset_for_tests()                                           # 模擬重啟：記憶體清空
    assert account_lock.is_locked(u, True) == 0
    assert account_lock.load_from_db() >= 1
    assert account_lock.is_locked(u, True) > 0
    # 啟動載入不會把帳號鎖混進 IP 鎖表
    import routers.auth as auth
    auth.init_rate_limiting()
    assert not [k for k in auth._rl_state if str(k).startswith("acct:")]


def test_failures_from_the_totp_step_count_too(client, make_user):
    """TOTP 步驟的錯誤驗證碼同樣計入帳號鎖（密碼步驟正確時退回預占，只有猜錯的驗證碼累積）。"""
    u, _ = make_user(username="vt1", password=PW, role="admin")
    _enable_totp(client, u)
    wrong = 0
    i = 0
    while wrong < 10:
        i += 1
        ch = _login(_tunnel(client, f"198.51.100.{60 + i}"), u).json()["challengeToken"]
        for j in range(4):
            if wrong >= 10:
                break
            c = _tunnel(client, f"198.51.100.{120 + wrong}")
            assert c.post("/api/auth/login/totp", json={"challenge_token": ch, "code": "000000"}).status_code == 401
            wrong += 1
    assert _login(_tunnel(client, "198.51.100.200"), u).status_code == 429


# ── 稽核與告警 ──────────────────────────────────────────────────────────────

def test_lock_writes_audit_without_secrets(client, make_user):
    u, _ = make_user(username="victim10", password=PW, role="sales")
    _fail_from_many_ips(client, u, 11)
    rows = _audit_rows("auth.account_locked")
    assert len(rows) == 1
    assert rows[0]["username"] == u and rows[0]["reason_code"] == "account_locked" and rows[0]["result"] == "fail"
    import json
    det = json.loads(rows[0]["detail"])
    assert det["fails"] == 10 and det["external"] is True and det["lockMinutes"] == 30 and det["ip"].startswith("198.51.100.")
    assert "wrong-password" not in rows[0]["detail"] and PW not in rows[0]["detail"]


def _fake_alert(monkeypatch, behaviour=None):
    calls = []

    def on_lockout(key, ip, usernames, fails, lock_seconds, **kw):
        calls.append({"key": key, "ip": ip, "usernames": list(usernames), "fails": fails, "lock_seconds": lock_seconds, **kw})
        if behaviour:
            raise behaviour
    mod = SimpleNamespace(on_lockout=on_lockout)
    monkeypatch.setitem(sys.modules, "helpers.auth_alert", mod)
    import helpers
    monkeypatch.setattr(helpers, "auth_alert", mod, raising=False)
    return calls


def test_lock_triggers_the_auth_lockout_alert_with_account_scope(client, make_user, monkeypatch):
    calls = _fake_alert(monkeypatch)
    u, _ = make_user(username="victim11", password=PW, role="sales")
    _fail_from_many_ips(client, u, 11)
    acct = [c for c in calls if c.get("scope") == "account"]
    assert len(acct) == 1
    assert acct[0]["key"] == account_lock.KEY_PREFIX + account_lock._key(u) and "victim11" not in acct[0]["key"] and acct[0]["usernames"] == [u] and acct[0]["lock_seconds"] == 1800 and acct[0]["fails"] == 10


def test_alert_failure_never_breaks_the_login_response(client, make_user, monkeypatch):
    _fake_alert(monkeypatch, behaviour=RuntimeError("line down"))
    u, _ = make_user(username="victim12", password=PW, role="sales")
    r = _fail_from_many_ips(client, u, 11)
    assert r.status_code == 429                               # 告警例外沒有讓回應變 500
    assert account_lock.is_locked(u, True) > 0


# ── 超級管理員：清單與手動解鎖 ──────────────────────────────────────────────

def test_superadmin_can_list_and_unlock(client, make_user):
    admin, _ = make_user(username="boss", password=PW, role="superadmin")
    u, _ = make_user(username="victim13", password=PW, role="sales")
    _fail_from_many_ips(client, u, 11)
    tok = _login(client, admin).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    lst = client.get("/api/auth/account-locks", headers=h).json()
    assert [x["username"] for x in lst["locks"]] == [u] and lst["config"]["threshold"] == 10
    assert client.post("/api/auth/account-locks/unlock", json={"username": u}, headers=h).status_code == 200
    assert _login(_tunnel(client, "198.51.100.250"), u, PW).status_code == 200
    unl = _audit_rows("auth.account_unlocked")
    assert len(unl) == 1 and unl[-1]["username"] == "boss" and '"by": "boss"' in unl[-1]["detail"]      # 操作者記在稽核列上
    assert client.post("/api/auth/account-locks/unlock", json={"username": u}, headers=h).status_code == 404


def test_unlock_endpoints_are_superadmin_only(client, make_user):
    make_user(username="adm9", password=PW, role="admin")
    tok = _login(client, "adm9").json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/auth/account-locks", headers=h).status_code in (401, 403)
    assert client.post("/api/auth/account-locks/unlock", json={"username": "x"}, headers=h).status_code in (401, 403)
    assert client.get("/api/auth/account-locks").status_code in (401, 403)


# ── 不影響既有行為 ─────────────────────────────────────────────────────────

def test_per_ip_lock_still_works_and_is_independent(client, make_user):
    u, _ = make_user(username="ipvictim", password=PW, role="sales")
    c = _tunnel(client, "198.51.100.77")
    for _i in range(5):
        assert _login(c, u, "wrong-password").status_code == 401
    assert _login(c, u, PW).status_code == 429                # 同 IP 第 6 次起被 IP 鎖擋（既有 5 次／15 分鐘）
