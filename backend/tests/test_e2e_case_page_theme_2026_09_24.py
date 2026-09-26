"""案件管理頁淺色／深色（CM12 P3，2026-09-24）。

P3 起案件頁讀語意 token、深色模式退出全站反轉（直接吃深色 token）。守的是：
① 深色模式逐分頁掃描：案件頁可見元素沒有淺色底塊（亮度 > 0.6）、沒有「深底上的近黑文字」，
   案件頁容器本身不再套反轉濾鏡（否則深色 token 被再反轉一次變回淺色）
② 淺色與深色各一組關鍵元素的 computed style golden（顏色、底色、框線色、字級）——P3 套用後錄製，
   之後改樣式要有意識地重錄（GOLDEN_WRITE=1）
種子資料與 golden 行為題相同（多狀態案件，每個分頁都有內容）。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
import os
import pathlib
import time

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402
from tests.test_e2e_case_page_golden_2026_09_24 import NO, _seed  # noqa: F401  (live_server 是 fixture)

#: O5-S1：本檔量版面／字級（getBoundingClientRect 等）⇒ 要真字型，不吃 conftest 的字型替身
pytestmark = pytest.mark.real_fonts
pytestmark = [*(pytestmark if isinstance(pytestmark, list) else [pytestmark]), requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')]

GOLDEN = pathlib.Path(__file__).with_name("golden_case_page_theme_2026_09_24.json")
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"

# 關鍵元素（每個選第一個可見的）
KEY_SELECTORS = [
    ".cm-list", ".cm-list__title", ".cm-list__tab.active", ".cm-list__tab:not(.active)", ".cm-card.selected",
    ".cm-card:not(.selected)", ".cm-card__tag", ".cm-card__stageprog", ".cm-list__search-input",
    ".cm-header", ".btn-save", ".cm-more__btn", ".cm-tab.active", ".cm-tab:not(.active)",
    "[data-testid=case-health]", ".cm-section-title", ".fi", ".vm-lamp", ".cm-body",
]

SCAN_JS = r"""() => {
  const lum = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null
    const p = m[1].split(',').map(s => parseFloat(s))
    if (p.length === 4 && p[3] < 0.5) return null            // 近乎透明：不算底色
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
    return 0.2126 * f(p[0]) + 0.7152 * f(p[1]) + 0.0722 * f(p[2])
  }
  const effBg = (el) => { for (let e = el; e; e = e.parentElement) { const l = lum(getComputedStyle(e).backgroundColor); if (l !== null) return l } return 0 }
  const roots = [...document.body.children].filter(e => !e.matches('.topbar,.mnav,.sidebar,.sidebar-overlay,script,style,.mui-root'))
  const bad = [], filters = []
  for (const r of roots) {
    const f = getComputedStyle(r).filter
    if (f && f !== 'none' && r.getClientRects().length) filters.push(r.className || r.tagName)
    for (const el of r.querySelectorAll('*')) {
      if (!el.getClientRects().length) continue
      const cs = getComputedStyle(el)
      if (cs.visibility === 'hidden' || cs.display === 'none' || el.closest('svg,.gantt-container,img,video,canvas')) continue
      const rect = el.getBoundingClientRect()
      // 燈號、進度條、階段條等小型指示色塊：亮色是語意（綠／琥珀），不是白塊
      const tiny = rect.width * rect.height < 400 || rect.height <= 10 || rect.width <= 8 || el.matches('.cm-mtx__spine')
      const bl = tiny ? null : lum(cs.backgroundColor)
      const label = (el.className && el.className.baseVal === undefined ? el.className : el.tagName) + ' ' + (el.innerText || '').trim().slice(0, 20)
      if (bl !== null && bl > 0.6) bad.push('淺底 ' + cs.backgroundColor + ' ｜ ' + label)
      const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
      if (hasText) {
        const tl = lum(cs.color)
        if (tl !== null && tl < 0.15 && effBg(el) < 0.3) bad.push('深底黑字 ' + cs.color + ' ｜ ' + label)
      }
    }
  }
  // 頁框（主導覽列）不屬於本頁內容：深色仍靠全站反轉，不可以被本頁的解除規則一起解除
  const nav = document.querySelector('body > .mnav')
  if (nav && getComputedStyle(nav).filter === 'none') filters.push('mnav 失去反轉（頁框被本頁規則誤傷）')
  return { bad: [...new Set(bad)], filters }
}"""

STYLE_JS = r"""(sels) => {
  const out = {}
  for (const s of sels) {
    const el = [...document.querySelectorAll(s)].find(e => e.getClientRects().length)
    if (!el) { out[s] = null; continue }
    const cs = getComputedStyle(el)
    out[s] = { color: cs.color, background: cs.backgroundColor, border: cs.borderTopColor, fontSize: cs.fontSize }
  }
  return out
}"""


def _open(browser, base, user, theme):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    ctx.add_init_script(f"try {{ localStorage.setItem('motrix_theme', '{theme}') }} catch (e) {{}}")
    page = ctx.new_page()
    page.on("dialog", lambda d: d.dismiss())
    inject_login(page, base, user[0], user[1])
    page.goto(f"{base}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}' && {DATA_JS}.caseCounts",
                           timeout=20000)
    page.wait_for_timeout(1200)
    return page


def _each_tab(page, fn):
    tabs = page.locator(".cm-tabs > .cm-tab")
    for i in range(tabs.count()):
        if tabs.nth(i).is_visible():
            tabs.nth(i).click()
            page.wait_for_timeout(700)
            fn(tabs.nth(i).inner_text().strip())


@pytest.mark.e2e
def test_dark_mode_has_no_light_blocks_or_black_text(live_server, make_user, e2e_browser):
    u = make_user(username="golden_su", role="superadmin")
    _seed()
    problems = {}
    browser = e2e_browser
    page = _open(browser, live_server, u, "dark")
    assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") == "dark"

    def scan(label):
        r = page.evaluate(SCAN_JS)
        assert not r["filters"], f"案件頁容器仍套著反轉濾鏡：{r['filters']}"
        if r["bad"]:
            problems[label] = r["bad"][:15]
    scan("清單＋案件資訊")
    _each_tab(page, scan)
    # 執行管理的子分頁
    page.locator(".cm-tabs > .cm-tab").nth(1).click()
    sub_js = ("(i) => { const b = [...document.querySelectorAll('button.cm-tab')]"
              ".filter(e => (e.getAttribute('@click') || '').startsWith('execSubTab'));"
              " if (i == null) return b.length; b[i].click() }")
    for j in range(page.evaluate(sub_js)):
        page.evaluate(sub_js, j)
        page.wait_for_timeout(500)
        scan(f"執行子分頁 {j}")
    # 看板、矩陣
    for label in ("看板", "矩陣", "清單"):
        page.click(f".cm-view-toggle button:text-is('{label}'):visible")
        page.wait_for_timeout(900)
        scan(label)
    # 各種視窗
    for label, js, sel in (
        ("結案檢查", f"() => {DATA_JS}.closeCaseAction()", "[data-testid=close-check]"),
        ("新增派工", f"() => {{ const c = {DATA_JS}; c.activeTab = 'dispatch'; c.openNewDispatch() }}", None),
        ("新增出貨單", f"() => {{ const c = {DATA_JS}; c.showDispatchModal = false; c.activeTab = 'shipping'; c.openNewShippingNote() }}", None),
    ):
        page.evaluate(js)
        page.wait_for_timeout(900)
        scan(label)
        page.keyboard.press("Escape")
    assert not problems, "深色模式有淺色塊或深底黑字：\n" + json.dumps(problems, ensure_ascii=False, indent=1)


@pytest.mark.e2e
def test_light_and_dark_computed_style_golden(live_server, make_user, e2e_browser):
    u = make_user(username="golden_su", role="superadmin")
    _seed()
    got = {}
    browser = e2e_browser
    for theme in ("light", "dark"):
        page = _open(browser, live_server, u, theme)
        got[theme] = page.evaluate(STYLE_JS, KEY_SELECTORS)
        page.context.close()
    for theme in got:
        missing = [s for s, v in got[theme].items() if v is None]
        assert not missing, f"{theme}：找不到可見元素 {missing}"
    if os.environ.get("GOLDEN_WRITE") == "1":
        GOLDEN.write_text(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        pytest.skip("已寫入 " + GOLDEN.name)
    exp = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for theme in ("light", "dark"):
        for s in KEY_SELECTORS:
            assert got[theme][s] == exp[theme][s], f"{theme} {s}：{got[theme][s]} ≠ {exp[theme][s]}"
    # 淺深兩組不可以相同（深色真的有生效）
    assert got["light"][".cm-body"] != got["dark"][".cm-body"] or got["light"][".cm-card:not(.selected)"] != got["dark"][".cm-card:not(.selected)"]
