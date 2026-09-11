"""瀏覽器層級端對端測試：選型資料庫「涵蓋度總覽」要涵蓋全部六類品牌目錄。

**背景**：自動化系統選型導覽（DB v65）在 2026-08-26 就上線，是選型資料庫的
第七類；但 `selection-db-overview.html` 的 `loadAll()` 一直只撈五組
（netarch／switch／monitor／access／gateway），自動化那一類的涵蓋度在這頁
完全看不到。`MOTRIX-ERP-QUICK.md` §6 當時記為「尚未查證」，2026-09-11 查證
確認是真的漏掉並補上。諷刺的是 `automation-guide.html::applyDeepLink()` 早就
寫好了「從涵蓋度總覽點過來」的深層連結處理，只差這一組 fetch。

**這支測試釘的是「新增第八類時不要再忘記這頁」**——漏掉不會有任何錯誤訊息，
頁面照樣正常渲染，只是少一個區塊，純靠人眼比對永遠抓不到。

場域選型導覽（env-guide）**刻意不在涵蓋範圍內**：它的資料形狀是情境×分層
文字建議，不是品牌/型號目錄，沒有「品牌數」可數。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明），
沒裝的環境整個檔案 skip。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn

# 六類品牌目錄，順序即頁面上的顯示順序
EXPECTED_SECTIONS = [
    "網路架構選型導覽",
    "交換器選型導覽",
    "監控系統選型導覽",
    "門禁系統選型導覽",
    "閘道器與控制器選型導覽",
    "自動化系統選型導覽",
]


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
def test_overview_covers_all_six_catalog_guides(live_server, make_user):
    """六個區塊都要在，且自動化那一區要真的顯示撈回來的分類與產品數。"""
    username, password = make_user(username="e2e_ovw", role="superadmin")

    # 種一筆自動化分類＋兩個不同品牌的產品：只檢查標題會漏掉「區塊在、但
    # fetch 沒接上」的情況（rows 永遠空、看起來像資料還沒建）
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO automation_categories (code, name, sort_order, updated_at) VALUES (?,?,?,?)",
            ("plc", "PLC 控制器", 0, "2026-09-11T00:00:00"),
        )
        for brand, model in (("Siemens", "S7-1200"), ("Mitsubishi", "FX5U")):
            conn.execute(
                "INSERT INTO automation_products (category_code, brand, model) VALUES (?,?,?)",
                ("plc", brand, model),
            )
        conn.commit()
    finally:
        conn.close()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            page.goto(f"{live_server}/pages/selection-db-overview.html")
            page.wait_for_selector(".ov-section", timeout=20000)

            titles = [t.strip() for t in page.locator(".ov-section .oh b").all_inner_texts()]
            assert titles == EXPECTED_SECTIONS, (
                f"涵蓋度總覽的區塊與預期不符。\n實際：{titles}\n預期：{EXPECTED_SECTIONS}\n"
                "新增選型類別時，記得同時補 selection-db-overview.html::loadAll()")

            # 自動化那一區要真的有資料，不是空殼
            auto = page.locator(".ov-section", has=page.locator(".oh b:text-is('自動化系統選型導覽')"))
            auto_text = auto.inner_text()
            assert "PLC 控制器" in auto_text, "自動化分類沒有被撈進來"
            assert "Siemens" in auto_text and "Mitsubishi" in auto_text, "自動化產品品牌沒有被撈進來"
            assert "共 2 筆產品" in auto_text, f"自動化產品筆數不對：{auto_text[:200]}"
        finally:
            browser.close()
