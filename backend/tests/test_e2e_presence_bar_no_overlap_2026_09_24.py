"""瀏覽器端對端：同時編輯提示條不可以蓋住頁面內容（W-1，2026-09-24 hichan-a3 實走開發機找到）。

#motrix-presence-bar（static/edit-presence.js）是 position:fixed、top=--topbar-h、z-index 400。
原本它疊在內容上面，第二個人打開同一件案件時，案件頁標頭的「儲存」「更多」被它蓋住
（1440／1024 寬 elementFromPoint 取到的都是提示條）。修法：提示條顯示時把高度加進 --topbar-h
（全站用它讓出上方空間），隱藏時還原；提示條本身用顯示前的原值定位。
觀測點：按鈕中心點的 elementFromPoint 必須是按鈕本身（或它的子元素）。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_case_concurrent_edit_2026_09_24 import DATA_JS, NO, _login, _seed, live_server  # noqa: F401

HIT_JS = """(sel) => {
  const b = document.querySelector(sel)
  if (!b) return 'missing'
  const r = b.getBoundingClientRect()
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
  return hit && (hit === b || b.contains(hit)) ? 'button' : (hit ? (hit.id || hit.className || hit.tagName) : 'none')
}"""



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。
    ⚠️ 只適用於沒有 CSS transition 的元素（有 transition 的要等轉場落定）。"""
    page.evaluate("() => new Promise(r => (window.Alpine ? Alpine.nextTick : (f => f()))(() => requestAnimationFrame(() => requestAnimationFrame(r))))")

def _open(browser, base, user, width, before_goto=None):
    page = browser.new_context(viewport={"width": width, "height": 900}).new_page()
    page.on("dialog", lambda d: d.accept())
    _login(page, base, *user)
    if before_goto:
        before_goto(page)
    page.goto(f"{base}/pages/case-management.html?q={NO}")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'", timeout=20000)
    return page


@pytest.mark.e2e
@pytest.mark.parametrize("width", [1440, 1024])
def test_presence_bar_does_not_cover_the_save_button(live_server, make_user, width):
    a = make_user(username=f"pb_a{width}", role="admin")
    b = make_user(username=f"pb_b{width}", role="admin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pa = _open(browser, live_server, a, width)
            pb = _open(browser, live_server, b, width)
            # 第二個人進來時 A 已在編 ⇒ B 會看到提示條（與主動跳出的提示框；先關掉提示框）
            pb.wait_for_function("() => { const e = document.getElementById('motrix-presence-bar');"
                                 " return e && getComputedStyle(e).display !== 'none' }", timeout=15000)
            pb.evaluate("() => document.querySelectorAll('#motrix-presence-modal button, .mp-modal button')"
                        ".forEach(b => b.click())")
            pb.keyboard.press("Escape")
            _rendered(pb)   # PERF #6：原本固定等 300ms
            for sel in (".cm-header .btn-save", '[data-testid="cm-more"]'):
                assert pb.evaluate(HIT_JS, sel) == "button", (width, sel, pb.evaluate(HIT_JS, sel))
            # 提示條本身要看得到、不能被推到內容底下
            bar = pb.evaluate("() => { const r = document.getElementById('motrix-presence-bar').getBoundingClientRect();"
                              " return [r.top, r.height] }")
            assert bar[1] > 0 and bar[0] >= 0
            # 對方離開 ⇒ 提示條消失、讓出的空間還原（不可以永遠多空一條）
            # page.close() 預設不觸發 beforeunload（不會送出釋放）⇒ 讓 A 正常離開
            # PERF #6：原本固定等 300ms ⇒ 等釋放請求（DELETE /api/edit-presence）真的送完再關頁
            with pa.expect_event("requestfinished", lambda r: r.method == "DELETE" and "/api/edit-presence" in r.url,
                                 timeout=10000):
                pa.evaluate("() => window.MotrixPresence.stop()")
            pa.close()
            pb.evaluate("() => window.MotrixPresence.refresh()")
            pb.wait_for_function("() => getComputedStyle(document.getElementById('motrix-presence-bar')).display === 'none'",
                                 timeout=15000)
            v = pb.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--topbar-h').trim()")
            assert v == "104px", v
        finally:
            browser.close()


@pytest.mark.e2e
def test_without_presence_the_layout_is_unchanged(live_server, make_user):
    """沒有提示條時 --topbar-h 維持原值（不可以永遠多空一條）。"""
    a = make_user(username="pb_solo", role="admin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            # PERF #6：原本固定等 800ms ⇒ 等第一次心跳（POST /api/edit-presence）回來——
            # 提示條要不要出現、要不要讓出空間，都是那一趟回來之後才決定（監聽在 goto 之前掛上，不會漏接）
            beats = []
            pa = _open(browser, live_server, a, 1440, before_goto=lambda pg: pg.on(
                "requestfinished", lambda r: beats.append(1) if r.method == "POST" and "/api/edit-presence" in r.url else None))
            for _ in range(200):
                if beats:
                    break
                pa.wait_for_timeout(50)   # 輪詢（L 類）：等到心跳回來就走
            assert beats, "20 秒內沒有送出同時編輯的心跳——這一題量不到它要量的東西"
            _rendered(pa)
            v = pa.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--topbar-h').trim()")
            assert v == "104px", v
        finally:
            browser.close()


@pytest.mark.e2e
def test_presence_bar_does_not_cover_quotation_form_toolbar(live_server, make_user):
    """其他 4 個有提示條的頁面走同一支 edit-presence.js；報價單最常用，驗它的「儲存草稿」。"""
    from tests.test_e2e_quote_number_input_2026_09_24 import QUOTE_NO, _seed as _seed_quote
    a = make_user(username="pb_qa", role="superadmin")
    b = make_user(username="pb_qb", role="superadmin")
    _seed_quote()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pages = []
            for u in (a, b):
                pg = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
                pg.on("dialog", lambda d: d.accept())
                _login(pg, live_server, *u)
                pg.goto(f"{live_server}/pages/quotation-form.html?id={QUOTE_NO}")
                pg.wait_for_function("() => document.body.innerText.includes('解析客戶')", timeout=20000)
                pages.append(pg)
            pb = pages[1]
            pb.wait_for_function("() => { const e = document.getElementById('motrix-presence-bar');"
                                 " return e && getComputedStyle(e).display !== 'none' }", timeout=15000)
            pb.evaluate("() => document.querySelectorAll('#motrix-presence-modal button').forEach(b => b.click())")
            _rendered(pb)   # PERF #6：原本固定等 300ms
            hit = pb.evaluate("""() => {
              const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('儲存草稿') && x.offsetParent)
              if (!b) return 'missing'
              const r = b.getBoundingClientRect()
              const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
              return h && (h === b || b.contains(h)) ? 'button' : (h ? (h.id || h.className || h.tagName) : 'none')
            }""")
            assert hit == "button", hit
        finally:
            browser.close()
