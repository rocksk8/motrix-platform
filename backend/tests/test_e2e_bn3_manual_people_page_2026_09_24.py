# -*- coding: utf-8 -*-
"""`BN3` 的**頁面那一半**：在獎金頁用「手動指定人員」建立項目，勾的人要真的存進資料庫。

API 那一半在 `test_bonus_manual_and_picker_2026_09_23.py::test_bn3_*`（題名刻意不以
`test_bn3_` 開頭：同一個編號出現在兩個題檔，覆蓋率守門會判成撞名而不給信用）。

⚙️ 觀測點是**資料庫的 `bonus_item_people`**（成功後才會被寫入），不是畫面上的成功訊息。
⚙️ 伺服器／登入寫法照抄 `test_e2e_bonus_empty_state_2026_09_23.py`。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port

BONUS_MODULE = "reports"


@pytest.fixture(autouse=True)
def _bonus_module_on(monkeypatch):
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
def test_a_manual_item_created_on_the_page_stores_the_ticked_people(live_server, make_user):
    a, _ = make_user("bn3p_alice", role="user")
    b, _ = make_user("bn3p_bob", role="user")
    c, _ = make_user("bn3p_carol", role="user")
    u, p = make_user("bn3p_sa", role="superadmin", modules=[BONUS_MODULE])
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("%s/pages/login.html" % live_server)
        page.fill('input[x-model="username"]', u)
        page.fill('input[x-model="password"]', p)
        page.click('button:has-text("登入")')
        page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
        page.goto("%s/pages/bonus.html" % live_server)
        page.wait_for_selector("#bn-new-src", timeout=15000)
        page.fill("#bn-new-name", "手動測試項目")
        page.select_option("#bn-new-src", "manual")
        box = '[data-testid="bonus-item-manual-people"]'
        page.wait_for_selector(box + ' input[value="%s"]' % a, timeout=10000)
        page.check(box + ' input[value="%s"]' % a)
        page.check(box + ' input[value="%s"]' % b)
        page.click('button:text-is("新增獎金項目")')
        page.wait_for_timeout(1500)
        text = page.locator("body").inner_text()
        browser.close()

    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT id, person_source FROM bonus_items WHERE name = ?",
                           ("手動測試項目",)).fetchone()
        assert row is not None, "畫面按了新增，而 bonus_items 沒有這一列。頁面錯誤：%r" % errors
        assert row["person_source"] == "manual", row["person_source"]
        people = {r["username"] for r in conn.execute(
            "SELECT username FROM bonus_item_people WHERE bonus_item_id = ?", (row["id"],))}
    finally:
        conn.close()
    assert people == {a, b}, "勾了 %r，存進 bonus_item_people 的是 %r" % ({a, b}, people)
    assert c not in people
    assert "手動指定人員" in text, "項目清單上看不到來源標示「手動指定人員」"
    assert not errors, "頁面有 JS 例外：%r" % errors
