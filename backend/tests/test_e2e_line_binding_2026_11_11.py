"""瀏覽器端對端：LINE 綁定（T79，2026-11-11）。

- 設定頁「LINE 通知」卡片：LINE Login 的 Channel ID／secret 欄位存檔、secret 重新整理後只剩遮罩；
- 帳號安全頁（change-password.html）：管理員沒設好時**不顯示**綁定卡片；設好後同仁按「綁定 LINE」→ 出現 QR →
  （手機端用 GET /api/line/callback 模擬）→ 畫面自動變成「已綁定」；再按「解除綁定」會真的解除。
對外呼叫一律換掉（`line_login._post_form`、`line_notify._http`），不連 LINE。
"""
import urllib.parse

import pytest

pytest.importorskip("playwright.sync_api")

CID = "1234567890"
SECRET = "0123456789abcdef0123456789abcdef"
UID = "U" + "e" * 32


@pytest.fixture()
def fakes(monkeypatch):
    from helpers import line_login, line_notify
    st = {"nonce": ""}

    def _form(path, fields):
        if path.endswith("/token"):
            return 200, {"id_token": "a.b.c"}
        return 200, {"aud": fields["client_id"], "nonce": st["nonce"], "sub": UID}

    monkeypatch.setattr(line_login, "_post_form", _form)
    monkeypatch.setattr(line_notify, "_http", lambda method, path, token, payload=None: (200, {}))
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (True, "測試允許"))
    line_login.reset_for_tests()
    return st


def _configure(login=True):
    from helpers.settings import _set_setting
    cfg = {"enabled": True, "channel_access_token": "tok-e2e-binding-0123456789", "events": {}}
    if login:
        cfg.update({"public_base_url": "https://line.example.com", "login_channel_id": CID, "login_channel_secret": SECRET})
    _set_setting("line_notify", cfg)


@pytest.mark.e2e
def test_settings_card_saves_login_channel_and_masks_the_secret(live_server, make_user, new_page, login_as, fakes):
    _configure(login=False)
    u = make_user(username="e2e_lb1", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 1600})
    login_as(page, u)
    page.goto(f"{live_server}/pages/notification-settings.html")
    panel = page.locator("#line-panel")
    panel.wait_for(state="visible", timeout=20000)
    page.locator("[data-testid=le-matrix] [data-testid='mx-row-approval_review_edit']").wait_for(state="attached", timeout=20000)
    panel.locator("input[placeholder^='https://']").fill("https://line.example.com")
    panel.locator("input[placeholder^='Channel ID']").fill(CID)
    panel.locator("input[placeholder^='Channel secret']").fill(SECRET)
    panel.get_by_role("button", name="儲存 LINE 設定").click()
    page.locator("[data-testid=line-msg]").filter(has_text="LINE 設定已儲存").wait_for(state="visible", timeout=10000)
    assert page.locator("#line-panel code").inner_text() == "https://line.example.com/api/line/callback"
    page.reload()
    page.locator("#line-panel").wait_for(state="visible", timeout=20000)
    page.wait_for_function("() => document.querySelector(\"#line-panel input[placeholder^='Channel secret']\").value.length > 0", timeout=10000)
    assert page.locator("#line-panel input[placeholder^='Channel ID']").input_value() == CID
    assert page.locator("#line-panel input[placeholder^='Channel secret']").input_value() == "••••••••"
    assert SECRET not in page.content()
    # 秘密欄位填壞格式 ⇒ 前端先檢核並顯示白話原因（T86 U6：不送請求、不存）
    page.locator("#line-panel input[placeholder^='Channel secret']").fill("short")
    page.get_by_role("button", name="儲存 LINE 設定").click()
    page.locator("[data-testid=line-msg]").filter(has_text="Channel secret 必須剛好 32 個英數字").wait_for(state="visible", timeout=10000)


@pytest.mark.e2e
def test_binding_card_is_hidden_until_the_admin_has_configured_login(live_server, make_user, new_page, login_as, fakes):
    _configure(login=False)
    u = make_user(username="e2e_lb2", role="sales")
    page = new_page(viewport={"width": 1280, "height": 1400})
    login_as(page, u)
    page.goto(f"{live_server}/pages/my-account.html?tab=notify")
    page.locator("[data-testid=notify-empty-hint]").wait_for(state="visible", timeout=20000)      # 通知分頁：沒有可自己設定的通知時的說明
    page.wait_for_timeout(1200)                      # 讓卡片的 GET /api/line/binding 回來
    assert page.locator("#line-bind-card").is_visible() is False


@pytest.mark.e2e
def test_user_binds_from_the_account_page_and_the_card_updates_by_itself(live_server, make_user, new_page, login_as, fakes):
    from helpers import line_notify
    _configure(login=True)
    u = make_user(username="e2e_lb3", role="sales")
    page = new_page(viewport={"width": 1280, "height": 1600})
    login_as(page, u)
    page.goto(f"{live_server}/pages/my-account.html?tab=notify")
    card = page.locator("#line-bind-card")
    card.wait_for(state="visible", timeout=20000)
    assert "未綁定" in card.inner_text()
    with page.expect_response("**/api/line/binding/start") as info:
        card.get_by_role("button", name="綁定 LINE").click()
    d = info.value.json()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(d["authorizeUrl"]).query)
    fakes["nonce"] = q["nonce"][0]
    card.locator("[data-testid=line-qr]").wait_for(state="visible", timeout=10000)
    # 手機端：LINE 授權後把瀏覽器導回 callback（沒有任何 session）
    r = page.request.get(f"{live_server}/api/line/callback", params={"code": "c-e2e", "state": q["state"][0]})
    assert r.status == 200 and "綁定完成" in r.text()
    card.locator("text=已綁定").first.wait_for(state="visible", timeout=15000)       # 每 3 秒輪詢
    assert card.locator("[data-testid=line-qr]").is_visible() is False
    assert line_notify.is_linked("e2e_lb3")
    assert card.locator("[data-testid=line-unconfirmed]").is_visible() is False
    # 解除綁定
    card.get_by_role("button", name="解除綁定").click()
    card.locator("text=未綁定").first.wait_for(state="visible", timeout=10000)
    assert not line_notify.is_linked("e2e_lb3")
