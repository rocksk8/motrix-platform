"""瀏覽器端對端：業務在案件管理刪掉已收款期別 → 畫面說出後端的原因（2026-09-24）。

後端擋下之後，前端原本只顯示「儲存失敗」，使用者看不出是哪一期、為什麼。
這支題釘住：畫面上看得到「已收款，不可刪除」，而且資料庫裡那一期還在。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import threading
import time

import pytest

from tests._e2e_login import inject_login  # noqa: E402
from tests._ui_dialogs import answer_confirm, forbid_native_dialogs

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._ports import free_safe_port
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

QUOTE_NO = "MQ-E2ELOCK-001"




def _login(page, base_url, username, password):
    return inject_login(page, base_url, username, password)


def _item_ids():
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (QUOTE_NO,)).fetchone()
    finally:
        conn.close()
    return [it.get("id") for it in json.loads(row["data_json"])["caseRecord"]["payment"]["items"]]


@pytest.mark.e2e
def test_sales_sees_reason_when_deleting_received_installment(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_lock_sales", role="sales")

    import db
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        items = [
            {"id": 1, "type": "訂金款", "pct": 30, "amount": 30000, "received": True,
             "receivedAt": "2026-08-01", "actualAmount": 30000, "feeAmount": 0},
            {"id": 2, "type": "交貨款", "pct": 30, "amount": 30000, "received": False},
            {"id": 3, "type": "驗收款", "pct": 40, "amount": 40000, "received": False},
        ]
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date, sales_person, sales_person_id, "
            "assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (QUOTE_NO, "已送出", "鎖定測客", "鎖定測專", 100000, 95238,
             json.dumps({"dealTag": "已成案", "caseRecord": {"payment": {"items": items}}},
                        ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-08-01",
             username, uid, json.dumps([uid])),
        )
        conn.commit()
    finally:
        conn.close()

    browser = e2e_browser
    page = browser.new_page()
    # 刪除款項期別會先確認（test_e2e_case_data_loss_2026_09_24）；這裡要走到後端那一關，
    # 所以按「確定」。CM12 P4 起確認框是 MotrixUI（不是原生 confirm）⇒ 用 helper 回答並驗訊息。
    natives = forbid_native_dialogs(page)
    _login(page, live_server, username, password)
    # CU5（2026-09-24）：收款搬到「財務」分頁 ⇒ 以 ?tab=fin 直接開到那一頁
    page.goto(f"{live_server}/pages/case-management.html?q={QUOTE_NO}&tab=fin")
    delete_received = page.locator(
        "xpath=//label[.//span[normalize-space()='已收款']]"
        "/following-sibling::button[contains(@class,'btn-del')]")
    delete_received.wait_for(state="visible", timeout=15000)
    assert delete_received.count() == 1
    delete_received.click()
    answer_confirm(page, ok=True, expect="訂金款")

    label = page.locator("span.save-label")
    page.wait_for_function(
        "() => { const e = document.querySelector('span.save-label');"
        " return e && /已收款|已儲存/.test(e.textContent) }", timeout=15000)
    assert natives == [], natives
    text = label.inner_text()
    assert "已收款，不可刪除" in text, text
    assert "訂金款" in text, text
    assert _item_ids() == [1, 2, 3], "已收款期別不可以被刪掉"
