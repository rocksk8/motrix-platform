"""T86 U6：LINE 設定 400 的訊息要說明「哪裡不對、怎麼處理」（白話）。狀態碼、驗證規則不變（既有題照舊）；這裡釘住訊息。"""
import pytest


def _hdr(client, make_user, name):
    u, p = make_user(username=name, role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.mark.parametrize("body,must", [
    ({"enabled": True}, ("token", "Messaging API")),
    ({"include_links": True}, ("對外網址", "關閉")),
    ({"include_links": "false"}, ("開或關",)),
    ({"channel_access_token": "short"}, ("token", "重新複製")),
    ({"channel_access_token": "x" * 30 + " " + "y" * 10}, ("空白或換行",)),
    ({"login_channel_id": "abc"}, ("Channel ID", "Basic settings")),
    ({"login_channel_secret": "zz"}, ("Channel secret", "32")),
    ({"public_base_url": "http://x.example.com"}, ("https://",)),
    ({"quota_thresholds": [0, 200]}, ("1～100", "80,100")),
])
def test_line_settings_400_says_what_and_how(client, make_user, body, must):
    h = _hdr(client, make_user, "lsm_" + str(abs(hash(str(body))))[:6])
    r = client.put("/api/settings/line-notify", headers=h, json=body)
    assert r.status_code == 400, r.text
    d = r.json()["detail"]
    for m in must:
        assert m in d, (m, d)
    assert len(d) >= 20, "訊息太短、沒有說明處理方式：%s" % d


def test_verify_400_messages_are_actionable(client, make_user, monkeypatch):
    from helpers import line_notify as L
    h = _hdr(client, make_user, "lsm_vf")
    d = client.post("/api/settings/line-notify/verify", headers=h)
    assert d.status_code == 400 and "先貼上 token" in d.json()["detail"] and "儲存" in d.json()["detail"]
    assert client.put("/api/settings/line-notify", headers=h, json={"channel_access_token": "T" * 40}).status_code == 200
    for status, key in ((401, "重新發行"), (500, "稍後再試")):
        monkeypatch.setattr(L, "_http", lambda m, p, t, payload=None, s=status: (s, {}))
        d = client.post("/api/settings/line-notify/verify", headers=h)
        assert d.status_code == 400 and key in d.json()["detail"], d.text

    def boom(*a, **k):
        raise OSError("x")
    monkeypatch.setattr(L, "_http", boom)
    d = client.post("/api/settings/line-notify/verify", headers=h)
    assert d.status_code == 400 and "連不到 LINE" in d.json()["detail"] and "防火牆" in d.json()["detail"], d.text
