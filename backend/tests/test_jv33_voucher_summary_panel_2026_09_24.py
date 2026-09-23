# -*- coding: utf-8 -*-
"""`JV33` · 點摘要就同時看到「本傳票已上傳檔案」與「支出項」，不用切頁籤。

使用者逐字：「我點傳票的摘要他也能自動帶入已上傳檔案跟支出項，不用每次來回點閱」。
權威原文：`SPEC-JV28-ATTACHMENT-PREVIEW.md` `JV33` ＋ A 2026-09-24 裁示：

```
① 既有「摘要來源」頁籤區保留；另加「帶入面板」，摘要格 focus 時出現，兩區同時列出
   支出項要先選案件（vouchers.py 既有限制）⇒ 沒選時照既有那句提示
② 面板點一項：摘要空白 ⇒ 填入；非空 ⇒ 以「；」接在後面（只限面板，頁籤區維持覆蓋）
③ 本傳票附件：文字 ⇒ 把檔名接進摘要；縮圖 ⇒ 走 JV28 頁內預覽，不動摘要
④ 「連金額一起帶入」這一輪不做（金額，待確認 N12）
```
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.test_voucher_preview_export_feedback_2026_09_23 import (  # noqa: E402,F401
    live_server, _login)
from tests.test_jv28_voucher_attachment_preview_2026_09_24 import (  # noqa: E402
    _png_bytes, _upload, _open_page)

QUOTE = "MQ-JV33-001"
PANEL = '[data-testid="summary-panel"]'
FILES = '[data-testid="summary-panel-files"]'
EXPENSES = '[data-testid="summary-panel-expenses"]'
SUMMARY = "textarea[x-model='l.summary']"


def _seed_case():
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax,"
            " data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (QUOTE, "已結案", "JV33客戶", "JV33案", 1000, 952, "{}",
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _setup(page, live_server, make_user, seed_extra_expense, uname):
    _seed_case()
    seed_extra_expense(QUOTE, total_cost=5000, category="運費", description="吊車運費",
                       expense_date="2026-09-10", doc_no="AB12345678")
    u, p = make_user(username=uname, role="superadmin", modules=["cashier"])
    _login(page, live_server, u, p)
    token = page.evaluate("() => JSON.parse(localStorage.getItem('motrix_session')).token")
    r = page.request.post(f"{live_server}/api/vouchers",
                          headers={"Authorization": "Bearer " + token},
                          data={"summary": "JV33", "lines": [
                              {"account_code": "6111", "debit": 5000, "credit": 0},
                              {"account_code": "1113", "debit": 0, "credit": 5000}]})
    assert r.ok, r.text()
    vid = r.json()["id"]
    _upload(page, live_server, token, vid, "吊車發票.png", "image/png", _png_bytes())
    r = page.request.get(f"{live_server}/api/vouchers/summary-sources?quote_no={QUOTE}",
                         headers={"Authorization": "Bearer " + token})
    exp = [it["summary"] for it in r.json()["tabs"]["支出項"]]
    assert exp, "量尺：案件底下沒有支出項——下面量不到東西：%r" % r.json()
    _open_page(page, live_server, vid)
    # 🔑 選案件走使用者真的會走的那一步：頁籤區「案件」點那一筆（它會覆蓋第 1 行摘要，
    #    所以下面的題都在**第 2 行**上量）。
    page.click('[data-testid="summary-source-tab"]:text-is("案件")')
    page.click(f'[data-testid="summary-source-item"]:has-text("{QUOTE}")')
    page.wait_for_function(
        "q => Alpine.$data(document.querySelector('[x-data]')).sourceQuote === q", arg=QUOTE,
        timeout=10000)
    return exp[0]


def _line2(page):
    return page.locator(SUMMARY).nth(1)


def _summary2(page):
    return page.evaluate("() => Alpine.$data(document.querySelector('[x-data]')).lines[1].summary")


@pytest.mark.e2e
def test_jv33_focusing_a_summary_shows_files_and_expenses_together(
        live_server, make_user, seed_extra_expense):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            exp = _setup(page, live_server, make_user, seed_extra_expense, "jv33_a")
            _line2(page).click()
            page.wait_for_selector(PANEL, state="visible", timeout=5000)
            files_vis = page.is_visible(FILES + ' :text("吊車發票.png")')
            exp_vis = page.is_visible(EXPENSES + ' :text("%s")' % exp[:6])
            print("JV33 頁面實測：focus 第 2 行摘要 ⇒ 附件區可見", files_vis, "／支出項區可見", exp_vis)
            assert files_vis and exp_vis, "兩區沒有同時出現（附件 %s／支出項 %s）" % (files_vis, exp_vis)
        finally:
            browser.close()


@pytest.mark.e2e
def test_jv33_clicking_items_fills_then_appends_with_a_fullwidth_semicolon(
        live_server, make_user, seed_extra_expense):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            exp = _setup(page, live_server, make_user, seed_extra_expense, "jv33_b")
            _line2(page).click()
            page.wait_for_selector(PANEL, state="visible", timeout=5000)
            assert _summary2(page) == "", "量尺：第 2 行一開始就不是空的：%r" % _summary2(page)
            page.click('[data-testid="summary-panel-expense"]:has-text("%s")' % exp[:6])
            first = _summary2(page)
            page.click('[data-testid="summary-panel-file"]:has-text("吊車發票.png")')
            second = _summary2(page)
            print("JV33 頁面實測：點支出項 ⇒", repr(first), "；再點附件 ⇒", repr(second))
            assert first == exp, "空白摘要應該直接填入：%r" % first
            assert second == exp + "；吊車發票.png", "非空應該以「；」接在後面：%r" % second
        finally:
            browser.close()


@pytest.mark.e2e
def test_jv33_the_thumbnail_previews_without_touching_the_summary(
        live_server, make_user, seed_extra_expense):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            _setup(page, live_server, make_user, seed_extra_expense, "jv33_c")
            _line2(page).click()
            page.wait_for_selector(PANEL, state="visible", timeout=5000)
            thumb = page.locator('[data-testid="summary-panel-thumb"]').first
            thumb.wait_for(state="visible", timeout=10000)
            thumb.click()
            page.wait_for_selector('[data-testid="voucher-att-preview"]', state="visible",
                                   timeout=10000)
            assert _summary2(page) == "", "點縮圖不應該動摘要：%r" % _summary2(page)
        finally:
            browser.close()
