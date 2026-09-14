"""瀏覽器層級：兩個人同時進同一份資料時，**主動跳出對話框**（2026-09-14）。

第一版只有頂端一條橫幅——使用者盯著自己的欄位打字，根本不會注意到上面多了一條。
使用者要求「先跳出提示」，所以改成：進入時若已有人在編、或編輯途中有人加入，都主動
跳一次對話框（同一個人只跳一次，否則每 30 秒跳一次會變成噪音，而噪音的下場是使用者
學會無視它）。

這支測試開兩個瀏覽器 context（等於兩個人）驗收，並包含反向控制——單獨一人時不能跳，
不然這個對話框會變成「每次開單都要按一下」的折磨。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
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


def _seed_quote(quote_no):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "草稿", "測客", "測專", 1000, 952,
             json.dumps({"quoteNo": quote_no, "customerName": "測客", "items": []},
                        ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "", "", "[]"),
        )
        conn.commit()
    finally:
        conn.close()
    return quote_no


@pytest.mark.e2e
def test_modal_pops_for_second_editor(live_server, make_user):
    """A 已在編，B 進來 → B 立刻跳出對話框（不只是頂端橫幅）。"""
    a_u, a_p = make_user(username="e2e_mod_a", role="superadmin")
    b_u, b_p = make_user(username="e2e_mod_b", role="superadmin")
    quote_no = _seed_quote("MQ-E2E-MODAL")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx_a, ctx_b = browser.new_context(), browser.new_context()
        try:
            page_a = ctx_a.new_page()
            _login(page_a, live_server, a_u, a_p)
            page_a.goto(f"{live_server}/pages/quotation-form.html?id={quote_no}")
            page_a.wait_for_timeout(1200)       # 讓 A 的第一次心跳送出去

            page_b = ctx_b.new_page()
            _login(page_b, live_server, b_u, b_p)
            page_b.goto(f"{live_server}/pages/quotation-form.html?id={quote_no}")
            page_b.wait_for_selector("#motrix-presence-modal", state="visible", timeout=10000)
            text = page_b.inner_text("#motrix-presence-modal")
            assert "e2e_mod_a" in text, text

            # 按「我知道了」要關得掉，而且不會再跳同一個人
            page_b.click("#motrix-presence-modal button:has-text('我知道了')")
            page_b.wait_for_timeout(1500)
            assert page_b.locator("#motrix-presence-modal").count() == 0
            # 橫幅留著當持續指示
            assert page_b.locator("#motrix-presence-bar").is_visible()
        finally:
            browser.close()


@pytest.mark.e2e
def test_modal_pops_when_someone_joins_midway(live_server, make_user):
    """A 先進來（沒人），B 後到 → **A 編輯途中**也要跳提示。

    第一版只在進入時看得到狀態，先進來的人完全不知道有人加入——那才是最容易
    互相覆蓋的情境。
    """
    a_u, a_p = make_user(username="e2e_mid_a", role="superadmin")
    b_u, b_p = make_user(username="e2e_mid_b", role="superadmin")
    quote_no = _seed_quote("MQ-E2E-MIDWAY")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx_a, ctx_b = browser.new_context(), browser.new_context()
        try:
            page_a = ctx_a.new_page()
            _login(page_a, live_server, a_u, a_p)
            page_a.goto(f"{live_server}/pages/quotation-form.html?id={quote_no}")
            page_a.wait_for_timeout(1200)
            assert page_a.locator("#motrix-presence-modal").count() == 0, "只有自己時不該跳"

            page_b = ctx_b.new_page()
            _login(page_b, live_server, b_u, b_p)
            page_b.goto(f"{live_server}/pages/quotation-form.html?id={quote_no}")

            # A 的心跳在有人同時編輯時會加速到 10 秒，最多等兩輪
            page_a.wait_for_selector("#motrix-presence-modal", state="visible", timeout=25000)
            assert "e2e_mid_b" in page_a.inner_text("#motrix-presence-modal")
        finally:
            browser.close()


@pytest.mark.e2e
def test_no_modal_for_single_editor(live_server, make_user):
    """反向控制：單獨一人不能跳——不然每次開單都要按一次，使用者會學會無視它。"""
    u, p = make_user(username="e2e_mod_solo", role="superadmin")
    quote_no = _seed_quote("MQ-E2E-MODAL-SOLO")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, u, p)
            page.goto(f"{live_server}/pages/quotation-form.html?id={quote_no}")
            page.wait_for_timeout(2000)
            assert page.locator("#motrix-presence-modal").count() == 0
        finally:
            browser.close()
