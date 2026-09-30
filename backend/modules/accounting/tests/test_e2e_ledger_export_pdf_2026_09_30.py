# -*- coding: utf-8 -*-
"""總帳兩個匯出（四大表、營業稅 401 工作底稿）：PDF 按鈕真的下載、Excel／PDF 各留一筆稽核（使用者規則 2026-09-30，第 27 班）。
截圖：D:\開發測試檔\shots\wip-w3-export-pdf\。"""
import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402
from tests.test_e2e_export_pdf_2026_09_30 import _assert_download_pair  # noqa: E402

import db  # noqa: E402


def _seed(date, lines):
    conn = db.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) FROM vouchers_all").fetchone()[0] + 900
        cur = conn.execute(
            "INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at)"
            " VALUES (?,?, '轉', 'e2e', '已核准', 't','n','n')", ("%s-%d" % (date.replace("-", ""), n), date))
        for i, (code, d, c) in enumerate(lines, 1):
            conn.execute("INSERT INTO voucher_lines(voucher_id,line_no,account_code,debit,credit) VALUES (?,?,?,?,?)", (cur.lastrowid, i, code, d, c))
        conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (cur.lastrowid,))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_periods_page_statements_export_has_a_pdf_button_and_both_are_logged(live_server, make_user, e2e_browser):
    from modules.accounting.ledger import periods as P
    user, pw = make_user(username="e2e_gl_expst", role="superadmin")
    y = 2197
    conn = db.get_db()
    try:
        P.create_year(conn, y, "t")
        conn.commit()
    finally:
        conn.close()
    _seed("%d-01-05" % y, [("1113", 100000, 0), ("3111", 0, 100000)])
    page = e2e_browser.new_context(accept_downloads=True).new_page()
    page.on("dialog", lambda d: d.accept())
    inject_login(page, live_server, user, pw)
    page.goto("%s/pages/ledger-periods.html" % live_server)
    page.locator("[data-testid=lp-export-pdf-%d]" % y).wait_for(state="visible", timeout=20000)
    _assert_download_pair(page, "[data-testid=lp-export-%d]" % y, "[data-testid=lp-export-pdf-%d]" % y,
                          "ledger-statements", "ledger-statements", expect_rows_min=0)


@pytest.mark.e2e
def test_hub_tax401_export_has_a_pdf_button_and_both_are_logged(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_extax", role="superadmin")
    page = e2e_browser.new_context(accept_downloads=True).new_page()
    page.on("dialog", lambda d: d.accept())
    # 401 目前列車標「尚未提供」（開關按不動）；PDF 按鈕的行為仍要驗，所以直接寫開關值（W4 開放後改回按開關）
    conn = db.get_db()
    try:
        conn.execute("INSERT OR REPLACE INTO gl_settings(key, value) VALUES ('feature.tax401', '1')")
        conn.commit()
    finally:
        conn.close()
    inject_login(page, live_server, user, pw)
    page.goto("%s/pages/ledger-hub.html" % live_server)
    page.locator("[data-testid=hb-tab-tax401]").click()
    page.locator("[data-testid=hb-tax]").wait_for(state="visible", timeout=20000)
    page.click("[data-testid=hb-tax-load]")
    page.wait_for_function("() => !document.querySelector('[data-testid=hb-tax-export]').disabled", timeout=20000)
    _assert_download_pair(page, "[data-testid=hb-tax-export]", "[data-testid=hb-tax-export-pdf]",
                          "ledger-tax401", "ledger-tax401", expect_rows_min=0)
