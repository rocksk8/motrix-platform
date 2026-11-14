"""瀏覽器端對端：通知設定頁內嵌 LINE 事件矩陣（T86，2026-11-14）。

舊的「逐項展開＋勾選」清單已移除，改為直接顯示事件×角色矩陣（共用 SettingsMatrix）；
「提醒未綁定的人」按鈕與綁定名單保留；line-events.html 網址仍可使用。
對外呼叫一律換掉 `line_notify._http`，不連 LINE。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect

OLD_TESTID_PREFIXES = ("line-group-", "line-event-", "line-aud-", "line-role-", "line-tag-")


@pytest.fixture()
def fake(monkeypatch):
    from helpers import line_notify, line_quota
    monkeypatch.setattr(line_notify, "_http", lambda method, path, token, payload=None: (200, {"totalUsage": 10} if path.endswith("/quota/consumption") else {"type": "limited", "value": 200}))
    monkeypatch.setattr("helpers.email_notify.email_send_policy", lambda env=None: (True, "測試允許"))
    line_quota._mem.update(checked_at=None, failed_at=None, error="", fp=None)


def _configure():
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": "tok-e2e-t86-0123456789", "public_base_url": "https://line.example.com",
                                 "login_channel_id": "1234567890", "login_channel_secret": "0123456789abcdef0123456789abcdef"})


def _open_settings(live_server, make_user, new_page, login_as, name, width=1440):
    u = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": width, "height": 1800})
    login_as(page, u)
    page.goto(f"{live_server}/pages/notification-settings.html")
    page.locator("#line-panel").wait_for(state="visible", timeout=20000)
    page.locator("[data-testid=le-matrix] " + ("[data-testid='mx-row-approval_request']" if width > 900 else ".mx-card-row")).first.wait_for(state="attached", timeout=20000)
    return page


@pytest.mark.e2e
def test_settings_page_shows_matrix_inline_and_old_list_is_gone(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open_settings(live_server, make_user, new_page, login_as, "e2e_t86a")
    expect(page.locator("[data-testid=le-matrix]")).to_be_visible()
    expect(page.locator("[data-testid=le-matrix] [data-testid='mx-row-approval_request']")).to_be_visible()
    # 批次、篩選與「復原這一批」來自共用矩陣元件
    expect(page.locator("[data-testid=le-matrix] input[data-mx=selall]")).to_have_count(1)
    # 原本收件人說明、群組計數、標籤都在矩陣裡
    expect(page.locator("[data-testid='mx-row-dev_case_unassigned']")).to_contain_text("前任負責人")
    expect(page.locator("[data-testid=le-matrix]")).to_contain_text("已開 ")
    expect(page.locator("[data-testid=le-matrix]")).to_contain_text("僅 LINE")
    expect(page.locator("[data-testid=le-matrix]")).to_contain_text("重要")
    # 舊清單（逐項展開＋勾選）與「前往矩陣頁」連結都已移除
    assert page.locator("[data-testid=line-open-matrix]").count() == 0
    assert page.locator("#line-panel input[id^=chk-line-ev-]").count() == 0
    sel = ",".join("[data-testid^='%s']" % p for p in OLD_TESTID_PREFIXES)
    assert page.locator(sel).count() == 0, "舊清單 testid 不應再出現"
    # 「提醒未綁定的人」按鈕與綁定名單保留
    expect(page.locator("[data-testid=line-bind-remind]")).to_be_visible()
    expect(page.locator("[data-testid=line-bind-summary]")).to_be_visible()


@pytest.mark.e2e
def test_inline_matrix_saves_a_draft_through_the_confirm_bar(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    page = _open_settings(live_server, make_user, new_page, login_as, "e2e_t86b")
    assert L.event_enabled("approval_request") is False
    row = page.locator("[data-testid=le-matrix] [data-testid='mx-row-approval_request']")
    row.locator(".mx-sw").click()
    assert L.event_enabled("approval_request") is False, "點選只是草稿，儲存前不生效"
    page.locator("[data-testid=mx-draft-save]").click()
    dlg = page.locator(".mx-dlg button").filter(has_text="儲存").first
    dlg.wait_for(state="visible", timeout=10000)
    dlg.click()
    expect(page.locator("[data-testid=mx-draftbar]")).to_have_count(0, timeout=10000)
    assert L.event_enabled("approval_request") is True


@pytest.mark.e2e
def test_line_events_page_url_still_works(live_server, make_user, new_page, login_as, fake):
    _configure()
    u = make_user(username="e2e_t86c", role="superadmin")
    page = new_page(viewport={"width": 1440, "height": 1800})
    login_as(page, u)
    page.goto(f"{live_server}/pages/line-events.html")
    expect(page.locator("[data-testid=le-matrix] [data-testid='mx-row-approval_request']")).to_be_visible(timeout=20000)
    expect(page.locator("[data-testid=le-back-link]")).to_be_visible()
