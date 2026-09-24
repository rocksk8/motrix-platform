"""瀏覽器層級：右上角的「在線成員」只給最高管理者看（2026-09-14）。

後端兩支端點已限 superadmin（`test_online_activity_2026_09_14.py`），這裡確認
**畫面上真的看得到／看不到**——權限做對了但按鈕給錯人，使用者一樣會困惑。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port


@pytest.fixture()
def live_server(client):
    """比照 test_e2e_playwright_2026_09_07.py 的同名 fixture。"""
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
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=10000)


@pytest.mark.e2e
def test_superadmin_sees_online_widget(live_server, make_user):
    """最高管理者：右上角有「在線 N」，點開看得到自己在名單裡。"""
    u, p = make_user(username="ow_super", role="superadmin")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, u, p)
            page.wait_for_selector("#tb-online-btn", timeout=10000)
            page.click("#tb-online-btn")
            page.wait_for_selector("#tb-online-pop", state="visible", timeout=5000)
            # PERF #6：原本固定等 400ms ⇒ 等清單真的列出人（沒列出來就交給下面有說明的斷言）
            try:
                page.wait_for_function("() => (document.getElementById('tb-online-list') || {}).innerText", timeout=5000)
            except Exception:
                pass
            # 觀測點放在清單內容：只看數字的話，0 人也會是「看起來正常」
            # 📌 更正留著（2026-09-25，PERF #6 換等待時突變實測）：原本是「清單有自己 **或** 數字不是空的」——
            #    清單整個壞掉（空白）時數字照樣有值 ⇒ 後半讓前半永遠不必成立，跟上一行註解說的正好相反。
            #    /api/online-users 會列出自己（任一 session 5 分鐘內活動）⇒ 清單一定看得到自己。
            assert "ow_super" in page.inner_text("#tb-online-list"), page.inner_text("#tb-online-pop")
        finally:
            browser.close()


@pytest.mark.e2e
def test_admin_does_not_see_online_widget(live_server, make_user):
    """反向控制：一般管理員的右上角沒有這顆按鈕（後端也會 403）。"""
    u, p = make_user(username="ow_admin", role="admin")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, u, p)
            page.wait_for_selector("#app-topbar .topbar__right", timeout=10000)
            page.wait_for_timeout(300)
            assert page.locator("#tb-online-btn").count() == 0, "管理員也看得到在線成員按鈕"
        finally:
            browser.close()
