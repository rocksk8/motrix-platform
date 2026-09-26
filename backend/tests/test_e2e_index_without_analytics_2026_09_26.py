"""首頁在「營運分析」模組（M08 analytics）不在時的降級（M08 搬遷 ④，PLAYBOOK §B-4）。

M08 不在 ⇒ `/api/dashboard/*` 回 404。首頁（L1）要明說「需要營運分析模組，其他功能照常」，
不可以講成「可能是連線或伺服器正在重啟」（那會讓人去等一件不會自己好的事），也不可以把 0 講成「沒有資料」。
以 page.route 讓 **`/api/dashboard/` 底下全部**回 404 模擬模組不在（路由在同一個行程裡拿不掉；稽核 ⑰ M-4：
第一版只攔 `/stats`，funnel 照常回資料 ⇒ 沒模擬到「兩格顯示 0＋沒有…」那個狀態）；正對照在 modules/analytics/tests。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

_MISSING = "[data-testid='analytics-missing']"


def _open(e2e_browser, live_server, make_user, name, stats_404):
    u = make_user(username=name, role="superadmin")
    page = e2e_browser.new_context().new_page()
    if stats_404:
        page.route("**/api/dashboard/**", lambda route: route.fulfill(status=404, body='{"detail":"Not Found"}',
                                                                       content_type="application/json"))
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/index.html")
    return page


@pytest.mark.e2e
def test_index_says_the_module_is_missing_not_that_the_server_is_restarting(live_server, make_user, e2e_browser):
    page = _open(e2e_browser, live_server, make_user, "idx_an_missing", stats_404=True)
    page.locator(_MISSING).wait_for(state="visible", timeout=15000)
    text = page.locator(_MISSING).inner_text()
    assert "營運分析" in text and "其他功能照常" in text
    body = page.inner_text("body")
    assert "伺服器正在重啟" not in body, "模組不在時不可以講成伺服器重啟"


@pytest.mark.e2e
def test_index_counters_do_not_say_zero_when_the_module_is_missing(live_server, make_user, e2e_browser):
    """稽核 ⑰ M-4：模組不在 ⇒ 「有效期將屆」「90 天內到期」兩格不可以顯示 0＋「沒有…」（跟真的 0 筆長得一樣）。"""
    page = _open(e2e_browser, live_server, make_user, "idx_an_band", stats_404=True)
    page.locator(_MISSING).wait_for(state="visible", timeout=15000)
    for tid in ("band-expiring", "band-warranty"):
        cell = page.locator("[data-testid='%s']" % tid)
        text = cell.inner_text()
        assert "營運分析" in text, (tid, text)
        assert cell.locator(".h-band__n").inner_text().strip() == "—", (tid, text)
        assert "沒有需要追蹤" not in text and "沒有已過保" not in text, (tid, text)
