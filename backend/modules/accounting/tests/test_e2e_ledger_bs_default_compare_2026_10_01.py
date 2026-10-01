# -*- coding: utf-8 -*-
"""瀏覽器端對端：財務報表一進頁面就有資料、且比較欄位已有預設（使用者 2026-10-01）：
資產負債表 ＝ 截至今天，比較 ＝ 上一年度期末（去年 12/31）；綜合損益表 ＝ 本年起迄今，比較 ＝ 去年同期間。
不按查詢、不填比較就要看到兩欄數字；總計／小計列的比較欄也要有數字（原本空白）；使用者改或清掉比較以使用者的為準，重新查詢不會被填回。終點狀態驗 DOM。"""
from datetime import date

import pytest

pytest.importorskip("playwright.sync_api")

from modules.accounting.tests.test_e2e_ledger_p1_pages_2026_09_30 import _open, _seed  # noqa: E402

Y = date.today().year
PRIOR_END = "%d-12-31" % (Y - 1)
TOT = "[data-testid=st-bs-total-assets] td.num"


def _book():
    _seed("%d-06-01" % (Y - 1), [("1191", 10500, 0), ("4111", 0, 10000), ("2204", 0, 500)])      # 去年：資產 10,500
    _seed("%d-01-01" % Y, [("1113", 5000, 0), ("4111", 0, 5000)])                                  # 今年：再 +5,000 ⇒ 今天資產 15,500


def _enter(e2e_browser, live_server, user, pw):
    page = e2e_browser.new_page()
    _open(page, live_server, user, pw, "ledger-statements.html")
    page.wait_for_selector("[data-testid=st-as-of]")
    return page


def _cells(page):
    return page.evaluate("() => Array.from(document.querySelectorAll('[data-testid=st-bs-total-assets] td.num')).filter(e => e.offsetParent !== null).map(e => e.textContent.trim())")


@pytest.mark.e2e
def test_entry_shows_both_columns_with_totals_compare_without_any_click(live_server, make_user, e2e_browser):
    user, pw = make_user(username="bsd_entry", role="superadmin")
    _book()
    page = _enter(e2e_browser, live_server, user, pw)
    assert page.input_value("[data-testid=st-compare-as-of]") == PRIOR_END                 # 比較欄位預設＝上一年度期末
    page.wait_for_function("() => { const c = Array.from(document.querySelectorAll('[data-testid=st-bs-total-assets] td.num')).filter(e => e.offsetParent !== null).map(e => e.textContent.trim()); return c.length === 2 && c[0] === '15,500' && c[1] === '10,500' }")
    assert _cells(page) == ["15,500", "10,500"]                                              # 總計列：本期與比較期都有數字（修正前比較欄是空白）
    for tid in ("st-bs-total-liab", "st-bs-total-eq", "st-bs-total-le"):
        assert page.evaluate("(t) => Array.from(document.querySelectorAll('[data-testid=' + t + '] td.num')).filter(e => e.offsetParent !== null).every(e => e.textContent.trim() !== '')", tid)
    assert page.locator("[data-testid=st-bs-line-BS_CA_AR] td.num").nth(1).inner_text().strip() == "10,500"   # 科目列的比較欄也在


@pytest.mark.e2e
def test_clearing_the_comparison_gives_a_single_column_and_is_not_refilled(live_server, make_user, e2e_browser):
    user, pw = make_user(username="bsd_clear", role="superadmin")
    _book()
    page = _enter(e2e_browser, live_server, user, pw)
    page.wait_for_function("() => Array.from(document.querySelectorAll('[data-testid=st-bs-total-assets] td.num')).filter(e => e.offsetParent !== null).length === 2")
    page.fill("[data-testid=st-compare-as-of]", "")
    page.click("[data-testid=st-run]")
    page.wait_for_function("() => Array.from(document.querySelectorAll('[data-testid=st-bs-total-assets] td.num')).filter(e => e.offsetParent !== null).length === 1")
    page.check("[data-testid=st-drafts]")                                                    # 再查一次（換個條件）也不會被填回
    page.click("[data-testid=st-run]")
    page.wait_for_selector("[data-testid=st-drafts-warn]", state="visible")
    page.wait_for_timeout(600)
    assert page.input_value("[data-testid=st-compare-as-of]") == "" and len(_cells(page)) == 1 and _cells(page) == ["15,500"]


@pytest.mark.e2e
def test_user_edited_comparison_survives_requery(live_server, make_user, e2e_browser):
    user, pw = make_user(username="bsd_edit", role="superadmin")
    _book()
    page = _enter(e2e_browser, live_server, user, pw)
    page.wait_for_function("() => Array.from(document.querySelectorAll('[data-testid=st-bs-total-assets] td.num')).filter(e => e.offsetParent !== null).length === 2")
    page.fill("[data-testid=st-compare-as-of]", "%d-07-31" % (Y - 1))
    page.click("[data-testid=st-run]")
    page.wait_for_function("() => { const c = Array.from(document.querySelectorAll('[data-testid=st-bs-total-assets] td.num')).filter(e => e.offsetParent !== null).map(e => e.textContent.trim()); return c.length === 2 && c[1] === '10,500' }")
    page.check("[data-testid=st-drafts]")
    page.click("[data-testid=st-run]")
    page.wait_for_selector("[data-testid=st-drafts-warn]", state="visible")
    page.wait_for_timeout(600)
    assert page.input_value("[data-testid=st-compare-as-of]") == "%d-07-31" % (Y - 1)
    assert page.locator("[data-testid=st-bs-sec-assets] td.num").nth(1).inner_text().strip() == "%d-07-31" % (Y - 1)      # 比較欄標頭＝使用者改的日期


@pytest.mark.e2e
def test_income_statement_defaults_to_same_period_last_year(live_server, make_user, e2e_browser):
    user, pw = make_user(username="bsd_is", role="superadmin")
    _seed("%d-03-10" % (Y - 1), [("1113", 8000, 0), ("4111", 0, 8000)])
    _seed("%d-03-10" % Y, [("1113", 3000, 0), ("4111", 0, 3000)])
    page = _enter(e2e_browser, live_server, user, pw)
    page.click("[data-testid=st-tab-is]")
    page.wait_for_selector("[data-testid=st-is-table]")
    page.wait_for_function("() => document.querySelector('[data-testid=st-is-table]').innerText.includes('比較期')")
    row = page.locator("[data-testid=st-is-line-IS_NI] td.num")
    page.wait_for_function("() => { const e = document.querySelectorAll('[data-testid=st-is-line-IS_NI] td.num'); return e.length >= 3 && e[2].textContent.trim() === '8,000' }")
    assert row.nth(1).inner_text().strip() == "3,000"                                       # 年初至今＝今年；比較期＝去年同期間
