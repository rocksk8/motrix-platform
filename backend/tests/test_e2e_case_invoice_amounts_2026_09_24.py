"""瀏覽器端對端：案件款項明細登錄「發票未稅／稅額」（AC1 使用者選 (a)）。

後端規則（helpers/quotations.py::validate_invoice_amounts）：兩欄一起填或都不填；只填一欄 ⇒ 400；
合計與該期金額不同 ⇒ 只提示不擋。沒有財務檢視權 ⇒ 比照 CM13 不渲染（後端本來就不回這兩鍵）。
觀測點打在資料庫落地值。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_case_concurrent_edit_2026_09_24 import (  # noqa: F401  (live_server 是 fixture)
    DATA_JS, NOTE_INPUT, _login,
)
from tests.test_case_money_mask_2026_09_24 import NO, _db_data, _seed

PRETAX = '[data-testid="invoice-pretax"]'
TAX = '[data-testid="invoice-tax"]'


def _open(browser, base, user):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, base, *user)
    # CU5（2026-09-24）：收款搬到「財務」分頁 ⇒ 以 ?tab=fin 直接開到那一頁
    page.goto(f"{base}/pages/case-management.html?q={NO}&tab=fin")
    page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=10000)
    return page


def _save(page):
    return page.evaluate(f"async () => {{ const c = {DATA_JS}; await c.saveCaseRecord(); return c.saveMsg }}")


@pytest.mark.e2e
def test_financial_user_enters_invoice_amounts_and_they_land(live_server, make_user, e2e_browser):
    u = make_user(username="inv_e2e_sales", role="sales")
    _seed(assigned=[u[0]])
    browser = e2e_browser
    page = _open(browser, live_server, u)
    assert page.locator(PRETAX).nth(0).input_value() == "2940"
    assert page.locator(TAX).nth(0).input_value() == "147"
    page.locator(PRETAX).nth(1).fill("6860")
    page.locator(TAX).nth(1).fill("343")
    assert page.evaluate(f"() => {{ const c = {DATA_JS}; return c.invoiceMismatch(c.paymentItems()[1], 1) }}") == ""
    assert not page.locator('[data-testid="invoice-mismatch"]').nth(1).is_visible()
    assert "已儲存" in _save(page)
    items = _db_data()["caseRecord"]["payment"]["items"]
    assert (items[1]["invoicePretax"], items[1]["invoiceTax"]) == (6860, 343)
    assert (items[0]["invoicePretax"], items[0]["invoiceTax"]) == (2940, 147)


@pytest.mark.e2e
def test_half_filled_and_mismatch_hints(live_server, make_user, e2e_browser):
    u = make_user(username="inv_e2e_sales2", role="sales")
    _seed(assigned=[u[0]])
    browser = e2e_browser
    page = _open(browser, live_server, u)
    page.locator(PRETAX).nth(1).fill("6000")
    half = page.locator('[data-testid="invoice-half"]').nth(1)
    half.wait_for(state="visible", timeout=5000)
    assert "一起填寫" in half.inner_text()
    page.locator(TAX).nth(1).fill("300")
    half.wait_for(state="hidden", timeout=5000)
    mism = page.locator('[data-testid="invoice-mismatch"]').nth(1)
    mism.wait_for(state="visible", timeout=5000)
    assert "6,300" in mism.inner_text() and "7,203" in mism.inner_text()
    assert "已儲存" in _save(page), "合計不符只提示，不擋存檔"
    items = _db_data()["caseRecord"]["payment"]["items"]
    assert (items[1]["invoicePretax"], items[1]["invoiceTax"]) == (6000, 300)


@pytest.mark.e2e
def test_masked_user_has_no_invoice_amount_inputs_and_values_survive(live_server, make_user, e2e_browser):
    u = make_user(username="inv_e2e_eng", role="engineer")
    _seed(assigned=[u[0]])
    browser = e2e_browser
    page = _open(browser, live_server, u)
    assert page.evaluate(f"() => {DATA_JS}.moneyMasked()") is True
    assert page.locator(PRETAX).count() == 0 and page.locator(TAX).count() == 0
    page.locator(NOTE_INPUT).nth(1).fill("工程師備註")
    assert "已儲存" in _save(page)
    items = _db_data()["caseRecord"]["payment"]["items"]
    assert (items[0]["invoicePretax"], items[0]["invoiceTax"]) == (2940, 147)


@pytest.mark.e2e
def test_zero_tax_counts_as_filled(live_server, make_user, e2e_browser):
    """零稅率／免稅的發票稅額就是 0：0 是「有填」，不是空（不可以跳出「要一起填寫」）。"""
    u = make_user(username="inv_e2e_sales3", role="sales")
    _seed(assigned=[u[0]])
    browser = e2e_browser
    page = _open(browser, live_server, u)
    page.locator(PRETAX).nth(1).fill("7203")
    page.locator(TAX).nth(1).fill("0")
    assert page.evaluate(
        f"() => {{ const c = {DATA_JS}; return c.invoiceHalfFilled(c.paymentItems()[1]) }}") is False
    assert "已儲存" in _save(page)
    items = _db_data()["caseRecord"]["payment"]["items"]
    assert (items[1]["invoicePretax"], items[1]["invoiceTax"]) == (7203, 0)
