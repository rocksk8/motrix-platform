"""瀏覽器層級：深色模式下側欄「畫出來」真的是深色（2026-09-13 新增）。

**起因**：使用者回報「部分頁面在黑暗模式下，左側的選單列表是白背景」。根因是
15 頁把 `<aside class="sidebar">` 包進 `<div class="app-shell">`，而深色模式的反轉
排除清單是 `body > *:not(.sidebar)` 這種**直接子元素**選擇器——包一層就對不上，
被反轉的是容器，側欄整片跟著變白。詳見 `style.css`「DARK MODE」區塊的註解。

**為什麼一定要用截圖量像素**：`filter` 是繪製階段的效果，**不會改變 computed
style**——側欄被反轉成白底時，`getComputedStyle(sidebar).backgroundColor` 讀到的
仍然是 `rgb(17, 17, 17)`。也就是說「斷言 background-color 是深色」在 bug 還在的
情況下照樣會綠，是典型的假綠燈。唯一誠實的觀測點是最終畫面的像素。

**這支測試包含一個負向控制**（`test_probe_catches_the_original_regression`）：
在瀏覽器裡把側欄重新包回 `.app-shell` 重現當初的結構，量到的像素必須翻成亮色。
少了它，上面那支「量到是深色」有可能只是因為探針永遠讀到深色（例如量錯位置、
截到別的元素）而假綠。

結構前提本身由 `test_dark_mode_chrome_structure_2026_09_13.py` 每次都跑的靜態
掃描守著（涵蓋全部 51 頁）；這支只在有裝 playwright 時跑，抽樣驗證機制成立。
需要 `playwright`（見 `test_e2e_playwright_2026_09_07.py` 檔頭說明）。
"""
import io
import statistics
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
pytest.importorskip("PIL")
from PIL import Image
from playwright.sync_api import sync_playwright

import uvicorn

# 當初的 15 個受害頁（側欄被包在 .app-shell 裡）全部量一次，
# 外加一頁本來就正確的當對照組——對照組若也紅，代表問題不在這次的結構修正上。
SAMPLE_PAGES = [
    "access-guide.html",
    "automation-guide.html",
    "case-management.html",
    "dev-crm.html",
    "env-guide.html",
    "gateway-guide.html",
    "inventory.html",
    "monitor-guide.html",
    "netarch-guide.html",
    "parts.html",
    "procurement.html",
    "reports.html",
    # sales-orders.html 當天稍晚被改成導向頁（模組權限稽核，見
    # MODULE-AUDIT-2026-09-13.md），已經沒有側欄可以量——留在清單裡的話，
    # 測試會在導向後量到 case-management 的側欄，然後綠燈給一個根本沒測到的頁面。
    "selection-db-overview.html",
    "switch-guide.html",
    "customers.html",            # 對照組：一直都是 body 直下
]

# --sidebar 是 #111111（亮度 17）；被反轉會變成 #EEEEEE（亮度 238）。
# 兩者差 220，門檻放在 60/190 兩端，中間留很大的緩衝。
DARK_MAX = 60
BRIGHT_MIN = 190


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


def _sidebar_median_luminance(page):
    """截側欄這個元素，回傳所有像素亮度的中位數。

    用中位數而不是平均：選單文字/圖示是淺色的，佔比不大但會拉高平均；
    中位數取到的是面積最大的那個顏色，也就是背景本身。"""
    png = page.locator(".sidebar").screenshot()
    img = Image.open(io.BytesIO(png)).convert("RGB")
    raw = img.tobytes()   # 不用 getdata()：Pillow 12 起已標記淘汰
    lums = [round(0.299 * raw[i] + 0.587 * raw[i + 1] + 0.114 * raw[i + 2])
            for i in range(0, len(raw), 3)]
    return statistics.median(lums)


def _open_dark(page, base_url, page_name):
    page.goto(f"{base_url}/pages/{page_name}")
    page.wait_for_selector(".sidebar .nav__item", timeout=10000)
    # 側欄是 sidebar.js 注入的，注入後還要等一次繪製才截得到穩定畫面
    page.wait_for_timeout(150)


@pytest.mark.e2e
def test_sidebar_paints_dark_in_dark_mode(live_server, make_user):
    """深色模式下，四頁的側欄背景實際畫出來都必須是深色。"""
    username, password = make_user(username="e2e_dark", role="superadmin")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        # 深色模式存在 localStorage，各頁 <head> 的同步腳本會在頁面腳本之前讀它
        context.add_init_script(
            "try { localStorage.setItem('motrix_theme', 'dark') } catch (e) {}")
        page = context.new_page()
        try:
            _login(page, live_server, username, password)

            offenders = []
            for name in SAMPLE_PAGES:
                _open_dark(page, live_server, name)
                assert page.evaluate(
                    "document.documentElement.getAttribute('data-theme')") == "dark", (
                    f"{name}：深色模式沒有生效，這次量到的顏色不能代表任何事")
                lum = _sidebar_median_luminance(page)
                if lum > DARK_MAX:
                    offenders.append(f"{name}: 側欄背景亮度 {lum}（深色應 ≤ {DARK_MAX}）")

            assert not offenders, (
                "深色模式下這些頁面的側欄被畫成亮底：\n  " + "\n  ".join(offenders)
                + "\n通常是 .sidebar 又被包進某個容器，導致 style.css 的反轉排除清單"
                  "（body > *:not(.sidebar)）對不上。")
        finally:
            browser.close()


@pytest.mark.e2e
def test_probe_catches_the_original_regression(live_server, make_user):
    """負向控制：把側欄重新包回 .app-shell，上面那支測試的探針必須翻成亮色。

    這證明兩件事——探針量得到差異（不是永遠回深色的假綠燈），以及「包一層容器」
    確實就是使用者看到白色側欄的原因。"""
    username, password = make_user(username="e2e_dark_ctl", role="superadmin")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_init_script(
            "try { localStorage.setItem('motrix_theme', 'dark') } catch (e) {}")
        page = context.new_page()
        try:
            _login(page, live_server, username, password)
            _open_dark(page, live_server, "reports.html")

            before = _sidebar_median_luminance(page)
            assert before <= DARK_MAX, f"修好的狀態就該是深色，卻量到 {before}"

            # 重現當初的結構：body > .app-shell > .sidebar
            page.evaluate("""() => {
                const sb = document.querySelector('.sidebar')
                const shell = document.createElement('div')
                shell.className = 'app-shell'
                sb.parentNode.insertBefore(shell, sb)
                shell.appendChild(sb)
            }""")
            page.wait_for_timeout(150)

            after = _sidebar_median_luminance(page)
            assert after >= BRIGHT_MIN, (
                f"把側欄包回 .app-shell 之後應該被反轉成亮底（≥ {BRIGHT_MIN}），"
                f"實際量到 {after}——表示這支探針或那條 CSS 規則跟預期不一樣，"
                f"上面那支『量到是深色』的測試也就不能當成證據。")
        finally:
            browser.close()
