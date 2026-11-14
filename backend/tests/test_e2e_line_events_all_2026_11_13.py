"""瀏覽器端對端：通知設定頁「LINE 通知」卡片改版（2026-11-13）。

驗綁定狀況（名單、提醒按鈕、解除綁定兩段確認）、手機寬度不橫向捲動。事件矩陣已內嵌於本卡（2026-11-14 T86），其行為由 test_e2e_line_events_matrix_* 與 test_e2e_line_matrix_inline_t86 驗證。
對外呼叫一律換掉 `line_notify._http`，不連 LINE；Email 換成記錄器。
"""
import pytest

pytest.importorskip("playwright.sync_api")

UID = "U" + "d" * 32


@pytest.fixture()
def fake(monkeypatch):
    from helpers import line_notify, line_quota, email_notify
    sent = []

    def _http(method, path, token, payload=None):
        if path.endswith("/quota/consumption"):
            return 200, {"totalUsage": 10}
        if path.endswith("/quota"):
            return 200, {"type": "limited", "value": 200}
        return 200, {}

    class _H:
        def wait(self, *a, **k):
            return "sent"
    monkeypatch.setattr(line_notify, "_http", _http)
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (True, "測試允許"))
    monkeypatch.setattr(email_notify, "_async_send", lambda to, subject, html: (sent.append((list(to), subject, html)), _H())[1])
    line_quota._mem.update(checked_at=None, failed_at=None, error="", fp=None)
    return sent


def _configure():
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": "tok-e2e-all-0123456789", "public_base_url": "https://line.example.com",
                                 "login_channel_id": "1234567890", "login_channel_secret": "0123456789abcdef0123456789abcdef"})


def _open(live_server, make_user, new_page, login_as, name, width=1440):
    u = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": width, "height": 1800})
    login_as(page, u)
    page.goto(f"{live_server}/pages/notification-settings.html")
    page.locator("#line-panel").wait_for(state="visible", timeout=20000)
    page.locator("[data-testid=le-matrix] " + ("[data-testid='mx-row-approval_request']" if width > 900 else ".mx-card-row")).first.wait_for(state="attached", timeout=20000)
    return page


@pytest.mark.e2e
def test_binding_status_list_remind_button_and_unlink(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    from db import get_db
    make_user(username="e2e_bound", role="sales")
    make_user(username="e2e_free", role="sales")
    c = get_db()
    c.execute("UPDATE users SET email='free@example.com' WHERE username='e2e_free'")
    c.commit()
    c.close()
    L.link_user("e2e_bound", UID)
    page = _open(live_server, make_user, new_page, login_as, "e2e_ev3")
    summary = page.locator("[data-testid=line-bind-summary]")
    page.wait_for_function("() => !document.querySelector('[data-testid=line-bind-summary]').innerText.includes('讀取中')", timeout=10000)
    assert summary.inner_text().startswith("已綁定 1／在職 ")
    page.locator("[data-testid=line-bind-toggle]").click()
    assert "已綁定" in page.locator("[data-testid=line-bind-row-e2e_bound]").inner_text()
    assert "尚未綁定" in page.locator("[data-testid=line-bind-row-e2e_free]").inner_text()
    # 提醒：站內通知＋Email（附「我的帳號」通知分頁連結）
    page.locator("[data-testid=line-bind-remind]").click()
    page.locator("[data-testid=line-msg]").filter(has_text="已提醒").wait_for(state="visible", timeout=10000)
    mails = [m for m in fake if "free@example.com" in m[0]]
    assert mails and "my-account.html?tab=notify" in mails[0][2]
    c = get_db()
    try:
        assert c.execute("SELECT COUNT(*) n FROM notifications WHERE username='e2e_free' AND type='line_binding_reminder'").fetchone()["n"] == 1
        assert c.execute("SELECT COUNT(*) n FROM notifications WHERE username='e2e_bound' AND type='line_binding_reminder'").fetchone()["n"] == 0, "已綁定的人不提醒"
    finally:
        c.close()
    assert page.locator("[data-testid=line-bind-row-e2e_free]").inner_text().strip() != ""
    # 再按一次：24 小時內不重複
    n_before = len(fake)
    page.locator("[data-testid=line-bind-remind]").click()
    page.locator("[data-testid=line-msg]").filter(has_text="略過").wait_for(state="visible", timeout=10000)
    assert len(fake) == n_before
    # 解除綁定：兩段確認（先等綁定名單的重新載入結束：它會重建列、把「確認中」狀態清掉）
    page.wait_for_load_state("networkidle")
    row = page.locator("[data-testid=line-bind-row-e2e_bound]")
    row.get_by_role("button", name="解除綁定").click()
    row.get_by_role("button", name="取消").click()
    assert L.is_linked("e2e_bound")
    row.get_by_role("button", name="解除綁定").click()
    row.get_by_role("button", name="確定", exact=True).click()
    page.wait_for_function("() => document.querySelector('[data-testid=line-bind-row-e2e_bound]').innerText.includes('尚未綁定')", timeout=10000)
    assert not L.is_linked("e2e_bound")


@pytest.mark.e2e
def test_remind_button_disabled_when_login_not_configured(live_server, make_user, new_page, login_as, fake):
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": "tok-e2e-all-0123456789"})
    make_user(username="e2e_free2", role="sales")
    page = _open(live_server, make_user, new_page, login_as, "e2e_ev4")
    page.wait_for_function("() => !document.querySelector('[data-testid=line-bind-summary]').innerText.includes('讀取中')", timeout=10000)
    assert page.locator("[data-testid=line-bind-remind]").is_disabled()
    assert page.locator("[data-testid=line-bind-unavailable]").is_visible()


@pytest.mark.e2e
def test_card_has_no_horizontal_scroll_on_phone_width(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open(live_server, make_user, new_page, login_as, "e2e_ev5", width=390)
    page.locator("[data-testid=line-bind-toggle]").click()
    assert page.locator("[data-testid=le-matrix] .mx-card-row").first.is_visible(), "手機寬度矩陣改為卡片列"
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "手機寬度頁面不可橫向捲動（超出 %s px）" % over
