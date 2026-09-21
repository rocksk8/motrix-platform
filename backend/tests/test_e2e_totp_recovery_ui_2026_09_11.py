"""瀏覽器層級端對端測試：「修改密碼」頁的救援碼存量與重新產生（2026-09-11）。

**為什麼要真的開瀏覽器**：這一區全靠 Alpine 的 `x-show`／`x-if` 綁定，寫錯
（打錯欄位名、`template` 少一層）不會有任何錯誤訊息，整塊就是安靜地不顯示——
API 測試全綠也完全看不出來。本專案已經在同一個坑裡摔過兩次（WebAuthn 設定頁、
叫料），所以新的自助功能一律補一支端到端。

涵蓋：存量顯示 → 低於門檻時變色示警 → 重新產生（需密碼）→ 新碼顯示 →
文案有講「舊的全部失效」。

需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import pyotp
import uvicorn
from tests._ports import free_safe_port

CARD = ".card:has-text('兩步驟驗證')"


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


def _session_token(page):
    return page.evaluate("() => JSON.parse(localStorage.getItem('motrix_session') || '{}').token")


def _enable_totp_via_api(page, base_url, token):
    """先用瀏覽器登入拿 session，再走 API 把 TOTP 啟用起來。

    刻意不用畫面操作啟用：那段流程要掃 QR code，在測試裡沒有意義，而這支
    測試要驗的是「啟用之後」那一塊。"""
    h = {"Authorization": f"Bearer {token}"}
    r = page.request.post(f"{base_url}/api/auth/totp/setup", headers=h)
    assert r.ok, r.text()
    secret = r.json()["secret"]
    r2 = page.request.post(f"{base_url}/api/auth/totp/enable", headers=h,
                           data={"code": pyotp.TOTP(secret).now()})
    assert r2.ok, r2.text()
    return secret, r2.json()["recoveryCodes"]


def _burn_one_recovery_code(page, base_url, username, password, code):
    """走真實登入路徑用掉一組救援碼。"""
    r1 = page.request.post(f"{base_url}/api/auth/login",
                           data={"username": username, "password": password})
    r2 = page.request.post(f"{base_url}/api/auth/login/totp",
                           data={"challenge_token": r1.json()["challengeToken"], "code": code})
    assert r2.ok, r2.text()


@pytest.mark.e2e
def test_recovery_remaining_and_regenerate_flow(live_server, make_user):
    username, password = make_user(username="e2e_totp", role="admin")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            _login(page, live_server, username, password)
            token = _session_token(page)
            assert token, "登入後 localStorage 應該有 session"
            _secret, old_codes = _enable_totp_via_api(page, live_server, token)
            # 先用掉一組：實際值變 9，而前端的初始預設值是 10。兩者不同才分得出
            # 「真的從 API 載到」跟「載入失敗、畫面顯示的是預設值」——兩者都是 10 的話，
            # 斷言永遠會過（實測過：把 API 欄位名打錯，這支測試照樣綠燈）。
            _burn_one_recovery_code(page, live_server, username, password, old_codes[0])

            page.goto(f"{live_server}/pages/change-password.html")
            page.wait_for_selector(f"{CARD} .totp-badge:text-is('已啟用')", timeout=20000)

            card = page.locator(CARD)
            assert "救援碼剩餘" in card.inner_text()
            # 針對那個數字本身斷言，不能只看「9」有沒有出現在卡片裡——
            # 「/ 10 組」是靜態文字，綁定壞掉也還在
            assert page.locator(f"{CARD} .recovery-remaining").inner_text().strip() == "9"

            # 重新產生：要先展開、輸入密碼
            page.click(f"{CARD} button:has-text('重新產生救援碼')")
            page.wait_for_selector(f"{CARD} :text('目前這 10 組全部失效')", timeout=10000)
            page.fill(f"{CARD} input[type='password']", password)
            page.click(f"{CARD} button:has-text('確認重新產生')")

            # 新碼一次性顯示，且文案講明舊的失效（不是「已啟用！」那句）
            page.wait_for_selector(f"{CARD} :text('舊的那一批現在全部失效')", timeout=15000)
            codes_shown = page.locator(f"{CARD} .recovery-code").all_inner_texts()
            assert len(codes_shown) == 10, codes_shown
            assert not (set(c.strip() for c in codes_shown) & set(old_codes)), \
                "畫面上顯示的應該是新碼，不是舊碼"

            # 收掉畫面後回到已啟用狀態，存量回到 10
            page.click(f"{CARD} button:has-text('我已儲存救援碼')")
            page.wait_for_selector(f"{CARD} button:has-text('重新產生救援碼')", timeout=10000)
            # 9 → 10：順便釘住「重產之後存量真的有跟著更新」
            assert page.locator(f"{CARD} .recovery-remaining").inner_text().strip() == "10"

            assert not errors, f"頁面有 JS 錯誤：{errors}"
        finally:
            browser.close()


@pytest.mark.e2e
def test_low_remaining_shows_warning(live_server, make_user):
    """剩 2 組以下要跳紅字警告——這是整個功能存在的理由，沒警告就等於沒做。"""
    username, password = make_user(username="e2e_totp2", role="admin")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            _login(page, live_server, username, password)
            token = _session_token(page)
            _secret, codes = _enable_totp_via_api(page, live_server, token)

            # 直接把救援碼消到剩 2 組：走真實登入路徑用掉 8 組
            for c in codes[:8]:
                r1 = page.request.post(f"{live_server}/api/auth/login",
                                       data={"username": username, "password": password})
                ch = r1.json()["challengeToken"]
                r2 = page.request.post(f"{live_server}/api/auth/login/totp",
                                       data={"challenge_token": ch, "code": c})
                assert r2.ok, r2.text()

            page.goto(f"{live_server}/pages/change-password.html")
            page.wait_for_selector(f"{CARD} .totp-badge:text-is('已啟用')", timeout=20000)
            text = page.locator(CARD).inner_text()
            assert "救援碼剩餘" in text
            assert page.locator(f"{CARD} .recovery-remaining").inner_text().strip() == "2"
            assert "用完之後" in text, f"剩 2 組應該要跳紅字警告，實際畫面：{text[:300]}"
        finally:
            browser.close()
