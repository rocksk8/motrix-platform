# -*- coding: utf-8 -*-
"""瀏覽器端對端：總帳 P1 兩個頁面（會計期間與結帳、帳簿報表）真的載得起來、按得動。

觀測點沿用 test_e2e_account_tree 的三格：①網路層無 4xx/5xx ②無 pageerror ③畫面真的有內容；
再加「動作的終點狀態」——按下結帳後驗 DOM 的狀態徽章與資料庫，不驗 Alpine 模型、不等某一趟請求。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

import db  # noqa: E402


def _open(page, base, user, pw, path):
    bad, errs = [], []
    page.on("response", lambda r: bad.append((r.status, r.url)) if r.status >= 400 else None)
    page.on("pageerror", lambda e: errs.append(str(e)))
    inject_login(page, base, user, pw)
    bad.clear()
    page.goto("%s/pages/%s" % (base, path))
    return bad, errs


def _seed(date, lines, status="已過帳"):
    conn = db.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) FROM vouchers_all").fetchone()[0] + 700
        cur = conn.execute(
            "INSERT INTO vouchers_all(voucher_no, voucher_date, category, summary, status, created_by, created_at, updated_at)"
            " VALUES (?,?, '轉', 'e2e', ?, 't','n','n')", ("%s-%d" % (date.replace("-", ""), n), date, "已核准" if status == "已過帳" else status))
        vid = cur.lastrowid
        for i, (code, d, c) in enumerate(lines, 1):
            conn.execute("INSERT INTO voucher_lines(voucher_id,line_no,account_code,debit,credit) VALUES (?,?,?,?,?)", (vid, i, code, d, c))
        if status == "已過帳":
            conn.execute("UPDATE vouchers_all SET status='已過帳' WHERE id=?", (vid,))
        conn.commit()
        return conn.execute("SELECT voucher_no FROM vouchers_all WHERE id=?", (vid,)).fetchone()[0]
    finally:
        conn.close()


@pytest.mark.e2e
def test_periods_page_create_year_close_and_reopen_needs_reason(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_periods", role="superadmin")
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw, "ledger-periods.html")
    page.wait_for_selector("[data-testid=lp-new-year]")

    page.fill("[data-testid=lp-new-year]", "2161")
    page.click("[data-testid=lp-create-year]")
    page.wait_for_selector("[data-testid=lp-period-2161-12]")                    # 12 個期間都畫出來
    assert page.locator("[data-testid^=lp-period-2161-]").count() == 12
    assert "已建立" in page.locator("[data-testid=lp-notice]").inner_text()

    conn = db.get_db()
    try:
        pid = conn.execute("SELECT id FROM gl_periods WHERE year=2161 AND period_no=3").fetchone()[0]
    finally:
        conn.close()
    row = page.locator("[data-testid=lp-period-2161-3]")
    row.locator("[data-testid=lp-close]").click()
    page.wait_for_selector("[data-testid=lp-dialog]", state="visible")
    assert "更早的期間" in page.locator("[data-testid=lp-dialog]").inner_text()   # 前面兩期還沒結：要明說，並要求確認
    page.click("[data-testid=lp-submit]")                                         # 沒確認就送出 ⇒ 被擋
    page.wait_for_selector("[data-testid=lp-dlg-error]", state="visible")
    page.check("[data-testid=lp-accept]")
    page.click("[data-testid=lp-submit]")
    page.wait_for_function("() => [...document.querySelectorAll('[data-testid=lp-period-2161-3] .lp-tag')].some(e => e.textContent.trim() === '已結帳')")

    conn = db.get_db()
    try:
        assert conn.execute("SELECT status FROM gl_periods WHERE year=2161 AND period_no=3").fetchone()[0] == "closed"
    finally:
        conn.close()

    row.locator("[data-testid=lp-reopen]").click()
    page.click("[data-testid=lp-submit]")                                         # 不填理由
    page.wait_for_selector("[data-testid=lp-dlg-error]", state="visible")
    assert "理由" in page.locator("[data-testid=lp-dlg-error]").inner_text()
    page.fill("[data-testid=lp-reason]", "補一張漏的傳票")
    page.click("[data-testid=lp-submit]")
    page.wait_for_function("() => [...document.querySelectorAll('[data-testid=lp-period-2161-3] .lp-tag')].some(e => e.textContent.trim() === '開放')")

    # 唯一允許的失敗請求＝本題刻意觸發的兩次 400（沒確認提醒就結帳、重開沒填理由）；其餘任何 4xx/5xx 都是頁面壞了
    assert sorted(u.split("/api/ledger/")[1] for s, u in bad if s == 400) == ["periods/%d/close" % pid, "periods/%d/reopen" % pid], bad
    assert not [b for b in bad if b[0] != 400], "開期間頁時有非預期的請求失敗：%s" % bad[:4]
    assert not errs, "頁面丟了例外：%s" % errs[:3]


@pytest.mark.e2e
def test_periods_page_opening_preview_shows_imbalance(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_open", role="superadmin")
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw, "ledger-periods.html")
    page.wait_for_selector("[data-testid=lp-op-text]")
    page.fill("[data-testid=lp-op-text]", "科目,借方,貸方\n1113,\"5,000\",\n3111,,4000")
    page.click("[data-testid=lp-op-preview]")
    page.wait_for_selector("[data-testid=lp-op-diff]", state="visible")
    assert "1,000" in page.locator("[data-testid=lp-op-diff]").inner_text()      # 差額被指出，不是靜默通過
    page.fill("[data-testid=lp-op-text]", "1113,5000,\n3111,,5000")
    page.click("[data-testid=lp-op-preview]")
    page.wait_for_function("() => !document.querySelector('[data-testid=lp-op-diff]') || document.querySelector('[data-testid=lp-op-diff]').offsetParent === null")
    assert not bad and not errs, (bad[:3], errs[:3])


@pytest.mark.e2e
def test_reports_page_trial_balance_drill_down_and_unbalanced_banner(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_rep", role="superadmin")
    no = _seed("2162-04-10", [("1113", 1234, 0), ("4111", 0, 1234)])
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw, "ledger-reports.html")
    page.wait_for_selector("[data-testid=lr-start]")
    page.fill("[data-testid=lr-start]", "2162-04-01")
    page.fill("[data-testid=lr-end]", "2162-04-30")
    page.click("[data-testid=lr-run]")
    page.wait_for_selector("[data-testid=lr-tb-table]")
    tb = page.locator("[data-testid=lr-tb-table]").inner_text()
    assert "銀行存款" in tb and "1,234" in tb                                     # 正對照：已知傳票在試算表出現
    assert not page.locator("[data-testid=lr-unbalanced]").is_visible()

    page.locator("[data-testid=lr-tb-table] tr", has_text="銀行存款").first.click()   # 逐層點入總分類帳
    page.wait_for_selector("[data-testid=lr-gl-table]")
    assert no in page.locator("[data-testid=lr-gl-table]").inner_text()

    # 反向控制：壞帳（不平衡）必須顯示紅色警告，不可被吸收
    _seed("2162-05-10", [("1113", 500, 0), ("4111", 0, 400)])
    page.click("[data-testid=lr-tab-tb]")
    page.fill("[data-testid=lr-start]", "2162-05-01")
    page.fill("[data-testid=lr-end]", "2162-05-31")
    page.click("[data-testid=lr-run]")
    page.wait_for_selector("[data-testid=lr-unbalanced]", state="visible")

    # 含未過帳：勾選後出現預覽警語
    page.check("[data-testid=lr-drafts]")
    page.wait_for_selector("[data-testid=lr-drafts-warn]", state="visible")
    assert not bad, "開帳簿報表頁時有請求失敗：%s" % bad[:4]
    assert not errs, "頁面丟了例外：%s" % errs[:3]


@pytest.mark.e2e
def test_reports_page_requires_the_ledger_modules(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_none", role="staff", modules=[])
    page = e2e_browser.new_page()
    _open(page, live_server, user, pw, "ledger-reports.html")
    page.wait_for_selector("[data-testid=lr-error]", state="visible")
    assert "權限" in page.locator("[data-testid=lr-error]").inner_text()           # 沒權限＝明說，不是空白頁
