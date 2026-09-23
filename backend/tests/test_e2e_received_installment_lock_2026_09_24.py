"""瀏覽器端對端：業務在案件管理刪掉已收款期別 → 畫面說出後端的原因（2026-09-24）。

後端擋下之後，前端原本只顯示「儲存失敗」，使用者看不出是哪一期、為什麼。
這支題釘住：畫面上看得到「已收款，不可刪除」，而且資料庫裡那一期還在。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port

QUOTE_NO = "MQ-E2ELOCK-001"


@pytest.fixture()
def live_server(client):
    """比照 test_e2e_t100_unconfirm_2026_09_10.py 的同名 fixture。"""
    import main
    config = uvicorn.Config(main.app, host="127.0.0.1", port=free_safe_port(), log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("uvicorn 測試伺服器在時限內沒有啟動")
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _login(page, base_url, username, password):
    page.goto(f"{base_url}/pages/login.html")
    page.fill('input[x-model="username"]', username)
    page.fill('input[x-model="password"]', password)
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)


def _item_ids():
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (QUOTE_NO,)).fetchone()
    finally:
        conn.close()
    return [it.get("id") for it in json.loads(row["data_json"])["caseRecord"]["payment"]["items"]]


@pytest.mark.e2e
def test_sales_sees_reason_when_deleting_received_installment(live_server, make_user):
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

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            _login(page, live_server, username, password)
            page.goto(f"{live_server}/pages/case-management.html?q={QUOTE_NO}")
            delete_received = page.locator(
                "xpath=//label[.//span[normalize-space()='已收款']]"
                "/following-sibling::button[contains(@class,'btn-del')]")
            delete_received.wait_for(state="visible", timeout=15000)
            assert delete_received.count() == 1
            delete_received.click()

            label = page.locator("span.save-label")
            page.wait_for_function(
                "() => { const e = document.querySelector('span.save-label');"
                " return e && /已收款|已儲存/.test(e.textContent) }", timeout=15000)
            text = label.inner_text()
            assert "已收款，不可刪除" in text, text
            assert "訂金款" in text, text
            assert _item_ids() == [1, 2, 3], "已收款期別不可以被刪掉"
        finally:
            browser.close()
