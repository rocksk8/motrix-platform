# -*- coding: utf-8 -*-
"""寄信精靈複驗（fbb4cf116，C／D／E／F 修正之後）——hichan-3，2026-11-13。

綠燈：修正真的生效（不靠 monkeypatch _send_raising——那會讓 `cfg` 參數沒被走到；這裡換掉 _smtp_open，驗真正用來登入的是候選設定）。
xfail(strict)＝複驗新發現：
  I 測試成功後存在 `email_setup_test_proof` 的候選設定帶著明文 SMTP 密碼；每日備份的「系統設定」匯出只挖掉 email_notify.smtp_password，
    這個新 key 走 `ELSE value_json` ⇒ 密碼落進備份資料夾（還會鏡像到雲端），而且沒按「我收到了」就一直留著。
  J 舊 PUT /api/settings/email-notify 仍可存任意連接埠（精靈只准 25/465/587/2525），再配舊的 POST …/test 就是無頻率限制的連接埠探測。
"""
import json

import pytest


def _h(client, make_user, name, role="superadmin", email="me@example.com"):
    su, sp = make_user(username=name, role=role)
    from db import get_db
    c = get_db()
    c.execute("UPDATE users SET email=? WHERE username=?", (email, name))
    c.commit()
    c.close()
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": su, "password": sp}).json()["token"]}


GOOD = {"provider": "gmail", "smtp_user": "co@gmail.com", "smtp_password": "abcd efgh ijkl mnop", "base_url": "https://erp.example.com"}
PW = "abcdefghijklmnop"


def _S():
    import importlib
    return importlib.import_module("routers.system")


def _cfg():
    return _S()._get_setting("email_notify", {}) or {}


@pytest.fixture()
def fake_smtp(monkeypatch):
    """換掉真正開連線的那一層，記下『實際拿來登入』的主機／埠／帳密。"""
    from helpers import email_notify as EN
    box = {"logins": [], "opens": [], "fail_login": False}

    class _S_:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, u, p):
            box["logins"].append((u, p))
            if box["fail_login"]:
                import smtplib
                raise smtplib.SMTPAuthenticationError(535, b"nope")
        def sendmail(self, *a, **k): pass

    def opener(host, port, timeout=15):
        box["opens"].append((host, port))
        return _S_()
    monkeypatch.setattr(EN, "_smtp_open", opener)
    monkeypatch.setattr(EN, "_smtp_send_blocked", lambda subject: False)
    return box


# ── 綠燈：C 真的生效（走真實的 _send_raising） ───────────────────────────────
def test_candidate_is_what_actually_logs_in_and_nothing_is_stored_on_failure(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r2_c")
    S = _S()
    S._set_setting("email_notify", {**S._EMAIL_DEFAULTS, "enabled": True, "smtp_host": "smtp.old.com", "smtp_port": 587,
                                   "smtp_user": "old@old.com", "smtp_password": "OLDPW"})
    before = dict(_cfg())
    fake_smtp["fail_login"] = True
    r = client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h)
    assert r.status_code == 502
    assert fake_smtp["logins"] == [("co@gmail.com", PW)], "登入用的不是候選設定"
    assert fake_smtp["opens"] == [("smtp.gmail.com", 587)]
    assert _cfg() == before, "失敗的測試動到了正在使用的設定"
    assert (S._get_setting(S._EMAIL_WIZARD_PROOF, {}) or {}) == {}, "失敗卻留下了證明"


