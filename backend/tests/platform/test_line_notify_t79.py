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
    assert t.splitlines() == ["【MOTRIX】報價單審核中被編輯", "有人改了", "單號：MQ-1", "客戶：甲 乙"]     # 連結預設不帶（見下方兩個開關的測試）
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
    assert ln.verify_token("other-token-0123456789")["ok"] is True and ln.fake.calls[-1][2] == "other-token-0123456789"


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
    evs = {e["key"]: e for e in g.pop("events")}                      # 2026-11-13：接線單位＝信件登記表；預設全關
    assert evs["approval_review_edit"]["name"] == "報價單審核中被簽核人編輯" and evs["warranty_expiry"]["name"] == "設備保固即將到期"
    assert evs["auth_lockout"]["name"] == "登入失敗鎖定告警"
    assert not any(e["enabled"] for e in evs.values()) and all(e["roles"] is None for e in evs.values())
    assert not any(k.startswith(("bonus_", "payslip_")) for k in evs) and "line_quota_warning" not in evs
    assert g.pop("event_groups")[0] == "報價單與審核"                    # 設定頁依模組分組（簽核優先）
    assert g.pop("role_choices") == ["superadmin", "admin", "sales", "engineer", "viewer", "finance"]         # 收件人角色（2026-11-12）
    assert g == {"enabled": True, "channel_access_token": "••••••••", "public_base_url": "", "include_links": False, "callback_url": "",
                 "login_channel_id": "", "login_channel_secret": "", "quota_thresholds": [80, 100]}
    assert TOKEN not in client.get("/api/settings/line-notify", headers=sa).text
    # 遮罩值／空值 ＝ 保留原 token
    assert client.put("/api/settings/line-notify", headers=sa, json={"enabled": False, "channel_access_token": "••••••••"}).status_code == 200
    from helpers.settings import _get_setting
    assert _get_setting("line_notify") == {"enabled": False, "channel_access_token": TOKEN, "public_base_url": "", "include_links": False,
                                                "login_channel_id": "", "login_channel_secret": "", "quota_thresholds": [80, 100]}
    assert client.put("/api/settings/line-notify", headers=sa, json={"enabled": True}).status_code == 200
    assert _get_setting("line_notify")["channel_access_token"] == TOKEN
    # 真的新值 ＝ 取代
    assert client.put("/api/settings/line-notify", headers=sa, json={"channel_access_token": "  new-token-0123456789abcdef  "}).status_code == 200
    assert _get_setting("line_notify")["channel_access_token"] == "new-token-0123456789abcdef"
    # 未知欄位不入庫
    client.put("/api/settings/line-notify", headers=sa, json={"evil": 1})
    assert "evil" not in _get_setting("line_notify")


# ── 兩個獨立開關：對外網址（callback）≠ 訊息帶連結（PM 裁示）─────────────────

LINK = "https://172.16.10.177:666/pages/quotation-form.html?no=MQ-202611-001"


def _put(client, sa, **body):
    return client.put("/api/settings/line-notify", headers=sa, json=body)


def test_public_base_alone_does_not_turn_on_links(client, make_user, ln):
    """A 案上線的狀態：有對外網址（callback 要用）、include_links 關 ⇒ 訊息裡**沒有任何連結**，callback 網址有值。"""
    sa = _hdr(client, make_user, "ln_sa4", "superadmin")
    assert _put(client, sa, public_base_url="https://line.example.com").status_code == 200
    g = client.get("/api/settings/line-notify", headers=sa).json()
    assert g["callback_url"] == "https://line.example.com/api/line/callback" and g["include_links"] is False
    assert ln.public_base() == "https://line.example.com" and ln.links_enabled() is False
    assert ln.safe_link(LINK) == ""
    assert LINK not in ln.build_text("t", [("k", "v")], link=LINK) and "https://" not in ln.build_text("t", [("k", "v")], link=LINK)


def test_links_need_both_switches_and_only_whitelisted_pages(client, make_user, ln):
    sa = _hdr(client, make_user, "ln_sa5", "superadmin")
    # 只開連結、沒有對外網址 ⇒ 拒絕
    assert _put(client, sa, include_links=True).status_code == 400
    assert _put(client, sa, public_base_url="https://line.example.com/", include_links=True).status_code == 200
    assert ln.links_enabled() is True
    # 內網網址被換成對外網址，path＋query 保留
    assert ln.safe_link(LINK) == "https://line.example.com/pages/quotation-form.html?no=MQ-202611-001"
    assert ln.safe_link("/pages/approval-queue.html") == "https://line.example.com/pages/approval-queue.html"
    assert "https://line.example.com/pages/quotation-form.html" in ln.build_text("t", [], link=LINK)
    assert "172.16.10.177" not in ln.build_text("t", [], link=LINK)
    # 白名單外／非 /pages／其他協定 ⇒ 不帶（不是改寫成別的網址）
    for bad in ("https://172.16.10.177:666/pages/payslips.html?q=PS-1", "https://x/pages/bonus.html", "https://x/api/quotations",
                "https://x/pages/../api/x", "javascript:alert(1)", "ftp://x/pages/cashier.html", "", None):
        assert ln.safe_link(bad) == "", bad
    # 關掉連結 ⇒ 立刻不帶，對外網址不受影響
    assert _put(client, sa, include_links=False).status_code == 200
    assert ln.safe_link(LINK) == "" and ln.public_base() == "https://line.example.com"
    # 清空對外網址時若連結還開著 ⇒ 拒絕（不留「連結開、網址空」的狀態）
    assert _put(client, sa, include_links=True).status_code == 200
    assert _put(client, sa, public_base_url="").status_code == 400


