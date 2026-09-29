"""搜尋載入失敗後，同一個字再觸發要能重送（D 稽核 S2）。

`onSearch()` 為「字沒變不送」記了 `_lastQ`；若失敗也記著，使用者看到「載入失敗」後再按一次同樣的字就永遠不會重送。
觀測點是**瀏覽器實際送出的 `?q=` 請求次數**（不是 Alpine 模型）。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login as _login  # noqa: E402,F401
from tests._mapiso import no_tile_probe  # noqa: E402,F401

RADAR = "Alpine.$data(document.querySelector('.tr-wrap'))"


def _open(page, base):
    page.goto(f"{base}/pages/tender-radar.html")
    page.wait_for_function(f"() => window.Alpine && {RADAR} && {RADAR}.status !== null", timeout=20000)


@pytest.mark.e2e
@pytest.mark.parametrize("failure", ["http500", "network"])
def test_same_search_text_is_resent_after_a_failed_load(live_server, make_user, no_tile_probe, e2e_browser, failure):
    u = make_user(username="sr_" + failure, role="superadmin", modules=["dashboard", "tender_radar"])
    page = e2e_browser.new_context().new_page()
    _login(page, live_server, *u)
    _open(page, live_server)
    sent = []

    def handler(route):
        sent.append(route.request.url)
        if len(sent) == 1:
            return route.fulfill(status=500, body="x") if failure == "http500" else route.abort()
        return route.continue_()
    page.route("**/api/tender-radar/tenders?q=*", handler)

    page.fill("input[type=search]", "監視")
    page.wait_for_function(f"() => {RADAR}.listError", timeout=10000)
    assert len(sent) == 1
    page.evaluate("() => document.querySelector('input[type=search]').dispatchEvent(new Event('input', { bubbles: true }))")
    page.wait_for_function(f"() => !{RADAR}.listError", timeout=10000)
    assert len(sent) == 2, "失敗之後同一個字沒有重送（_lastQ 沒清）"


@pytest.mark.e2e
def test_same_search_text_is_not_resent_after_a_successful_load(live_server, make_user, no_tile_probe, e2e_browser):
    """正對照：成功之後同一個字不重送（去抖的本意）。"""
    u = make_user(username="sr_ok", role="superadmin", modules=["dashboard", "tender_radar"])
    page = e2e_browser.new_context().new_page()
    _login(page, live_server, *u)
    _open(page, live_server)
    sent = []
    page.route("**/api/tender-radar/tenders?q=*", lambda route: (sent.append(1), route.continue_())[1])
    page.fill("input[type=search]", "監視")
    page.wait_for_timeout(1500)
    assert len(sent) == 1
    page.evaluate("() => document.querySelector('input[type=search]').dispatchEvent(new Event('input', { bubbles: true }))")
    page.wait_for_timeout(1500)
    assert len(sent) == 1
