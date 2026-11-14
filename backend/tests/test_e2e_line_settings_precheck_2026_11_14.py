"""瀏覽器端對端：LINE 設定頁「送出前先檢核＋白話錯誤」（T86 U6）。

正式機 30 天內 `PUT /api/settings/line-notify` 回 400 ×5、`POST …/verify` 回 400 ×2，都是伺服器才擋、使用者看到的是技術性訊息。
這裡驗：輸入不合規則時，畫面在**送出前**就說明「哪裡不對、怎麼處理」，而且**沒有**送出 PUT／verify 請求；
合規的輸入照常存檔。對外呼叫一律換掉 `line_notify._http`，不連 LINE。
"""
import pytest

pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def fake_line(monkeypatch):
    from helpers import line_notify as L

    def _http(method, path, token, payload=None):
        if path == "/v2/bot/info":
            return 200, {"displayName": "MOTRIX 測試官方帳號", "basicId": "@t"}
        return 200, {"type": "limited", "value": 200, "totalUsage": 12}

    monkeypatch.setattr(L, "_http", _http)


def _open(live_server, make_user, new_page, login_as, name):
    u = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 1400})
    login_as(page, u)
    page.goto(f"{live_server}/pages/notification-settings.html")
    page.locator("#line-panel").wait_for(state="visible", timeout=20000)
    page.locator("[data-testid=le-matrix] [data-testid='mx-row-approval_review_edit']").wait_for(state="attached", timeout=20000)
    sent = []
    page.on("request", lambda r: sent.append((r.method, r.url.split("?")[0].split("/api/", 1)[-1])) if "/api/settings/line-notify" in r.url else None)
    return page, sent


def _save(page):
    page.locator("#line-panel").get_by_role("button", name="儲存 LINE 設定").click()


def _says(page, text):
    page.locator("[data-testid=line-msg]").filter(has_text=text).wait_for(state="visible", timeout=10000)
    return page.locator("[data-testid=line-msg]").inner_text()


def _writes(sent):
    return [x for x in sent if x[0] in ("PUT", "POST") and x[1] in ("settings/line-notify", "settings/line-notify/verify")]


# (欄位標記, 填入的值, 訊息要有的字, 要點的開關)
@pytest.mark.e2e
@pytest.mark.parametrize("case", [
    ("token_space", "tok ABCDEFGHIJKLMNOPQRSTUV", "空白或換行"),
    ("token_cjk", "tok-中文ABCDEFGHIJKLMNOPQRSTUV", "不允許的字元"),
    ("token_short", "abc123", "太短"),
    ("url_http", "http://line.example.com", "https://"),
    ("url_noscheme", "line.example.com", "https://"),
    ("url_path", "https://line.example.com/pages/x.html", "路徑"),
    ("login_id", "12ab", "Channel ID"),
    ("login_secret", "xyz", "Channel secret"),
    ("threshold_range", "80,200", "1～100"),
    ("threshold_dup", "80,80", "重複"),
    ("threshold_empty", "", "不能是空的"),
], ids=lambda c: c[0])
def test_bad_input_is_explained_before_sending(live_server, make_user, new_page, login_as, fake_line, case):
    kind, value, expect = case
    page, sent = _open(live_server, make_user, new_page, login_as, "e2e_lp_" + kind[:10])
    panel = page.locator("#line-panel")
    if kind.startswith("token"):
        panel.locator("input[type=password]").first.fill(value)
    elif kind.startswith("url"):
        panel.locator("input[placeholder^='https://網域']").fill(value)
    elif kind == "login_id":
        panel.locator("input[placeholder^='Channel ID']").fill(value)
    elif kind == "login_secret":
        panel.locator("input[placeholder^='Channel secret']").fill(value)
    else:
        panel.locator("#line-quota-th").fill(value)
    _save(page)
    txt = _says(page, expect)
    assert "尚未儲存" in txt
    assert _writes(sent) == [], "不合規則的輸入不該送出請求：%s" % _writes(sent)


@pytest.mark.e2e
def test_enable_without_token_and_links_without_url_are_explained(live_server, make_user, new_page, login_as, fake_line):
    page, sent = _open(live_server, make_user, new_page, login_as, "e2e_lp_en")
    panel = page.locator("#line-panel")
    panel.locator("#chk-line-enabled").check()
    _save(page)
    assert "Channel access token" in _says(page, "必須先填")
    panel.locator("#chk-line-enabled").uncheck()
    panel.locator("#chk-line-links").check()
    _save(page)
    assert "取消勾選" in _says(page, "對外網址")
    assert _writes(sent) == []


@pytest.mark.e2e
def test_verify_without_saved_token_or_with_unsaved_token_is_explained(live_server, make_user, new_page, login_as, fake_line):
    page, sent = _open(live_server, make_user, new_page, login_as, "e2e_lp_vf")
    panel = page.locator("#line-panel")
    panel.get_by_role("button", name="驗證 token").click()
    assert "先在上方貼上 token" in _says(page, "尚未填寫 Channel access token")
    panel.locator("input[type=password]").first.fill("tok-new-ABCDEFGHIJKLMNOPQRSTUV")
    panel.get_by_role("button", name="驗證 token").click()
    _says(page, "尚未儲存")
    assert _writes(sent) == [], "沒存過／剛改還沒存：不送 verify"
    # 合規：存檔成功，再驗證成功
    _save(page)
    _says(page, "LINE 設定已儲存")
    panel.get_by_role("button", name="驗證 token").click()
    _says(page, "MOTRIX 測試官方帳號")
    assert ("POST", "settings/line-notify/verify") in sent
