"""瀏覽器端對端：出納「標記已收款」視窗的實收金額驗證（2026-09-24）。

後端開始拒收空白／非數字的實收金額之後，畫面若照樣讓人按「確認」，使用者只會
看到一個 400 的 alert。這支題釘住：清空實收金額 → 畫面說出原因、按鈕不能按；
填回數字 → 真的寫進資料庫，而且收款人是伺服器記的操作者。

觀測點打在資料庫落地值，不打在頁面上寫死的文字。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port

QUOTE_NO = "MQ-E2ERCV-001"




def _login(page, base_url, username, password):
    inject_login(page, base_url, username, password)


def _item():
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (QUOTE_NO,)).fetchone()
    finally:
        conn.close()
    return json.loads(row["data_json"])["caseRecord"]["payment"]["items"][0]


@pytest.mark.e2e
def test_receive_modal_blocks_empty_actual_amount(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_rcv", role="admin")

    import db
    conn = db.get_db()
    try:
        data_json = json.dumps({"dealTag": "已成案", "caseRecord": {"payment": {"items": [
            {"id": 1, "type": "訂金", "pct": 100, "amount": 50000, "received": False},
        ]}}}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (QUOTE_NO, "已送出", "收款測客", "收款測專", 50000, 47619, data_json,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-09-01"),
        )
        conn.commit()
    finally:
        conn.close()

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/cashier.html")
    page.click('button.ctab:has-text("待收款")')
    row = page.locator("tr", has=page.locator("td.mono", has_text=QUOTE_NO))
    row.locator("button.action-btn.pay").click()

    amount = page.locator('input[x-model\\.number="receiveActualAmount"]')
    confirm = page.locator("button", has_text="確認標記已收款")
    amount.wait_for(state="visible")
    assert amount.input_value() == "50000", "預設帶應收金額"
    assert confirm.is_enabled()

    amount.fill("")
    err = page.locator('div[x-text="receiveAmountError()"]')
    err.wait_for(state="visible")
    assert "實收金額" in err.inner_text()
    assert confirm.is_disabled(), "實收金額空白時不可以按確認"
    assert _item()["received"] is False

    amount.fill("49800")
    assert confirm.is_enabled()
    confirm.click()
    for _ in range(100):
        if _item().get("received"):
            break
        time.sleep(0.1)
    it = _item()
    assert it["received"] is True
    assert it["actualAmount"] == 49800
    assert it["receivedBy"] == username
    assert len(it["receivedAt"]) == 10
