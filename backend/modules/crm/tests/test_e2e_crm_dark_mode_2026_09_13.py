"""瀏覽器端對端：業務開發列表在深色模式下的面板配色。

（2026-09-26 自 tests/test_e2e_dark_mode_sidebar_2026_09_13.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
瀏覽器層級：深色模式下頁面外框（頂欄＋主導覽列）「畫出來」真的是深色。

**起因（2026-09-13）**：使用者回報「部分頁面在黑暗模式下，左側的選單列表是白背景」。
根因是 15 頁把 `<aside class="sidebar">` 包進 `<div class="app-shell">`，而深色模式的
反轉排除清單是 `body > *:not(.sidebar)` 這種**直接子元素**選擇器——包一層就對不上，
被反轉的是容器，側欄整片跟著變白。詳見 `style.css`「DARK MODE」區塊的註解。

**2026-09-14 側欄退役**：導覽整組搬到上方（`--sidebar-w: 0`，且 `style.css` 有
`.sidebar, .sidebar-overlay, .sidebar-toggle { display: none !important }`），這支測試
原本量的 `.sidebar` 已經不會被畫出來，三支測試裡有兩支因此紅了一輪沒人發現
（第七輪的驗收只跑了靜態掃描那支）。觀測點搬到現在真的會畫出來的兩個元素，
**測的是同一件事**：

  `.topbar`  深色底、**在**排除清單裡 → 兩種模式都該維持深色。
             這是原本 `.sidebar` 的直接對應物：一旦被包進任何容器，排除就失效、
             整條會被反轉成亮底，跟當初使用者看到的白側欄是同一個 bug class。
  `.mnav`    白底、**不在**排除清單裡 → 深色模式下應該被反轉成深底。
             它是 `<body>` 直接子元素（`sidebar.js` 插在 `#app-topbar` 之後），
             會被反轉是正確的，跟內容區一致。

**為什麼一定要用截圖量像素**：`filter` 是繪製階段的效果，**不會改變 computed
style**——頂欄被反轉成白底時，`getComputedStyle(topbar).backgroundColor` 讀到的
仍然是 `rgb(17, 17, 17)`。也就是說「斷言 background-color 是深色」在 bug 還在的
情況下照樣會綠，是典型的假綠燈。唯一誠實的觀測點是最終畫面的像素。

**這支測試包含一個負向控制**（`test_probe_catches_the_original_regression`）：
在瀏覽器裡把頂欄包進 `.app-shell` 重現當初的結構，量到的像素必須翻成亮色。
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

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port

# 當初的 15 個受害頁（側欄被包在 .app-shell 裡）全部量一次，外加一頁本來就
# 正確的當對照組。側欄退役後這份清單量的是各頁的頂欄與主導覽列——頁面本身
# 仍然是有意義的抽樣（它們是當初唯一出過事的那批頁面結構）。
SAMPLE_PAGES = [
    "case-management.html",
    "dev-crm.html",
    "inventory.html",
    "parts.html",
    "procurement.html",
    "reports.html",
    # sales-orders.html 當天稍晚被改成導向頁（模組權限稽核，見
    # MODULE-AUDIT-2026-09-13.md），已經沒有側欄可以量——留在清單裡的話，
    # 測試會在導向後量到 case-management 的側欄，然後綠燈給一個根本沒測到的頁面。
    "customers.html",            # 對照組：一直都是 body 直下
]

# --sidebar / .topbar 是 #111111（亮度 17）；被反轉會變成 #EEEEEE（亮度 238）。
# .mnav 反過來：白底 #FFFFFF（255）被反轉成近黑。兩端都差 220 以上，
# 門檻放在 60/190，中間留很大的緩衝。
DARK_MAX = 60
BRIGHT_MIN = 190


def _login(page, base_url, username, password):
    inject_login(page, base_url, username, password)


def _median_luminance(page, selector):
    """截某個元素，回傳所有像素亮度的中位數。

    用中位數而不是平均：選單文字/圖示跟背景反差很大、佔比不大但會拉動平均；
    中位數取到的是面積最大的那個顏色，也就是背景本身。"""
    png = page.locator(selector).screenshot()
    img = Image.open(io.BytesIO(png)).convert("RGB")
    raw = img.tobytes()   # 不用 getdata()：Pillow 12 起已標記淘汰
    lums = [round(0.299 * raw[i] + 0.587 * raw[i + 1] + 0.114 * raw[i + 2])
            for i in range(0, len(raw), 3)]
    return statistics.median(lums)


def _open_dark(page, base_url, page_name):
    page.goto(f"{base_url}/pages/{page_name}")
    # 2026-09-14：原本等的是 `.sidebar .nav__item`，側欄退役後那個選擇器永遠
    # 等不到（display:none 的元素不算 visible），改等上方導覽列的分組標題。
    page.wait_for_selector(".mnav .mnav__top", timeout=10000)
    # 導覽是 sidebar.js 注入的，注入後還要等一次繪製才截得到穩定畫面
    page.wait_for_timeout(150)


@pytest.mark.e2e
def test_dev_crm_list_panel_paints_dark(live_server, make_user, e2e_browser):
    """業務開發的左側案件列表在深色模式下要是深的（2026-09-14 使用者回報）。

    這頁原本自己寫了 11 條 `:root[data-theme="dark"]` 手寫深色覆寫，被全站的反轉
    濾鏡再翻一次 → 整片變白。**這種錯誤只有量像素看得到**：computed style 讀到的
    是作者寫的 `#1A1A1A`（看起來完全正確），畫出來卻是 `#E5E5E5`。

    結構面的守門在 `test_dark_mode_chrome_structure_2026_09_13.py`
    （掃頁面有沒有自己的深色色票），這裡是最終畫面的驗收。
    """
    username, password = make_user(username="e2e_dark_dc", role="superadmin")
    browser = e2e_browser
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_init_script(
        "try { localStorage.setItem('motrix_theme', 'dark') } catch (e) {}")
    page = context.new_page()
    _login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/dev-crm.html")
    page.wait_for_selector(".dc-list", timeout=10000)
    page.wait_for_timeout(200)
    median = _median_luminance(page, ".dc-list")
    assert median <= DARK_MAX, (
        f"業務開發的案件列表在深色模式下亮度 {median}（深色應 ≤ {DARK_MAX}）"
        f"——通常是頁面自己寫了 :root[data-theme=\"dark\"] 的深色覆寫，被反轉成淺色")
