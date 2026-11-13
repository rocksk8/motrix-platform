# -*- coding: utf-8 -*-
"""寄信帳號精靈（批次 3，2026-11-13）：供應商預設、儲存即驗證、失敗分類、設定單、寄測試信給自己並啟用。

守的不變式：
  ① 測試信成功之前不會啟用；啟用只認「剛測試成功的那一份設定」（改過就要重測）。
  ② 任何回應與稽核都不含密碼。
  ③ 失敗分成白話類別；Microsoft 365 驗證失敗附設定單；畫面不顯示錯誤碼。
  ④ 連接埠 465 走隱含 SSL，其餘 STARTTLS；寄信路徑三處共用同一個連線函式。
"""
import json
import smtplib
import socket

import pytest

from helpers import email_setup as ES


# ── 純函式 ───────────────────────────────────────────────────────────────────
def test_providers_have_prefilled_host_and_port_and_other_is_blank():
    keys = [p["key"] for p in ES.PROVIDERS]
    assert keys == ["gmail", "microsoft365", "yahoo", "zoho", "other"]
    for p in ES.PROVIDERS:
        if p["key"] == "other":
            assert p["host"] == ""
        else:
            assert p["host"] and p["port"] == 587
    assert ES.provider_by_key("gmail")["host"] == "smtp.gmail.com"
    assert ES.provider_by_key("nope") is None


@pytest.mark.parametrize("data,ok", [
    ({"smtp_user": "a@b.com"}, True),
    ({"smtp_user": ""}, True),
    ({"smtp_user": "not-an-email"}, False),
    ({"smtp_user": "a b@c.com"}, False),
    ({"smtp_host": "smtp.gmail.com"}, True),
    ({"smtp_host": "https://smtp.gmail.com"}, False),
    ({"smtp_host": "smtp gmail.com"}, False),
    ({"smtp_port": 587}, True),
    ({"smtp_port": "465"}, True),
    ({"smtp_port": 0}, False),
    ({"smtp_port": 70000}, False),
    ({"smtp_port": "abc"}, False),
    ({"base_url": "https://erp.example.com"}, True),
    ({"base_url": ""}, True),
    ({"base_url": "erp.example.com"}, False),
    ({"from_name": "x" * 81}, False),
])
def test_validate_config(data, ok):
    assert (ES.validate_config(data) is None) is ok


def test_gmail_password_spaces_are_stripped_others_only_trimmed():
    assert ES.normalize_password("gmail", " abcd efgh ijkl mnop ") == "abcdefghijklmnop"
    assert ES.normalize_password("yahoo", "  p w  ") == "p w"


def test_fingerprint_changes_with_any_field_and_hides_password():
    a = ES.config_fingerprint("h", 587, "u@x.com", "pw")
    assert a == ES.config_fingerprint("H", "587", "U@x.com", "pw")           # 大小寫與型別不影響
    assert a != ES.config_fingerprint("h", 587, "u@x.com", "pw2")
    assert a != ES.config_fingerprint("h", 465, "u@x.com", "pw")
    assert "pw" not in a


def test_classify_m365_auth_failure_offers_a_ticket():
    e = smtplib.SMTPAuthenticationError(535, b"5.7.139 Authentication unsuccessful, SmtpClientAuthentication is disabled for the Tenant")
    c = ES.classify_error(e, "smtp.office365.com", "microsoft365")
    assert c["category"] == "auth" and c["ticketKind"] == "m365_auth"
    assert "設定單" in c["hint"]


def test_classify_gmail_needs_app_password_and_no_ticket():
    e = smtplib.SMTPAuthenticationError(534, b"5.7.9 Application-specific password required")
    c = ES.classify_error(e, "smtp.gmail.com", "gmail")
    assert c["category"] == "auth" and not c["ticketKind"] and "應用程式密碼" in c["title"]


def test_classify_plain_auth_failure_is_wrong_password():
    c = ES.classify_error(smtplib.SMTPAuthenticationError(535, b"bad"), "smtp.example.com", "other")
    assert c["category"] == "auth" and "帳號或密碼不對" in c["title"] and not c["ticketKind"]


