"""瀏覽器端對端：M05 應收應付不在時，別人的頁面要說出原因（2026-09-26 M05 搬遷，PLAYBOOK §B-4）。

取用方這一側（M05 不在也成立）；以 page.route 讓 M05 的端點回 404 "Not Found"（＝路由不存在）模擬。
① M01 案件頁財務分頁：開票申請／請款單 ⇒ 顯示「應收應付模組未安裝…」，兩個申請按鈕收起（不是空清單＋點了跳 Not Found）
② M08 營運報表：現金口徑收入 ⇒ 顯示 incomeNotice（不是 NT$ 0）；財務快照的應收應付 ⇒ 顯示原因（不是 NT$ 0）
   報表的 JSON 用 page.route 回一份帶 incomeNotice 的內容（後端那一半由 tests/platform/test_receivables_absent.py 驗）
正對照：端點正常回應時，兩頁都不出現這些提示。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import contextlib
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_case_concurrent_edit_2026_09_24 import DATA_JS, _login  # noqa: F401,E402
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

NO = "MQ-ARAPABS-001"


def _seed():
    import db
    cr = {"payment": {"items": [{"id": 1, "type": "訂金款", "pct": 100, "amount": 100, "received": False}]},
          "materials": []}
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "無應收客", "無應收案", 100, 95,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False), now, now, "已成案"))
        conn.commit()
    finally:
        conn.close()


@contextlib.contextmanager
def _page(browser):
    """每題自己的 context，結束一定關（稽核 D M5-M2：沒關 context、又用了 route.fetch ⇒ 同一 worker 的下一題偶發
    TargetClosedError）。關閉前先 unroute_all(ignoreErrors)，讓還在飛的 route 處理器不會對已關的 context 回應。"""
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        yield page
    finally:
        try:
            page.unroute_all(behavior="ignoreErrors")
        finally:
            ctx.close()


def _not_found(route):
    route.fulfill(status=404, body='{"detail":"Not Found"}', content_type="application/json")


def _open_fin(page, live_server):
    page.goto(f"{live_server}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    page.evaluate(f"() => {{ {DATA_JS}.activeTab = 'fin' }}")
    # 終點：兩支清單都載完（loading 旗標解除），不是「提示出現」（那會讓正對照假綠）
    page.wait_for_function(f"() => !{DATA_JS}.invoiceVouchersLoading && !{DATA_JS}.paymentRequestsLoading", timeout=20000)


@pytest.mark.e2e
def test_case_page_says_arap_is_missing_and_hides_the_request_buttons(live_server, make_user, e2e_browser):
    u = make_user(username="arapabs_admin", role="admin")
    _seed()
    with _page(e2e_browser) as page:
        page.route("**/api/invoice-vouchers**", _not_found)
        page.route("**/api/payment-requests**", _not_found)
        _login(page, live_server, *u)
        _open_fin(page, live_server)
        note = page.locator("[data-testid=arap-missing]")
        assert note.is_visible() and "應收應付模組未安裝" in note.inner_text()
        assert page.locator("button:text-is('申請開立發票')").is_hidden()
        assert page.locator("button:text-is('申請請款單')").is_hidden()


@pytest.mark.e2e
def test_case_page_positive_control_no_notice_when_endpoints_answer(live_server, make_user, e2e_browser):
    u = make_user(username="arapok_admin", role="admin")
    _seed()
    with _page(e2e_browser) as page:
        page.route("**/api/invoice-vouchers?quote_no=**", lambda r: r.fulfill(status=200, body="[]", content_type="application/json"))
        page.route("**/api/payment-requests?quote_no=**", lambda r: r.fulfill(status=200, body="[]", content_type="application/json"))
        _login(page, live_server, *u)
        _open_fin(page, live_server)
        assert page.locator("[data-testid=arap-missing]").is_hidden()
        assert page.locator("button:text-is('申請開立發票')").is_visible()


@pytest.mark.e2e
def test_reports_page_says_income_and_cashier_queues_are_missing(live_server, make_user, e2e_browser):
    from core import source_tree
    if not source_tree.module_installed("modules/analytics/"):
        pytest.skip("M08 營運分析不在這個安裝包 ⇒ 報表頁本來就不在（PLAYBOOK §B-11）")
    u = make_user(username="arapabs_sa", role="superadmin")
    with _page(e2e_browser) as page:
        page.route("**/api/cashier/**", _not_found)

        def _expenses(route):
            resp = route.fetch()
            data = resp.json()
            data["incomeNotice"] = "應收應付模組未安裝：收款與銷項發票資料不提供（現金口徑收入、銷項發票匯出需要它）"
            route.fulfill(response=resp, body=json.dumps(data, ensure_ascii=False), content_type="application/json")
        page.route("**/api/reports/expenses-monthly**", _expenses)
        _login(page, live_server, *u)
        page.goto(f"{live_server}/pages/reports.html")
        page.wait_for_selector(".period-bar", timeout=20000)
        page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).setBasis('cash')")
        page.wait_for_function("() => { const d = Alpine.$data(document.querySelector('[x-data]')); return d.expensesData && d.incomeNotice }",
                               timeout=20000)
        page.evaluate("() => { Alpine.$data(document.querySelector('[x-data]')).activeTab = 'expenses' }")   # 收支分頁
        note = page.locator("[data-testid=income-unavailable]")
        note.wait_for(state="visible", timeout=10000)
        assert "應收應付模組未安裝" in note.inner_text()
        d = "Alpine.$data(document.querySelector('[x-data]'))"
        page.evaluate(f"() => {d}._loadPayableSnapshot()")
        page.wait_for_function(f"() => {d}.payableSnapLoaded", timeout=20000)
        assert page.evaluate(f"() => {d}.payableKnown") is False
        assert page.evaluate(f"() => {d}.payableSnapMissing") == "應收應付模組未安裝"


@pytest.mark.e2e
def test_reports_snapshot_shows_the_payable_queues_own_reason(live_server, make_user, e2e_browser):
    """只有待付款 404 並帶說明（M04 外包工班不在 ⇒ 依設計 404＋CONTRACTOR_MISSING），待收款照常 ⇒
    快照顯示那一句、不畫 NT$ 0（兩支分開驗，否則任一支的處理都會讓另一支的缺陷看不見）。"""
    from core import source_tree
    if not source_tree.module_installed("modules/analytics/"):
        pytest.skip("M08 營運分析不在這個安裝包 ⇒ 報表頁本來就不在（PLAYBOOK §B-11）")
    reason = "外包工班模組未安裝：出納頁不顯示承攬商匯款"
    u = make_user(username="arapabs_sa2", role="superadmin")
    with _page(e2e_browser) as page:
        page.route("**/api/cashier/payable-queue**", lambda r: r.fulfill(
            status=404, body=json.dumps({"detail": reason}, ensure_ascii=False), content_type="application/json"))
        _login(page, live_server, *u)
        page.goto(f"{live_server}/pages/reports.html")
        page.wait_for_selector(".period-bar", timeout=20000)
        d = "Alpine.$data(document.querySelector('[x-data]'))"
        page.evaluate(f"() => {{ {d}.payableSnapLoaded = false; {d}.payableSnapMissing = ''; return {d}._loadPayableSnapshot() }}")
        page.wait_for_function(f"() => {d}.payableSnapLoaded", timeout=20000)
        assert page.evaluate(f"() => {d}.payableSnapMissing") == reason
        assert page.evaluate(f"() => {d}.payableKnown") is False


@pytest.mark.e2e
def test_reports_cashier_tab_entry_also_records_the_reason(live_server, make_user, e2e_browser):
    """稽核 D M5-S1：從 reports.html?tab=cashier 進來 ⇒ 出納頁籤先載（cashierLoaded），快照略過自己的載入；
    那條路徑的 404 也要記原因，否則快照畫出 NT$ 0。"""
    from core import source_tree
    if not source_tree.module_installed("modules/analytics/"):
        pytest.skip("M08 營運分析不在這個安裝包 ⇒ 報表頁本來就不在（PLAYBOOK §B-11）")
    u = make_user(username="arapabs_sa3", role="superadmin")
    with _page(e2e_browser) as page:
        page.route("**/api/cashier/payable-queue**", _not_found)
        _login(page, live_server, *u)
        page.goto(f"{live_server}/pages/reports.html?tab=cashier")
        d = "Alpine.$data(document.querySelector('[x-data]'))"
        page.wait_for_function(f"() => {d} && {d}.cashierLoaded", timeout=20000)
        assert page.evaluate(f"() => {d}.payableSnapMissing") == "應收應付模組未安裝"
        assert page.evaluate(f"() => {d}.payableKnown") is False