@pytest.mark.parametrize("bad", ["http://line.example.com", "https://line.example.com/path", "https://u:p@line.example.com",
                                 "https://line.example.com?x=1", "line.example.com", "javascript:alert(1)", "https://a b.com",
                                 "https://line.example.com:99999x"])
def test_public_base_url_validation(client, make_user, ln, bad):
    sa = _hdr(client, make_user, "ln_sa6", "superadmin")
    assert _put(client, sa, public_base_url=bad).status_code == 400
    assert ln.public_base() == ""


def test_include_links_must_be_boolean(client, make_user, ln):
    sa = _hdr(client, make_user, "ln_sa7", "superadmin")
    assert _put(client, sa, public_base_url="https://line.example.com").status_code == 200
    for v in ("false", "true", 1, "yes"):
        assert _put(client, sa, include_links=v).status_code == 400, v      # 不把字串 "false" 當成 true
    assert ln.links_enabled() is False


def test_hand_edited_garbage_settings_fail_closed(ln):
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": TOKEN, "public_base_url": "http://bad/x", "include_links": True})
    assert ln.public_base() == "" and ln.links_enabled() is False and ln.callback_url() == "" and ln.safe_link(LINK) == ""
    _set_setting("line_notify", {"enabled": True, "channel_access_token": TOKEN, "public_base_url": "https://ok.example.com", "include_links": "true"})
    assert ln.links_enabled() is False                                    # 非布林 true ⇒ 不當成開


# ── 事件開關與綁定 ────────────────────────────────────────────────────────

def test_event_switch_endpoint_only_wired_types_and_strict_bool(client, make_user, ln):
    sa = _hdr(client, make_user, "ln_sa8", "superadmin")
    adm = _hdr(client, make_user, "ln_adm2", "admin")
    url = "/api/settings/line-notify/events/%s"
    assert client.put(url % "approval_review_edit", headers=adm, json={"enabled": True}).status_code == 403
    assert ln.event_enabled("approval_review_edit") is False                    # 預設關
    assert client.put(url % "approval_review_edit", headers=sa, json={"enabled": True}).status_code == 200
    assert ln.event_enabled("approval_review_edit") is True and ln.event_enabled("warranty_expiry") is False
    for bad in ("true", 1, None):
        assert client.put(url % "warranty_expiry", headers=sa, json={"enabled": bad}).status_code == 400
    assert client.put(url % "payslip_payable", headers=sa, json={"enabled": True}).status_code == 404    # 沒接線的類型不開放勾選
    assert client.put(url % "no_such_type", headers=sa, json={"enabled": True}).status_code == 404
    # 其他設定（PUT 主設定）不會洗掉事件開關
    assert _put(client, sa, enabled=True).status_code == 200
    assert ln.event_enabled("approval_review_edit") is True
    assert client.put(url % "approval_review_edit", headers=sa, json={"enabled": False}).status_code == 200
    assert ln.event_enabled("approval_review_edit") is False


def test_event_needs_line_enabled_and_wired(ln):
    from helpers.settings import _set_setting
    ln.set_event("warranty_expiry", True)
    assert ln.event_enabled("warranty_expiry") is True
    _set_setting("line_notify", {**ln._cfg(), "enabled": False})
    assert ln.event_enabled("warranty_expiry") is False
    with pytest.raises(ValueError):
        ln.set_event("bonus_submitted", True)
    for k in ln.WIRED_EVENTS:                                     # 每個已接線的類型都真的登記過（或是 LINE-only／細項），且不是獎金／薪資／勞報單類
        from helpers import mail_types as mt, line_catalog as lc
        assert mt.get(k) is not None or k in lc.LINE_ONLY_EVENTS, k
        assert not k.startswith(("bonus_", "payslip_")) and not (mt.get(k) and mt.get(k).owner == "payroll"), k


def test_link_rules(ln):
    a, b = "U" + "a" * 32, "U" + "b" * 32
    ln.link_user("amy", a)
    assert ln.is_linked("amy") and ln.ids_for(["amy", "nobody", "amy"]) == [a]
    with pytest.raises(ValueError):
        ln.link_user("bob", a)                                    # 同一個 LINE 帳號不能綁給兩個系統帳號（通知會送錯人）
    ln.link_user("amy", b)                                        # 同一系統帳號重綁＝換成新的
    assert ln.ids_for(["amy"]) == [b]
    ln.link_user("bob", a)                                        # 舊的釋放後可以給別人
    for bad in ("", "x", "U123", "u" + "a" * 32, "U" + "g" * 32, None):
        with pytest.raises(ValueError):
            ln.link_user("cy", bad)
    assert ln.unlink_user("amy") is True and ln.unlink_user("amy") is False and ln.ids_for(["amy"]) == []
    from helpers.settings import _set_setting
    _set_setting("line_links", {"amy": "garbage", "bob": {"userId": "nope"}})        # 手改壞的資料 ⇒ 當成沒綁，不丟例外
    assert ln.ids_for(["amy", "bob"]) == [] and not ln.is_linked("amy")


def test_notify_users_noop_cases_never_raise(ln):
    ln.link_user("amy", "U" + "a" * 32)
    assert ln.notify_users("approval_review_edit", ["amy"], "t") is None          # 類型沒勾選
    ln.set_event("approval_review_edit", True)
    assert ln.notify_users("approval_review_edit", ["nobody"], "t") is None        # 沒人綁定
    assert ln.notify_users("approval_review_edit", None, "t") is None
    th = ln.notify_users("approval_review_edit", ["amy"], "標題", [("單號", "MQ-1")])
    th.join(5)
    assert ln.fake.calls[-1][1] == "/v2/bot/message/push" and ln.fake.calls[-1][3]["to"] == "U" + "a" * 32


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