def test_classify_network_connect_rejected_other():
    assert ES.classify_error(socket.gaierror(-2, "Name or service not known"), "x")["category"] == "network"
    assert ES.classify_error(ConnectionRefusedError(), "x")["category"] == "connect"
    assert ES.classify_error(socket.timeout(), "x")["category"] == "connect"
    assert ES.classify_error(smtplib.SMTPConnectError(421, b"busy"), "x")["category"] == "connect"
    assert ES.classify_error(smtplib.SMTPSenderRefused(550, b"no", "a@b.com"), "x")["category"] == "rejected"
    assert ES.classify_error(ValueError("weird"), "x")["category"] == "other"


def test_classify_never_leaks_raw_error_text():
    c = ES.classify_error(smtplib.SMTPAuthenticationError(535, b"SECRET-RAW-TEXT"), "smtp.example.com", "other")
    assert "SECRET-RAW-TEXT" not in json.dumps(c, ensure_ascii=False)


def test_ticket_has_account_host_port_and_no_password():
    t = ES.build_ticket("m365_auth", user="boss@corp.com", host="smtp.office365.com", port=587, company="某某公司", requester="王大明")
    assert "boss@corp.com" in t["text"] and "smtp.office365.com:587" not in t["text"] and "587" in t["text"]
    assert "Set-CASMailbox" in t["text"] and "某某公司" in t["text"]
    assert "密碼：（不在此單上" in t["text"]
    n = ES.build_ticket("network", user="u@x.com", host="mail.x.com", port=25)
    assert "mail.x.com:25" in n["text"]


# ── 連線函式：465 隱含 SSL、其餘 STARTTLS ──────────────────────────────────────
class _FakeSMTP:
    log = []

    def __init__(self, host, port, timeout=None, context=None):
        self.kind = type(self).__name__
        _FakeSMTP.log.append((self.kind, host, port))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        _FakeSMTP.log.append(("ehlo",))

    def starttls(self):
        _FakeSMTP.log.append(("starttls",))

    def quit(self):
        _FakeSMTP.log.append(("quit",))


class _FakeSMTPSSL(_FakeSMTP):
    pass


def test_smtp_open_uses_ssl_on_465_and_starttls_otherwise(monkeypatch):
    from helpers import email_notify as EN
    monkeypatch.setattr(EN.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(EN.smtplib, "SMTP_SSL", _FakeSMTPSSL)
    _FakeSMTP.log = []
    with EN._smtp_open("h", 587, 5):
        pass
    assert ("_FakeSMTP", "h", 587) in _FakeSMTP.log and ("starttls",) in _FakeSMTP.log
    _FakeSMTP.log = []
    with EN._smtp_open("h", 465, 5):
        pass
    assert ("_FakeSMTPSSL", "h", 465) in _FakeSMTP.log and ("starttls",) not in _FakeSMTP.log


def test_all_three_send_paths_share_the_connection_helper():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "helpers" / "email_notify.py").read_text(encoding="utf-8")
    assert src.count("_smtp_open(host, port,") == 3
    assert "smtplib.SMTP(host, port" not in src


# ── API ──────────────────────────────────────────────────────────────────────
def _h(client, make_user, name, role="superadmin", email=None):
    su, sp = make_user(username=name, role=role)
    if email is not None:
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

    def fake(to, subject, html, ignore_enabled=False, cfg=None):
        box["calls"].append({"to": to, "subject": subject, "ignore_enabled": ignore_enabled})
        if box["raise"]:
            raise box["raise"]
    monkeypatch.setattr(EN, "_send_raising", fake)
    return box


BODY = {"provider": "gmail", "smtp_user": "co@gmail.com", "smtp_password": "abcd efgh ijkl mnop", "base_url": "https://erp.example.com"}


def test_put_validates_and_trims(client, make_user):
    h = _h(client, make_user, "es_su1")
    for bad in ({"smtp_user": "nope"}, {"smtp_port": 99999}, {"base_url": "erp.example.com"}, {"smtp_host": "http://x"}):
        r = client.put("/api/settings/email-notify", json={"enabled": False, **bad}, headers=h)
        assert r.status_code == 422, (bad, r.text)
    r = client.put("/api/settings/email-notify", json={"enabled": False, "smtp_user": "  a@b.com ", "smtp_host": "smtp.b.com", "smtp_port": 587}, headers=h)
    assert r.status_code == 200
    assert client.get("/api/settings/email-notify", headers=h).json()["smtp_user"] == "a@b.com"


