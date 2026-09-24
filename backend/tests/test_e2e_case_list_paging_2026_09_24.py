"""案件頁清單：伺服器分頁／搜尋（2026-09-24 使用者表單）。

一頁 100 件、「載入更多」；搜尋打到伺服器（第一頁以外的也搜得到）；
上方摘要數字是全部案件（不是已載入的那一頁）；深連結 ?q= 指向第一頁以外的案件也打得開。
觀測點：清單卡片數、摘要數字、selected。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
OLDEST = "MQ-PAGE-0000"


def _bulk(n):
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        for i in range(n):
            no = f"MQ-PAGE-{i:04d}"
            cust = "最舊的客戶" if i == 0 else "分頁客戶"
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (no, "已送出", cust, f"專案{i}", 1000, 952,
                 json.dumps({"dealTag": "已成案"}, ensure_ascii=False), now, now, "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()




def _open(browser, base, user, query=""):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    inject_login(page, base, user[0], user[1])
    page.goto(f"{base}/pages/case-management.html{query}")
    page.wait_for_function(f"() => {DATA_JS} && {DATA_JS}.session && {DATA_JS}.session.token && !{DATA_JS}.loading",
                           timeout=20000)
    return page


def _cards(page):
    return page.locator(".cm-card[data-quote-no]")


@pytest.mark.e2e
def test_first_page_then_load_more(live_server, make_user, e2e_browser):
    u = make_user(username="pg_e1", role="admin")
    _bulk(130)
    browser = e2e_browser
    page = _open(browser, live_server, u)
    page.wait_for_function("() => document.querySelectorAll('.cm-card[data-quote-no]').length === 100",
                           timeout=10000)
    page.wait_for_function(f"() => {DATA_JS}.caseCounts", timeout=10000)   # 件數是另一支非同步請求
    assert page.evaluate(f"() => {DATA_JS}.summaryTotal()") == 130, "摘要要算全部案件"
    more = page.locator("[data-testid=case-load-more]")
    assert more.is_visible()
    more.click()
    page.wait_for_function("() => document.querySelectorAll('.cm-card[data-quote-no]').length === 130",
                           timeout=10000)
    page.locator("[data-testid=case-load-more]").wait_for(state="hidden", timeout=5000)


@pytest.mark.e2e
def test_search_reaches_cases_outside_the_loaded_page(live_server, make_user, e2e_browser):
    u = make_user(username="pg_e2", role="admin")
    _bulk(505)          # 超過舊版一次拉的 500 件：最舊的一件在舊版清單裡根本不存在
    browser = e2e_browser
    page = _open(browser, live_server, u)
    page.wait_for_function("() => document.querySelectorAll('.cm-card[data-quote-no]').length === 100",
                           timeout=10000)
    page.fill(".cm-list__search-input[type=text]", "最舊")
    page.wait_for_function(
        "() => { const c = document.querySelectorAll('.cm-card[data-quote-no]');"
        f" return c.length === 1 && c[0].dataset.quoteNo === '{OLDEST}' }}", timeout=10000)


@pytest.mark.e2e
def test_deep_link_opens_a_case_outside_the_first_page(live_server, make_user, e2e_browser):
    u = make_user(username="pg_e3", role="admin")
    _bulk(505)
    browser = e2e_browser
    page = _open(browser, live_server, u, query=f"?q={OLDEST}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{OLDEST}'",
                           timeout=15000)


@pytest.mark.e2e
def test_summary_never_shows_the_loaded_page_count_as_the_total(live_server, make_user, e2e_browser):
    """件數（counts）比清單晚到時，摘要不可以先顯示已載入的那一頁件數（100）當總數。"""
    u = make_user(username="pg_e4", role="admin")
    _bulk(130)
    browser = e2e_browser
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    inject_login(page, live_server, u[0], u[1])
    page.route("**/api/quotations?*counts=1*", lambda route: (time.sleep(2.0), route.continue_()))
    page.goto(f"{live_server}/pages/case-management.html")
    page.wait_for_function("() => document.querySelectorAll('.cm-card[data-quote-no]').length === 100",
                           timeout=15000)
    sub = page.locator(".cm-placeholder__sub")
    assert "100" not in sub.inner_text(), sub.inner_text()
    page.wait_for_function(f"() => {DATA_JS}.caseCounts", timeout=10000)
    page.wait_for_function("() => document.querySelector('.cm-placeholder__sub').textContent.includes('130')",
                           timeout=5000)
