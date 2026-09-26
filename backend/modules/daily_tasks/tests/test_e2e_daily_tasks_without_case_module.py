"""瀏覽器端對端（M01-PLAN §5 ④ SO，主持裁示）：案件模組（M01）不在時，每日工作頁的「關聯案件」要說出原因，
不是一個看起來「沒有已成案案件」的空清單。

M01 不在 ⇒ `/api/sales-orders`（M01 的端點）404。本題以攔截回應模擬 404（驗的是 M12 頁面在 M01 不在時的行為，
不可以因為 M01 不在就略過）；正對照：端點正常回應 ⇒ 沒有這句說明、選單可用。
〔稽核 D M4-M1：~~只驗 Alpine 模型~~ ⇒ 改驗使用者看得到的東西：說明在 DOM 上可見、選單真的停用〕
"""
import pytest

pytest.importorskip("playwright.sync_api")

NOTICE = "案件模組未安裝：無法關聯案件（其他欄位照常可填）"
NOTE = "[data-testid=cases-unavailable]"
PICKER = "select[x-model='form.case_no']"


def _open_form(live_server, make_user, new_page, login_as, name, route_404):
    user = make_user(username=name, role="superadmin")
    page = new_page()
    if route_404:
        page.route("**/api/sales-orders*", lambda route: route.fulfill(status=404, content_type="application/json",
                                                                        body='{"detail":"Not Found"}'))
    login_as(page, tuple(user)[:2])
    with page.expect_response(lambda r: "/api/sales-orders" in r.url, timeout=20000):
        page.goto(f"{live_server}/pages/daily-tasks.html")
    # 打開「新增工作」表單（桌機寬度預設是月曆視圖，列表列的「新增」鈕不在畫面上 ⇒ 呼叫同一支 openCreate()）
    page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).openCreate()")
    page.wait_for_selector(PICKER, state="visible", timeout=10000)
    return page


@pytest.mark.e2e
def test_case_picker_says_why_when_the_case_module_is_absent(live_server, make_user, new_page, login_as):
    page = _open_form(live_server, make_user, new_page, login_as, "e2e_so_absent", route_404=True)
    note = page.locator(NOTE)
    note.wait_for(state="visible", timeout=10000)
    assert note.inner_text().strip() == NOTICE
    assert page.locator(PICKER).is_disabled()


@pytest.mark.e2e
def test_no_notice_when_the_case_module_answers(live_server, make_user, new_page, login_as):
    page = _open_form(live_server, make_user, new_page, login_as, "e2e_so_present", route_404=False)
    assert not page.locator(NOTE).is_visible()
    assert page.locator(PICKER).is_enabled()