def test_providers_endpoint_superadmin_only(client, make_user):
    h = _h(client, make_user, "es_su2")
    assert client.get("/api/settings/email-notify/providers", headers=h).json()["providers"][0]["key"] == "gmail"
    ha = _h(client, make_user, "es_adm", role="admin")
    assert client.get("/api/settings/email-notify/providers", headers=ha).status_code == 403
    assert client.post("/api/settings/email-notify/wizard/test-me", json=BODY, headers=ha).status_code == 403
    assert client.post("/api/settings/email-notify/wizard/activate", json=BODY, headers=ha).status_code == 403


def test_wizard_happy_path_test_then_activate(client, make_user, sent):
    h = _h(client, make_user, "es_su3", email="boss@example.com")
    # 沒測試過就想啟用 ⇒ 擋
    assert client.post("/api/settings/email-notify/wizard/activate", json=BODY, headers=h).status_code == 400
    r = client.post("/api/settings/email-notify/wizard/test-me", json=BODY, headers=h)
    assert r.status_code == 200 and r.json() == {"ok": True, "sent_to": "boss@example.com"}
    assert sent["calls"][0]["to"] == ["boss@example.com"] and sent["calls"][0]["ignore_enabled"] is True
    cfg = client.get("/api/settings/email-notify", headers=h).json()
    assert cfg["enabled"] is False and cfg["smtp_user"] == ""                                   # 測試成功還不會寫進正式設定（要按「我收到了」）
    ra = client.post("/api/settings/email-notify/wizard/activate", json=BODY, headers=h)
    assert ra.status_code == 200 and ra.json()["enabled"] is True
    cfg = client.get("/api/settings/email-notify", headers=h).json()
    assert cfg["enabled"] is True and cfg["smtp_user"] == "co@gmail.com" and cfg["smtp_host"] == "smtp.gmail.com"
    assert cfg["smtp_password"] != "abcdefghijklmnop" and "abcd" not in json.dumps(cfg)        # 回應只有遮罩


def test_activation_requires_the_same_config_that_was_tested(client, make_user, sent):
    h = _h(client, make_user, "es_su4", email="boss@example.com")
    assert client.post("/api/settings/email-notify/wizard/test-me", json=BODY, headers=h).status_code == 200
    # 測試成功後改了帳號 ⇒ 指紋不符 ⇒ 不能啟用
    client.put("/api/settings/email-notify", json={"enabled": False, "smtp_user": "other@gmail.com", "smtp_host": "smtp.gmail.com", "smtp_port": 587}, headers=h)
    r = client.post("/api/settings/email-notify/wizard/activate", json=BODY, headers=h)
    assert r.status_code == 400 and "測試" in r.json()["detail"]


def test_failed_test_never_activates_and_returns_plain_category(client, make_user, sent):
    h = _h(client, make_user, "es_su5", email="boss@example.com")
    sent["raise"] = smtplib.SMTPAuthenticationError(535, b"5.7.139 basic authentication is disabled")
    body = {**BODY, "provider": "microsoft365", "smtp_user": "boss@corp.com"}
    r = client.post("/api/settings/email-notify/wizard/test-me", json=body, headers=h)
    d = r.json()
    assert r.status_code == 502 and d["category"] == "auth"
    assert d["ticket"]["title"] and "Set-CASMailbox" in d["ticket"]["text"] and "abcd" not in d["ticket"]["text"]
    assert "5.7.139" not in json.dumps(d, ensure_ascii=False)           # 不顯示錯誤碼
    assert client.post("/api/settings/email-notify/wizard/activate", json=BODY, headers=h).status_code == 400
    assert client.get("/api/settings/email-notify", headers=h).json()["enabled"] is False


