# -*- coding: utf-8 -*-
"""瀏覽器端對端（G1）：報表設定頁的『費用類別科目對應』頁籤——新增類別、設定科目、儲存、移除對應；非最高管理者唯讀。
終點狀態驗資料庫（gl_category_map／expense_categories），不驗 Alpine 模型。"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

import db  # noqa: E402


def _open(page, base, user, pw):
    bad, errs = [], []
    page.on("response", lambda r: bad.append((r.status, r.url)) if r.status >= 400 else None)
    page.on("pageerror", lambda e: errs.append(str(e)))
    inject_login(page, base, user, pw)
    bad.clear()
    page.goto("%s/pages/ledger-settings.html" % base)
    page.wait_for_selector("[data-testid=ls-tab-catmap]")
    page.click("[data-testid=ls-tab-catmap]")
    page.wait_for_selector("[data-testid=ls-catmap]")
    return bad, errs


def _q(sql, *a):
    c = db.get_db()
    try:
        return [tuple(r) for r in c.execute(sql, a)]
    finally:
        c.close()


@pytest.mark.e2e
def test_superadmin_adds_category_maps_it_and_removes_the_mapping(live_server, make_user, e2e_browser):
    user, pw = make_user(username="e2e_gl_catmap", role="superadmin")
    page = e2e_browser.new_page()
    bad, errs = _open(page, live_server, user, pw)
    page.fill("[data-testid=ls-catmap-new-code]", "e2e_travel")
    page.fill("[data-testid=ls-catmap-new-name]", "差旅交通")
    page.select_option("[data-testid=ls-catmap-new-tax]", "taxable")
    page.click("[data-testid=ls-catmap-add]")
    page.wait_for_selector("[data-testid=ls-catmap-row-e2e_travel]")
    assert _q("SELECT name, default_tax, active FROM expense_categories WHERE code='e2e_travel'") == [("差旅交通", "taxable", 1)]
    assert "e2e_travel" in page.locator("[data-testid=ls-catmap-unmapped]").inner_text()         # 沒對應＝明說，不是綠燈
    row = page.locator("[data-testid=ls-catmap-row-e2e_travel]")
    assert row.locator("[data-testid=ls-catmap-save]").is_disabled()                              # 沒選科目不能存
    row.locator("[data-testid=ls-catmap-account]").select_option("6134")
    row.locator("[data-testid=ls-catmap-nd]").check()
    row.locator("[data-testid=ls-catmap-save]").click()
    page.wait_for_function("() => (document.querySelector('[data-testid=ls-catmap-notice]') || {}).textContent.includes('已儲存')")     # 等這一次動作的終點（上一則「已新增」的提示還在畫面上）
    assert _q("SELECT account_code, nondeductible FROM gl_category_map WHERE source='extra_expense' AND category='e2e_travel'") == [("6134", 1)]
    page.wait_for_function("() => !document.querySelector('[data-testid=ls-catmap-unmapped]') || document.querySelector('[data-testid=ls-catmap-unmapped]').offsetParent === null")
    page.locator("[data-testid=ls-catmap-row-e2e_travel] [data-testid=ls-catmap-del]").click()
    page.wait_for_function("() => document.querySelector('[data-testid=ls-catmap-row-e2e_travel] [data-testid=ls-catmap-del]').disabled")
    assert _q("SELECT COUNT(*) FROM gl_category_map WHERE category='e2e_travel'") == [(0,)]
    # 壞代碼：後端訊息照實顯示、沒有新增
    page.fill("[data-testid=ls-catmap-new-code]", "有中文")
    page.fill("[data-testid=ls-catmap-new-name]", "x")
    page.click("[data-testid=ls-catmap-add]")
    page.wait_for_selector("[data-testid=ls-catmap-error]", state="visible")
    assert _q("SELECT COUNT(*) FROM expense_categories WHERE name='x'") == [(0,)]
    assert not [b for b in bad if b[0] != 400], bad[:4]
    assert not errs, errs[:3]
    page.close()


@pytest.mark.e2e
def test_finance_user_sees_the_table_read_only(live_server, make_user, e2e_browser):
    c = db.get_db()
    try:
        c.execute("INSERT OR REPLACE INTO expense_categories(code,name,default_tax,active,sort,note) VALUES ('e2e_ro','唯讀類別','',1,0,'')")
        c.commit()
    finally:
        c.close()
    user, pw = make_user(username="e2e_gl_catmap_ro", role="engineer", modules=["finance"])
    page = e2e_browser.new_page()
    _open(page, live_server, user, pw)
    page.wait_for_selector("[data-testid=ls-catmap-row-e2e_ro]")
    assert page.locator("[data-testid=ls-catmap-row-e2e_ro] [data-testid=ls-catmap-account]").is_disabled()
    assert page.locator("[data-testid=ls-catmap-row-e2e_ro] [data-testid=ls-catmap-save]").is_disabled()
    assert not page.locator("[data-testid=ls-catmap-add]").is_visible()
    page.close()
