"""瀏覽器端對端：營運報表的口徑切換與待補登清單；案件頁四處補登欄位（階段比例、派工／額外支出／叫料發票日）。

觀測點打在資料庫落地值（補登欄位）與後端回應驅動的畫面（報表），不打在頁面寫死的文字。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_material_orders_2026_09_11 import live_server, _login  # noqa: F401
from tests.test_report_recognition_basis_2026_09_24 import _case, _stage, _dispatch, _db

RPT = "Alpine.$data(document.querySelector('[x-data]'))"


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
def test_report_shows_basis_note_and_flag_list_and_switches_basis(live_server, make_user):
    _case("MQ-RBE-001")
    _dispatch("MQ-RBE-001", dispatch_date="2026-03-15")
    u = make_user(username="rbe_sa", role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _page(browser, live_server, u)
            page.goto(f"{live_server}/pages/reports.html")
            page.wait_for_function(f"() => {RPT} && typeof {RPT}.showExpensesTab === 'function'", timeout=20000)
            page.evaluate(f"() => {{ const c = {RPT}; c.expensesYear = 2026; c.showExpensesTab() }}")
            note = page.locator('[data-testid="basis-note"]')
            note.wait_for(state="visible", timeout=20000)
            assert "權責" in note.inner_text()
            flag = page.locator('[data-testid="flag-dispatch_no_invoice"]')
            flag.wait_for(state="visible", timeout=10000)
            flag.click()
            link = page.locator('[data-testid="recognition-flags"] a:has-text("MQ-RBE-001")')
            link.wait_for(state="visible", timeout=5000)
            assert link.get_attribute("href") == "case-management.html?q=MQ-RBE-001"

            page.click('[data-testid="basis-cash"]')
            page.wait_for_function(f"() => ({RPT}.expensesData || {{}}).basis === 'cash'", timeout=20000)
            assert "現金" in note.inner_text()
            assert page.evaluate(f"() => {RPT}.incomeTaxLabel") == "含稅"
        finally:
            browser.close()


@pytest.mark.e2e
def test_case_page_stage_ratio_and_dispatch_invoice_date_land(live_server, make_user):
    _case("MQ-RBE-010")
    sid = _stage("MQ-RBE-010", "施工", done=True, done_at="2026-03-01")
    # 頁面讀 data_json 的階段鏡像：造資料要走正式那一支同步，不然頁面會自己補預設階段
    from routers.quotations import _sync_stages_to_json
    conn = _db()
    try:
        _sync_stages_to_json(conn, "MQ-RBE-010")
        conn.commit()
    finally:
        conn.close()
    did = _dispatch("MQ-RBE-010")
    u = make_user(username="rbe_sa2", role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _page(browser, live_server, u)
            page.goto(f"{live_server}/pages/case-management.html?q=MQ-RBE-010")
            page.wait_for_selector('.cm-tab:has-text("執行管理")', timeout=20000)
            page.click('.cm-tab:has-text("執行管理")')
            ratio = page.locator('[data-testid="stage-ratio"]').first
            ratio.wait_for(state="visible", timeout=20000)
            ratio.fill("60")
            ratio.dispatch_event("change")
            for _ in range(50):
                if _one("SELECT ratio_bp FROM case_stages WHERE id=?", (sid,)) == 6000:
                    break
                page.wait_for_timeout(100)
            assert _one("SELECT ratio_bp FROM case_stages WHERE id=?", (sid,)) == 6000
            summary = page.locator('[data-testid="stage-ratio-summary"]')
            page.wait_for_function(
                "() => (document.querySelector('[data-testid=\"stage-ratio-summary\"]').innerText || '').includes('60')",
                timeout=5000)
            assert "不等於 100%" in summary.inner_text()

            page.click('.cm-tab:has-text("承攬商")')
            inv = page.locator('[data-testid="dispatch-invoice-date"]').first
            inv.wait_for(state="visible", timeout=20000)
            inv.fill("2026-05-03")
            inv.dispatch_event("change")
            for _ in range(50):
                if _one("SELECT invoice_date FROM contractor_dispatches WHERE id=?", (did,)) == "2026-05-03":
                    break
                page.wait_for_timeout(100)
            assert _one("SELECT invoice_date FROM contractor_dispatches WHERE id=?", (did,)) == "2026-05-03"
        finally:
            browser.close()


@pytest.mark.e2e
def test_extra_expense_dates_after_approval_land(live_server, make_user, seed_extra_expense):
    _case("MQ-RBE-020")
    eid = seed_extra_expense("MQ-RBE-020", total_cost=800, description="吊車", expense_date="2026-03-02",
                             status="已核准")
    u = make_user(username="rbe_sa3", role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _page(browser, live_server, u)
            page.goto(f"{live_server}/pages/case-management.html?q=MQ-RBE-020")
            page.wait_for_selector(".cm-tab:has-text('額外支出')", timeout=20000)
            page.click(".cm-tab:has-text('額外支出')")
            inv = page.locator('[data-testid="xe-invoice-date"]').first
            inv.wait_for(state="visible", timeout=20000)
            inv.fill("2026-04-04")
            inv.dispatch_event("change")
            paid = page.locator('[data-testid="xe-paid-date"]').first
            paid.fill("2026-04-10")
            paid.dispatch_event("change")
            for _ in range(50):
                row = (_one("SELECT invoice_date FROM case_extra_expenses WHERE id=?", (eid,)),
                       _one("SELECT paid_date FROM case_extra_expenses WHERE id=?", (eid,)))
                if row == ("2026-04-04", "2026-04-10"):
                    break
                page.wait_for_timeout(100)
            assert row == ("2026-04-04", "2026-04-10"), "已核准的支出也要登得進去"
        finally:
            browser.close()


@pytest.mark.e2e
def test_material_invoice_date_survives_save_and_reload(live_server, make_user):
    mo = {"itemId": "m1", "itemName": "線材", "quantity": 1, "unit": "捲", "unitPrice": 100,
          "totalPrice": 100, "paidStatus": "pending", "paidAmount": 0, "paidDate": None, "notes": ""}
    _case("MQ-RBE-030", data={"caseRecord": {"materialOrders": [mo]}})
    u = make_user(username="rbe_sa4", role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _page(browser, live_server, u)
            page.goto(f"{live_server}/pages/case-management.html?q=MQ-RBE-030")
            page.wait_for_selector('.cm-tab:has-text("財務")', timeout=20000)
            page.click('.cm-tab:has-text("財務")')
            inv = page.locator('[data-testid="mo-invoice-date"]').first
            inv.wait_for(state="visible", timeout=20000)
            inv.fill("2026-04-20")
            page.click('#fin-material-orders button:has-text("儲存叫料")')

            def stored():
                d = json.loads(_one("SELECT data_json FROM quotations WHERE quote_no='MQ-RBE-030'"))
                return d["caseRecord"]["materialOrders"][0].get("invoiceDate")
            for _ in range(50):
                if stored() == "2026-04-20":
                    break
                page.wait_for_timeout(100)
            assert stored() == "2026-04-20"
            # 改別的欄位再存一次：整份覆寫的端點，發票日期不可以被抹掉
            page.locator('#fin-material-orders input[placeholder="備註（供應商、單號…）"]').first.fill("改備註")
            page.click('#fin-material-orders button:has-text("儲存叫料")')
            for _ in range(50):
                d = json.loads(_one("SELECT data_json FROM quotations WHERE quote_no='MQ-RBE-030'"))
                if d["caseRecord"]["materialOrders"][0].get("notes") == "改備註":
                    break
                page.wait_for_timeout(100)
            assert stored() == "2026-04-20"
        finally:
            browser.close()
