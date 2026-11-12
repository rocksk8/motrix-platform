# -*- coding: utf-8 -*-
"""登入失敗告警（2026-11-12 票；外網 go-live 補上的門檻）。

涵蓋：鎖定那一刻才發（不是每次失敗）、內容不含密碼、同範圍鎖定期間只發一次、全系統每小時上限＋摘要、
四種失敗來源（密碼／TOTP／QR／Passkey）都寫 auth.login_failed 稽核列且 reason_code 不同、
收件人（T80 收件設定：預設超管／僅超管／自訂帳號＋角色）與 LINE 的角色／個人勾選、
**LINE 獨立通道**（沒 Email 的管理者收得到；有 Email 沒綁 LINE 的只收 Email；一邊失敗不影響另一邊；不雙推）、
發送失敗與背景執行不影響登入回應。對外呼叫一律換掉（不連外）。"""
import json
import threading
import time

import pyotp
import pytest

from helpers import auth_alert as AA

TOKEN = "tok-SECRET-0123456789"
UID_A = "U" + "a" * 32
UID_B = "U" + "b" * 32
UID_C = "U" + "c" * 32


@pytest.fixture(autouse=True)
def _clean_audit_state():
    from helpers import audit as A
    A._FAIL_LAST.clear()
    A._FAIL_HOUR.clear()
    AA.reset_for_tests()                 # conftest 只在用到 client 的題才換乾淨的節流狀態；純函式題要自己清
    yield
    AA.reset_for_tests()
    A._FAIL_LAST.clear()
    A._FAIL_HOUR.clear()


@pytest.fixture
def sync(monkeypatch):
    """背景發送改同步（conftest 預設是不做事）；不排真的摘要計時器。回傳 {'timers': [...]}。"""
    monkeypatch.setattr(AA, "_spawn", lambda fn, *a: fn(*a))
    st = {"timers": []}
    monkeypatch.setattr(AA, "_schedule_summary_locked", lambda now: st["timers"].append(now))
    return st


@pytest.fixture
def delivered(sync, monkeypatch):
    """攔下 `_deliver`：記錄 (title, rows, reason)，不碰 Email／LINE。"""
    got = []
    monkeypatch.setattr(AA, "_deliver", lambda title, rows, reason: got.append((title, rows, reason)))
    return got


def _rows_of(where="1=1", params=()):
    from db import get_db
    c = get_db()
    try:
        return [dict(r) for r in c.execute(f"SELECT * FROM audit_log WHERE {where} ORDER BY id", params).fetchall()]
    finally:
        c.close()


def _bad_login(client, name="ghost", ip="203.0.113.7", pw="SuperSecret!1"):
    return client.post("/api/auth/login", json={"username": name, "password": pw}, headers={"X-Forwarded-For": ip})


# ── 1. 觸發：只在鎖定那一刻、內容不含密碼 ─────────────────────────────────────

def test_alert_fires_only_when_lockout_is_reached(client, delivered):
    for i in range(4):
        assert _bad_login(client).status_code == 401
    assert delivered == []                                   # 前 4 次失敗不發
    assert _bad_login(client).status_code == 401              # 第 5 次＝鎖定
    assert len(delivered) == 1
    assert _bad_login(client).status_code == 429             # 鎖定期間再打：不再發
    assert len(delivered) == 1


def test_alert_content_has_ip_account_count_until_but_no_secret(client, delivered):
    for _ in range(5):
        _bad_login(client, name="ghost", pw="SuperSecret!1")
    title, rows, reason = delivered[0]
    text = json.dumps([title, rows, reason], ensure_ascii=False)
    d = dict(rows)
    assert "ghost" in d["嘗試的帳號"] and "5" in d["連續失敗"] and "分鐘" in d["鎖定至"]
    assert "SuperSecret" not in text and TOKEN not in text
    assert "203.0.113.7" in text or "testclient" in text or d["來源 IP"]      # 來源 IP 一定有值


def test_alert_names_are_sanitized_and_capped(delivered, sync):
    AA.on_lockout("k1", "1.2.3.4", ["a\nb" + "x" * 200, "u2", "u3", "u4", "u5", "u6", "u7"], 5, 900, now=100.0)
    d = dict(delivered[0][1])
    assert "\n" not in d["嘗試的帳號"] and len(d["嘗試的帳號"].split("、")) == 5
    assert all(len(n) <= 64 for n in d["嘗試的帳號"].split("、"))


# ── 2. 節流：同範圍鎖定期間一次；全系統每小時上限＋摘要 ───────────────────────────