def test_network_failure_has_network_ticket_and_unknown_has_none(client, make_user, sent):
    h = _h(client, make_user, "es_su6", email="boss@example.com")
    sent["raise"] = socket.gaierror(-2, "x")
    d = client.post("/api/settings/email-notify/wizard/test-me", json=BODY, headers=h).json()
    assert d["category"] == "network" and d["ticket"]["title"] == "寄信連線設定單"
    sent["raise"] = ValueError("???")
    d = client.post("/api/settings/email-notify/wizard/test-me", json=BODY, headers=h).json()
    assert d["category"] == "other" and "ticket" not in d and d["traceId"]


def test_user_without_email_is_asked_then_saved(client, make_user, sent):
    h = _h(client, make_user, "es_su7")
    r = client.post("/api/settings/email-notify/wizard/test-me", json=BODY, headers=h)
    assert r.status_code == 400 and r.json()["needEmail"] is True and not sent["calls"]
    r = client.post("/api/settings/email-notify/wizard/test-me", json={**BODY, "recipient": "bad"}, headers=h)
    assert r.status_code == 422
    r = client.post("/api/settings/email-notify/wizard/test-me", json={**BODY, "recipient": "me@example.com"}, headers=h)
    assert r.status_code == 200 and r.json()["sent_to"] == "me@example.com"
    from db import get_db
    c = get_db()
    try:
        assert c.execute("SELECT email FROM users WHERE username='es_su7'").fetchone()[0] == "me@example.com"
    finally:
        c.close()


def test_missing_fields_get_plain_422(client, make_user, sent):
    h = _h(client, make_user, "es_su8", email="boss@example.com")
    for patch, word in (({"smtp_user": ""}, "信箱"), ({"smtp_password": ""}, "密碼"), ({"provider": "other", "smtp_host": ""}, "主機"), ({"provider": "zzz"}, "信箱服務")):
        r = client.post("/api/settings/email-notify/wizard/test-me", json={**BODY, **patch}, headers=h)
        assert r.status_code == 422 and word in r.json()["detail"], (patch, r.text)
    assert not sent["calls"]


def test_masked_password_keeps_the_stored_one(client, make_user, sent):
    h = _h(client, make_user, "es_su9", email="boss@example.com")
    assert client.post("/api/settings/email-notify/wizard/test-me", json=BODY, headers=h).status_code == 200
    assert client.post("/api/settings/email-notify/wizard/activate", json=BODY, headers=h).status_code == 200        # 密碼先存進正式設定
    r = client.post("/api/settings/email-notify/wizard/test-me", json={**BODY, "smtp_password": "••••••••"}, headers=h)
    assert r.status_code == 200                                                                          # 遮罩 ⇒ 沿用已存的密碼
    from helpers.settings import _get_setting
    assert _get_setting("email_notify", {})["smtp_password"] == "abcdefghijklmnop"
    h2 = _h(client, make_user, "es_su9b", email="boss2@example.com")
    from db import get_db
    c = get_db(); c.execute("DELETE FROM system_settings WHERE key='email_notify'"); c.commit(); c.close()
    r = client.post("/api/settings/email-notify/wizard/test-me", json={**BODY, "smtp_password": "••••••••"}, headers=h2)
    assert r.status_code == 422                                                                          # 沒有已存密碼又只給遮罩 ⇒ 要填密碼


def test_audit_has_no_password(client, make_user, sent):
    h = _h(client, make_user, "es_su10", email="boss@example.com")
    client.post("/api/settings/email-notify/wizard/test-me", json=BODY, headers=h)
    client.post("/api/settings/email-notify/wizard/activate", json=BODY, headers=h)
    from db import get_db
    c = get_db()
    try:
        rows = c.execute("SELECT * FROM audit_log WHERE action LIKE 'settings.email_notify.wizard%'").fetchall()
    finally:
        c.close()
    assert len(rows) == 2
    assert "abcd" not in json.dumps([dict(r) for r in rows], ensure_ascii=False)


def test_dev_machine_block_message_is_passed_through(client, make_user, sent):
    h = _h(client, make_user, "es_su11", email="boss@example.com")
    sent["raise"] = RuntimeError("這台機器被設定成「不寄真實信件」")
    r = client.post("/api/settings/email-notify/wizard/test-me", json=BODY, headers=h)
    assert r.status_code == 400 and r.json()["category"] == "blocked" and "不寄真實信件" in r.json()["detail"]
