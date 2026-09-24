"""瀏覽器端對端：案件頁標頭整理＋收款搬到財務分頁（2026-09-24 使用者表單 CU5）。

- 第一列＝客戶名＋狀態；主鈕只留「儲存」，其餘（產生專案報告／解鎖／完結案）收進「更多」
- 「專案資訊」子分頁改名「成員」
- 收款（款項明細）在「財務」分頁；看得到案件的人都看得到（沒有財務檢視權照 CM13 遮蔽金額），
  財務分頁其餘區塊（應收應付總覽）仍只給有財務檢視權的人
- 案件健康總覽「收款」關卡的「前往」指到財務分頁
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_case_concurrent_edit_2026_09_24 import (  # noqa: F401  (live_server 是 fixture)
    DATA_JS, NOTE_INPUT, _login, live_server,
)
from tests.test_case_money_mask_2026_09_24 import NO, _seed


def _open(browser, base, user, tab=""):
    page = browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, base, *user)
    page.goto(f"{base}/pages/case-management.html?q={NO}" + (f"&tab={tab}" if tab else ""))
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    return page


@pytest.mark.e2e
def test_header_first_row_is_customer_and_status_and_only_save_is_a_main_button(live_server, make_user):
    u = make_user(username="cu5_sa", role="superadmin")
    _seed(assigned=[u[0]])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u)
            row1 = page.locator(".cm-header__row1")
            assert row1.locator('[data-testid="cm-header-customer"]').inner_text().strip() != ""
            assert row1.locator(".deal-tag-badge").count() == 1, "狀態在第一列"
            assert row1.locator(".cm-header__no").count() == 0, "單號移到第二列"
            report = page.locator('button:has-text("產生專案報告")')
            close = page.locator('.cm-header button.btn-close-case')
            assert not report.is_visible() and not close.is_visible(), "次要動作收進「更多」"
            assert page.locator(".cm-header .btn-save").is_visible()
            page.click('[data-testid="cm-more"]')
            report.wait_for(state="visible", timeout=5000)
            assert close.is_visible(), "最高管理者在「更多」裡看得到完結案"
            page.keyboard.press("Escape")
            report.wait_for(state="hidden", timeout=5000)

            page.click('.cm-tab:has-text("執行管理")')
            assert page.locator('.cm-tab:text-is("成員")').is_visible()
            assert page.locator('.cm-tab:text-is("專案資訊")').count() == 0
        finally:
            browser.close()


@pytest.mark.e2e
def test_payment_lives_in_the_finance_tab(live_server, make_user):
    u = make_user(username="cu5_sales", role="sales")
    _seed(assigned=[u[0]])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u)
            page.locator('.cm-tab:has-text("案件資訊")').wait_for(timeout=10000)
            assert page.locator(NOTE_INPUT).first.is_hidden(), "案件資訊分頁不再有收款"
            page.click('.cm-tab:has-text("財務")')
            page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=10000)
            assert page.locator("#fin-ar-ap-overview").is_visible(), "有財務檢視權的人照樣看得到應收應付總覽"
            assert page.evaluate(f"() => {DATA_JS}._gateTab({{key: 'payment'}})") == "fin"
        finally:
            browser.close()


@pytest.mark.e2e
def test_member_without_financial_view_still_reaches_payment_but_not_the_rest(live_server, make_user):
    u = make_user(username="cu5_eng", role="engineer")
    _seed(assigned=[u[0]])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u, tab="fin")
            page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=20000)
            assert page.evaluate(f"() => {DATA_JS}.moneyMasked()") is True
            assert page.locator("#fin-ar-ap-overview").count() == 0 or page.locator("#fin-ar-ap-overview").is_hidden()
            assert page.evaluate(f"() => {DATA_JS}._gateTab({{key: 'payment'}})") == "fin"
            assert page.evaluate(f"() => {DATA_JS}._gateTab({{key: 'settlement'}})") == "biz", \
                "精算不給沒有財務檢視權的人 ⇒ 退回案件資訊"
        finally:
            browser.close()


# ══════════════════════════════════════════════════════════════════════
# CU8：手機／窄螢幕不溢出（款項明細、拜訪紀錄兩欄；分頁列捲動提示）
# ══════════════════════════════════════════════════════════════════════

_OVERFLOW_JS = """(sel) => [...document.querySelectorAll(sel)]
  .filter(el => el.offsetParent !== null)
  .map(el => [el.scrollWidth, el.clientWidth])"""


@pytest.mark.e2e
def test_narrow_screen_payment_rows_do_not_overflow_and_tabs_hint_shows(live_server, make_user):
    u = make_user(username="cu8_sales", role="sales")
    _seed(assigned=[u[0]])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
            page.on("dialog", lambda d: d.accept())
            _login(page, live_server, *u)
            page.goto(f"{live_server}/pages/case-management.html?q={NO}&tab=fin")
            page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=20000)
            grids = page.evaluate(_OVERFLOW_JS, ".pay-grid")
            assert grids, "款項明細的欄位列要在畫面上"
            assert all(sw <= cw + 1 for sw, cw in grids), "款項明細欄位列在窄螢幕溢出：%r" % grids
            cols = page.evaluate("() => getComputedStyle(document.querySelector('.pay-grid')).gridTemplateColumns")
            assert len(cols.split()) == 2, "窄螢幕款項明細改兩欄：%s" % cols
            assert page.locator('[data-testid="cm-tabs-hint"]').is_visible()
        finally:
            browser.close()


@pytest.mark.e2e
def test_wide_screen_keeps_the_original_layout(live_server, make_user):
    u = make_user(username="cu8_sales2", role="sales")
    _seed(assigned=[u[0]])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = _open(browser, live_server, u, tab="fin")
            page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=20000)
            cols = page.evaluate("() => getComputedStyle(document.querySelector('.pay-grid')).gridTemplateColumns")
            assert len(cols.split()) == 5, cols
            assert page.locator('[data-testid="cm-tabs-hint"]').is_hidden()
        finally:
            browser.close()
