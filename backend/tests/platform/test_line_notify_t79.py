# -*- coding: utf-8 -*-
"""LINE 發送管道（T79 候選票，階段 1：封裝＋token 設定）。

L1 `helpers.line_notify`：push／multicast 分流、錯誤分類（sent／transient／permanent／skipped）、開發機硬擋、
token 遮罩與不外洩（GET 遮罩、PUT 遮罩值保留、每日 JSON 匯出挖掉、不進 log）、設定端點只限最高管理者。
對外呼叫一律換掉 `line_notify._http`，不連外（conftest NETGUARD 另擋 urllib）。
"""
import logging

import pytest

TOKEN = "tok-SECRET-0123456789"


class _FakeLine:
    def __init__(self, status=200, body=None):
        self.status, self.body, self.calls = status, body or {}, []

    def __call__(self, method, path, token, payload=None):
        self.calls.append((method, path, token, payload))
        if isinstance(self.status, dict):
            return self.status.get(path, 200), self.body
        return self.status, self.body


@pytest.fixture
def ln(client, monkeypatch):      # 要 client：建好測試用 DB（system_settings 表）
    from helpers import line_notify
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": TOKEN})
    fake = _FakeLine()
    monkeypatch.setattr(line_notify, "_http", fake)
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (True, "測試允許"))
    line_notify.fake = fake
    return line_notify


def _hdr(client, make_user, name, role):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


# ── build_text ────────────────────────────────────────────────────────────

def test_build_text_layout_and_sanitizing():
    from helpers import line_notify as L
    t = L.build_text("報價單審核中被編輯", [("單號", "MQ-1"), ("客戶", "甲\n乙")], reason="有人改了", link="https://x/y")
    assert t.splitlines() == ["【MOTRIX】報價單審核中被編輯", "有人改了", "單號：MQ-1", "客戶：甲 乙", "https://x/y"]
    assert len(L.build_text("t", [("k", "v" * 5000)])) <= L.MAX_TEXT


# ── push：分流與分類 ──────────────────────────────────────────────────────

def test_single_recipient_uses_push_many_use_multicast(ln):
    assert ln.push(["U1"], "hi") == ln.SEND_SENT
    assert ln.fake.calls[-1][:2] == ("POST", "/v2/bot/message/push")
    assert ln.fake.calls[-1][3] == {"to": "U1", "messages": [{"type": "text", "text": "hi"}]}
    assert ln.push(["U1", "U2", "U1"], "hi") == ln.SEND_SENT          # 重複的 userId 只算一次
    assert ln.fake.calls[-1][1] == "/v2/bot/message/multicast"
    assert ln.fake.calls[-1][3]["to"] == ["U1", "U2"]
    assert ln.fake.calls[-1][2] == TOKEN


def test_multicast_batches_of_500(ln):
    ids = ["U%d" % i for i in range(1201)]
    assert ln.push(ids, "x") == ln.SEND_SENT
    assert [len(c[3]["to"]) for c in ln.fake.calls] == [500, 500, 201]


@pytest.mark.parametrize("status,expect", [(200, "sent"), (429, "transient_fail"), (500, "transient_fail"),
                                           (400, "permanent_fail"), (401, "skipped"), (403, "skipped")])
def test_status_classification(ln, status, expect):
    ln.fake.status = status
    assert ln.push(["U1"], "hi") == expect


def test_connection_error_is_transient_and_never_raises(ln, monkeypatch):
    def boom(*a, **k):
        raise OSError("dns")
    monkeypatch.setattr(ln, "_http", boom)
    assert ln.push(["U1"], "hi") == ln.SEND_TRANSIENT_FAIL


def test_no_recipients_is_permanent_and_makes_no_call(ln):
    assert ln.push([], "hi") == ln.SEND_PERMANENT_FAIL
    assert ln.push([None, "", "  "], "hi") == ln.SEND_PERMANENT_FAIL
    assert ln.fake.calls == []


def test_disabled_or_no_token_is_skipped_machine_level(ln):
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": False, "channel_access_token": TOKEN})
    assert ln.push(["U1"], "hi") == ln.SEND_SKIPPED
    _set_setting("line_notify", {"enabled": True, "channel_access_token": ""})
    assert ln.push(["U1"], "hi") == ln.SEND_SKIPPED
    assert ln.fake.calls == []


def test_dev_machine_marker_blocks_line_too(ln, monkeypatch):
    """開發機標記（.no_email_send／MOTRIX_EMAIL_SEND=off）同時擋 LINE：不呼叫 LINE。"""
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (False, "測試：開發機"))
    assert ln.push(["U1"], "hi") == ln.SEND_SKIPPED
    assert ln.fake.calls == []


