"""實走第 3～8 節續（hichan-a3 走查找到，HANDOFF「實走第 3～8 節續」）——四個小項。

- D4-1：營運報表匯出沒帶 `&basis=` ⇒ 畫面切現金口徑，匯出的仍是權責。
- D8-2：customers.html 新增客戶彈窗沒有 max-height（字級特、1366×768 超出畫面，只能捲外層）。
- 4.3：待補登連結改直接開對應分頁（使用者裁）：開「那筆資料實際登錄的分頁」。
- 7-SL：業務預設開地圖模組（使用者裁；只影響新建帳號與角色樣板）。
"""
import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from tests.test_e2e_material_orders_2026_09_11 import live_server, _login  # noqa: F401,E402

RPT = "Alpine.$data(document.querySelector('[x-data]'))"


# ── 4.3 待補登連結 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,tab", [
    ("dispatch_no_invoice", "dispatch"),     # 廠商發票登在承攬商分頁（setDispatchInvoiceDate）
    ("material_no_invoice", "fin"),          # 叫料在財務分頁
    ("extra_no_invoice", "xexp"),            # 額外支出分頁
    ("extra_no_paid_date", "xexp"),
    ("stage_ratio_unset", "exec"),           # 階段比例在執行分頁
    ("stage_ratio_not_100", "exec"),
    ("case_incomplete", "exec"),
])
def test_flag_link_opens_the_tab_where_the_data_is_entered(kind, tab):
    from helpers.recognition import FLAG_TABS, _flag_item
    assert FLAG_TABS[kind] == tab
    it = _flag_item("MQ-X-1", "客", "案件", "d", 1, "2026-01-01", True, kind=kind)
    assert it["link"] == "case-management.html?q=MQ-X-1&tab=%s" % tab


def test_every_flag_kind_has_a_tab_decision():
    """守門：新增旗標種類時必須決定它開哪個分頁（legacy_tax 是報價單層級，刻意不帶分頁）。"""
    from helpers.recognition import FLAG_LABELS, FLAG_TABS
    assert set(FLAG_TABS) == set(FLAG_LABELS), set(FLAG_LABELS) ^ set(FLAG_TABS)
    assert FLAG_TABS["legacy_tax"] is None


def test_case_page_accepts_every_flag_tab_as_deep_link():
    from pathlib import Path
    import re
    from helpers.recognition import FLAG_TABS
    js = (Path(__file__).resolve().parents[2] / "frontend" / "js" / "case-management-core.js").read_text(encoding="utf-8")
    valid = re.search(r"var valid = \[([^\]]*)\]", js).group(1)
    for tab in {t for t in FLAG_TABS.values() if t}:
        assert "'%s'" % tab in valid, tab


# ── 7-SL 業務預設地圖 ────────────────────────────────────────────────────────

def test_sales_role_template_includes_map():
    from helpers.module_registry import ROLE_TEMPLATES
    assert "map" in ROLE_TEMPLATES["sales"]


# ── D4-1 匯出帶口徑（e2e）─────────────────────────────────────────────────────

@pytest.mark.e2e
def test_report_export_sends_the_basis_on_screen(live_server, make_user):
    u = make_user(username="wb_rpt", role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_context().new_page()
            _login(page, live_server, *u)
            page.goto(f"{live_server}/pages/reports.html")
            page.wait_for_function(f"() => {RPT} && typeof {RPT}.exportFile === 'function'", timeout=20000)
            urls = []
            page.on("request", lambda r: urls.append(r.url) if "/api/reports/financial/" in r.url else None)
            page.evaluate(f"() => {{ {RPT}.expensesBasis = 'cash' }}")
            page.evaluate(f"async () => {{ await {RPT}.exportFile('excel') }}")
            assert urls and "basis=cash" in urls[-1], urls
        finally:
            browser.close()


# ── D8-2 客戶彈窗（e2e）───────────────────────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.parametrize("pg", ["customers", "suppliers"])   # suppliers：同型彈窗（0a 派，2026-09-25）
def test_customer_modal_fits_the_viewport_and_scrolls_inside(live_server, make_user, pg):
    u = make_user(username="wb_" + pg, role="superadmin")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(viewport={"width": 1366, "height": 768})
            ctx.add_init_script("try { localStorage.setItem('motrix_font_zoom', '1.3') } catch (e) {}")
            page = ctx.new_page()
            _login(page, live_server, *u)
            page.goto(f"{live_server}/pages/{pg}.html")
            page.wait_for_function(f"() => {RPT} && typeof {RPT}.openCreate === 'function'", timeout=20000)
            page.evaluate(f"() => {RPT}.openCreate()")
            box = page.locator('.modal-overlay[x-show="showModal"] .modal-box')
            box.wait_for(state="visible", timeout=5000)
            # ⚠ 要等 x-transition 進場結束再量：進場途中外層 scale(0.95) 會把彈窗縮小，
            #   第一版量在途中 ⇒ master 上假綠（穩定後底邊 781 > 768）。
            page.wait_for_function("""() => { const o = document.querySelector('.modal-overlay[x-show="showModal"]')
              const cs = getComputedStyle(o); return cs.transform === 'none' && cs.opacity === '1' }""", timeout=5000)
            m = page.evaluate("""() => {
              const b = document.querySelector('.modal-overlay[x-show="showModal"] .modal-box')
              const body = b.querySelector('.modal-body')
              const r = b.getBoundingClientRect()
              return { bottom: r.bottom, vh: window.innerHeight, bodyScrolls: body.scrollHeight > body.clientHeight,
                       overflow: getComputedStyle(body).overflowY }
            }""")
            assert m["bottom"] <= m["vh"] + 1, m
            assert m["overflow"] in ("auto", "scroll"), m
        finally:
            browser.close()
