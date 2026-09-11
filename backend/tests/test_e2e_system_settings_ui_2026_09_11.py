"""瀏覽器層級端對端測試：系統技術設定的四張卡片（2026-09-11 新增前端入口）。

這四支端點（備份保留天數／PDF 存檔根目錄／Edge 路徑／雲端備份目標）系統一直在讀，
但先前完全沒有前端入口，只能直接打 API——是新加的打包入口檢查掃出來的，
`routers/system.py` 裡甚至有註解把「還沒做」寫成了慣例（「這類非機密設定值，
無對應前端頁面…透過 API 直接調整」）。

四張卡片都是 Alpine `x-model` 綁定，綁錯不會有錯誤訊息、只會安靜地存不進去，
所以用真實瀏覽器驗一條完整來回：改值 → 儲存 → 重新載入頁面後值還在。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn

PAGE = "/pages/company-profile-settings.html"
RET_CARD = ".ns-card:has-text('備份保留天數')"
CLOUD_CARD = ".ns-card:has-text('雲端備份目標')"


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
def test_all_four_cards_render_for_superadmin(live_server, make_user):
    """四張卡片都要出現——少一張不會有任何錯誤訊息，只會安靜地不見。"""
    username, password = make_user(username="e2e_sys", role="superadmin")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            _login(page, live_server, username, password)
            page.goto(f"{live_server}{PAGE}")
            page.wait_for_selector(RET_CARD, timeout=20000)

            body = page.locator("main").inner_text()
            for title in ("備份保留天數", "PDF 存檔根目錄", "Edge 瀏覽器路徑", "雲端備份目標"):
                assert title in body, f"少了「{title}」這張卡片"
            assert not errors, f"頁面有 JS 錯誤：{errors}"
        finally:
            browser.close()


@pytest.mark.e2e
def test_backup_retention_round_trip(live_server, make_user):
    """改值 → 儲存 → 重新載入後仍在，並且真的寫進 system_settings。"""
    username, password = make_user(username="e2e_sys2", role="superadmin")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            page.goto(f"{live_server}{PAGE}")
            page.wait_for_selector(RET_CARD, timeout=20000)

            page.fill(f"{RET_CARD} input[type='number'] >> nth=0", "45")
            page.click(f"{RET_CARD} button:has-text('儲存設定')")
            page.wait_for_selector(f"{RET_CARD} :text('設定已儲存')", timeout=10000)

            # 真的落到 DB
            import db
            import json as _json
            conn = db.get_db()
            try:
                row = conn.execute(
                    "SELECT value_json FROM system_settings WHERE key='backup_retention'").fetchone()
            finally:
                conn.close()
            assert row, "system_settings 裡找不到 backup_retention"
            assert _json.loads(row["value_json"])["local_db_keep_days"] == 45

            # 重新載入畫面也要看得到新值（證明 GET 那半也接上了）
            page.reload()
            page.wait_for_selector(RET_CARD, timeout=20000)
            assert page.input_value(f"{RET_CARD} input[type='number'] >> nth=0") == "45"
        finally:
            browser.close()


@pytest.mark.e2e
def test_retention_out_of_range_is_blocked_with_field_name(live_server, make_user):
    """超出 1～3650 要在前端就擋下，而且訊息要指名是哪一欄——
    後端只回「某個欄位不對」的話，四個欄位要自己猜是哪個。"""
    username, password = make_user(username="e2e_sys3", role="superadmin")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            page.goto(f"{live_server}{PAGE}")
            page.wait_for_selector(RET_CARD, timeout=20000)

            page.fill(f"{RET_CARD} input[type='number'] >> nth=2", "99999")
            page.click(f"{RET_CARD} button:has-text('儲存設定')")
            page.wait_for_selector(f"{RET_CARD} :text('雲端週備份')", timeout=10000)
            assert "1～3650" in page.locator(RET_CARD).inner_text()
        finally:
            browser.close()


@pytest.mark.e2e
def test_s3_fields_appear_only_when_s3_selected(live_server, make_user):
    """S3 欄位平常收起來；切到 S3 才展開，且 bucket 沒填要被擋。"""
    username, password = make_user(username="e2e_sys4", role="superadmin")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            page.goto(f"{live_server}{PAGE}")
            page.wait_for_selector(CLOUD_CARD, timeout=20000)

            assert "Bucket" not in page.locator(CLOUD_CARD).inner_text()

            page.select_option(f"{CLOUD_CARD} select", "s3")
            page.wait_for_selector(f"{CLOUD_CARD} :text('Bucket')", timeout=10000)

            page.click(f"{CLOUD_CARD} button:has-text('儲存設定')")
            page.wait_for_selector(f"{CLOUD_CARD} :text('Bucket 為必填')", timeout=10000)
        finally:
            browser.close()
