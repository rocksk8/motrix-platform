"""瀏覽器層級端對端測試：系統技術設定的四張卡片（2026-09-11 新增前端入口）。

這四支端點（備份保留天數／PDF 存檔根目錄／Edge 路徑／雲端備份目標）系統一直在讀，
但先前完全沒有前端入口，只能直接打 API——是新加的打包入口檢查掃出來的，
`routers/system.py` 裡甚至有註解把「還沒做」寫成了慣例（「這類非機密設定值，
無對應前端頁面…透過 API 直接調整」）。

四張卡片都是 Alpine `x-model` 綁定，綁錯不會有錯誤訊息、只會安靜地存不進去，
所以用真實瀏覽器驗一條完整來回：改值 → 儲存 → 重新載入頁面後值還在。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。

⚠️ 等待時限一律 45 秒：這四張卡片要等 `_loadSysSettings()` 的四支 GET 都回來才
渲染，而整個 pytest session 期間有背景排程在寫 db，SQLite 寫鎖被佔住時
`db.py` 的 `connect(timeout=30)` 最多會等 30 秒。單檔跑碰不到、全套跑才會——
比照 `test_e2e_playwright_2026_09_07.py` 既有的同款處理。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn
from tests._ports import free_safe_port

PAGE = "/pages/company-profile-settings.html"
RET_CARD = ".ns-card:has-text('備份保留天數')"
CLOUD_CARD = ".ns-card:has-text('雲端備份目標')"


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
            page.wait_for_selector(RET_CARD, timeout=45000)

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
            page.wait_for_selector(RET_CARD, timeout=45000)

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
            page.wait_for_selector(RET_CARD, timeout=45000)
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
            page.wait_for_selector(RET_CARD, timeout=45000)

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
            page.wait_for_selector(CLOUD_CARD, timeout=45000)

            assert "Bucket" not in page.locator(CLOUD_CARD).inner_text()

            page.select_option(f"{CLOUD_CARD} select", "s3")
            page.wait_for_selector(f"{CLOUD_CARD} :text('Bucket')", timeout=10000)

            # ⚠️ **不要把斷言打在那句錯誤訊息上當唯一證據**（2026-09-11 偶發紅，單檔
            # 連跑 5 輪卻全綠）。`saveCloudTarget()` 設完 `cloudMsg` 之後有
            # `setTimeout(() => this.cloudMsg = '', 5000)`——訊息 **5 秒後會自己消失**，
            # 原本卻等 10 秒。只要第一次輪詢落在它消失之後，就變成「等一個已經死掉的
            # 元素」，再等多久都沒有用。**會自我銷毀的東西沒辦法可靠地斷言。**
            #
            # 真正不會過期的證據是「**儲存請求根本沒送出去**」——那才是這條驗證要保證
            # 的契約。訊息降為輔助資訊。
            #
            # （偶發的根因另有其一：這頁的雙重初始化會讓第二次 `_loadSysSettings()`
            #   晚一步把使用者改過的欄位蓋回舊值，見 test_init_runs_exactly_once。）
            saves = []
            page.on("request", lambda r: saves.append(r.url)
                    if "cloud-backup-target" in r.url and r.method in ("PUT", "PATCH") else None)

            page.click(f"{CLOUD_CARD} button:has-text('儲存設定')")
            page.wait_for_timeout(700)   # 留時間讓「不該送出的請求」真的送出來
            assert not saves, f"Bucket 沒填就不該送出儲存請求，實際送了 {saves}"

            if page.locator(f"{CLOUD_CARD} :text('Bucket 為必填')").count() == 0:
                print("（註）驗證訊息已自動消失，未能觀察到；本題以「請求未送出」為準")
        finally:
            browser.close()


@pytest.mark.e2e
def test_init_runs_exactly_once(live_server, make_user):
    """開一次頁面，設定 API 只能被打一次。

    `<body x-data="companyProfilePage()" x-init="init()">` —— Alpine 3 本來就會自動
    呼叫資料物件的 `init()`，`x-init` 再寫一次就**剛好跑兩遍**，而且完全沒有警告。
    兩遍的後果不只是多發一次請求：第二次 `_loadSysSettings()` 的回應晚一步抵達，
    會把使用者這段期間改過的欄位用伺服器上的舊值**無聲蓋回去**——這正是
    2026-09-11 這支檔案偶發紅（單檔連跑 5 輪卻全綠）的根因之一。

    跟 2026-09-11 第三輪在 `case-management.js` 修掉的是同一個坑；當時的紀錄就寫明
    「全站還有 50 個頁面是同樣寫法」，這是第二頁。

    **刻意數請求次數，而不是等競態自己重現**：競態要靠時序碰巧才看得到，
    次數是確定性的——修掉前一定是 2、修掉後一定是 1（實測過兩邊）。
    """
    username, password = make_user(username="e2e_sys5", role="superadmin")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            hits = []
            page.on("request", lambda r: hits.append(r.url)
                    if "/api/settings/backup-retention" in r.url else None)
            page.goto(f"{live_server}{PAGE}")
            page.wait_for_selector(RET_CARD, timeout=45000)
            page.wait_for_timeout(1200)   # 第二次 init 若存在，這段時間一定跑得完
            assert len(hits) == 1, (
                f"init() 應該只跑一次，實際打了 {len(hits)} 次設定 API"
                "（body 同時有 x-data 與 x-init 就會跑兩遍）")
        finally:
            browser.close()