def test_success_stores_nothing_live_until_activate_then_proof_is_consumed(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r2_c2")
    S = _S()
    S._set_setting("email_notify", {**S._EMAIL_DEFAULTS, "enabled": True, "smtp_host": "smtp.old.com", "smtp_port": 587,
                                   "smtp_user": "old@old.com", "smtp_password": "OLDPW"})
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code == 200
    assert _cfg()["smtp_user"] == "old@old.com"                       # 還沒按「我收到了」，正式設定不變
    assert client.post("/api/settings/email-notify/wizard/activate", json=GOOD, headers=h).status_code == 200
    c = _cfg()
    assert c["smtp_user"] == "co@gmail.com" and c["smtp_password"] == PW and c["enabled"] is True
    assert client.post("/api/settings/email-notify/wizard/activate", json=GOOD, headers=h).status_code == 400, "證明沒有被用掉"


def test_activate_refused_when_live_config_changed_after_the_test(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r2_c3")
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code == 200
    S = _S()
    S._set_setting("email_notify", {**S._EMAIL_DEFAULTS, **_cfg(), "smtp_user": "someone@else.com", "smtp_password": "zzz"})
    assert client.post("/api/settings/email-notify/wizard/activate", json=GOOD, headers=h).status_code == 400
    assert _cfg()["smtp_user"] == "someone@else.com"


# ── 綠燈：D／E／F ──────────────────────────────────────────────────────────
def test_put_enabling_needs_a_proof_for_exactly_these_credentials(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r2_d")
    full = {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "smtp_user": "co@gmail.com", "smtp_password": PW,
            "base_url": "https://erp.example.com", "from_name": "x"}
    assert client.put("/api/settings/email-notify", json={**full, "enabled": True}, headers=h).status_code == 422      # 沒證明
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code == 200
    assert client.put("/api/settings/email-notify", json={**full, "smtp_user": "other@gmail.com", "enabled": True}, headers=h).status_code == 422
    assert client.put("/api/settings/email-notify", json={**full, "smtp_password": "different", "enabled": True}, headers=h).status_code == 422
    assert client.put("/api/settings/email-notify", json={**full, "smtp_port": 465, "enabled": True}, headers=h).status_code == 422
    assert _cfg().get("enabled") in (None, False)
    assert client.put("/api/settings/email-notify", json={**full, "enabled": True}, headers=h).status_code == 200      # 同一份 ⇒ 可
    assert _cfg()["enabled"] is True
    assert client.put("/api/settings/email-notify", json={"enabled": False}, headers=h).status_code == 200            # 關閉不需證明
    assert _cfg()["enabled"] is False and _cfg()["smtp_user"] == "co@gmail.com"                                         # E：缺的欄位保留


def test_put_enabling_with_stale_proof_is_refused(client, make_user, fake_smtp):
    from datetime import datetime, timedelta
    h = _h(client, make_user, "atk_r2_d2")
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code == 200
    S = _S()
    p = S._get_setting(S._EMAIL_WIZARD_PROOF, {})
    S._set_setting(S._EMAIL_WIZARD_PROOF, {**p, "at": (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")})
    r = client.put("/api/settings/email-notify", json={"smtp_host": "smtp.gmail.com", "smtp_port": 587, "smtp_user": "co@gmail.com",
                                                      "smtp_password": PW, "enabled": True}, headers=h)
    assert r.status_code == 422


def test_rate_limit_sixth_call_never_opens_a_connection_and_ports_are_restricted(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r2_f")
    codes = [client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code for _ in range(7)]
    assert codes == [200] * 5 + [429, 429], codes
    assert len(fake_smtp["opens"]) == 5
    h2 = _h(client, make_user, "atk_r2_f2")                                                # 另一個帳號有自己的額度
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h2).status_code == 200
    for port in (22, 3306, 6379, 80, 8080):
        r = client.post("/api/settings/email-notify/wizard/test-me", headers=h2,
                        json={**GOOD, "provider": "other", "smtp_host": "10.0.0.5", "smtp_port": port})
        assert r.status_code == 422, port
    assert ("10.0.0.5", 22) not in fake_smtp["opens"]


def test_no_secret_in_responses_or_audit_after_the_fix(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r2_pw")
    fake_smtp["fail_login"] = True
    a = client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h)
    fake_smtp["fail_login"] = False
    b = client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h)
    c = client.post("/api/settings/email-notify/wizard/activate", json=GOOD, headers=h)
    d = client.get("/api/settings/email-notify", headers=h)
    from db import get_db
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM audit_log WHERE action LIKE 'settings.email_notify%'").fetchall()]
    finally:
        conn.close()
    blob = json.dumps([a.text, b.text, c.text, d.text, rows], ensure_ascii=False)
    assert PW not in blob and "abcd efgh" not in blob and "535" not in blob


# ── 複驗新發現 ───────────────────────────────────────────────────────────────
def test_atk_wizard_proof_must_not_put_the_smtp_password_into_the_backup_export(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r2_i")
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code == 200
    import archive
    import db
    conn = db.get_db()
    try:
        rows = conn.execute(archive._daily_backup_tables()["系統設定"]).fetchall()
    finally:
        conn.close()
    leaked = [r[0] for r in rows if PW in (r[1] or "")]
    assert not leaked, "備份匯出含明文 SMTP 密碼的設定列：%s（archive.py 只對 email_notify 做 json_remove）" % leaked


def test_atk_old_put_must_not_accept_arbitrary_smtp_ports(client, make_user, fake_smtp):
    h = _h(client, make_user, "atk_r2_j")
    r = client.put("/api/settings/email-notify", json={"smtp_host": "10.0.0.5", "smtp_port": 3306, "enabled": False}, headers=h)
    assert r.status_code == 422, "PUT 接受了連接埠 3306"


# ── 補充（I／J 的另一面）────────────────────────────────────────────────────────────────
def _proof():
    import importlib
    S = importlib.import_module("routers.system")
    return S._get_setting(S._EMAIL_WIZARD_PROOF, {}) or {}


def test_failed_retest_and_an_expired_proof_do_not_keep_the_candidate_password(client, make_user, fake_smtp):
    import importlib
    from datetime import datetime, timedelta
    S = importlib.import_module("routers.system")
    h = _h(client, make_user, "atk_r2_i2")
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code == 200
    import json as _j
    raw = _j.dumps(_proof(), ensure_ascii=False)
    assert "cfg" not in _proof() and PW not in raw and "abcd" not in raw       # 證明不存密碼（連純雜湊都沒有），只有帶金鑰的 HMAC 指紋
    assert len(_proof().get("fp", "")) == 64 and _proof().get("fp_full")
    # 按「我收到了」送來的候選設定與測試時不同（改密碼／主機／埠）⇒ 指紋不符 ⇒ 擋
    for patch in ({"smtp_password": "zzzzzzzzzzzzzzzz"}, {"provider": "other", "smtp_host": "evil.example", "smtp_port": 587}, {"smtp_user": "x@gmail.com"}):
        assert client.post("/api/settings/email-notify/wizard/activate", json={**GOOD, **patch}, headers=h).status_code == 400, patch
    assert client.post("/api/settings/email-notify/wizard/activate", headers=h).status_code == 400     # 不帶設定也不能啟用
    S._set_setting(S._EMAIL_WIZARD_PROOF, {**_proof(), "at": (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")})
    assert client.get("/api/settings/email-notify", headers=h).status_code == 200
    assert _proof() == {}                                                    # 過期的證明在讀設定時順手清掉


def test_old_put_keeps_working_for_an_unchanged_unusual_port_and_old_test_endpoint_is_rate_limited(client, make_user, fake_smtp, monkeypatch):
    import importlib
    S = importlib.import_module("routers.system")
    h = _h(client, make_user, "atk_r2_j2")
    S._set_setting("email_notify", {**S._EMAIL_DEFAULTS, "smtp_host": "mail.lan.example", "smtp_port": 2587, "smtp_user": "u@lan.example", "smtp_password": "pw"})
    r = client.put("/api/settings/email-notify", json={"smtp_host": "mail.lan.example", "smtp_port": 2587, "from_name": "舊設定頁"}, headers=h)
    assert r.status_code == 200                                              # 沒改埠 ⇒ 既有的非標準埠照常可存
    assert client.put("/api/settings/email-notify", json={"smtp_port": 3306}, headers=h).status_code == 422
    codes = [client.post("/api/settings/email-notify/test", headers=h).status_code for _ in range(7)]
    assert 429 in codes and codes.index(429) == 5, codes                     # 舊的寄測試信端點也限 5 次（前 5 次可能因沒有收件人回 400，但仍計數）


def test_unusable_hmac_key_is_regenerated_not_a_500(client, make_user, fake_smtp):
    """金鑰列被改成不能用的值（例如從備份匯出的「[已遮蔽]」還原）⇒ 重生金鑰，精靈照常運作（舊證明作廢）。"""
    import importlib
    S = importlib.import_module("routers.system")
    h = _h(client, make_user, "atk_r2_k1")
    for bad in ("[已遮蔽]", "zz" * 32, "ab", 123):
        S._set_setting(S._WIZARD_HMAC_KEY, bad)
        assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code == 200, bad
        assert len(S._get_setting(S._WIZARD_HMAC_KEY, "")) == 64
        assert client.post("/api/settings/email-notify/wizard/activate", json=GOOD, headers=h).status_code == 200
        S._set_setting("email_notify", {**S._EMAIL_DEFAULTS})