def test_same_key_only_once_during_lockout_then_again_after_expiry(delivered, sync):
    assert AA.on_lockout("k", "1.1.1.1", ["a"], 5, 900, now=1000.0) == "sent"
    assert AA.on_lockout("k", "1.1.1.1", ["a"], 5, 900, now=1500.0) == "dedup"
    assert AA.on_lockout("k", "1.1.1.1", ["a"], 5, 900, now=1901.0) == "sent"      # 鎖定結束後新的一輪
    assert len(delivered) == 2


def test_hourly_cap_merges_overflow_into_one_summary(delivered, sync):
    for i in range(AA.HOURLY_CAP):
        assert AA.on_lockout("k%d" % i, "10.0.0.%d" % i, ["a"], 5, 900, now=1000.0 + i) == "sent"
    assert AA.on_lockout("over1", "9.9.9.1", ["a"], 5, 900, now=1100.0) == "capped"
    assert AA.on_lockout("over2", "9.9.9.2", ["b"], 5, 900, now=1101.0) == "capped"
    assert len(delivered) == AA.HOURLY_CAP and sync["timers"]            # 沒再發，且排了摘要
    # 視窗騰出空位後送摘要：一則、講件數與 IP
    assert AA.flush_summary(now=1000.0 + AA.WINDOW_SECONDS + 1) == "sent"
    assert len(delivered) == AA.HOURLY_CAP + 1
    title, rows, reason = delivered[-1]
    d = dict(rows)
    assert "摘要" in title and d["期間內另有鎖定"] == "2 次" and "9.9.9.1" in d["來源 IP"] and "9.9.9.2" in d["來源 IP"]
    assert AA.flush_summary(now=1000.0 + AA.WINDOW_SECONDS + 2) == "empty"      # 不重複送


def test_window_slides_after_an_hour(delivered, sync):
    for i in range(AA.HOURLY_CAP):
        AA.on_lockout("k%d" % i, "10.0.0.%d" % i, [], 5, 900, now=1000.0)
    assert AA.on_lockout("later", "8.8.8.8", [], 5, 900, now=1000.0 + AA.WINDOW_SECONDS + 5) == "sent"


def test_account_scope_alert_has_own_title_and_dedups_separately(delivered, sync):
    """`scope="account"`（外網登入強化票用）：標題／欄位不同；以傳入的 key 去重（與 IP 鎖定互不影響），全系統每小時上限仍共用。"""
    assert AA.on_lockout("1.1.1.1", "1.1.1.1", ["a"], 5, 900, now=100.0) == "sent"
    assert AA.on_lockout("acct:alice", "1.1.1.1", ["alice"], 5, 900, now=101.0, scope="account") == "sent"
    assert AA.on_lockout("acct:alice", "2.2.2.2", ["alice"], 5, 900, now=102.0, scope="account") == "dedup"
    title, rows, reason = delivered[-1]
    assert "帳號" in title and dict(rows)["帳號"] == "alice" and dict(rows)["觸發來源 IP"] == "1.1.1.1"
    assert "來源 IP" not in dict(rows)


