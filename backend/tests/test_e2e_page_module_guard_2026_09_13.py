"""瀏覽器層級：沒有某個模組的人，手打網址也開不了那一頁（2026-09-13）。

在此之前前端**沒有任何頁面層守門**——`auth-guard.js` 只驗 session。沒有某個模組
的人在側欄看不到入口，但手打網址照樣進得去；這一輪後端補上模組檢查之後，症狀會
變成「頁面開得起來、資料一片 403」，看起來像壞掉而不是像沒權限。

守門刻意**沿用側欄自己的顯示條件**（`sidebar.js::ni()` 判定不顯示時把該頁記進
`_deniedPages`），不另外維護一份頁面→模組對照表——那份表一旦跟顯示條件漂移，
就會變成這次盤點抓到的那類錯配。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn


@pytest.fixture()
def live_server(client):
    """比照 test_e2e_playwright_2026_09_07.py 的同名 fixture。"""
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
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=10000)


@pytest.mark.e2e
def test_page_without_module_shows_no_permission(live_server, make_user):
    """沒有「供應商／料號／採購」模組的工程師手打 parts.html → 顯示沒有權限。

    **刻意不導轉**：`index.html` 自己也有一道守門（非 admin 且沒有 finance／
    quotation 模組就導去 case-management.html），導轉會做出無限迴圈——只有
    「儀表板」模組的檢視者會在兩頁之間一直跳。這一題實測時就是這樣才發現的。
    """
    u, p = make_user(username="pg_eng", role="engineer",
                     modules=["dashboard", "case_manage"])
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, u, p)
            page.goto(f"{live_server}/pages/parts.html")
            page.wait_for_selector("#no-module-notice", timeout=10000)
            # 頁面內容要真的被換掉，不是只疊一個提示上去
            assert page.locator(".toolbar").count() == 0, "料號頁的內容還在"
        finally:
            browser.close()


@pytest.mark.e2e
def test_page_with_module_is_not_redirected(live_server, make_user):
    """反向控制：有那個模組的人留在頁面上。

    少了這一題，上面那題有可能只是因為「每個人都被導回首頁」而綠。
    """
    u, p = make_user(username="pg_proc", role="engineer",
                     modules=["dashboard", "procurement"])
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, u, p)
            page.goto(f"{live_server}/pages/parts.html")
            page.wait_for_selector(".sidebar .nav__item", timeout=10000)
            page.wait_for_timeout(300)   # 給守門一個真的會動作的機會
            assert page.url.endswith("parts.html"), f"有模組卻被導走了：{page.url}"
            assert page.locator("#no-module-notice").count() == 0, "有模組卻被擋"
        finally:
            browser.close()
