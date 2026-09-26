"""案件頁的切換鈕（.aq-sort）要有樣式，淺色與深色都看得清楚（W-5，2026-09-24 開發機實走發現）。

.aq-sort 只在簽核佇列頁定義過，案件頁從來沒有 ⇒ 矩陣排序、「多選」、常用篩選都是瀏覽器原生的灰框按鈕。
觀測點：計算後的樣式——不是瀏覽器預設（灰底 rgb(240,240,240)、直角）；選中（.on）時底色與字色對比足夠。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests.test_e2e_case_page_golden_2026_09_24 import _seed  # noqa: F401  (live_server 是 fixture)
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

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
def test_toggle_buttons_are_styled_and_readable(live_server, make_user, theme, e2e_browser):
    u = make_user(username=f"tgl_{theme}", role="superadmin")
    _seed()
    browser = e2e_browser
    ctx = browser.new_context()
    ctx.add_init_script(f"try {{ localStorage.setItem('motrix_theme', '{theme}') }} catch (e) {{}}")
    page = ctx.new_page()
    inject_login(page, live_server, u[0], u[1])
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
