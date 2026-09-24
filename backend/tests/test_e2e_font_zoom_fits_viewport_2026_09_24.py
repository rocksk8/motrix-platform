# -*- coding: utf-8 -*-
"""字級「特」：選單面板／簽核彈窗／側邊清單不可以超出畫面（1366×768）。

使用者：「部分使用者在字型用特大情況下，左右列表會無法閱讀，簽核跟選單在頁面外無法拖動」。
權威原文：`docs/windows/HANDOFF-PENDING-2026-09-23.md`「🟡 字級『特』」＋ A 2026-09-24 裁示。

# 成因（A 實測）

字級按鈕用 `document.documentElement.style.zoom`（小 0.85／標 1／大 1.15／特 1.3）。
根元素 zoom 會把 `vh`／`dvh` 一起乘上倍率 ⇒ 以視窗高度限高的 fixed 元素超出畫面，
fixed 不隨頁捲動 ⇒ 拖不到。修法：`--fz` ＝ 目前倍率，`Nvh` ⇒ `calc(Nvh / var(--fz,1))`。

# 📌 更正留著：三頁補完（2026-09-24）

原本「`case-management.html`、`cashier.html`、`quotation-form.html` 三頁在並行視窗 hichan-8d 的
檔案領域內，等它合回 master 後再補」——hichan-8d 合回後已補（19 處；quotation-form FORM_VERSION
V3.1 → V3.2）。最下面的**靜態守門**釘住「前端沒有裸的 Nvh」，三頁也在範圍內。

# ⚙️ 對照組（A 加）

「標」（1.0）字級下，現有版面尺寸不變：彈窗高＝0.9×視窗高、側邊清單（詳情抽屜）高＝視窗高。
"""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_voucher_preview_export_feedback_2026_09_23 import _login  # noqa: E402,F401

W, H = 1366, 768
ZOOMS = (0.85, 1.0, 1.15, 1.3)



def _rendered(page):
    """PERF #6：等 Alpine 把這次狀態變化畫完（nextTick）＋瀏覽器實際畫出兩個影格。
    ⚠️ 只適用於沒有 CSS transition 的元素（有 transition 的要等轉場落定）。"""
    page.evaluate("() => new Promise(r => (window.Alpine ? Alpine.nextTick : (f => f()))(() => requestAnimationFrame(() => requestAnimationFrame(r))))")

def _page(p_, live_server, make_user, zoom, uname):
    u, pw_ = make_user(username=uname, role="superadmin", modules=["cashier"])
    _pending_voucher(u)
    browser = p_   # PERF #5：共用瀏覽器（e2e_browser 外殼）
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
    _rendered(page)   # PERF #6：原本固定等 300ms（抽屜沒有 transition）


