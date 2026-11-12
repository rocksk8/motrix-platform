"""瀏覽器端對端：通知設定頁「LINE 通知」卡片改版（2026-11-13）。

驗每個新按鈕真的動：事件依模組分組（預設只展開第一組、顯示「已開 N／共 M」）、「僅 LINE」與「重要」標籤、
「設定誰要發」編輯器（三種模式、指定角色與人員、儲存後重新整理仍在）、綁定狀況（名單、提醒按鈕、解除綁定兩段確認）、手機寬度不橫向捲動。
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
    page.wait_for_function("() => document.querySelectorAll('#line-panel input[id^=chk-line-ev-]').length >= 2", timeout=20000)
    return page


@pytest.mark.e2e
def test_groups_collapse_and_show_counts_tags_and_priority(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    L.set_event("approval_request", True)
    page = _open(live_server, make_user, new_page, login_as, "e2e_ev1")
    head = lambda g: page.locator("[data-testid='line-group-head-%s']" % g)          # noqa: E731
    assert head("報價單與簽核").get_attribute("aria-expanded") == "true", "第一組（簽核）預設展開"
    assert head("業務開發").get_attribute("aria-expanded") == "false"
    assert page.locator("[data-testid='line-group-count-報價單與簽核']").inner_text().startswith("已開 1／共 ")
    assert page.locator("#chk-line-ev-approval_request").is_checked()
    assert page.locator("#chk-line-ev-dev_case_unassigned").count() == 0, "收合的組不渲染"
    head("業務開發").click()
    page.locator("#chk-line-ev-dev_case_unassigned").wait_for(state="visible", timeout=10000)
    assert page.locator("[data-testid=line-tag-only-dev_case_unassigned]").is_visible(), "LINE-only 事件標「僅 LINE」"
    assert not page.locator("[data-testid=line-tag-only-dev_case_assigned]").is_visible()
    head("系統告警").click()
    page.locator("[data-testid=line-tag-critical-backup_error]").wait_for(state="visible", timeout=10000)
    assert page.locator("[data-testid=line-tag-critical-auth_lockout]").is_visible()
    assert page.locator("#chk-line-ev-bonus_submitted").count() == 0 and page.locator("#chk-line-ev-system_test_mail").count() == 0
    # 勾選會即時更新該組的「已開 N」（業務開發組上面已經展開）
    page.locator("#chk-line-ev-crm_case_status").check()
    page.locator("[data-testid=line-msg]").filter(has_text="已開啟").wait_for(state="visible", timeout=10000)
    assert L.event_enabled("crm_case_status")
    assert page.locator("[data-testid='line-group-count-業務開發']").inner_text().startswith("已開 1／共 ")


@pytest.mark.e2e
def test_audience_editor_saves_modes_roles_and_people(live_server, make_user, new_page, login_as, fake):
    _configure()
    make_user(username="e2e_pick", role="engineer")
    page = _open(live_server, make_user, new_page, login_as, "e2e_ev2")
    from helpers import line_notify as L
    key = "approval_request"
    assert page.locator("[data-testid=line-aud-summary-%s]" % key).inner_text() == "收件人：照原本的設定"
    page.locator("[data-testid=line-aud-open-%s]" % key).click()
    ed = page.locator("[data-testid=line-aud-editor-%s]" % key)
    ed.wait_for(state="visible", timeout=10000)
    assert page.locator("[data-testid=line-aud-mode-%s-business]" % key).is_checked()
    assert not page.locator("[data-testid=line-aud-pick-%s]" % key).is_visible(), "『照原本』模式不顯示指定欄"
    page.locator("[data-testid=line-aud-mode-%s-business_plus]" % key).check()
    page.locator("[data-testid=line-aud-role-%s-finance]" % key).check()
    page.locator("[data-testid=line-aud-pick-%s]" % key).select_option("e2e_pick")
    page.locator("[data-testid=line-aud-chip-%s-e2e_pick]" % key).wait_for(state="visible", timeout=5000)
    assert "尚未綁定" in page.locator("[data-testid=line-aud-chip-%s-e2e_pick]" % key).inner_text()
    page.locator("[data-testid=line-aud-save-%s]" % key).click()
    page.locator("[data-testid=line-msg]").filter(has_text="的收件人").wait_for(state="visible", timeout=10000)
    assert L.audience_view()[key] == {"mode": "business_plus", "roles": ["finance"], "users": ["e2e_pick"]}
    assert page.locator("[data-testid=line-aud-editor-%s]" % key).count() == 0, "儲存後收合"
    s = page.locator("[data-testid=line-aud-summary-%s]" % key).inner_text()
    assert s.startswith("原本的收件人，另加：") and "財務" in s and "e2e_pick" in s
    page.reload()
    page.locator("[data-testid=line-aud-summary-%s]" % key).wait_for(state="visible", timeout=20000)
    assert "財務" in page.locator("[data-testid=line-aud-summary-%s]" % key).inner_text(), "重新整理後仍在"
    # 改成只發給指定、再改回預設
    page.locator("[data-testid=line-aud-open-%s]" % key).click()
    page.locator("[data-testid=line-aud-mode-%s-only]" % key).check()
    page.locator("[data-testid=line-aud-del-%s-e2e_pick]" % key).click()
    page.locator("[data-testid=line-aud-save-%s]" % key).click()
    page.wait_for_function("() => document.querySelector(\"[data-testid='line-aud-summary-approval_request']\").innerText.startsWith('只發給')", timeout=10000)
    assert L.audience_view()[key]["mode"] == "only" and L.audience_view()[key]["users"] == []
    page.locator("[data-testid=line-aud-open-%s]" % key).click()
    page.locator("[data-testid=line-aud-mode-%s-business]" % key).check()
    page.locator("[data-testid=line-aud-save-%s]" % key).click()
    page.wait_for_function("() => document.querySelector(\"[data-testid='line-aud-summary-approval_request']\").innerText.startsWith('收件人：照原本')", timeout=10000)
    assert L.audience_view()[key]["mode"] == "business"


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
    # 解除綁定：兩段確認
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
    page.locator("[data-testid='line-group-head-業務開發']").click()
    page.locator("[data-testid=line-aud-open-crm_case_status]").click()
    page.locator("[data-testid=line-aud-mode-crm_case_status-only]").check()
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "手機寬度頁面不可橫向捲動（超出 %s px）" % over