def test_on_lockout_never_raises(monkeypatch):
    monkeypatch.setattr(AA, "_spawn", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert AA.on_lockout("k", "1.1.1.1", ["a"], 5, 900) == "error"


# ── 3. 稽核補洞：四種失敗來源 ───────────────────────────────────────────────────

def test_password_failure_audit_row_unchanged_semantics(client):
    for _ in range(3):
        assert _bad_login(client, name="ghost").status_code == 401
    rows = _rows_of("action='auth.login_failed'")
    assert len(rows) == 1 and rows[0]["reason_code"] == "login_failed" and rows[0]["result"] == "fail"
    assert json.loads(rows[0]["detail"]) == {"ip": "testclient", "repeat": 2}      # 歷史形狀不變（來源 IP＝TCP 對端；XFF 不再被信任）
    assert "SuperSecret" not in json.dumps(rows[0], ensure_ascii=False)


def _enable_totp(client, make_user):
    u, p = make_user(role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    secret = client.post("/api/auth/totp/setup", headers=h).json()["secret"]
    assert client.post("/api/auth/totp/enable", headers=h, json={"code": pyotp.TOTP(secret).now()}).status_code == 200
    return u, p


def test_totp_failure_writes_audit_row_with_own_reason_code(client, make_user):
    u, p = _enable_totp(client, make_user)
    hdr = {"X-Forwarded-For": "203.0.113.90"}
    ch = client.post("/api/auth/login", json={"username": u, "password": p}, headers=hdr).json()["challengeToken"]
    for _ in range(2):
        assert client.post("/api/auth/login/totp", json={"challenge_token": ch, "code": "000000"}, headers=hdr).status_code == 401
    rows = _rows_of("action='auth.login_failed'")
    assert len(rows) == 1 and rows[0]["reason_code"] == "totp_failed" and rows[0]["username"] == u
    det = json.loads(rows[0]["detail"])
    assert det["method"] == "totp" and det["repeat"] == 1 and det["ip"] == "testclient"
    assert "000000" not in json.dumps(rows[0], ensure_ascii=False)                  # 不記驗證碼


def test_qr_failure_writes_audit_row_with_own_reason_code(client, make_user):
    u, p = _enable_totp(client, make_user)
    hdr = {"X-Forwarded-For": "203.0.113.91"}
    ch = client.post("/api/auth/login", json={"username": u, "password": p}, headers=hdr).json()["challengeToken"]
    r = client.post("/api/auth/login/qr-approve", json={"challenge_token": ch, "password": "wrong-password"}, headers=hdr)
    assert r.status_code == 401
    rows = _rows_of("action='auth.login_failed'")
    assert len(rows) == 1 and rows[0]["reason_code"] == "qr_failed" and json.loads(rows[0]["detail"])["method"] == "qr"
    assert "wrong-password" not in json.dumps(rows[0], ensure_ascii=False)


def test_passkey_failure_writes_audit_row_with_own_reason_code(client, make_user, monkeypatch):
    import helpers.auth
    monkeypatch.setattr(helpers.auth, "PASSKEY_ENABLED", True)          # 功能總開關預設關（見 test_passkey_disabled）
    u, _p = make_user(role="staff")
    hdr = {"X-Forwarded-For": "203.0.113.92"}
    r = client.post("/api/auth/webauthn/login/complete", headers=hdr, json={
        "username": u, "challengeToken": "no-such-challenge", "id": "AA", "rawId": "AA", "type": "public-key",
        "response": {"clientDataJSON": "", "authenticatorData": "", "signature": ""}})
    assert r.status_code == 401, r.text
    rows = _rows_of("action='auth.login_failed'")
    assert len(rows) == 1 and rows[0]["reason_code"] == "passkey_failed" and json.loads(rows[0]["detail"])["method"] == "passkey"


def test_sources_do_not_merge_into_each_other():
    """同帳號＋同 IP 但來源不同 ⇒ 各自一列；同來源 60 秒內合併成 repeat。"""
    from helpers.audit import _audit_login_failed
    assert _audit_login_failed("u", "1.1.1.1", source="password") == "new"
    assert _audit_login_failed("u", "1.1.1.1", source="totp") == "new"
    assert _audit_login_failed("u", "1.1.1.1", source="passkey") == "new"
    assert _audit_login_failed("u", "1.1.1.1", source="qr") == "new"
    assert _audit_login_failed("u", "1.1.1.1", source="totp") == "repeat"
    assert sorted(r["reason_code"] for r in _rows_of("action='auth.login_failed'")) == \
        ["login_failed", "passkey_failed", "qr_failed", "totp_failed"]
    assert _audit_login_failed("u", "1.1.1.1", source="bogus") == "repeat"          # 不認得的來源當密碼（固定詞彙）


def test_new_reason_codes_have_labels():
    from helpers.audit import _FAIL_REASON_LABELS, LOGIN_FAIL_REASONS
    assert all(c in _FAIL_REASON_LABELS for c in LOGIN_FAIL_REASONS.values())


# ── 4. 收件人（T80 收件設定）與 LINE 獨立通道（三個事件） ───────────────────────

def _user(make_user, name, role, email=None, line=None):
    make_user(username=name, role=role)
    if email:
        from db import get_db
        c = get_db()
        c.execute("UPDATE users SET email=? WHERE username=?", (email, name))
        c.commit()
        c.close()
    if line:
        from helpers import line_notify
        line_notify.link_user(name, line)
    return name


@pytest.fixture
def env(client, make_user, monkeypatch):
    """LINE 啟用＋三個事件都勾選；攔下 LINE `push`（記錄每次推給哪些 userId）與 Email `_async_send`（記錄寄給哪些信箱）。"""
    from helpers import line_notify, email_notify
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": TOKEN,
                                 "events": {"auth_lockout": True, "approval_review_edit": True, "warranty_expiry": True}})
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (True, "測試允許"))
    out = {"line": [], "mail": [], "make_user": make_user}

    def fake_push(ids, text):
        out["line"].append({"to": list(ids), "text": text})
        return line_notify.SEND_TRANSIENT_FAIL if out.get("line_fail") else line_notify.SEND_SENT
    monkeypatch.setattr(line_notify, "push", fake_push)
    monkeypatch.setattr("helpers.line_quota.after_push", lambda *a, **k: None)

    class _H:
        def wait(self, *a, **k):
            return out.get("mail_outcome", "sent")
    def fake_async(to, subject, html):
        if out.get("mail_fail"):
            raise RuntimeError("smtp down")
        out["mail"].append((list(to), subject, html))
        return _H()
    monkeypatch.setattr(email_notify, "_async_send", fake_async)
    # LINE 的背景執行緒改同步（測試可立刻檢查）
    real_deliver = line_notify.deliver_event
    monkeypatch.setattr(line_notify, "notify_event", lambda ev, **kw: real_deliver(ev, **kw))
    monkeypatch.setattr(AA, "_spawn", lambda fn, *a: fn(*a))
    return out


