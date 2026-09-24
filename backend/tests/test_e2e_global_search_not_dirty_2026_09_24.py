"""頂端全域搜尋框打字不可以觸發「尚未儲存」離頁警告（開發機實走 W-7，2026-09-24）。

sidebar.js 的 _maybeSetDirty 只略過 type=search 或 class 含 search／filter 的欄位；
全域搜尋框是 type=text 且沒有 class ⇒ 打字就設 motrixIsDirty=true，之後點任何連結都問
「確定要離開嗎？」。心跳不再清 dirty（同日 a01e628）之後這個問題才一直留著。

觀測點：在報價單清單頁的全域搜尋框打字後 window.motrixIsDirty 仍為 false；
正對照：同頁一般表單欄位（非搜尋）打字仍會設成 true，證明偵測本身沒有被整個關掉。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

GLOBAL_SEARCH = "input[placeholder^='搜尋客戶']"




@pytest.mark.e2e
def test_typing_in_global_search_does_not_mark_page_dirty(live_server, make_user, e2e_browser):
    u = make_user(username="gsd_e1", role="admin")
    browser = e2e_browser
    page = browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/quotations.html")
    page.wait_for_selector(GLOBAL_SEARCH, timeout=15000)
    page.evaluate("() => { window.motrixIsDirty = false }")
    page.locator(GLOBAL_SEARCH).first.type("abc")
    assert page.evaluate("() => window.motrixIsDirty") is not True, \
        "全域搜尋框打字被當成未存修改 ⇒ 之後點任何連結都會跳離頁警告"
    # 正對照：一般（非搜尋）文字欄位打字仍會設 dirty
    page.evaluate("""() => { const i = document.createElement('input'); i.type = 'text';
                             i.id = 'gsd-probe'; document.body.appendChild(i); }""")
    page.locator("#gsd-probe").type("x")
    assert page.evaluate("() => window.motrixIsDirty") is True, "偵測被整個關掉了（正對照失敗）"


@pytest.mark.e2e
def test_voucher_list_filters_do_not_mark_page_dirty(live_server, make_user, e2e_browser):
    """W-8：傳票清單左側的關鍵字／起迄日期／狀態篩選是檢視條件，不是未存修改。"""
    u = make_user(username="gsd_e2", role="superadmin")
    browser = e2e_browser
    page = browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/voucher.html")
    page.wait_for_selector("[data-testid=voucher-filter-kw]", timeout=15000)
    page.evaluate("() => { window.motrixIsDirty = false }")
    page.locator("[data-testid=voucher-filter-kw]").type("abc")
    page.locator("[data-testid=voucher-filter-from]").fill("2026-09-01")
    page.locator("[data-testid=voucher-filter-to]").fill("2026-09-30")
    assert page.evaluate("() => window.motrixIsDirty") is not True, \
        "傳票清單的篩選欄被當成未存修改 ⇒ 換頁會跳離頁警告"


@pytest.mark.e2e
def test_user_list_search_does_not_mark_page_dirty(live_server, make_user, e2e_browser):
    """D8-3：使用者管理頁的搜尋框是檢視條件，不是未存修改。"""
    u = make_user(username="gsd_e3", role="superadmin")
    browser = e2e_browser
    page = browser.new_context().new_page()
    inject_login(page, live_server, u[0], u[1])
    page.goto(f"{live_server}/pages/users.html")
    page.wait_for_selector("input[x-model=userSearch]", timeout=15000)
    page.evaluate("() => { window.motrixIsDirty = false }")
    page.locator("input[x-model=userSearch]").type("abc")
    assert page.evaluate("() => window.motrixIsDirty") is not True, \
        "使用者搜尋框被當成未存修改 ⇒ 換頁會跳離頁警告"
