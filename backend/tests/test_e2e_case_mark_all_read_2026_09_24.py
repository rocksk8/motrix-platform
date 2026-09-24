"""「一鍵已讀」之後未讀列不可以又跳回來（W-4，2026-09-24 開發機實走發現）。

markAllRead() 原本對每一筆送出已讀（不等回應）就重抓件數；件數先回來時，伺服器還沒記到已讀 ⇒
未讀數又變 1、未讀列重新出現。觀測點：已讀請求刻意延後回應時，按下後未讀列不再出現、件數為 0。
"""
import json
import threading
import time
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

NO = "MQ-MARKALL-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"


def _seed():
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客戶", "專案", 1000, 952, json.dumps({"dealTag": "已成案"}), now, now, "已成案", "2026-08-01"))
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
def test_mark_all_read_does_not_bounce_back(live_server, client, make_user):
    u = make_user(username="mar_e1", role="admin")
    _seed()
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}
    client.post("/api/reads/unread", headers=h, json={"kind": "case", "keys": []})
    time.sleep(1.1)
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO case_updates (quote_no, author, content, created_at) VALUES (?,?,?,?)",
                     (NO, "別人", "新動態", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    finally:
        conn.close()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context().new_page()
            page.goto(f"{live_server}/pages/login.html")
            page.fill('input[x-model="username"]', u[0])
            page.fill('input[x-model="password"]', u[1])
            page.click('button:has-text("登入")')
            page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
            page.goto(f"{live_server}/pages/case-management.html")
            bar = page.locator(".cm-unread-bar")
            bar.wait_for(state="visible", timeout=15000)
            time.sleep(1.1)                          # 已讀時間要嚴格晚於動態時間（到秒）

            def slow(route):
                if route.request.method == "POST":
                    time.sleep(1.5)                  # 已讀請求比件數重抓晚回來
                route.continue_()
            page.route("**/api/reads", slow)
            page.locator(".cm-unread-bar button:has-text('一鍵已讀')").click()
            page.wait_for_timeout(4000)
            assert page.evaluate(f"() => {DATA_JS}.unreadCount()") == 0, "一鍵已讀後未讀數又回來了"
            assert not bar.is_visible(), "一鍵已讀後未讀列又出現了"
        finally:
            browser.close()
