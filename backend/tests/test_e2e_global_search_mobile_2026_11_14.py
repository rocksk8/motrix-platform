"""手機全域搜尋下拉不可超出畫面（T86 業務開發體驗審查 問題 8，2026-11-14）。

頂端列的全域搜尋下拉（sidebar.js 注入，每一頁都有）原本固定 340px 寬、靠搜尋框左緣，
390px 手機上搜尋框左緣約 102px ⇒ 右緣 442px 超出畫面、右側文字被切掉。

修法：≤767px 時改成 position:fixed、左右各留 8px、每個結果列至少 44px 高；桌機維持 340px。
觀測點：搜尋結果以攔截的 /api/search 回應固定（五個群組各一筆、其中一筆名稱很長），
量下拉與各結果列的實際位置與高度。正對照：桌機寬度下下拉仍是 340px（證明規則只作用在手機）。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from tests._e2e_login import inject_login  # noqa: E402

GLOBAL_SEARCH = "input[placeholder^='搜尋客戶']"
DROP = '[data-testid="gsearch-drop"]'

_RESULT = {
    "customers": [{"id": 1, "name": "測試客戶股份有限公司", "code": "C-001"}],
    "suppliers": [{"id": 1, "name": "測試供應商", "code": "S-001"}],
    "quotations": [{"quoteNo": "MQ-2611-001", "customerName": "測試客戶股份有限公司", "projectName": "這是一個名稱非常非常長的專案名稱用來確認下拉在手機上會換行而不是被切掉", "status": "草稿"}],
    "devCases": [{"id": 1, "caseName": "網路佈線　大安國小", "customerName": "大安國小", "status": "成案"}],
    "parts": [{"partNo": "P-001", "name": "測試料件", "brand": "BRAND"}],
}


def _open_search(browser, live_server, user, width, height, zoom=None, result=None):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    page = ctx.new_page()
    body = json.dumps(result or _RESULT)
    page.route("**/api/search?*", lambda route: route.fulfill(status=200, content_type="application/json", body=body))
    if zoom:
        page.add_init_script("try { localStorage.setItem('motrix_font_zoom', '%s') } catch (e) {}" % zoom)
    inject_login(page, live_server, user[0], user[1])
    page.goto(f"{live_server}/pages/quotations.html")
    page.wait_for_selector(GLOBAL_SEARCH, timeout=15000)
    page.locator(GLOBAL_SEARCH).first.fill("測試")
    page.locator(DROP).wait_for(state="visible", timeout=10000)
    return page


@pytest.mark.e2e
def test_mobile_search_dropdown_stays_inside_390px_viewport_with_44px_rows(live_server, make_user, e2e_browser):
    u = make_user(username="gsm_e1", role="admin")
    page = _open_search(e2e_browser, live_server, u, 390, 844)
    page.wait_for_function("() => document.querySelectorAll('[data-testid=\"gsearch-drop\"] .gs-item').length === 5", timeout=10000)
    box = page.evaluate("""() => { const r = document.querySelector('[data-testid="gsearch-drop"]').getBoundingClientRect();
                                   return { left: r.left, right: r.right, width: r.width } }""")
    assert box["left"] >= 0 and box["right"] <= 390, f"下拉超出 390 視窗：{box}"
    assert abs(box["left"] - 8) <= 1 and abs(box["right"] - 382) <= 1, f"手機下拉應左右各留 8px：{box}"
    heights = page.evaluate("""() => Array.from(document.querySelectorAll('[data-testid="gsearch-drop"] .gs-item'))
                                          .map(e => e.getBoundingClientRect().height)""")
    assert len(heights) == 5 and min(heights) >= 43.5, f"每個結果列至少 44px 高：{heights}"
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"), "開著下拉時整頁不可出現橫向捲動"


@pytest.mark.e2e
def test_desktop_search_dropdown_keeps_340px(live_server, make_user, e2e_browser):
    u = make_user(username="gsm_e2", role="admin")
    page = _open_search(e2e_browser, live_server, u, 1280, 800)
    width = page.evaluate("() => document.querySelector('[data-testid=\"gsearch-drop\"]').getBoundingClientRect().width")
    assert abs(width - 340) <= 1, f"桌機下拉維持 340px（正對照）：{width}"


@pytest.mark.e2e
def test_mobile_search_dropdown_bottom_stays_on_screen_at_biggest_font_zoom(live_server, make_user, e2e_browser):
    """字級「特」（1.3 倍）：根元素 zoom 會把 vh 一起放大，限高沒除回去的話，結果多時下拉底部掉到螢幕外。"""
    u = make_user(username="gsm_e3", role="admin")
    many = dict(_RESULT, customers=[{"id": i, "name": "測試客戶 %d" % i, "code": "C-%03d" % i} for i in range(1, 31)])
    page = _open_search(e2e_browser, live_server, u, 390, 844, zoom="1.3", result=many)
    page.wait_for_function("() => document.querySelectorAll('[data-testid=\"gsearch-drop\"] .gs-item').length >= 30", timeout=10000)
    page.wait_for_function("() => document.documentElement.style.getPropertyValue('--fz') === '1.3'", timeout=5000)
    # 不比座標（zoom 後 getBoundingClientRect 的單位因瀏覽器版本而異）：直接問「畫面最底下那一點是不是下拉」。
    # 限高沒除回去 ⇒ 下拉底部超出螢幕，最底下那一點還是下拉；修好之後下拉在螢幕內結束，最底下那一點是別的東西。
    hit = page.evaluate("""() => { const d = document.querySelector('[data-testid="gsearch-drop"]');
                                   const at = (y) => { const e = document.elementFromPoint(195, y); return !!(e && d.contains(e)) };
                                   return { mid: at(400), bottom: at(window.innerHeight - 3) } }""")
    assert hit["mid"], "下拉中段應該蓋在畫面上（30 筆結果）"
    assert not hit["bottom"], "字級特時下拉底部超出螢幕：畫面最底下那一點還是下拉"
