# -*- coding: utf-8 -*-
"""瀏覽器端對端（含截圖）：額外支出「作廢」按鈕（A2 S1；按鈕與 API 同一片）。
驗：只有 superadmin 看得到按鈕（admin 看不到）、已付款列沒有按鈕、取消不動資料、填理由確定後 ⇒ 資料庫狀態＝已作廢＋畫面標「已作廢」＋總額不含該筆。
截圖：暫存夾（BK19），事後複製到 D:\\開發測試檔\\shots\\wip-w2-expense-a2\\。"""
import json
import os
import tempfile

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests._ui_dialogs import answer_prompt, forbid_native_dialogs  # noqa: E402

PANEL = "#xe-panel"
TAB = ".cm-tab:has-text('額外支出')"
QN = "MQ-VOIDUI-1"
QN_ADMIN = "MQ-VOIDUI-2"           # admin 與 superadmin 各開自己的案件：同案件的「有人同時編輯」遮罩會擋住第二個人的點擊


def _shot(page, name):
    try:
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w2-shots"), "wip-w2-expense-a2")
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _seed(seed_extra_expense, qn=QN):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (qn, "已送出", "作廢測客", "測專", 100000, 95238, json.dumps({"dealTag": "已成案", "caseRecord": {}}, ensure_ascii=False),
                   "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        c.commit()
    finally:
        c.close()
    ids = {"open": seed_extra_expense(qn, total_cost=700, description="可作廢的運費", expense_date="2026-03-01", created_by_name="x"),
           "keep": seed_extra_expense(qn, total_cost=300, description="保留的雜支", expense_date="2026-03-02", created_by_name="x"),
           "paid": seed_extra_expense(qn, total_cost=500, description="已付款的材料", expense_date="2026-03-03", created_by_name="x")}
    c = db.get_db()
    try:
        c.execute("UPDATE case_extra_expenses SET paid_date='2026-03-20' WHERE id=?", (ids["paid"],))
        c.commit()
    finally:
        c.close()
    return ids


def _open(browser, live_server, cred, qn=QN):
    page = browser.new_context().new_page()
    inject_login(page, live_server, *cred)
    page.goto(f"{live_server}/pages/case-management.html?q={qn}")
    page.wait_for_selector(TAB, timeout=20000)
    page.click(TAB)
    page.wait_for_selector(f"{PANEL} input[placeholder='品項說明（必填）']", timeout=20000)
    return page


def _card(page, eid):
    return page.locator(f'{PANEL} [data-xe-card="{eid}"]')


@pytest.mark.e2e
def test_void_button_only_for_superadmin_and_ends_in_voided_state(live_server, make_user, e2e_browser, seed_extra_expense):
    ids = _seed(seed_extra_expense)
    sa = make_user(username="vdui_sa", role="superadmin")

    # superadmin：已核准未付款的兩列有按鈕、已付款列沒有
    page = _open(e2e_browser, live_server, sa)
    dialogs = forbid_native_dialogs(page)
    btns = page.locator(f'{PANEL} [data-testid="xe-void-btn"]:visible')
    assert btns.count() == 2
    _shot(page, "10-void-buttons")
    # 取消：不動資料
    _card(page, ids["open"]).locator('[data-testid="xe-void-btn"]').click()
    answer_prompt(page, None, expect="作廢")
    assert _q("SELECT status FROM case_extra_expenses WHERE id=?", (ids["open"],))[0]["status"] == "已核准"
    # 填理由確定
    _card(page, ids["open"]).locator('[data-testid="xe-void-btn"]').click()
    answer_prompt(page, "重複請款", expect="作廢")
    page.wait_for_selector(f'{PANEL} [data-testid="xe-voided-note"]:visible', timeout=15000)
    row = _q("SELECT status, void_reason, voided_by FROM case_extra_expenses WHERE id=?", (ids["open"],))[0]
    assert row == {"status": "已作廢", "void_reason": "重複請款", "voided_by": "vdui_sa"}
    note = page.locator(f'{PANEL} [data-testid="xe-voided-note"]:visible').inner_text()
    assert "重複請款" in note
    kpi = page.locator(f"{PANEL} .cm-kpi__val").first.inner_text()
    assert "800" in kpi and "1,500" not in kpi and "1500" not in kpi                              # 300 + 500；不含作廢的 700
    assert page.locator(f'{PANEL} [data-testid="xe-void-btn"]:visible').count() == 1             # 剩「保留的雜支」那一列（已付款列沒有）
    _shot(page, "11-voided")
    assert not dialogs, dialogs                                                                     # 沒有原生對話框
    # 另一列與已付款列沒被動
    assert _q("SELECT status FROM case_extra_expenses WHERE id IN (?, ?) ORDER BY id", (ids["keep"], ids["paid"])) == [{"status": "已核准"}, {"status": "已核准"}]


@pytest.mark.e2e
def test_admin_sees_no_void_button(live_server, make_user, e2e_browser, seed_extra_expense):
    _seed(seed_extra_expense, QN_ADMIN)
    adm = make_user(username="vdui_admin", role="admin")
    page = _open(e2e_browser, live_server, adm, QN_ADMIN)
    assert page.locator(f'{PANEL} [data-testid="xe-void-btn"]:visible').count() == 0
    _shot(page, "12-admin-no-void-button")