def _line_targets(env):
    return sorted({u for p in env["line"] for u in p["to"]})


def _mail_targets(env):
    return sorted(a for to, _s, _h in env["mail"] for a in to)


def _send(event, **kw):
    from helpers import email_notify as EN
    return EN.send_registered(event, title="t", rows=[("k", "v")], reason="r", **kw)


def _mk_all_events_users(env):
    """四種人：沒 Email 有 LINE／有 Email 沒 LINE／兩邊都有／一般管理員。"""
    mk = env["make_user"]
    _user(mk, "sa_noemail", "superadmin", email=None, line=UID_A)
    _user(mk, "sa_mail_only", "superadmin", email="m@example.com")
    _user(mk, "sa_both", "superadmin", email="b@example.com", line=UID_B)
    _user(mk, "plain_admin", "admin", email="a@example.com", line=UID_C)


def test_auth_lockout_line_reaches_admin_without_email_email_only_for_unlinked(env):
    _mk_all_events_users(env)
    AA._deliver("登入失敗過多，來源已被鎖定", [("來源 IP", "1.2.3.4")], "x")
    assert _mail_targets(env) == ["b@example.com", "m@example.com"]       # 有 Email 的超管
    assert _line_targets(env) == [UID_A, UID_B]                           # 有綁 LINE 的超管（含沒有 Email 的）；一般管理員不是預設收件人
    assert len(env["line"]) == 1                                          # LINE 只推一次


def test_approval_review_edit_line_without_email(env):
    """送審人沒有 Email 但有綁 LINE ⇒ 收得到；群組（超管）照 T80 預設。"""
    _mk_all_events_users(env)
    _user(env["make_user"], "requester", "sales", email=None, line="U" + "d" * 32)
    _send("approval_review_edit", usernames=["requester"], to_group=True)
    assert _line_targets(env) == sorted([UID_A, UID_B, "U" + "d" * 32])
    assert _mail_targets(env) == ["b@example.com", "m@example.com"]


def test_warranty_expiry_line_without_email(env):
    _mk_all_events_users(env)
    _user(env["make_user"], "owner", "sales", email=None, line="U" + "e" * 32)
    _send("warranty_expiry", usernames=["owner"], to_group=True)
    ln = _line_targets(env)
    assert "U" + "e" * 32 in ln and UID_C in ln and UID_B in ln           # 業務負責人（沒 Email）＋管理員群組（warranty_expiry 預設群組＝admins）
    assert "a@example.com" in _mail_targets(env) and "m@example.com" in _mail_targets(env)


_THREE = [("auth_lockout", dict(to_group=True)),
          ("approval_review_edit", dict(usernames=["u_sa"], to_group=True)),
          ("warranty_expiry", dict(usernames=["u_sa"], to_group=True))]


@pytest.mark.parametrize("event,kw", _THREE)
def test_email_unsubscribe_does_not_affect_line_and_line_optout_does_not_affect_email(env, event, kw):
    from db import get_db
    from helpers import line_recipients
    _user(env["make_user"], "u_sa", "superadmin", email="u@example.com", line=UID_A)
    # Email 個人退訂（users.notification_muted）⇒ 沒有信，LINE 照發
    c = get_db()
    c.execute("UPDATE users SET notification_muted=? WHERE username='u_sa'", (json.dumps([event]),))
    c.commit()
    c.close()
    _send(event, **kw)
    assert "u@example.com" not in _mail_targets(env) and UID_A in _line_targets(env)
    # 還原 Email、改 LINE 個人退訂 ⇒ 信照寄，沒有 LINE
    c = get_db()
    c.execute("UPDATE users SET notification_muted='[]' WHERE username='u_sa'")
    c.commit()
    c.close()
    env["line"].clear(); env["mail"].clear()
    line_recipients.set_muted("u_sa", event, True)
    _send(event, **kw)
    assert "u@example.com" in _mail_targets(env) and _line_targets(env) == []


