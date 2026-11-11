# -*- coding: utf-8 -*-
"""T79 LINE 通知 K 審修正的測試（hichan-13 的審查）：S2 token 格式與日誌、L1 寫入鎖、L3 網址、L4 壞資料。
對外呼叫一律換掉 `line_notify._http`，不連 LINE。"""
import logging

import pytest

TOKEN = "tok-SECRET-0123456789"
UID = "U" + "a" * 32


class _FakeLine:
    def __init__(self):
        self.calls, self.status, self.body = [], 200, {}

    def __call__(self, method, path, token, payload=None):
        self.calls.append((method, path, token, payload))
        return self.status, self.body


@pytest.fixture
def ln(client, monkeypatch):
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


def _put(client, sa, **body):
    return client.put("/api/settings/line-notify", headers=sa, json=body)


BAD_TOKENS = ["abc-SECRETPART1\nSECRETPART2-0123456789", "中文token" + "x" * 30, "x" * 600, "short", "has space in it 0123456789",
              "tok\r\nX-Evil: 1-0123456789"]


@pytest.mark.parametrize("bad", BAD_TOKENS)
def test_put_rejects_malformed_token_and_keeps_the_old_one(client, make_user, ln, bad):
    from helpers.settings import _get_setting
    sa = _hdr(client, make_user, "ln_sa9", "superadmin")
    r = _put(client, sa, channel_access_token=bad)
    assert r.status_code == 400 and "SECRETPART" not in r.text
    assert _get_setting("line_notify")["channel_access_token"] == TOKEN


@pytest.mark.parametrize("bad", BAD_TOKENS)
def test_hand_edited_malformed_token_is_never_sent_nor_logged(ln, caplog, bad):
    """資料庫被手改成壞 token：不呼叫 LINE、不把 token 寫進 log、對外錯誤訊息不含 token。"""
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": bad})
    with caplog.at_level(logging.DEBUG):
        assert ln.push([UID], "hi") == ln.SEND_SKIPPED
        v = ln.verify_token()
        q = ln.quota()
    assert ln.fake.calls == [] and v["ok"] is False and q["ok"] is False
    for frag in ("SECRETPART", "X-Evil"):
        assert frag not in caplog.text and frag not in str(v) and frag not in str(q)


def test_exception_path_logs_only_the_type_not_the_message(ln, caplog, monkeypatch):
    """連線層例外的訊息可能帶整串 token（例如 http.client 的 Invalid header value）⇒ log 只記型別。"""
    def boom(*a, **k):
        raise ValueError("Invalid header value b'Bearer %s'" % TOKEN)
    monkeypatch.setattr(ln, "_http", boom)
    with caplog.at_level(logging.DEBUG):
        assert ln.push([UID], "hi") == ln.SEND_TRANSIENT_FAIL
        assert ln.verify_token()["ok"] is False
        assert ln.quota()["ok"] is False
        ln.link_user("amy", UID)
        ln.set_event("approval_review_edit", True)
        th = ln.notify_users("approval_review_edit", ["amy"], "t")
        th.join(5)
    assert TOKEN not in caplog.text and "ValueError" in caplog.text


def test_settings_lock_serializes_put_and_set_event(client, make_user, ln):
    """PUT 主設定與 set_event 共用同一把鎖：鎖被占住時兩邊都要等（否則 PUT 會把剛勾的事件開關用舊值蓋回去）。"""
    import threading
    import time
    sa = _hdr(client, make_user, "ln_sa10", "superadmin")
    done = {}

    def _event():
        ln.set_event("warranty_expiry", True)
        done["event"] = True

    def _put_it():
        done["put"] = _put(client, sa, enabled=True).status_code

    with ln.settings_lock():
        ts = [threading.Thread(target=_event), threading.Thread(target=_put_it)]
        for t in ts:
            t.start()
        time.sleep(0.4)
        assert done == {}, "鎖還被占著，兩邊都不該完成"
    for t in ts:
        t.join(10)
    assert done == {"event": True, "put": 200}
    assert ln.event_enabled("warranty_expiry") is True and ln._cfg()["enabled"] is True


@pytest.mark.parametrize("bad", ["https://a..b", "https://-a.com", "https://a-.com", "https://a.com:0", "https://a.com:65536",
                                 "https://a.com:99999", "https://.a.com", "https://a.com."])
def test_public_base_url_rejects_bad_host_and_port(bad):
    from helpers import line_notify as L
    with pytest.raises(ValueError):
        L.normalize_public_base(bad)


def test_public_base_url_accepts_normal_forms():
    from helpers import line_notify as L
    assert L.normalize_public_base("https://line.example.com/") == "https://line.example.com"
    assert L.normalize_public_base("https://a-b.example.co:8443") == "https://a-b.example.co:8443"
    assert L.normalize_public_base("https://a.com:65535") == "https://a.com:65535"
    assert L.normalize_public_base("") == "" and L.normalize_public_base(None) == ""


@pytest.mark.parametrize("junk", ["oops", ["x"], 5, {"events": "oops"}, {"events": ["x"]}, {"events": None}])
def test_hand_edited_garbage_settings_never_break_the_page_or_the_sender(client, make_user, ln, junk):
    """設定值被手改壞（不是物件／events 不是物件）：GET 仍回 200（設定頁不死）、事件全關、不丟例外。"""
    from helpers.settings import _set_setting
    sa = _hdr(client, make_user, "ln_sa11", "superadmin")
    _set_setting("line_notify", junk)
    g = client.get("/api/settings/line-notify", headers=sa)
    assert g.status_code == 200, g.text
    assert all(e["enabled"] is False for e in g.json()["events"])
    assert ln.enabled() is False and ln.event_enabled("approval_review_edit") is False
    assert ln.push([UID], "hi") == ln.SEND_SKIPPED
    assert _put(client, sa, enabled=False).status_code == 200            # 也能用 PUT 修回來
