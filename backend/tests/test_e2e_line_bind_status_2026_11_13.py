"""瀏覽器端對端：「誰還沒綁 LINE」（T83，2026-11-13）。

- 名單三種狀態（已綁定／尚未綁定／綁定失效）、未綁好的人底下列「綁好後會收到：…」、畫面沒有 LINE 識別碼
- 提醒綁定按鈕（人數＝尚未綁定＋綁定失效）
- 手機寬度（390px）頁面不橫向捲動
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_line_events_all_2026_11_13 import UID, _configure, _open, fake  # noqa: E402,F401  夾具共用


@pytest.mark.e2e
def test_three_states_missed_events_and_remind_count(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    L.set_event("approval_request", True)
    make_user(username="e2e_ok", role="sales")
    make_user(username="e2e_none", role="sales")
    make_user(username="e2e_bad", role="sales")
    L.link_user("e2e_ok", UID)
    L.link_user("e2e_bad", "U" + "e" * 32)
    L.set_confirmed("e2e_bad", False)
    page = _open(live_server, make_user, new_page, login_as, "e2e_t83a")
    page.wait_for_function("() => !document.querySelector('[data-testid=line-bind-summary]').innerText.includes('讀取中')", timeout=10000)
    assert "還沒綁定" in page.locator("[data-testid=line-bind-summary]").inner_text() and "綁定失效 1 人" in page.locator("[data-testid=line-bind-summary]").inner_text()
    page.locator("[data-testid=line-bind-toggle]").click()
    assert "已綁定" in page.locator("[data-testid=line-bind-row-e2e_ok]").inner_text()
    assert "尚未綁定" in page.locator("[data-testid=line-bind-row-e2e_none]").inner_text()
    assert "綁定失效" in page.locator("[data-testid=line-bind-row-e2e_bad]").inner_text()
    miss = page.locator("[data-testid=line-bind-missed-e2e_none]")
    miss.wait_for(state="visible", timeout=10000)
    assert miss.inner_text().startswith("綁好後會收到：")
    assert page.locator("[data-testid=line-bind-missed-e2e_ok]").count() == 0 or not page.locator("[data-testid=line-bind-missed-e2e_ok]").is_visible()
    html = page.content()
    assert UID not in html and "d" * 32 not in html and "e" * 32 not in html, "畫面上沒有 LINE 識別碼"
    btn = page.locator("[data-testid=line-bind-remind]")
    assert "提醒綁定（" in btn.inner_text()
    btn.click()
    page.locator("[data-testid=line-msg]").filter(has_text="已提醒").wait_for(state="visible", timeout=10000)
    from db import get_db
    c = get_db()
    try:
        n = lambda u: c.execute("SELECT COUNT(*) n FROM notifications WHERE username=? AND type='line_binding_reminder'", (u,)).fetchone()["n"]   # noqa: E731
        assert n("e2e_bad") == 1 and n("e2e_none") == 1 and n("e2e_ok") == 0, "尚未綁定與綁定失效的人都被提醒，綁好的不提醒"
    finally:
        c.close()


@pytest.mark.e2e
def test_bind_list_fits_a_390px_phone_without_horizontal_page_scroll(live_server, make_user, new_page, login_as, fake):
    _configure()
    from helpers import line_notify as L
    for k in list(L.WIRED_EVENTS)[:12]:
        L.set_event(k, True)
    make_user(username="e2e_long_name_person", role="sales")
    page = _open(live_server, make_user, new_page, login_as, "e2e_t83b", width=390)
    page.wait_for_function("() => !document.querySelector('[data-testid=line-bind-summary]').innerText.includes('讀取中')", timeout=10000)
    page.locator("[data-testid=line-bind-toggle]").click()
    page.locator("[data-testid=line-bind-row-e2e_long_name_person]").wait_for(state="visible", timeout=10000)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "手機寬度不橫向捲動"
    assert page.locator("[data-testid=line-bind-remind]").is_visible()
