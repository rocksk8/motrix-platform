# -*- coding: utf-8 -*-
"""寄信精靈（feat/menu-ux-3 @ 74e8e3442）對抗式測試（hichan-3，2026-11-13）。

已守住（綠燈）：密碼不外洩（回應／稽核／log）、非最高管理者 403、啟用必須有「同一份設定、24 小時內」的測試證明。
已知未修（xfail strict；修好之後 strict 會逼人把 xfail 拿掉）：
  C 測試失敗仍把壞的新帳密寫進原本能用且已啟用的設定
  D 舊的 PUT /api/settings/email-notify 可以不經測試證明直接 enabled=true
  E PUT 缺欄位 ⇒ 全部欄位被重設成預設（含 enabled→False、smtp_user→""）
  F test-me 沒有頻率限制
"""
import json
import smtplib
from datetime import datetime, timedelta

import pytest


def _h(client, make_user, name, role="superadmin", email="me@example.com"):
    su, sp = make_user(username=name, role=role)
    from db import get_db
    c = get_db()
    c.execute("UPDATE users SET email=? WHERE username=?", (email, name))
    c.commit()
    c.close()
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": su, "password": sp}).json()["token"]}


@pytest.fixture()
def sent(monkeypatch):
    from helpers import email_notify as EN
    box = {"calls": [], "raise": None}

    def fake(to, subject, html, ignore_enabled=False):
        box["calls"].append({"to": list(to), "subject": subject})
        if box["raise"]:
            raise box["raise"]
    monkeypatch.setattr(EN, "_send_raising", fake)
    return box


GOOD = {"provider": "gmail", "smtp_user": "co@gmail.com", "smtp_password": "abcd efgh ijkl mnop", "base_url": "https://erp.example.com"}
PW = "abcdefghijklmnop"


def _cfg():
    import importlib
    S = importlib.import_module("routers.system")
    return S._get_setting("email_notify", {}) or {}


def _set(**kw):
    import importlib
    S = importlib.import_module("routers.system")
    S._set_setting("email_notify", {**S._EMAIL_DEFAULTS, **_cfg(), **kw})


def _activate_ready(client, h, sent):
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code == 200
    r = client.post("/api/settings/email-notify/wizard/activate", headers=h)
    assert r.status_code == 200 and _cfg()["enabled"] is True


# ── 綠燈：密碼 ────────────────────────────────────────────────────────
def test_password_never_in_responses_audit_or_logs(client, make_user, sent, caplog):
    h = _h(client, make_user, "atk_e_pw1")
    caplog.set_level("DEBUG")
    ok = client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h)
    sent["raise"] = smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted " + PW.encode())
    bad = client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h)
    act = client.post("/api/settings/email-notify/wizard/activate", headers=h)
    get = client.get("/api/settings/email-notify", headers=h)
    from db import get_db
    c = get_db()
    try:
        rows = [dict(r) for r in c.execute("SELECT * FROM audit_log WHERE action LIKE 'settings.email_notify%'").fetchall()]
    finally:
        c.close()
    blob = json.dumps([ok.text, bad.text, act.text, get.text, rows], ensure_ascii=False)
    assert PW not in blob and "abcd efgh" not in blob
    assert bad.status_code == 502 and "5.7.8" not in bad.text and "535" not in bad.text      # 不回傳原始 SMTP 例外
    assert get.json()["smtp_password"] != PW


def test_classified_error_text_never_echoes_the_server_message(client, make_user, sent):
    h = _h(client, make_user, "atk_e_pw2")
    sent["raise"] = smtplib.SMTPException("secret-internal-detail host=10.0.0.5")
    r = client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h)
    assert r.status_code == 502 and "secret-internal-detail" not in r.text and "10.0.0.5" not in r.text


# ── 綠燈：權限 ────────────────────────────────────────────────────────
def test_every_wizard_endpoint_is_superadmin_only(client, make_user, sent):
    hs = _h(client, make_user, "atk_e_su")
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=hs).status_code == 200
    for role in ("admin", "sales", "finance", "viewer"):
        h = _h(client, make_user, "atk_e_" + role, role=role)
        assert client.get("/api/settings/email-notify/providers", headers=h).status_code == 403
        assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code == 403
        assert client.post("/api/settings/email-notify/wizard/activate", headers=h).status_code == 403
        assert client.put("/api/settings/email-notify", json={"enabled": True}, headers=h).status_code == 403
    assert client.post("/api/settings/email-notify/wizard/activate").status_code in (401, 403)
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD).status_code in (401, 403)


def test_test_mail_goes_only_to_the_callers_own_account_address(client, make_user, sent):
    """收件人不可被呼叫端指定：body.recipient 只在帳號沒有 Email 時才用，而且只存回呼叫者自己的帳號。"""
    h = _h(client, make_user, "atk_e_rcpt", email="mine@example.com")
    r = client.post("/api/settings/email-notify/wizard/test-me",
                    json={**GOOD, "recipient": "victim@evil.example"}, headers=h)
    assert r.status_code == 200 and r.json()["sent_to"] == "mine@example.com"
    assert sent["calls"][-1]["to"] == ["mine@example.com"]