@pytest.mark.parametrize("event,kw", _THREE)
def test_mail_type_switched_off_does_not_stop_line_but_stops_email(env, event, kw):
    """「信件與通知收件設定」把這種信關掉（`off`）⇒ 沒有信；LINE 有自己的公司開關，不受影響。（auth_lockout 的信件關閉被鎖住，只驗 LINE 不受 off 欄位影響。）"""
    from helpers.settings import _set_setting
    _user(env["make_user"], "u_sa", "superadmin", email="u@example.com", line=UID_A)
    _set_setting("mail_recipient_overrides", {event: {"mode": "default", "off": True}})
    _send(event, **kw)
    assert UID_A in _line_targets(env)
    if event != "auth_lockout":
        assert env["mail"] == []


@pytest.mark.parametrize("event,kw", _THREE)
def test_inactive_user_gets_nothing_on_either_channel(env, event, kw):
    from db import get_db
    _user(env["make_user"], "u_sa", "superadmin", email="u@example.com", line=UID_A)
    _user(env["make_user"], "u_sb", "superadmin", email="v@example.com", line=UID_B)
    c = get_db()
    c.execute("UPDATE users SET active=0 WHERE username='u_sb'")
    c.commit()
    c.close()
    _send(event, **kw)
    assert _line_targets(env) == [UID_A] and _mail_targets(env) == ["u@example.com"]


def test_line_off_by_company_switch_email_still_sent(env):
    from helpers import line_notify
    _user(env["make_user"], "sa", "superadmin", email="s@example.com", line=UID_A)
    line_notify.set_event("auth_lockout", False)
    AA._deliver("t", [("k", "v")], "r")
    assert env["line"] == [] and _mail_targets(env) == ["s@example.com"]


def test_email_failure_does_not_stop_line(env):
    _user(env["make_user"], "sa", "superadmin", email="s@example.com", line=UID_A)
    env["mail_fail"] = True                                                 # Email 炸了 ⇒ LINE 照發（LINE 先於信件處理），_deliver 不丟例外
    AA._deliver("t", [("k", "v")], "r")
    assert _line_targets(env) == [UID_A] and env["mail"] == []


def test_line_failure_does_not_stop_email_and_never_raises(env, monkeypatch):
    from helpers import line_notify
    _user(env["make_user"], "sa", "superadmin", email="s@example.com", line=UID_A)
    env["line_fail"] = True                                                 # LINE 暫時失敗 ⇒ Email 照寄
    AA._deliver("t", [("k", "v")], "r")
    assert _mail_targets(env) == ["s@example.com"]
    monkeypatch.setattr(line_notify, "push", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))      # push 本身炸 ⇒ deliver_event 永不丟
    assert line_notify.deliver_event("auth_lockout", to_group=True, title="t") == line_notify.SEND_TRANSIENT_FAIL
    env["mail"].clear()
    AA._deliver("t", [("k", "v")], "r")
    assert _mail_targets(env) == ["s@example.com"]


def test_line_respects_t80_override_modes_and_line_prefs(env):
    from helpers import line_recipients, line_notify
    from helpers.settings import _set_setting
    mk = env["make_user"]
    _user(mk, "sa", "superadmin", line=UID_A)
    _user(mk, "ad", "admin", line=UID_B)
    _user(mk, "eng", "engineer", line=UID_C)
    # custom：角色 admin＋指定帳號 eng（取代預設的超管群組）
    _set_setting("mail_recipient_overrides", {"auth_lockout": {"mode": "custom", "users": ["eng"], "roles": ["admin"]}})
    AA._deliver("t", [("k", "v")], "r")
    assert _line_targets(env) == [UID_B, UID_C]
    # LINE 角色允許清單只留 admin ⇒ eng 被濾掉
    env["line"].clear()
    line_notify.set_event_roles("auth_lockout", ["admin"])
    AA._deliver("t", [("k", "v")], "r")
    assert _line_targets(env) == [UID_B]
    # 本人 LINE 退訂 ⇒ 不推
    env["line"].clear()
    line_recipients.set_muted("ad", "auth_lockout", True)
    AA._deliver("t", [("k", "v")], "r")
    assert env["line"] == []
    # superadmin_only 覆寫
    line_notify.set_event_roles("auth_lockout", None)
    _set_setting("mail_recipient_overrides", {"auth_lockout": {"mode": "superadmin_only"}})
    AA._deliver("t", [("k", "v")], "r")
    assert _line_targets(env) == [UID_A]


