"""案件清單件數載入失敗要說出來、可重試（2026-09-24，hichan-8d 全量預演查到）。

loadCaseCounts() 原本回應非 2xx 或例外時 catch {} 靜默吞掉：caseCounts 永遠 null，摘要與頁籤數字
一直空白，畫面沒有任何說明。改為顯示「件數載入失敗」＋「重試」。
觀測點：畫面上的失敗訊息；重試成功後訊息消失、數字出現。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
ERR = "[data-testid=case-counts-error]"


def _seed():
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-CNTERR-1", "已送出", "客戶", "專案", 1000, 952, json.dumps({"dealTag": "已成案"}), now, now,
             "已成案", "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def live_server(client):
    import uvicorn
    import main
    from tests._ports import free_safe_port
    config = uvicorn.Config(main.app, host="127.0.0.1", port=free_safe_port(), log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
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
        t.join(timeout=5)


@pytest.mark.e2e
def test_counts_failure_is_shown_and_retry_recovers(live_server, make_user):
    u = make_user(username="cnterr_e1", role="admin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.on("dialog", lambda d: d.accept())
            page.goto(f"{live_server}/pages/login.html")
            page.fill('input[x-model="username"]', u[0])
            page.fill('input[x-model="password"]', u[1])
            page.click('button:has-text("登入")')
            page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
            fail = {"on": True}

            def handler(route):
                if fail["on"]:
                    route.fulfill(status=500, content_type="application/json", body='{"detail":"boom"}')
                else:
                    route.continue_()
            page.route("**/api/quotations?*counts=1*", handler)
            page.goto(f"{live_server}/pages/case-management.html")
            err = page.locator(ERR)
            err.wait_for(state="visible", timeout=15000)
            assert "件數載入失敗" in err.inner_text()
            assert err.get_attribute("role") == "alert"
            fail["on"] = False
            err.locator("button:text-is('重試')").click()
            err.wait_for(state="hidden", timeout=10000)
            assert page.evaluate(f"() => {DATA_JS}.summaryTotal()") == 1
        finally:
            browser.close()
