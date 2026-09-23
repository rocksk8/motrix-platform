# -*- coding: utf-8 -*-
"""`BN4` 的**頁面那一半**：真的開獎金頁，畫面上的字要是「獎金分潤單」。

靜態題（`test_bonus_manual_and_picker_2026_09_23.py::test_bn4_*`）驗的是原始碼；
這一題驗**渲染之後使用者看得到的文字**——`x-text` 組出來的字串、
區塊標題、按鈕，都只有在頁面上才看得到最後長什麼樣。

⚙️ 伺服器與登入的寫法照抄 `test_e2e_bonus_empty_state_2026_09_23.py`
（同行程 uvicorn ＋ 本機 chromium；帳號是 `make_user` 建的測試帳號）。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port

OLD_NAME = "獎金單"
NEW_NAME = "獎金分潤單"
#: bonus.html 由 reports 模組把關（見 test_e2e_bonus_empty_state 的 BONUS_MODULE 註解）
BONUS_MODULE = "reports"


@pytest.fixture(autouse=True)
def _bonus_module_on(monkeypatch):
    """模組預設關著（使用者 2026-09-23 裁示暫停）⇒ 打開才量得到頁面本體。"""
    import helpers.bonus as hb
    monkeypatch.delenv("BONUS_MODULE_ENABLED", raising=False)
    monkeypatch.setattr(hb, "BONUS_MODULE_ENABLED", True)
    assert hb.bonus_module_on(), "打開旗標之後模組還是關的 —— 前提失效，先修這裡。"


@pytest.fixture()
def live_server(client):
    import main
    config = uvicorn.Config(main.app, host="127.0.0.1",
                            port=free_safe_port(), log_level="warning")
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
        yield "http://127.0.0.1:%d" % port
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.e2e
def test_the_bonus_page_says_the_new_name(live_server, make_user):
    """`BN4` 頁面那一半。

    ⚠️ 題名**刻意不以 `test_bn4_` 開頭**：覆蓋率守門把「同一個編號出現在兩個題檔」判成撞名
    （`AMBIGUOUS`）而不給信用 —— `BN4` 的信用由靜態那一題
    （`test_bonus_manual_and_picker_2026_09_23.py::test_bn4_*`）承擔，這一題是它的頁面佐證。
    """
    u, p = make_user("bn4_sa", role="superadmin", modules=[BONUS_MODULE])
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto("%s/pages/login.html" % live_server)
        page.fill('input[x-model="username"]', u)
        page.fill('input[x-model="password"]', p)
        page.click('button:has-text("登入")')
        page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
        page.goto("%s/pages/bonus.html" % live_server)
        page.wait_for_timeout(2500)
        text = page.locator("body").inner_text()
        browser.close()

    assert "暫停使用" not in text, "頁面顯示模組暫停使用 —— 量到的不是 BN4，先看 fixture。"
    assert ("產生" + NEW_NAME) in text, (
        "畫面上找不到「產生%s」（區塊標題／按鈕）。畫面前 400 字：%r" % (NEW_NAME, text[:400]))
    assert OLD_NAME not in text, (
        "畫面上仍然出現「%s」：%r" % (OLD_NAME, text[max(0, text.find(OLD_NAME) - 40):text.find(OLD_NAME) + 40]))