def test_event_recipients_follow_override_for_existing_events(env):
    """既有事件的事件收件人也套 T80 覆寫：superadmin_only ⇒ 送審人被換成超管；custom ⇒ 送審人＋指定帳號。"""
    from helpers.settings import _set_setting
    mk = env["make_user"]
    _user(mk, "sa", "superadmin", line=UID_A)
    _user(mk, "req", "sales", line=UID_B)
    _user(mk, "extra", "engineer", line=UID_C)
    _set_setting("mail_recipient_overrides", {"approval_review_edit": {"mode": "superadmin_only"}})
    _send("approval_review_edit", usernames=["req"], to_group=True)
    assert _line_targets(env) == [UID_A]
    env["line"].clear()
    _set_setting("mail_recipient_overrides", {"approval_review_edit": {"mode": "custom", "users": ["extra"], "roles": []}})
    _send("approval_review_edit", usernames=["req"], to_group=True)
    assert _line_targets(env) == [UID_B, UID_C]


# ── 4b. 批次 0 的共用機制：重試不重推、額度保留、line_group／exclude、事件字典 ─────

def test_wait_true_email_transient_retry_does_not_repush_line(env):
    """每日檢查型（wait=True）：Email 暫時失敗隔天重試 ⇒ LINE 第一次就發（獨立），重試時被「已推播」記號擋住，不重推。"""
    _user(env["make_user"], "sa", "superadmin", email="s@example.com", line=UID_A)
    env["mail_outcome"] = "transient_fail"
    out = {}
    assert _send("warranty_expiry", usernames=[], to_group=True, wait=True, out=out, line_key="k1") is False      # 呼叫端不寫記號 ⇒ 明天重試
    assert out["line"] == "sent" and len(env["line"]) == 1
    out2 = {}
    assert _send("warranty_expiry", usernames=[], to_group=True, wait=True, out=out2, line_key="k1") is False       # 重試
    assert out2["line"] == "already_pushed" and len(env["line"]) == 1                                         # 沒有第二則
    env["mail_outcome"] = "sent"
    assert _send("warranty_expiry", usernames=[], to_group=True, wait=True, line_key="k1") is True              # 信這次寄成功 ⇒ 可寫記號；LINE 仍不重推
    assert len(env["line"]) == 1
    assert _send("warranty_expiry", usernames=[], to_group=True, wait=True, line_key="k2") is True              # 不同鑰匙＝不同的事 ⇒ 會推
    assert len(env["line"]) == 2


def test_line_mark_is_not_written_on_transient_failure_and_expires(env):
    from helpers import line_notify
    from helpers.settings import _get_setting, _set_setting
    _user(env["make_user"], "sa", "superadmin", line=UID_A)
    env["line_fail"] = True                                                 # 暫時失敗 ⇒ 不記，下次還會試
    assert line_notify.deliver_event("auth_lockout", to_group=True, title="t", dedupe_key="kx") == line_notify.SEND_TRANSIENT_FAIL
    assert "kx" not in (_get_setting(line_notify.MARKS_KEY, {}) or {})
    env["line_fail"] = False
    assert line_notify.deliver_event("auth_lockout", to_group=True, title="t", dedupe_key="kx") == line_notify.SEND_SENT
    assert "kx" in _get_setting(line_notify.MARKS_KEY, {})
    _set_setting(line_notify.MARKS_KEY, {"kx": "2020-01-01T00:00:00", "old": "2020-01-01T00:00:00"})              # 過期的會被清掉
    assert line_notify.deliver_event("auth_lockout", to_group=True, title="t", dedupe_key="ky") == line_notify.SEND_SENT
    assert sorted(_get_setting(line_notify.MARKS_KEY, {})) == ["ky"]


def test_wait_true_nobody_has_email_line_is_the_only_channel(env):
    """沒有任何 Email 收件人：以前回 False（每天重試、永遠沒結果）；現在 LINE 發成功才回 True（寫記號、不再重試）。"""
    from helpers import line_notify
    _user(env["make_user"], "sa", "superadmin", email=None, line=UID_A)
    out = {}
    assert _send("warranty_expiry", usernames=[], to_group=True, wait=True, out=out, line_key="k") is True
    assert out["outcome"] == "no_recipient" and out["line"] == "sent" and _line_targets(env) == [UID_A]
    assert _send("warranty_expiry", usernames=[], to_group=True, wait=True, line_key="k") is True               # 重試：已推過 ⇒ 仍回 True（記號已寫），不重推
    assert len(env["line"]) == 1
    env["line"].clear()
    env["line_fail"] = True                                                 # LINE 暫時失敗 ⇒ False（下次重試）
    assert _send("warranty_expiry", usernames=[], to_group=True, wait=True, line_key="k-new") is False
    line_notify.set_event("warranty_expiry", False)                         # 沒開 LINE ⇒ 維持舊行為 False
    env["line_fail"] = False
    assert _send("warranty_expiry", usernames=[], to_group=True, wait=True, line_key="k-new2") is False


