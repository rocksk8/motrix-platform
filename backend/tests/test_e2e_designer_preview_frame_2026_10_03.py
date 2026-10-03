# -*- coding: utf-8 -*-
"""D12 驗證發現的 bug（使用者）：請款類型頁按「預覽表單」後，預覽區最上面出現一條黑色橫帶，蓋住標題。
根因：預覽 iframe 載入 custom-records.html?preview=1；預覽模式 sidebar.js 不掛載頂欄內容，但頁面的 `#app-topbar` 空殼仍是 position:fixed 的黑色 60px 橫帶。
修法：`html[data-preview="1"]` 把 #app-topbar／#app-sidebar／.sidebar-overlay 藏起來。
本檔斷言（不只斷言存在）：① 預覽 frame 裡頂欄不可見（computed display:none）；② 預覽區最上面一段的像素是淺色（不是黑帶）；
③ 預覽標題在最上面、沒有被別的元素蓋住（elementFromPoint 命中標題本身）。headless。"""
import io

import pytest

pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.e2e

from tests._e2e_login import inject_login  # noqa: E402

FRESH = ("try { if (!sessionStorage.getItem('_d12_fresh')) { localStorage.removeItem('mb_designer'); localStorage.removeItem('et_designer');"
         " sessionStorage.setItem('_d12_fresh', '1'); } sessionStorage.setItem('_no_legacy_pin', '1'); } catch (e) {}")


@pytest.fixture()
def page(live_server, make_user, new_context):
    u = make_user(username="pf_sa", role="superadmin")
    pg = new_context(viewport={"width": 1500, "height": 1100}).new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(pg, live_server, u[0], u[1])
    pg.context.add_init_script(FRESH)
    pg.goto(live_server + "/pages/expense-types.html?key=travel")
    pg.wait_for_selector(".fd .fd-paper", state="visible", timeout=20000)
    pg.click("[data-testid=et-preview-btn]")
    pg.wait_for_selector("#et-preview iframe", timeout=15000)
    frame = pg.frame_locator("#et-preview iframe")
    frame.locator(".cr-main").wait_for(state="visible", timeout=20000)
    pg.wait_for_function("() => { const f = document.querySelector('#et-preview iframe'); return f && f.getBoundingClientRect().height > 200 }", timeout=15000)
    yield pg
    assert not errors, errors


def test_preview_frame_has_no_black_topbar_band(page):
    frame = [f for f in page.frames if f != page.main_frame][-1]
    assert frame.evaluate("() => getComputedStyle(document.getElementById('app-topbar')).display") == "none"
    assert frame.evaluate("() => getComputedStyle(document.getElementById('app-sidebar')).display") == "none"
    from PIL import Image
    page.set_viewport_size({"width": 1500, "height": 3200})                                              # 整頁都在視窗內：不捲動，外層固定頂欄不會疊到預覽區上
    page.wait_for_function("() => document.querySelector('#et-preview iframe').getBoundingClientRect().top > 70", timeout=10000)
    png = page.locator("#et-preview iframe").screenshot()
    im = Image.open(io.BytesIO(png)).convert("L")
    w, h = im.size
    band = [im.getpixel((x, y)) for y in range(2, 40, 4) for x in range(10, w - 10, max(1, w // 40))]
    assert sum(band) / len(band) > 180, "預覽區最上面一段太暗（黑帶？）平均亮度 %.0f" % (sum(band) / len(band))
    assert min(band) > 60, "預覽區最上面有接近全黑的像素（%d）" % min(band)


def test_preview_title_is_not_covered_by_anything(page):
    frame = [f for f in page.frames if f != page.main_frame][-1]
    hit = frame.evaluate("""() => {
        const t = document.querySelector('.cr-main h1, .cr-main h2, .cr-main .cr-title, .cr-main .cr-card h2, .cr-main [data-testid=cr-title]') || document.querySelector('.cr-main *');
        const r = t.getBoundingClientRect();
        const el = document.elementFromPoint(r.x + Math.min(10, r.width / 2), r.y + Math.min(6, r.height / 2));
        return { covered: !(el === t || t.contains(el) || (el && el.contains(t))), top: Math.round(r.y), tag: t.tagName + '.' + t.className, hit: el ? el.tagName + '#' + el.id : null };
    }""")
    assert not hit["covered"], hit
    assert hit["top"] < 120, hit                                                                         # 標題在最上面，沒有被頂欄推下去