# ── 綠燈：啟用必須有證明 ────────────────────────────────────────────────
def test_activate_without_proof_is_refused(client, make_user, sent):
    h = _h(client, make_user, "atk_e_np")
    assert client.post("/api/settings/email-notify/wizard/activate", headers=h).status_code == 400
    assert _cfg().get("enabled") in (None, False)


def test_activate_refused_after_config_changed_or_proof_stale(client, make_user, sent):
    h = _h(client, make_user, "atk_e_stale")
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code == 200
    # 測試成功之後，帳密被改掉（PUT）⇒ 指紋不符
    assert client.put("/api/settings/email-notify", json={**_cfg(), "smtp_user": "other@gmail.com", "smtp_password": "zzzz"}, headers=h).status_code == 200
    assert client.post("/api/settings/email-notify/wizard/activate", headers=h).status_code == 400
    # 重測成功 ⇒ 可以啟用；證明過期（>24h）⇒ 不行
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code == 200
    import importlib
    S = importlib.import_module("routers.system")
    proof = S._get_setting(S._EMAIL_WIZARD_PROOF, {})
    S._set_setting(S._EMAIL_WIZARD_PROOF, {**proof, "at": (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")})
    assert client.post("/api/settings/email-notify/wizard/activate", headers=h).status_code == 400
    S._set_setting(S._EMAIL_WIZARD_PROOF, {**proof, "at": "not-a-date"})
    assert client.post("/api/settings/email-notify/wizard/activate", headers=h).status_code == 400


def test_failed_test_does_not_create_a_proof(client, make_user, sent):
    h = _h(client, make_user, "atk_e_fp")
    sent["raise"] = smtplib.SMTPAuthenticationError(535, b"x")
    assert client.post("/api/settings/email-notify/wizard/test-me", json=GOOD, headers=h).status_code == 502
    assert client.post("/api/settings/email-notify/wizard/activate", headers=h).status_code == 400
    sent["raise"] = None


# ── 已知未修 ─────────────────────────────────────────────────────────
@pytest.mark.xfail(strict=True, reason="C（Medium）：test-me 先把未驗證的新帳密存進去才測；測試失敗不還原，原本能用且已啟用的設定被打壞")
def test_atk_failed_test_must_not_clobber_a_working_enabled_config(client, make_user, sent):
    h = _h(client, make_user, "atk_e_c")
    _activate_ready(client, h, sent)
    before = dict(_cfg())
    sent["raise"] = smtplib.SMTPAuthenticationError(535, b"x")
    typo = {**GOOD, "smtp_user": "typo@gmail.com", "smtp_password": "wrong wrong wrong wrong"}
    assert client.post("/api/settings/email-notify/wizard/test-me", json=typo, headers=h).status_code == 502
    after = _cfg()
    assert after["smtp_user"] == before["smtp_user"] and after["smtp_password"] == before["smtp_password"], \
        "測試失敗後，正在用的寄信帳密被換成打錯的那份：" + after["smtp_user"]


@pytest.mark.xfail(strict=True, reason="D（Medium/Low）：舊 PUT 可直接 enabled=true，不需要測試證明；『我收到了』只是畫面上的儀式")
def test_atk_put_cannot_flip_enabled_on_without_a_fresh_proof(client, make_user, sent):
    h = _h(client, make_user, "atk_e_d")
    r = client.put("/api/settings/email-notify", json={**GOOD, "smtp_password": "x", "smtp_host": "smtp.gmail.com", "smtp_port": 587, "enabled": True}, headers=h)
    assert r.status_code in (400, 409, 422) or _cfg().get("enabled") is not True, "沒寄過任何測試信，PUT 就把 Email 通知啟用了"


@pytest.mark.xfail(strict=True, reason="E（Low）：PUT 缺欄位 ⇒ 每個沒帶的欄位都被重設成預設（enabled→False、smtp_user→\"\"）；精靈端點已避開，但舊 PUT 沒修")
def test_atk_partial_put_must_not_reset_omitted_fields(client, make_user, sent):
    h = _h(client, make_user, "atk_e_e")
    _activate_ready(client, h, sent)
    r = client.put("/api/settings/email-notify", json={"from_name": "新名稱"}, headers=h)
    assert r.status_code == 200
    c = _cfg()
    assert c["enabled"] is True and c["smtp_user"] == "co@gmail.com" and c["base_url"] == "https://erp.example.com", \
        {k: c.get(k) for k in ("enabled", "smtp_user", "base_url")}


@pytest.mark.xfail(strict=True, reason="F（Low）：test-me 沒有頻率限制；可無限次對任意主機／埠做真實 SMTP 登入嘗試，錯誤分類（連不上／認證失敗）等於內網探測")
def test_atk_test_me_has_a_rate_limit(client, make_user, sent):
    h = _h(client, make_user, "atk_e_f")
    codes = [client.post("/api/settings/email-notify/wizard/test-me", json={**GOOD, "provider": "other", "smtp_host": "10.0.0.%d" % (i % 250 + 1), "smtp_port": 25}, headers=h).status_code
             for i in range(40)]
    assert 429 in codes, "40 次連續 test-me 全部放行"
