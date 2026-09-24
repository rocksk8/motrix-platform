"""案件頁的切換鈕（.aq-sort）要有樣式，淺色與深色都看得清楚（W-5，2026-09-24 開發機實走發現）。

.aq-sort 只在簽核佇列頁定義過，案件頁從來沒有 ⇒ 矩陣排序、「多選」、常用篩選都是瀏覽器原生的灰框按鈕。
觀測點：計算後的樣式——不是瀏覽器預設（灰底 rgb(240,240,240)、直角）；選中（.on）時底色與字色對比足夠。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_case_page_golden_2026_09_24 import _seed, live_server  # noqa: F401  (live_server 是 fixture)

DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
STYLE = """(sel) => { const e = document.querySelector(sel); const s = getComputedStyle(e);
  return { bg: s.backgroundColor, fg: s.color, radius: s.borderTopLeftRadius, border: s.borderTopStyle } }"""


def _lum(rgb):
    p = [float(x) for x in rgb[rgb.index("(") + 1:rgb.index(")")].split(",")[:3]]
    f = [v / 255 for v in p]
    f = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in f]
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]


def _contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.e2e
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_toggle_buttons_are_styled_and_readable(live_server, make_user, theme):
    u = make_user(username=f"tgl_{theme}", role="superadmin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context()
            ctx.add_init_script(f"try {{ localStorage.setItem('motrix_theme', '{theme}') }} catch (e) {{}}")
            page = ctx.new_page()
            page.goto(f"{live_server}/pages/login.html")
            page.fill('input[x-model="username"]', u[0])
            page.fill('input[x-model="password"]', u[1])
            page.click('button:has-text("登入")')
            page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
            page.goto(f"{live_server}/pages/case-management.html")
            page.wait_for_function(f"() => {DATA_JS} && {DATA_JS}.caseCounts", timeout=20000)
            off = page.evaluate(STYLE, "[data-quick=mine]")
            assert off["bg"] != "rgb(240, 240, 240)" and off["radius"] != "0px" and off["border"] != "outset", off
            assert _contrast(off["fg"], off["bg"]) >= 3, off
            page.click("[data-quick=mine]")
            page.wait_for_timeout(500)
            on = page.evaluate(STYLE, "[data-quick=mine]")
            assert on["bg"] != off["bg"], ("選中與未選中看起來一樣", on, off)
            assert _contrast(on["fg"], on["bg"]) >= 4.5, ("選中時字看不清楚", on)
        finally:
            browser.close()