def test_token_never_logged(ln, caplog):
    ln.fake.status = 400
    with caplog.at_level(logging.DEBUG):
        ln.push(["U1"], "hi")
        ln.verify_token()
    assert TOKEN not in caplog.text


# ── verify_token／quota ───────────────────────────────────────────────────

def test_verify_token_ok_and_failures(ln):
    ln.fake.body = {"displayName": "MOTRIX 通知", "basicId": "@abc"}
    assert ln.verify_token() == {"ok": True, "name": "MOTRIX 通知", "basicId": "@abc"}
    assert ln.fake.calls[-1][:2] == ("GET", "/v2/bot/info")
    ln.fake.status = 401
    r = ln.verify_token()
    assert r["ok"] is False and "401" in r["error"]
    ln.fake.status = 200                                          # token 給空字串 ⇒ 退回已存設定
    assert ln.verify_token("")["ok"] is True
    assert ln.fake.calls[-1][2] == TOKEN
    assert ln.verify_token("other-tok")["ok"] is True and ln.fake.calls[-1][2] == "other-tok"


def test_quota_limited_and_unlimited(ln):
    ln.fake.status = 200
    ln.fake.body = {"type": "limited", "value": 200, "totalUsage": 37}
    assert ln.quota() == {"ok": True, "type": "limited", "limit": 200, "used": 37}
    ln.fake.body = {"type": "none", "totalUsage": 5}
    assert ln.quota()["limit"] is None


# ── 設定端點 ──────────────────────────────────────────────────────────────

def test_settings_get_masks_put_keeps_and_replaces(client, make_user, ln):
    sa = _hdr(client, make_user, "ln_sa", "superadmin")
    g = client.get("/api/settings/line-notify", headers=sa).json()
    assert g == {"enabled": True, "channel_access_token": "••••••••"}
    assert TOKEN not in client.get("/api/settings/line-notify", headers=sa).text
    # 遮罩值／空值 ＝ 保留原 token
    assert client.put("/api/settings/line-notify", headers=sa, json={"enabled": False, "channel_access_token": "••••••••"}).status_code == 200
    from helpers.settings import _get_setting
    assert _get_setting("line_notify") == {"enabled": False, "channel_access_token": TOKEN}
    assert client.put("/api/settings/line-notify", headers=sa, json={"enabled": True}).status_code == 200
    assert _get_setting("line_notify")["channel_access_token"] == TOKEN
    # 真的新值 ＝ 取代
    assert client.put("/api/settings/line-notify", headers=sa, json={"channel_access_token": "  new-tok  "}).status_code == 200
    assert _get_setting("line_notify")["channel_access_token"] == "new-tok"
    # 未知欄位不入庫
    client.put("/api/settings/line-notify", headers=sa, json={"evil": 1})
    assert "evil" not in _get_setting("line_notify")


def test_cannot_enable_without_token(client, make_user):
    from helpers.settings import _get_setting
    sa = _hdr(client, make_user, "ln_sa3", "superadmin")
    r = client.put("/api/settings/line-notify", headers=sa, json={"enabled": True})
    assert r.status_code == 400 and "token" in r.json()["detail"]
    assert not (_get_setting("line_notify", {}) or {}).get("enabled")        # 沒存進去
    assert client.post("/api/settings/line-notify/verify", headers=sa).status_code == 400   # 沒 token 也不能驗


def test_settings_endpoints_superadmin_only(client, make_user, ln):
    adm = _hdr(client, make_user, "ln_adm", "admin")
    for call in (lambda: client.get("/api/settings/line-notify", headers=adm),
                 lambda: client.put("/api/settings/line-notify", headers=adm, json={"enabled": True}),
                 lambda: client.post("/api/settings/line-notify/verify", headers=adm)):
        assert call().status_code == 403
    assert client.get("/api/settings/line-notify").status_code in (401, 403)


def test_verify_endpoint(client, make_user, ln):
    sa = _hdr(client, make_user, "ln_sa2", "superadmin")
    ln.fake.body = {"displayName": "官方帳號", "basicId": "@x", "type": "none", "totalUsage": 1}
    r = client.post("/api/settings/line-notify/verify", headers=sa)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "官方帳號" and r.json()["quota"]["ok"] is True
    ln.fake.status = 401
    assert client.post("/api/settings/line-notify/verify", headers=sa).status_code == 400


# ── 祕密不進備份 ──────────────────────────────────────────────────────────

def test_daily_export_removes_line_token(client, ln):
    import json
    import db
    from tests.test_system_audit_2026_09_14 import _json_backup_queries
    conn = db.get_db()
    try:
        rows = {r[0]: r[1] for r in conn.execute(_json_backup_queries()["系統設定"]).fetchall()}
    finally:
        conn.close()
    exported = json.loads(rows["line_notify"])
    assert "channel_access_token" not in exported and exported["enabled"] is True
    assert TOKEN not in rows["line_notify"]
