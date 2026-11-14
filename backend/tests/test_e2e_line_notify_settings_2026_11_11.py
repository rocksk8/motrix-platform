"""瀏覽器端對端：通知設定頁的「LINE 通知」卡片（T79 候選，2026-11-11）。

驗每個按鈕真的動：儲存（token 遮罩、重新整理後仍是遮罩）、驗證 token（LINE 對外呼叫換成假的）、事件開關已移到內嵌的事件矩陣（見 test_e2e_line_events_matrix_*）、
沒填對外網址就開「帶連結」會被擋並顯示原因。對外呼叫一律換掉 `line_notify._http`，不連 LINE。
"""
import pytest

pytest.importorskip("playwright.sync_api")


@pytest.fixture()
def fake_line(monkeypatch):
    from helpers import line_notify as L
    calls = []

    def _http(method, path, token, payload=None):
        calls.append((method, path, token))
        if path == "/v2/bot/info":
            return 200, {"displayName": "MOTRIX 測試官方帳號", "basicId": "@t"}
        return 200, {"type": "limited", "value": 200, "totalUsage": 12}

    monkeypatch.setattr(L, "_http", _http)
    return calls


def _open(live_server, make_user, new_page, login_as, name):
    u = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 1400})
    login_as(page, u)
    page.goto(f"{live_server}/pages/notification-settings.html")
    page.locator("#line-panel").wait_for(state="visible", timeout=20000)
    page.locator("[data-testid=le-matrix] [data-testid='mx-row-approval_review_edit']").wait_for(state="attached", timeout=20000)
    return page


@pytest.mark.e2e
def test_line_card_save_masks_token_and_verify_shows_account_and_quota(live_server, make_user, new_page, login_as, fake_line):
    page = _open(live_server, make_user, new_page, login_as, "e2e_ln1")
    panel = page.locator("#line-panel")
    assert panel.locator("#chk-line-enabled").is_checked() is False        # 預設關
    assert panel.locator("#chk-line-links").is_checked() is False          # 連結預設關
    panel.locator("input[type=password]").first.fill("tok-ui-SECRET-0123456789")
    panel.locator("#chk-line-enabled").check()
    panel.get_by_role("button", name="儲存 LINE 設定").click()
    page.locator("[data-testid=line-msg]").filter(has_text="LINE 設定已儲存").wait_for(state="visible", timeout=10000)
    # 重新整理：token 欄位只剩遮罩，不回傳原文
    page.reload()
    page.locator("#line-panel").wait_for(state="visible", timeout=20000)
    page.wait_for_function("() => document.querySelector('#line-panel input[type=password]').value.length > 0", timeout=10000)
    val = page.locator("#line-panel input[type=password]").first.input_value()
    assert val == "••••••••" and "SECRET" not in page.content()
    assert page.locator("#chk-line-enabled").is_checked()
    # 驗證 token：顯示官方帳號名稱與本月額度
    page.get_by_role("button", name="驗證 token").click()
    page.locator("[data-testid=line-msg]").filter(has_text="MOTRIX 測試官方帳號").wait_for(state="visible", timeout=10000)
    txt = page.locator("[data-testid=line-msg]").inner_text()
    assert "12 / 200" in txt
    assert ("GET", "/v2/bot/info", "tok-ui-SECRET-0123456789") in fake_line


@pytest.mark.e2e
def test_line_card_links_need_a_public_url(live_server, make_user, new_page, login_as, fake_line):
    from helpers import line_notify as L
    page = _open(live_server, make_user, new_page, login_as, "e2e_ln2")
    panel = page.locator("#line-panel")
    panel.locator("input[type=password]").first.fill("tok-ui-2-0123456789abcdef")
    panel.locator("#chk-line-enabled").check()
    panel.get_by_role("button", name="儲存 LINE 設定").click()
    page.locator("[data-testid=line-msg]").filter(has_text="LINE 設定已儲存").wait_for(state="visible", timeout=10000)
    # 沒有對外網址就開「帶連結」⇒ 被擋、畫面顯示原因、設定沒被改
    panel.locator("#chk-line-links").check()
    panel.get_by_role("button", name="儲存 LINE 設定").click()
    page.locator("[data-testid=line-msg]").filter(has_text="對外網址").wait_for(state="visible", timeout=10000)
    assert L.links_enabled() is False
    # 填對外網址（連結維持關）⇒ 顯示 Callback URL，而且訊息仍不帶連結
    panel.locator("#chk-line-links").uncheck()
    panel.locator("input[placeholder^='https://網域']").fill("https://line.example.com")
    panel.get_by_role("button", name="儲存 LINE 設定").click()
    page.locator("[data-testid=line-msg]").filter(has_text="LINE 設定已儲存").wait_for(state="visible", timeout=10000)
    assert "https://line.example.com/api/line/callback" in panel.inner_text()
    assert L.public_base() == "https://line.example.com" and L.links_enabled() is False