def _set_usage(used, limit=100):
    from helpers import line_quota
    from helpers.settings import _set_setting
    _set_setting(line_quota.STATE_KEY, {"month": line_quota.month_key(), "used": used, "limit": limit, "alerted": []})


def test_quota_reserve_pauses_normal_events_but_not_critical(env):
    """用量 ≥ 90%：一般事件（保固／審核編輯）暫停（不記記號，之後還能補發）；critical（登入鎖定告警）照發。"""
    from helpers import line_notify
    _user(env["make_user"], "sa", "superadmin", email="s@example.com", line=UID_A)
    _set_usage(90)
    assert line_notify.deliver_event("warranty_expiry", to_group=True, title="t", dedupe_key="w1") == "paused_quota"
    assert line_notify.deliver_event("approval_review_edit", to_group=True, title="t") == "paused_quota"
    assert env["line"] == []
    assert line_notify.deliver_event("auth_lockout", to_group=True, title="t") == line_notify.SEND_SENT
    assert _line_targets(env) == [UID_A]
    _set_usage(89)                                                          # 回到 90% 以下 ⇒ 恢復；先前暫停的沒有記號，可以補發
    assert line_notify.deliver_event("warranty_expiry", to_group=True, title="t", dedupe_key="w1") == line_notify.SEND_SENT


def test_quota_reserve_ignores_unreadable_usage_and_other_month(env):
    from helpers import line_notify, line_quota
    from helpers.settings import _set_setting
    _user(env["make_user"], "sa", "superadmin", line=UID_A)
    assert line_quota.cached_percent() is None and not line_quota.reserve_paused()          # 沒讀過用量 ⇒ 不擋
    _set_setting(line_quota.STATE_KEY, {"month": "2020-01", "used": 99, "limit": 100})
    assert line_quota.cached_percent() is None                              # 不是本月的狀態 ⇒ 不擋
    _set_setting(line_quota.STATE_KEY, {"month": line_quota.month_key(), "used": 99, "limit": None})
    assert not line_quota.reserve_paused()                                  # 無限方案 ⇒ 不擋
    assert line_notify.deliver_event("warranty_expiry", to_group=True, title="t") == line_notify.SEND_SENT


def test_event_dictionary_shape_and_priorities():
    from helpers import line_notify as L
    assert set(L.LINE_EVENTS) == set(L.WIRED_EVENTS) >= {"auth_lockout", "approval_review_edit", "warranty_expiry"}
    for k, spec in L.LINE_EVENTS.items():
        assert set(spec) == {"priority", "digest", "line_group"}, k
        assert spec["priority"] in ("critical", "normal") and spec["digest"] is False
        assert spec["line_group"] in (None, "inherit") or spec["line_group"] in __import__("helpers.mail_types", fromlist=["GROUPS"]).GROUPS
    assert L.LINE_EVENTS["auth_lockout"]["priority"] == "critical"
    assert L.LINE_EVENTS["warranty_expiry"]["priority"] == "normal" and L.LINE_EVENTS["approval_review_edit"]["priority"] == "normal"


def test_line_group_override_and_exclude(env, monkeypatch):
    """`line_group`：None＝LINE 只發給事件收件人；指定群組＝LINE 用另一個群組；`exclude`＝排除操作者本人（只影響 LINE）。"""
    from helpers import line_notify
    mk = env["make_user"]
    _user(mk, "sa", "superadmin", line=UID_A)
    _user(mk, "ad", "admin", line=UID_B)
    _user(mk, "req", "sales", line=UID_C)
    monkeypatch.setitem(line_notify.LINE_EVENTS, "warranty_expiry", {"priority": "normal", "digest": False, "line_group": None})
    _send("warranty_expiry", usernames=["req"], to_group=True)                                # 保固信件群組＝admins；LINE 只給事件收件人
    assert _line_targets(env) == [UID_C]
    env["line"].clear()
    monkeypatch.setitem(line_notify.LINE_EVENTS, "warranty_expiry", {"priority": "normal", "digest": False, "line_group": "superadmins"})
    _send("warranty_expiry", usernames=["req"], to_group=True)
    assert _line_targets(env) == [UID_A, UID_C]
    env["line"].clear()
    monkeypatch.setitem(line_notify.LINE_EVENTS, "warranty_expiry", {"priority": "normal", "digest": False, "line_group": "inherit"})
    _send("warranty_expiry", usernames=["req"], to_group=True, line_exclude=["req", "sa"])
    assert _line_targets(env) == [UID_B]                                                      # admins 群組（sa 被排除、req 被排除）
    assert _mail_targets(env) == []                                                           # 沒有人有 Email（排除只影響 LINE，這裡只是確認信件路徑沒被動到）


