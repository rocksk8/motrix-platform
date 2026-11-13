"""瀏覽器端對端：LINE 通知事件矩陣頁（pages/line-events.html，共用元件 mx-table.js；2026-11-13，LINE 事件矩陣票）。

驗：單格開關（新開預設只發給我、復原）、勾選＋批次開啟（確認視窗）、批次關閉重要告警（兩段確認、取消不動）、
收件對象下拉＋指定視窗、搜尋與篩選、手機寬度變卡片且不橫向捲動、舊通知設定頁有連結過來、「已累積 N 天」標示。
對外呼叫一律換掉 `line_notify._http`，不連 LINE。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import expect  # noqa: E402


@pytest.fixture()
def fake(monkeypatch):
    from helpers import line_notify, line_quota

    def _http(method, path, token, payload=None):
        if path.endswith("/quota/consumption"):
            return 200, {"totalUsage": 10}
        if path.endswith("/quota"):
            return 200, {"type": "limited", "value": 200}
        return 200, {}
    monkeypatch.setattr(line_notify, "_http", _http)
    line_quota._mem.update(checked_at=None, failed_at=None, error="", fp=None)


def _configure():
    from helpers.settings import _set_setting
    _set_setting("line_notify", {"enabled": True, "channel_access_token": "tok-e2e-mx-0123456789", "public_base_url": "https://line.example.com",
                                 "login_channel_id": "1234567890", "login_channel_secret": "0123456789abcdef0123456789abcdef"})


def _open(live_server, make_user, new_page, login_as, name, width=1440):
    u = make_user(username=name, role="superadmin")
    page = new_page(viewport={"width": width, "height": 1800})
    login_as(page, u)
    page.goto(f"{live_server}/pages/line-events.html")
    page.locator("[data-testid='mx-row-approval_request']" if width > 900 else ".mx-card-row").first.wait_for(state="attached", timeout=20000)
    return page


def _row(page, key):
    return page.locator("[data-testid='mx-row-%s']" % key)


def _sw(page, key):
    return _row(page, key).locator(".mx-sw")


def _dlg_btn(page, text):
    return page.locator(".mx-dlg button").filter(has_text=text).first


@pytest.mark.e2e
def test_switch_defaults_to_only_me_and_has_no_cell_undo(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx1")
    key = "approval_request"
    expect(_sw(page, key)).to_have_attribute("aria-checked", "false")
    _sw(page, key).click()
    expect(_sw(page, key)).to_have_attribute("aria-checked", "true")
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已開啟")
    assert L.event_enabled(key)
    assert L.audience_view()[key] == {"mode": "only", "roles": [], "users": ["e2e_mx1"]}, "新開的事件預設只發給操作者本人"
    expect(_row(page, key).locator("[data-testid='le-who-%s']" % key)).to_contain_text("e2e_mx1")
    expect(page.locator("[data-testid=mx-undo]")).to_have_count(0)           # 單格操作沒有復原（PM N2：復原只給「這一批」）


@pytest.mark.e2e
def test_batch_on_confirm_then_apply_and_filters(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx2")
    keys = ["approval_request", "dev_case_unassigned"]
    page.locator("[data-testid=mx-batch]").wait_for(state="hidden", timeout=5000)
    for k in keys:
        _row(page, k).locator("input[data-mx=sel]").check()
    expect(page.locator("[data-testid=mx-batch-count]")).to_have_text("已選 2 項")
    page.locator("[data-testid=mx-batch-on]").click()
    _dlg_btn(page, "開啟").wait_for(state="visible", timeout=5000)
    _dlg_btn(page, "取消").click()
    expect(page.locator(".mx-dlg")).to_have_count(0)
    assert not any(L.event_enabled(k) for k in keys), "取消 ⇒ 不動"
    page.locator("[data-testid=mx-batch-on]").click()
    _dlg_btn(page, "開啟").click()
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已開啟")
    assert all(L.event_enabled(k) for k in keys)
    assert all(L.audience_view()[k]["users"] == ["e2e_mx2"] for k in keys)
    # 篩選「已開啟」只剩這兩列；搜尋
    page.locator(".mx-toolbar [data-f=on]").first.click()
    expect(page.locator(".mx-table tbody tr.mx-row")).to_have_count(2)
    page.locator(".mx-toolbar [data-f=all]").first.click()
    page.locator("[data-mx=search]").fill("dev_case_unassigned")
    expect(page.locator(".mx-table tbody tr.mx-row")).to_have_count(1)


@pytest.mark.e2e
def test_batch_off_critical_needs_two_confirms_and_cancel_changes_nothing(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    L.set_event("backup_error", True)
    L.set_event("approval_request", True)
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx3")
    for k in ("backup_error", "approval_request"):
        _row(page, k).locator("input[data-mx=sel]").check()
    page.locator("[data-testid=mx-batch-off]").click()
    _dlg_btn(page, "繼續").click()
    expect(page.locator(".mx-dlg h3")).to_contain_text("重要")
    expect(page.locator(".mx-dlg .mx-danger-box")).to_be_visible()
    _dlg_btn(page, "取消").click()
    expect(page.locator(".mx-dlg")).to_have_count(0)
    assert L.event_enabled("backup_error") and L.event_enabled("approval_request"), "第二段取消 ⇒ 都不動"
    page.locator("[data-testid=mx-batch-off]").click()
    _dlg_btn(page, "繼續").click()
    _dlg_btn(page, "仍要關閉").click()
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已關閉")
    assert not L.event_enabled("backup_error") and not L.event_enabled("approval_request")
    page.locator("[data-testid=mx-undo]").click()
    expect(_sw(page, "backup_error")).to_have_attribute("aria-checked", "true")
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已復原這一批")
    assert L.event_enabled("backup_error") and L.event_enabled("approval_request")


@pytest.mark.e2e
def test_undo_batch_refused_when_changed_by_someone_else(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx7")
    keys = ["approval_request", "dev_case_unassigned"]
    for k in keys:
        _row(page, k).locator("input[data-mx=sel]").check()
    page.locator("[data-testid=mx-batch-on]").click()
    _dlg_btn(page, "開啟").click()
    expect(page.locator("[data-testid=mx-toast-text]")).to_contain_text("已開啟")
    L.set_event("dev_case_unassigned", False)                                 # 套用之後，別的視窗改了其中一個
    page.locator("[data-testid=mx-undo]").click()
    expect(page.locator(".mx-toast-error")).to_contain_text("無法復原這一批")
    assert L.event_enabled("approval_request"), "拒絕時整批都不復原"


@pytest.mark.e2e
def test_single_critical_switch_off_asks_and_mode_picker_saves(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    L.set_event("auth_lockout", True)
    L.set_event("approval_request", True)
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx4")
    _sw(page, "auth_lockout").click()
    _dlg_btn(page, "取消").click()
    expect(page.locator(".mx-dlg")).to_have_count(0)
    assert L.event_enabled("auth_lockout")
    _sw(page, "auth_lockout").click()
    _dlg_btn(page, "仍要關閉").click()
    expect(_sw(page, "auth_lockout")).to_have_attribute("aria-checked", "false")
    assert not L.event_enabled("auth_lockout")
    # 收件對象：照原本 → 只發給指定（開指定視窗，勾財務角色）
    key = "approval_request"
    L.set_audience(key, "business", [], [])
    page.reload()
    _row(page, key).wait_for(state="attached", timeout=20000)
    _row(page, key).locator("select[data-col=mode]").select_option("only")
    page.locator("[data-testid=le-pick-mode-only]").wait_for(state="visible", timeout=5000)
    page.locator(".le-roles input[data-role=finance]").check()
    _dlg_btn(page, "套用").click()
    expect(_row(page, key).locator("select[data-col=mode]")).to_have_value("only")
    assert L.audience_view()[key] == {"mode": "only", "roles": ["finance"], "users": []}
    expect(_row(page, key).locator(".mx-chip, .mx-rc.on.a")).to_have_count(1)
    # 改回「照原本」：不開視窗、直接寫入並清掉指定
    _row(page, key).locator("select[data-col=mode]").select_option("business")
    expect(_row(page, key).locator("select[data-col=mode]")).to_have_value("business")
    assert L.audience_view()[key]["mode"] == "business"


@pytest.mark.e2e
def test_header_shows_accumulated_days_and_old_page_links_here(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx5")
    expect(page.locator("[data-testid=le-total30]")).to_be_visible()
    expect(page.locator("[data-testid=le-accum]")).to_contain_text("已累積")
    page.goto(f"{live_server}/pages/notification-settings.html")
    link = page.locator("[data-testid=line-open-matrix]")
    link.wait_for(state="visible", timeout=20000)
    with page.expect_navigation():
        link.click()
    expect(page.locator("[data-testid=le-matrix]")).to_be_visible()


@pytest.mark.e2e
def test_phone_width_uses_cards_and_has_no_horizontal_scroll(live_server, make_user, new_page, login_as, fake):
    _configure()
    page = _open(live_server, make_user, new_page, login_as, "e2e_mx6", width=390)
    expect(page.locator(".mx-wrap")).to_be_hidden()
    expect(page.locator(".mx-card-row").first).to_be_visible()
    over = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, "手機寬度頁面不可橫向捲動（超出 %s px）" % over
