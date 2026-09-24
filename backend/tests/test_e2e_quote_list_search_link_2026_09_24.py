"""瀏覽器端對端：報價清單單號搜尋不分大小寫、報價單的「案件管理」連結帶單號（2026-09-24）。

- quotations.html 的搜尋把輸入轉小寫，卻拿去比對沒轉小寫的 quote_no ⇒ 打「mq-」找不到
- quotation-form.html 的「案件管理」連結原本是 href="case-management.html" ⇒ 點過去要自己再找一次
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port

QUOTE_NO = "MQ-202609-072"
DATA = "Alpine.$data(document.querySelector('[x-data]'))"



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。
    ⚠️ 只適用於沒有 CSS transition 的元素（有 transition 的要等轉場落定）。"""
    page.evaluate("() => new Promise(r => (window.Alpine ? Alpine.nextTick : (f => f()))(() => requestAnimationFrame(() => requestAnimationFrame(r))))")



def _login(page, base_url, username, password):
    return inject_login(page, base_url, username, password)


def _seed():
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, "
            "pretax, data_json, created_at, updated_at, deal_tag, quote_date) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (QUOTE_NO, "已送出", "搜尋客戶", "搜尋專案", 1050, 1000,
             json.dumps({"quoteNo": QUOTE_NO, "customerName": "搜尋客戶", "projectName": "搜尋專案",
                         "status": "已送出", "dealTag": "已成案",
                         "items": [{"id": 1, "description": "品項", "qty": 1, "unitPrice": 1000,
                                    "amount": 1000}],
                         "tot": {"total": 1050, "pretax": 1000, "directMarginPct": 0,
                                 "netMarginPct": 0}}, ensure_ascii=False),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00", "已成案", "2026-09-01"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_quote_no_search_is_case_insensitive(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_qsearch", role="superadmin")
    _seed()
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/quotations.html")
    page.wait_for_function(f"() => {DATA}.quotes.length > 0", timeout=20000)
    for term in ("MQ-202609-072", "mq-202609-072", "Mq-202609"):
        page.evaluate(f"{DATA}.search = {json.dumps(term)}")
        nos = page.evaluate(f"{DATA}.filtered.map(q => q.quote_no)")
        assert QUOTE_NO in nos, (term, nos)


@pytest.mark.e2e
def test_case_link_carries_quote_no(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_qlink", role="superadmin")
    _seed()
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/quotation-form.html?id={QUOTE_NO}")
    page.wait_for_function("() => document.body.innerText.includes('搜尋客戶')", timeout=20000)
    # 側欄也有一個「案件管理」連結（沒帶單號），所以用 href 精確比對，不用文字
    link = page.locator(f"a[href='case-management.html?q={QUOTE_NO}']")
    link.wait_for(state="visible", timeout=15000)
    assert "案件管理" in link.inner_text()


DRAFT_NO = "MQ-202609-073"


def _seed_draft():
    import db
    conn = db.get_db()
    try:
        items = [{"id": 1, "description": "第一項", "qty": 1, "unit": "台", "unitPrice": 100, "amount": 100},
                 {"id": 2, "description": "第二項", "qty": 1, "unit": "式", "unitPrice": 200, "amount": 200}]
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, "
            "pretax, data_json, created_at, updated_at, deal_tag, quote_date) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (DRAFT_NO, "草稿", "草稿客戶", "草稿專案", 315, 300,
             json.dumps({"quoteNo": DRAFT_NO, "customerName": "草稿客戶", "projectName": "草稿專案",
                         "status": "草稿", "dealTag": "", "items": items,
                         "tot": {"total": 315, "pretax": 300, "directMarginPct": 0,
                                 "netMarginPct": 0}}, ensure_ascii=False),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00", "", "2026-09-01"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_list_filters_survive_returning_to_list(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_qfilter", role="superadmin")
    _seed()
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/quotations.html")
    page.wait_for_function(f"() => {DATA}.quotes.length > 0", timeout=20000)
    page.evaluate(f"{DATA}.search = 'mq-202609'; {DATA}.activeTab = '已送出'; {DATA}.filterMonth = '2026-09'")
    _rendered(page)   # PERF #6：原本固定等 200ms（等 $watch 把篩選條件存起來再離開）
    page.goto(f"{live_server}/pages/quotation-form.html?id={QUOTE_NO}")
    page.goto(f"{live_server}/pages/quotations.html")
    page.wait_for_function(f"() => {DATA}.quotes.length > 0", timeout=20000)
    got = page.evaluate(f"[{DATA}.search, {DATA}.activeTab, {DATA}.filterMonth]")
    assert got == ["mq-202609", "已送出", "2026-09"], got


@pytest.mark.e2e
def test_tab_and_status_labels_explain_themselves(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_qlabel", role="superadmin")
    _seed_draft()
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/quotations.html")
    tab = page.locator("button.filter-tab", has=page.locator("span", has_text="進行中")).first
    tab.wait_for(state="visible", timeout=20000)
    assert "已結案" in (tab.get_attribute("title") or "")
    assert page.locator("button.filter-tab span", has_text="全部(不含未成案)").count() == 0

    page.goto(f"{live_server}/pages/quotation-form.html?id={DRAFT_NO}")
    hint = page.locator("span", has_text="需完成簽核（已送出）才能標記「已成案」").last
    hint.wait_for(state="visible", timeout=20000)


@pytest.mark.e2e
def test_keyboard_insert_and_move_items(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_qkeys", role="superadmin")
    _seed_draft()
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/quotation-form.html?id={DRAFT_NO}")
    page.wait_for_function("() => document.body.innerText.includes('草稿客戶')", timeout=20000)
    rows = page.locator("tbody[x-ref='itemsTbody'] > tr")
    rows.first.wait_for()

    # 單位欄 focus 不清空
    unit0 = rows.nth(0).locator("input[placeholder='單位']")
    unit0.focus()
    assert unit0.input_value() == "台"

    focused_row_js = ("() => [...document.querySelectorAll(\"tbody[x-ref='itemsTbody'] > tr\")]"
                      ".findIndex(r => r.contains(document.activeElement))")

    def _wait_order(expected):
        page.wait_for_function(
            f"() => JSON.stringify({DATA}.q.items.map(i => i.description)) === "
            f"{json.dumps(json.dumps(expected, ensure_ascii=False, separators=(',', ':')), ensure_ascii=False)}",
            timeout=5000)

    # Ctrl+Enter：在第一列下方插入，焦點移到新列
    rows.nth(0).locator("textarea").first.focus()
    page.keyboard.press("Control+Enter")
    _wait_order(["第一項", "", "第二項"])
    page.wait_for_function(f"() => ({focused_row_js})() === 1", timeout=5000)

    # Alt+↓ 兩次：第一項移到最後；焦點跟著那一列走
    rows.nth(0).locator("textarea").first.focus()
    page.keyboard.press("Alt+ArrowDown")
    _wait_order(["", "第一項", "第二項"])
    page.wait_for_function(f"() => ({focused_row_js})() === 1", timeout=5000)
    page.keyboard.press("Alt+ArrowDown")
    _wait_order(["", "第二項", "第一項"])
    page.wait_for_function(f"() => ({focused_row_js})() === 2", timeout=5000)
    page.keyboard.press("Alt+ArrowUp")
    _wait_order(["", "第一項", "第二項"])