def test_non_wired_event_never_pushes_line(env):
    _user(env["make_user"], "sa", "superadmin", email="s@example.com", line=UID_A)
    _send("settlement_finalized", to_group=True)
    assert env["line"] == [] and _mail_targets(env) == ["s@example.com"]


def test_group_usernames_matches_group_emails_when_everyone_has_email(client, make_user):
    """`event_audience`（不要求 Email）與 `email_notify._group_emails`／`_lookup_emails` 的收件規則不可漂移：人人有 Email、沒人退訂時兩者必須是同一批人。"""
    from helpers import email_notify as EN, event_audience as EA
    from helpers.settings import _set_setting
    for name, role in (("sa1", "superadmin"), ("ad1", "admin"), ("sl1", "sales"), ("en1", "engineer"), ("fi1", "finance")):
        _user(make_user, name, role, email=name + "@example.com")
    for ov in (None,
               {"mode": "default"},
               {"mode": "superadmin_only"},
               {"mode": "custom", "users": ["sl1"], "roles": ["finance"]},
               {"mode": "custom", "users": [], "roles": []},
               {"mode": "custom", "users": ["nobody"], "roles": ["bogus"]}):
        for key in ("auth_lockout", "backup_error", "settlement_finalized", "payment_request_approved", "not_registered_key"):
            _set_setting("mail_recipient_overrides", {} if ov is None else {key: ov})
            for ev_users, grp in ((None, True), (["sl1"], False), (["sl1", "ad1"], True), (["en1"], False)):
                emails = sorted(set((EN._lookup_emails(ev_users, key) if ev_users else []) + (EN._group_emails(key) if grp else [])))
                names = sorted(set(u + "@example.com" for u in EA.resolve_usernames(key, ev_users, grp) if u != "demo"))     # 種子 DB 的 demo 是沒有 Email 的超管
                assert emails == names, (key, ov, ev_users, grp)


def test_unregistered_key_falls_back_to_superadmins_only(client, make_user):
    from helpers import event_audience as EA
    _user(make_user, "sa1", "superadmin")
    _user(make_user, "ad1", "admin")
    assert [u for u in EA.group_usernames("not_registered_key") if u != "demo"] == ["sa1"]


def test_auth_lockout_is_registered_system_type_locked_on(client):
    from helpers import mail_types, notify_matrix, line_notify
    t = mail_types.get("auth_lockout")
    assert t and t.category == "system" and t.group == "superadmins"
    assert "auth_lockout" in notify_matrix.MAIL_OFF_LOCKED                  # 資安告警不可被關
    assert {"auth_lockout", "approval_review_edit", "warranty_expiry"} <= set(line_notify.WIRED_EVENTS)


# ── 5. 不拖慢、不阻塞登入 ────────────────────────────────────────────────────────

def test_lockout_response_not_blocked_by_slow_delivery(client, monkeypatch):
    """發送卡住（模擬 Email／LINE 很慢）⇒ 第 5 次失敗的回應照常立刻回來：發送在背景執行緒。"""
    gate = threading.Event()
    started = threading.Event()
    def slow(title, rows, reason):
        started.set()
        gate.wait(10)
    monkeypatch.setattr(AA, "_deliver", slow)
    monkeypatch.setattr(AA, "_spawn", lambda fn, *a: (threading.Thread(target=fn, args=a, daemon=True).start()))
    t0 = time.monotonic()
    for _ in range(5):
        assert _bad_login(client).status_code == 401
    assert time.monotonic() - t0 < 5
    assert started.wait(5)                                                  # 真的有在背景跑
    gate.set()


def test_delivery_failure_never_breaks_login_response(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("everything is on fire")
    monkeypatch.setattr(AA, "_deliver", boom)
    monkeypatch.setattr(AA, "_spawn", lambda fn, *a: fn(*a))                # 同步＋炸 ⇒ on_lockout 自己吞掉
    for _ in range(5):
        r = _bad_login(client)
        assert r.status_code == 401
    assert _bad_login(client).status_code == 429                            # 鎖定照常生效


def test_on_lockout_exception_inside_rl_fail_is_swallowed(client, monkeypatch):
    monkeypatch.setattr(AA, "on_lockout", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    for _ in range(5):
        assert _bad_login(client).status_code == 401
    assert _bad_login(client).status_code == 429
