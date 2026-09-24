"""瀏覽器端對端：沒有財務檢視權的帳號在案件頁看不到金額、存檔不會把金額蓋成空值（CM13）。

API 層見 test_case_money_mask_2026_09_24.py。這裡驗真的頁面：engineer 打開案件、改收款備註、
按百分比欄位不存在、存檔後資料庫的金額不變。觀測點打在資料庫落地值。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_case_concurrent_edit_2026_09_24 import (  # noqa: F401  (live_server 是 fixture)
    DATA_JS, NOTE_INPUT, _login, live_server,
)
from tests.test_case_money_mask_2026_09_24 import NO, _db_data, _seed


def _open(browser, base, user):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, base, *user)
    # CU5（2026-09-24）：收款搬到「財務」分頁 ⇒ 以 ?tab=fin 直接開到那一頁
    page.goto(f"{base}/pages/case-management.html?q={NO}&tab=fin")
    page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=10000)
    return page


@pytest.mark.e2e
def test_engineer_edits_payment_note_and_amounts_survive(live_server, make_user):
    u = make_user(username="mk_e2e_eng", role="engineer")
    _seed(assigned=[u[0]])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u)
            assert page.evaluate(f"() => {DATA_JS}.moneyMasked()") is True
            assert page.locator("input.fi--pct:visible").count() == 0, "看不到金額的人不該有百分比輸入"
            assert not page.locator("button:has-text('平衡尾款')").first.is_visible()
            # 換算函式本身也要擋（雙保險）：直接呼叫也不可以在頁面上寫出 amount／pct
            touched = page.evaluate(f"""() => {{ const c = {DATA_JS}; const it = c.cr.caseRecord.payment.items
              c.onPctChange(0); c.balanceLastPayment(); c.onAmountWithTaxChange(0, 100); c.onAmountPretaxChange(0, 100)
              c._setItemAmount(it, 0, 100); c._syncLast(it)
              return it.some(i => 'amount' in i || 'pct' in i) }}""")
            assert touched is False
            note = page.locator(NOTE_INPUT).nth(1)
            note.fill("工程師備註")
            msg = page.evaluate(f"async () => {{ const c = {DATA_JS}; await c.saveCaseRecord(); return c.saveMsg }}")
            assert "已儲存" in msg, msg
            items = _db_data()["caseRecord"]["payment"]["items"]
            assert items[1]["note"] == "工程師備註"
            assert [i["amount"] for i in items] == [3087, 7203]
            assert [i["pct"] for i in items] == [30, 70]
            assert items[0]["actualAmount"] == 3087 and items[0]["feeAmount"] == 15
        finally:
            browser.close()


@pytest.mark.e2e
def test_financial_user_still_sees_amount_inputs(live_server, make_user):
    u = make_user(username="mk_e2e_sales", role="sales")
    _seed(assigned=[u[0]])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u)
            assert page.evaluate(f"() => {DATA_JS}.moneyMasked()") is False
            assert page.locator("input.fi--pct:visible").count() == 2
        finally:
            browser.close()
