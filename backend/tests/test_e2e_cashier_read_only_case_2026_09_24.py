"""瀏覽器端對端：非成員出納打開案件——收款可登錄，其他內容唯讀（CM14b）。

API 層見 test_cashier_reads_all_cases_2026_09_24.py。觀測點：收款備註存進資料庫；合約、角色欄位
在畫面上是 disabled；成員出納則不受限。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_e2e_case_concurrent_edit_2026_09_24 import (  # noqa: F401  (live_server 是 fixture)
    DATA_JS, NOTE_INPUT, _login,
)
from tests.test_cashier_reads_all_cases_2026_09_24 import NO, _seed


def _open(browser, base, user):
    page = browser.new_context().new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, base, *user)
    # CU5（2026-09-24）：收款搬到「財務」分頁 ⇒ 以 ?tab=fin 直接開到那一頁
    page.goto(f"{base}/pages/case-management.html?q={NO}&tab=fin")
    page.locator(NOTE_INPUT).first.wait_for(state="visible", timeout=20000)
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=10000)
    return page


def _payment_note():
    import json
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])
    finally:
        conn.close()
    return d["caseRecord"]["payment"]["items"][0]["note"]


@pytest.mark.e2e
def test_non_member_cashier_can_only_edit_payment(live_server, make_user, e2e_browser):
    u = make_user(username="ro_cash", role="engineer", modules=["case_manage", "cashier"])
    _seed()
    browser = e2e_browser
    page = _open(browser, live_server, u)
    assert page.evaluate(f"() => {DATA_JS}.caseReadOnly()") is True
    # CU5：提示在「案件資訊」與「財務」（收款所在）各一份；目前開的是財務分頁
    assert page.locator('[data-testid="fin-payment"] >> text=以出納身分開啟').is_visible()
    assert page.locator(".cm-fgrid--contract input").first.is_disabled(), "合約欄位應唯讀"
    assert page.locator(".cm-fgrid--people select").first.is_disabled(), "角色欄位應唯讀"
    # 純檢視的切換鈕不可以被一起停用（hichan-0a：清單／時間軸切換移出唯讀範圍）
    assert page.locator(".stage-view-btn").first.is_enabled()
    assert page.locator(".stage-view-btn").nth(1).is_enabled()
    assert page.locator("button:has-text('新增階段')").first.is_disabled(), "執行進度的編輯鈕仍唯讀"
    note = page.locator(NOTE_INPUT).first
    assert note.is_enabled()
    note.fill("出納登錄")
    msg = page.evaluate(f"async () => {{ const c = {DATA_JS}; await c.saveCaseRecord(); return c.saveMsg }}")
    assert "已儲存" in msg, msg
    assert _payment_note() == "出納登錄"


@pytest.mark.e2e
def test_member_cashier_is_not_locked(live_server, make_user, e2e_browser):
    u = make_user(username="ro_mem", role="engineer", modules=["case_manage", "cashier"])
    _seed(roles={"executor": "ro_mem"})
    browser = e2e_browser
    page = _open(browser, live_server, u)
    assert page.evaluate(f"() => {DATA_JS}.caseReadOnly()") is False
    assert page.locator(".cm-fgrid--contract input").first.is_enabled()
