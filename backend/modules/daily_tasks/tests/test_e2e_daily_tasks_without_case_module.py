"""瀏覽器端對端（M01-PLAN §5 ④ SO，主持裁示）：案件模組（M01）不在時，每日工作頁的「關聯案件」要說出原因，
不是一個看起來「沒有已成案案件」的空清單。

M01 不在 ⇒ `/api/sales-orders`（M01 的端點）404。本題以攔截回應模擬 404（驗的是 M12 頁面在 M01 不在時的行為，
不可以因為 M01 不在就略過）；正對照：端點正常回應 ⇒ 沒有這句說明、選單可用。
"""
import pytest

pytest.importorskip("playwright.sync_api")

DATA = "Alpine.$data(document.querySelector('[x-data]'))"
NOTICE = "案件模組未安裝：無法關聯案件（其他欄位照常可填）"


def _open(live_server, make_user, new_page, login_as, name, route_404):
    user = make_user(username=name, role="superadmin")
    page = new_page()
    if route_404:
        page.route("**/api/sales-orders*", lambda route: route.fulfill(status=404, content_type="application/json",
                                                                        body='{"detail":"Not Found"}'))
    login_as(page, tuple(user)[:2])
    with page.expect_response(lambda r: "/api/sales-orders" in r.url, timeout=20000):
        page.goto(f"{live_server}/pages/daily-tasks.html")
    return page


@pytest.mark.e2e
def test_case_picker_says_why_when_the_case_module_is_absent(live_server, make_user, new_page, login_as):
    page = _open(live_server, make_user, new_page, login_as, "e2e_so_absent", route_404=True)
    page.wait_for_function(f"() => {DATA}.casesNotice === {NOTICE!r}", timeout=10000)
    assert page.evaluate(f"() => {DATA}.activeCases.length") == 0


@pytest.mark.e2e
def test_no_notice_when_the_case_module_answers(live_server, make_user, new_page, login_as):
    page = _open(live_server, make_user, new_page, login_as, "e2e_so_present", route_404=False)
    page.wait_for_timeout(300)                     # 回應已到（expect_response），給 Alpine 一個 tick 套用
    assert page.evaluate(f"() => {DATA}.casesNotice") == ""
