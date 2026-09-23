# -*- coding: utf-8 -*-
"""字級「特」：選單面板／簽核彈窗／側邊清單不可以超出畫面（1366×768）。

使用者：「部分使用者在字型用特大情況下，左右列表會無法閱讀，簽核跟選單在頁面外無法拖動」。
權威原文：`docs/windows/HANDOFF-PENDING-2026-09-23.md`「🟡 字級『特』」＋ A 2026-09-24 裁示。

# 成因（A 實測）

字級按鈕用 `document.documentElement.style.zoom`（小 0.85／標 1／大 1.15／特 1.3）。
根元素 zoom 會把 `vh`／`dvh` 一起乘上倍率 ⇒ 以視窗高度限高的 fixed 元素超出畫面，
fixed 不隨頁捲動 ⇒ 拖不到。修法：`--fz` ＝ 目前倍率，`Nvh` ⇒ `calc(Nvh / var(--fz,1))`。

# ⚠️ 已知未修（A 裁示）

`case-management.html`、`cashier.html`、`quotation-form.html` 三頁在並行視窗 hichan-8d 的
檔案領域內，等它合回 master 後再補 ⇒ 本檔**不量這三頁**。

# ⚙️ 對照組（A 加）

「標」（1.0）字級下，現有版面尺寸不變：彈窗高＝0.9×視窗高、側邊清單（詳情抽屜）高＝視窗高。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.test_voucher_preview_export_feedback_2026_09_23 import (  # noqa: E402,F401
    live_server, _login)

W, H = 1366, 768
ZOOMS = (0.85, 1.0, 1.15, 1.3)


def _page(p_, live_server, make_user, zoom, uname):
    u, pw_ = make_user(username=uname, role="superadmin", modules=["cashier"])
    _pending_voucher(u)
    browser = p_.chromium.launch()
    page = browser.new_page(viewport={"width": W, "height": H})
    page.add_init_script("localStorage.setItem('motrix_font_zoom', '%s')" % zoom)
    _login(page, live_server, u, pw_)
    return browser, page


def _pending_voucher(username):
    """一張待審核傳票，讓佇列有一筆可以點開詳情抽屜（右側清單）。"""
    import datetime as _dt
    import db
    now = _dt.datetime.now().isoformat()
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO vouchers_all (voucher_no, voucher_date, category, summary, status,"
            " created_by, created_at, updated_at, submitted_by, submitted_at, approval_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("FZ-0001", now[:10], "轉", "字級測試", "待審核", username, now, now, username, now,
             '{"tiers": [], "currentTier": 0, "requestedBy": "%s"}' % username))
        conn.commit()
    finally:
        conn.close()


def _queue(page, live_server):
    page.goto(live_server + "/pages/approval-queue.html")
    page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')"
                           " && Alpine.$data(document.querySelector('[x-data]'))", timeout=15000)
    card = page.locator(".aq-card:visible:has-text('FZ-0001'), .aq-qrow:visible:has-text('FZ-0001')").first
    card.wait_for(state="visible", timeout=15000)
    card.click()
    page.wait_for_selector(".aq-drawer", state="visible", timeout=10000)
    page.wait_for_timeout(300)


def _modal_rect(page):
    """簽核彈窗（佇列的 PDF 預覽窗，`height:90vh`）。直接打開 modal 量版面——
    正式的開法要先產生一份 PDF，而這一題量的是版面不是 PDF。"""
    page.evaluate("() => { Alpine.$data(document.querySelector('[x-data]')).previewModal = true }")
    page.wait_for_timeout(250)
    return page.evaluate("""() => {
        const ov = document.querySelector('[x-show="previewModal"]');
        const box = ov && ov.firstElementChild;
        const r = box.getBoundingClientRect();
        return {top: r.top, bottom: r.bottom, height: r.height, ih: innerHeight};
    }""")


def _queue_rect(page):
    """側邊清單＝佇列右側的詳情抽屜 `.aq-drawer`（fixed，top:0、bottom:0，內部捲動）。
    📌 更正留著：第一版量 `.main--queue`（沒有任何頁面在用的 class ⇒ null），
       第二版量 `.sidebar`（這一頁沒有 ⇒ rect 全是 0，**假綠**：0 ≤ 768 永遠成立）。
       ⇒ 下面加了「量尺」斷言：高度必須 > 0。"""
    return page.evaluate("""() => {
        const el = document.querySelector('.aq-drawer');
        const r = el.getBoundingClientRect();
        const tb = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--topbar-h')) || 0;
        return {bottom: r.bottom, height: r.height, ih: innerHeight, topbar: tb};
    }""")


def _menu_bottoms(page):
    """每一組頂端選單 hover 後，面板底邊（取最大）。"""
    out = []
    n = page.locator(".mnav__grp").count()
    for i in range(n):
        g = page.locator(".mnav__grp").nth(i)
        g.hover()
        page.wait_for_timeout(250)
        b = g.evaluate("g => { const p = g.querySelector('.mnav__panel');"
                       " return p ? p.getBoundingClientRect().bottom : 0 }")
        out.append(b)
    page.mouse.move(W // 2, H - 5)
    return out


@pytest.mark.e2e
@pytest.mark.parametrize("zoom", ZOOMS, ids=["小", "標", "大", "特"])
def test_fz_the_queue_modal_list_and_menus_stay_inside_the_viewport(live_server, make_user, zoom):
    with sync_playwright() as p_:
        browser, page = _page(p_, live_server, make_user, zoom, "fz_%d" % int(zoom * 100))
        try:
            _queue(page, live_server)
            q = _queue_rect(page)
            assert q["height"] > 100, "量尺：側邊清單沒有量到東西：%r" % q
            m = _modal_rect(page)
            page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]'));"
                          " d.previewModal = false; d.drawerOpen = false }")
            page.wait_for_timeout(250)
            menus = _menu_bottoms(page)
            print("字級 %.2f 實測（%d×%d）：側邊清單底 %.0f／彈窗底 %.0f／選單面板底 max %.0f"
                  % (zoom, W, H, q["bottom"], m["bottom"], max(menus or [0])))
            assert q["bottom"] <= H + 1, "字級 %.2f：佇列側邊清單底邊 %.0f 超出畫面 %d" % (zoom, q["bottom"], H)
            assert m["bottom"] <= H + 1, "字級 %.2f：簽核彈窗底邊 %.0f 超出畫面 %d" % (zoom, m["bottom"], H)
            assert max(menus or [0]) <= H + 1, (
                "字級 %.2f：選單面板底邊 %r 超出畫面 %d" % (zoom, [round(b) for b in menus], H))
        finally:
            browser.close()


@pytest.mark.e2e
def test_fz_the_standard_size_layout_is_unchanged(live_server, make_user):
    """對照組：「標」字級下，彈窗高＝0.9×視窗高、側邊清單（詳情抽屜）高＝視窗高（修法前後都一樣）。"""
    with sync_playwright() as p_:
        browser, page = _page(p_, live_server, make_user, 1.0, "fz_std")
        try:
            _queue(page, live_server)
            q = _queue_rect(page)
            assert q["height"] > 100, "量尺：側邊清單沒有量到東西：%r" % q
            m = _modal_rect(page)
            print("字級 1.00 對照：彈窗高 %.1f（0.9×%d＝%.1f）／側邊清單高 %.1f（視窗 %d）"
                  % (m["height"], H, 0.9 * H, q["height"], H))
            assert abs(m["height"] - 0.9 * H) < 1.5, m
            assert abs(q["height"] - H) < 1.5, q
        finally:
            browser.close()


@pytest.mark.e2e
def test_fz_switching_to_the_largest_size_on_the_page_also_fits(live_server, make_user):
    """按字級按鈕（`motrixSetZoom`）當場切到「特」——不是重新載入——彈窗一樣要在畫面內。
    ⚠️ 上面那題是載入前就設好字級（走 sidebar.js 初始化那一條），量不到這一條。"""
    with sync_playwright() as p_:
        browser, page = _page(p_, live_server, make_user, 1.0, "fz_switch")
        try:
            _queue(page, live_server)
            page.evaluate("() => window.motrixSetZoom(1.3)")
            page.wait_for_timeout(250)
            m = _modal_rect(page)
            print("字級 1.00 → 1.30（按鈕切換）實測：彈窗底 %.0f" % m["bottom"])
            assert m["bottom"] <= H + 1, "按鈕切到「特」後，簽核彈窗底邊 %.0f 超出畫面 %d" % (m["bottom"], H)
        finally:
            browser.close()