def _modal_rect(page):
    """簽核彈窗（佇列的 PDF 預覽窗，`height:90vh`）。直接打開 modal 量版面——
    正式的開法要先產生一份 PDF，而這一題量的是版面不是 PDF。"""
    page.evaluate("() => { Alpine.$data(document.querySelector('[x-data]')).previewModal = true }")
    _rendered(page)   # PERF #6：原本固定等 250ms（預覽窗沒有 x-transition）
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
        # PERF #6：原本固定等 250ms ⇒ 選單面板有 0.18s 的 opacity／transform transition，等它落定再量
        g.evaluate("""g => new Promise(r => { const p = g.querySelector('.mnav__panel')
            if (!p) return r()
            const t0 = performance.now()
            const f = () => { const cs = getComputedStyle(p)
              if ((cs.transform === 'none' && cs.opacity === '1') || performance.now() - t0 > 2000) r()
              else requestAnimationFrame(f) }
            f() })""")
        b = g.evaluate("g => { const p = g.querySelector('.mnav__panel');"
                       " return p ? p.getBoundingClientRect().bottom : 0 }")
        out.append(b)
    page.mouse.move(W // 2, H - 5)
    return out


@pytest.mark.e2e
@pytest.mark.parametrize("zoom", ZOOMS, ids=["小", "標", "大", "特"])
def test_fz_the_queue_modal_list_and_menus_stay_inside_the_viewport(live_server, make_user, zoom, e2e_browser):
    p_ = e2e_browser   # PERF #5：共用瀏覽器
    browser, page = _page(p_, live_server, make_user, zoom, "fz_%d" % int(zoom * 100))
    try:
        _queue(page, live_server)
        q = _queue_rect(page)
        assert q["height"] > 100, "量尺：側邊清單沒有量到東西：%r" % q
        m = _modal_rect(page)
        page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]'));"
                      " d.previewModal = false; d.drawerOpen = false }")
        _rendered(page)   # PERF #6：原本固定等 250ms
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
def test_fz_the_standard_size_layout_is_unchanged(live_server, make_user, e2e_browser):
    """對照組：「標」字級下，彈窗高＝0.9×視窗高、側邊清單（詳情抽屜）高＝視窗高（修法前後都一樣）。"""
    p_ = e2e_browser   # PERF #5：共用瀏覽器
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
def test_fz_switching_to_the_largest_size_on_the_page_also_fits(live_server, make_user, e2e_browser):
    """按字級按鈕（`motrixSetZoom`）當場切到「特」——不是重新載入——彈窗一樣要在畫面內。
    ⚠️ 上面那題是載入前就設好字級（走 sidebar.js 初始化那一條），量不到這一條。"""
    p_ = e2e_browser   # PERF #5：共用瀏覽器
    browser, page = _page(p_, live_server, make_user, 1.0, "fz_switch")
    try:
        _queue(page, live_server)
        page.evaluate("() => window.motrixSetZoom(1.3)")
        _rendered(page)   # PERF #6：原本固定等 250ms
        m = _modal_rect(page)
        print("字級 1.00 → 1.30（按鈕切換）實測：彈窗底 %.0f" % m["bottom"])
        assert m["bottom"] <= H + 1, "按鈕切到「特」後，簽核彈窗底邊 %.0f 超出畫面 %d" % (m["bottom"], H)
    finally:
        browser.close()


# ══════════════════════════════════════════════════════════════════════
# 靜態守門：前端沒有「裸的」Nvh／Ndvh（註解裡的說明文字不算）
# ══════════════════════════════════════════════════════════════════════

def _raw_vh_tokens():
    """回 `(code, comments)`：程式碼裡沒包 `/ var(--fz,1)` 的 Nvh 與註解裡的 Nvh。

    📌 「該改的 ＝ 0；**解釋它的 ＝ 10**」——註解裡那 10 處是說明「為什麼用 calc」的文字，
       機械修法最省力的做法是連它們一起改掉或刪掉（那會讓下一個人看不懂而改回去），
       所以把數字釘死：少了也紅，提醒有人動了解釋。
    """
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[2] / "frontend"
    token = re.compile(r"(?<![\w.\-#])(\d+(?:\.\d+)?)(d?vh)(?![\w])")
    code, comments = [], []
    for p in sorted(root.rglob("*")):
        if p.suffix not in (".html", ".css", ".js") or not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if "vendor" in rel or ".min." in rel:
            continue
        text = p.read_text(encoding="utf-8")
        spans = [(m.start(), m.end()) for m in re.finditer(r"/\*.*?\*/", text, re.S)]
        if p.suffix == ".html":
            spans += [(m.start(), m.end()) for m in re.finditer(r"<!--.*?-->", text, re.S)]
        if p.suffix in (".js", ".html"):
            spans += [(m.start(), m.end()) for m in re.finditer(r"(?<![:\"'\\])//[^\n]*", text)]
        for m in token.finditer(text):
            if any(a <= m.start() < b for a, b in spans):
                comments.append((rel, m.group(0)))
            elif not text[m.end():m.end() + 16].startswith(" / var(--fz"):
                code.append((rel, text.count("\n", 0, m.start()) + 1, m.group(0)))
    return code, comments


def test_fz_no_raw_vh_is_left_in_the_frontend():
    code, comments = _raw_vh_tokens()
    print("字級靜態守門：裸 Nvh %d 處（%s）；註解裡 %d 處"
          % (len(code), sorted({c[0] for c in code}), len(comments)))
    assert code == [], (
        "還有沒包 `calc(Nvh / var(--fz,1))` 的 Nvh（字級放大時會超出畫面）：%r" % code[:10])
    assert len(comments) == 10, (
        "註解裡說明 vh 的文字從 10 處變成 %d 處——有人動了解釋，確認是不是機械修法順手改掉的：%r"
        % (len(comments), comments))
