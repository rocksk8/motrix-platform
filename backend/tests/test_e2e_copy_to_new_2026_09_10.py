"""瀏覽器端對端：報價單「複製為新單」在取不到號時仍要能正常存檔。

背景：`copyToNew()` 原本在取不到號時會造 `MQ-YYYYMM-???` 當單號帶到新頁面。
那個字串不會跟任何既有單號衝突，所以後端 INSERT 成功、接著 `int('???')`
炸成 500——使用者只看到「儲存失敗」，而複製的內容在頁面載入時就已經從
sessionStorage 清掉，重新整理再也回不來。

這支測試把 `/api/next-quote-no` 打成失敗來重現「取不到號」，然後走完
複製 → 存檔，斷言：存得起來、拿到合法單號、內容真的被複製過去。
純後端測試攔不下來——後端收到什麼取決於前端造了什麼。
"""
import json
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn


@pytest.fixture()
def live_server(client):
    import main
    config = uvicorn.Config(main.app, host="127.0.0.1", port=0, log_level="warning")
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


@pytest.mark.e2e
def test_copy_to_new_survives_quote_no_outage(live_server, make_user):
    """取號端點掛掉時複製為新單：不得造出 `???` 假號，存檔要成功並拿到合法單號。"""
    username, password = make_user(username="e2e_copy", role="superadmin")

    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, "
            "pretax, data_json, created_at, updated_at, deal_tag, quote_date) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-202609-050", "草稿", "來源客戶", "來源專案", 50000, 47619,
             json.dumps({"quoteNo": "MQ-202609-050", "customerName": "來源客戶",
                         "projectName": "來源專案", "status": "草稿",
                         "items": [{"id": 1, "description": "來源品項 X", "qty": 1,
                                    "unitPrice": 50000, "amount": 50000}],
                         "tot": {"total": 50000, "pretax": 47619,
                                 "directMarginPct": 0, "netMarginPct": 0}},
                        ensure_ascii=False),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00", "", "2026-09-01"),
        )
        conn.commit()
    finally:
        conn.close()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("dialog", lambda d: d.accept())
        try:
            _login(page, live_server, username, password)

            # 取號端點一律失敗 → 逼出「取不到號」那條路徑
            page.route("**/api/next-quote-no*",
                       lambda route: route.fulfill(status=503, body="{}"))

            page.goto(f"{live_server}/pages/quotation-form.html?id=MQ-202609-050")
            page.wait_for_function(
                "() => document.body.innerText.includes('來源客戶')", timeout=20000)

            page.evaluate("Alpine.$data(document.querySelector('[x-data]')).copyToNew()")
            page.wait_for_function(
                "() => location.search.includes('copy=1') || location.search.includes('id=')",
                timeout=20000)

            # 關鍵：不得出現 ??? 假號
            assert "%3F" not in page.url and "?" not in page.url.split("?", 1)[1], \
                f"複製後的網址帶了假單號：{page.url}"
            assert "???" not in page.inner_text("body"), "畫面出現 ??? 假單號"

            # 內容真的被複製過來
            page.wait_for_function(
                "() => document.querySelector('input[x-model=\"q.customerName\"]')?.value"
                " === '來源客戶'", timeout=20000)

            page.click('button:has-text("儲存草稿")')
            page.wait_for_function(
                "() => document.querySelector('.form-quote-no')?.textContent?.includes('MQ-')",
                timeout=20000)
            shown = page.inner_text(".form-quote-no").strip()
        finally:
            browser.close()

    conn = db.get_db()
    try:
        rows = [r["quote_no"] for r in conn.execute(
            "SELECT quote_no FROM quotations ORDER BY quote_no")]
    finally:
        conn.close()

    assert shown in rows, f"畫面顯示的單號 {shown!r} 不在資料庫裡：{rows}"
    assert not any("?" in q for q in rows), f"資料庫出現含 ? 的單號：{rows}"
    assert len(rows) == 2, f"複製應該只多一張，實際 {rows}"
