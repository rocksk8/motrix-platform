"""瀏覽器端對端：營運報表的口徑切換與待補登清單；案件頁四處補登欄位（階段比例、派工／額外支出／叫料發票日）。

觀測點打在資料庫落地值（補登欄位）與後端回應驅動的畫面（報表），不打在頁面寫死的文字。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_material_orders_2026_09_11 import _login  # noqa: F401
from tests.test_report_recognition_basis_2026_09_24 import _case, _stage, _dispatch, _db

RPT = "Alpine.$data(document.querySelector('[x-data]'))"


#: 更正留著（2026-09-24）：原本存檔後「輪詢資料庫 50 次 × 100ms」＝5 秒牆鐘，並行全量下偶發紅（階段比例那一題，
#: 單跑與 -n 6 重現三輪皆綠，沒有抓到錯誤）。改成**等那一支存檔請求回應**再斷言資料庫——事件為準、不量快慢；
#: 並把送出的內容印在失敗訊息裡：分得出「慢」與「值在送出前被重繪洗掉」（後者是產品競態）。
_SAVE_WAIT_MS = 30000


def _sends(resp, key, value):
    """這一個回應對應的請求有沒有送出 key=value。

    ☠️ 只比網址會接錯回應：Playwright 的 fill() 在日期欄上**本身就會觸發 change**，
    再 dispatch_event("change") ⇒ 同一格送兩次；晚到的那一次會被下一格的等待接走，
    題目就在下一格的請求還沒完成時去讀資料庫（實測：付款日的等待接到 {"invoiceDate":...}）。
    """
    try:
        body = json.loads(resp.request.post_data or "{}")
    except (TypeError, ValueError):
        return False
    return isinstance(body, dict) and body.get(key) == value


def _saved(resp_info, what):
    r = resp_info.value
    body = r.request.post_data or ""
    assert r.ok, "%s 存檔失敗：HTTP %s，送出 %s" % (what, r.status, body[:200])
    return body


def _page(browser, base, user):
    page = browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, base, *user)
    return page


def _one(sql, args=()):
    conn = _db()
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


@pytest.mark.e2e
def test_extra_expense_dates_after_approval_land(live_server, make_user, seed_extra_expense, e2e_browser):
    _case("MQ-RBE-020")
    eid = seed_extra_expense("MQ-RBE-020", total_cost=800, description="吊車", expense_date="2026-03-02",
                             status="已核准")
    u = make_user(username="rbe_sa3", role="superadmin")
    browser = e2e_browser
    page = _page(browser, live_server, u)
    page.goto(f"{live_server}/pages/case-management.html?q=MQ-RBE-020")
    page.wait_for_selector(".cm-tab:has-text('額外支出')", timeout=20000)
    page.click(".cm-tab:has-text('額外支出')")
    inv = page.locator('[data-testid="xe-invoice-date"]').first
    inv.wait_for(state="visible", timeout=20000)
    inv.fill("2026-04-04")
    with page.expect_response(lambda r: r.url.endswith("/dates") and _sends(r, "invoiceDate", "2026-04-04"), timeout=_SAVE_WAIT_MS) as resp:
        inv.dispatch_event("change")
    _saved(resp, "額外支出發票日期")
    paid = page.locator('[data-testid="xe-paid-date"]').first
    paid.fill("2026-04-10")
    with page.expect_response(lambda r: r.url.endswith("/dates") and _sends(r, "paidDate", "2026-04-10"), timeout=_SAVE_WAIT_MS) as resp:
        paid.dispatch_event("change")
    _b2 = _saved(resp, "額外支出付款日")
    row = (_one("SELECT invoice_date FROM case_extra_expenses WHERE id=?", (eid,)),
           _one("SELECT paid_date FROM case_extra_expenses WHERE id=?", (eid,)))
    assert row == ("2026-04-04", "2026-04-10"), "已核准的支出也要登得進去；付款日送出：%s" % _b2


@pytest.mark.e2e
def test_material_invoice_date_survives_save_and_reload(live_server, make_user, e2e_browser):
    mo = {"itemId": "m1", "itemName": "線材", "quantity": 1, "unit": "捲", "unitPrice": 100,
          "totalPrice": 100, "paidStatus": "pending", "paidAmount": 0, "paidDate": None, "notes": ""}
    _case("MQ-RBE-030", data={"caseRecord": {"materialOrders": [mo]}})
    u = make_user(username="rbe_sa4", role="superadmin")
    browser = e2e_browser
    page = _page(browser, live_server, u)
    page.goto(f"{live_server}/pages/case-management.html?q=MQ-RBE-030")
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    inv = page.locator('[data-testid="mo-invoice-date"]').first
    inv.wait_for(state="visible", timeout=20000)
    inv.fill("2026-04-20")
    with page.expect_response(lambda r: "/invoice-date" in r.url and _sends(r, "invoiceDate", "2026-04-20"), timeout=_SAVE_WAIT_MS) as resp:
        inv.dispatch_event("change")   # 發票日期改了就直接存（專用端點），不必按「儲存叫料」
    _saved(resp, "叫料發票日期")

    def stored():
        d = json.loads(_one("SELECT data_json FROM quotations WHERE quote_no='MQ-RBE-030'"))
        return d["caseRecord"]["materialOrders"][0].get("invoiceDate")
    assert stored() == "2026-04-20"
    # 改別的欄位再存一次：整份覆寫的端點，發票日期不可以被抹掉
    page.locator('#fin-material-orders input[placeholder="備註（供應商、單號…）"]').first.fill("改備註")
    with page.expect_response(lambda r: r.url.endswith("/material-orders") and r.request.method == "PATCH",
                              timeout=_SAVE_WAIT_MS) as resp:
        page.click('#fin-material-orders button:has-text("儲存叫料")')
    _saved(resp, "儲存叫料")
    d = json.loads(_one("SELECT data_json FROM quotations WHERE quote_no='MQ-RBE-030'"))
    assert d["caseRecord"]["materialOrders"][0].get("notes") == "改備註"
    assert stored() == "2026-04-20"


@pytest.mark.e2e
def test_material_invoice_date_on_a_closed_case_lands_without_pressing_save(live_server, make_user, e2e_browser):
    mo = {"itemId": "m9", "itemName": "線材", "quantity": 1, "unit": "捲", "unitPrice": 100,
          "totalPrice": 100, "paidStatus": "paid", "paidAmount": 100, "paidDate": "2026-03-09", "notes": ""}
    _case("MQ-RBE-031", deal="已結案", data={"caseRecord": {"materialOrders": [mo]}})
    u = make_user(username="rbe_sa5", role="superadmin")
    browser = e2e_browser
    page = _page(browser, live_server, u)
    page.goto(f"{live_server}/pages/case-management.html?q=MQ-RBE-031")
    page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
    page.click('.cm-tab:has-text("財務")')
    inv = page.locator('[data-testid="mo-invoice-date"]').first
    inv.wait_for(state="visible", timeout=20000)
    assert inv.is_enabled(), "已結案也要能登發票日期"
    inv.fill("2026-05-05")
    with page.expect_response(lambda r: "/invoice-date" in r.url and _sends(r, "invoiceDate", "2026-05-05"), timeout=_SAVE_WAIT_MS) as resp:
        inv.dispatch_event("change")
    _saved(resp, "已結案叫料發票日期")

    def stored():
        d = json.loads(_one("SELECT data_json FROM quotations WHERE quote_no='MQ-RBE-031'"))
        return d["caseRecord"]["materialOrders"][0].get("invoiceDate")
    assert stored() == "2026-05-05"
    page.locator('[data-testid="mo-msg-readonly"]').wait_for(state="visible", timeout=5000)
