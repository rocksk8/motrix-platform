"""瀏覽器端對端：報價單預覽的品項備註移到品項下方整列（2026-11-17，使用者裁示「有備註一律移到下方」）。

預覽 modal 的 iframe 內容與 PDF 同一支 builder（pdf_gen._build_quote_html），所以這題同時代表 PDF 的版面：
- 沒有「備註」欄表頭；每個有備註的品項下一列 .remark-row，備註框橫跨品名欄到最右（寬度 > 表格一半）
- 長備註（兩行）不再把品項列撐高：品項列高度與無備註的品項列相同
- 換行保留、短備註（「含安裝」）也在下方
- 切內部版（含成本欄）備註列同樣橫跨到最右
"""
from tests._requires import requires_module  # noqa: E402
import json
import time

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象')

QUOTE_NO = "MQ-202611-171"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
LONG = "智慧人形／車形偵測 4路，每一路攝影機一套 AI 影像分析軟體授權；包含 Argo ONVIF 錄影授權 x16、AI 軟體授權金鑰 x1"


def _seed():
    import db
    notes = ["", LONG + "\n第二行說明", "含安裝"]
    items = [{"id": i + 1, "description": f"品項 {i + 1}", "brand": f"BR-{i + 1}", "qty": 1, "unit": "台",
              "cost": 100, "margin": 0.35, "unitPrice": 160, "amount": 160, "notes": n}
             for i, n in enumerate(notes)]
    data = {"quoteNo": QUOTE_NO, "customerName": "備註客戶", "projectName": "備註專案", "status": "草稿",
            "items": items, "tot": {"total": 504, "pretax": 480, "directMarginPct": 0, "netMarginPct": 0}}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (QUOTE_NO, "草稿", "備註客戶", "備註專案", 504, 480, json.dumps(data, ensure_ascii=False),
             "2026-11-01T00:00:00", "2026-11-01T00:00:00", "", "2026-11-01"))
        conn.commit()
    finally:
        conn.close()


def _frame(page):
    page.locator("#quote-preview-frame").wait_for(state="visible", timeout=20000)
    for _ in range(100):
        fr = page.locator("#quote-preview-frame").element_handle().content_frame()
        if fr:
            try:
                if fr.evaluate("() => document.readyState === 'complete' && !!document.getElementById('root')"):
                    return fr
            except Exception:
                pass
        time.sleep(0.1)
    pytest.fail("預覽 iframe 沒有載入完成")


_MEASURE = """() => {
  const tbl = document.querySelector('#root table');
  const tw = tbl.getBoundingClientRect().width;
  const rows = [...tbl.querySelectorAll('tbody tr')];
  const rem = [...tbl.querySelectorAll('tr.remark-row')].map(r => {
    const box = r.querySelector('.rbox').getBoundingClientRect();
    return {w: box.width, html: r.querySelector('.rbox').innerHTML, prev: r.previousElementSibling.innerText.slice(0, 6)};
  });
  const itemH = rows.filter(r => !r.classList.contains('remark-row')).map(r => Math.round(r.getBoundingClientRect().height));
  return {tw, heads: [...tbl.querySelectorAll('thead th')].map(t => t.innerText.trim()), rem, itemH,
          cols: tbl.querySelectorAll('thead th').length};
}"""


@pytest.mark.e2e
def test_remarks_render_as_full_width_row_under_each_item(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_rm1", role="superadmin")
    _seed()
    page = e2e_browser.new_page()
    inject_login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/quotation-form.html?id={QUOTE_NO}")
    page.wait_for_function("() => document.body.innerText.includes('備註客戶')", timeout=20000)
    page.evaluate(f"{DATA_JS}.openPreview('external')")
    m = _frame(page).evaluate(_MEASURE)

    assert "備註" not in m["heads"] and m["cols"] == 7, m["heads"]
    assert len(m["rem"]) == 2                                   # 品項 2、3 有備註；品項 1 沒有
    for r in m["rem"]:
        assert r["w"] > m["tw"] * 0.6, ("備註框要橫跨品名欄到最右", r["w"], m["tw"])
    assert "第二行說明" in m["rem"][0]["html"] and "<br>" in m["rem"][0]["html"]
    assert m["rem"][1]["html"].endswith("含安裝")
    # 品項列高度不被備註撐高：三個品項列（+ 沒有分組列）高度相同
    assert max(m["itemH"]) - min(m["itemH"]) <= 2, m["itemH"]

    # 內部版（含成本／毛利率欄）：同樣橫跨到最右
    page.evaluate(f"{DATA_JS}.previewMode = 'internal'")
    page.wait_for_function(f"() => {DATA_JS}.previewHtml.includes('35.0%')", timeout=20000)
    m2 = _frame(page).evaluate(_MEASURE)
    assert m2["cols"] == 9 and "備註" not in m2["heads"]
    assert len(m2["rem"]) == 2 and all(r["w"] > m2["tw"] * 0.6 for r in m2["rem"]), m2


# ───────────── 欄寬依內容自動分配：長料號不被拆行、數字欄不溢出（同一個預覽 iframe）─────────────
def _seed_widths(quote_no, brand, name, price):
    import db
    items = [{"id": 1, "description": name, "brand": brand, "qty": 1, "unit": "台", "cost": int(price * .7),
              "margin": 0.3, "unitPrice": price, "amount": price, "notes": ""},
             {"id": 2, "description": "網路攝影機 4MP", "brand": "CAM-1", "qty": 2, "unit": "台", "cost": 3000,
              "margin": 0.3, "unitPrice": 5200, "amount": 10400, "notes": ""}]
    data = {"quoteNo": quote_no, "customerName": "欄寬客戶", "projectName": "欄寬專案", "status": "草稿",
            "items": items, "tot": {"total": 105000, "pretax": 100000, "directMarginPct": 0, "netMarginPct": 0}}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "草稿", "欄寬客戶", "欄寬專案", 105000, 100000, json.dumps(data, ensure_ascii=False),
             "2026-11-01T00:00:00", "2026-11-01T00:00:00", "", "2026-11-01"))
        conn.commit()
    finally:
        conn.close()


_FIT = """() => {
  const tbl = document.querySelector('#root table');
  const rows = [...tbl.querySelectorAll('tbody tr')].filter(r => r.cells.length > 2);
  const lineH = c => { const s = getComputedStyle(c); return parseFloat(s.lineHeight) || 20; };
  const first = rows[0];
  return {
    fixed: getComputedStyle(tbl).tableLayout,
    overflowX: tbl.scrollWidth - tbl.clientWidth,
    brandLines: rows.map(r => Math.round((r.cells[2].getBoundingClientRect().height - 16) / lineH(r.cells[2]))),
    numOverflow: rows.map(r => [...r.querySelectorAll('td.r')].some(c => c.scrollWidth > c.clientWidth + 1)),
    widths: [...first.cells].map(c => Math.round(c.getBoundingClientRect().width)),
    cols: tbl.querySelectorAll('thead th').length,
  };
}"""


@pytest.mark.e2e
def test_long_part_number_stays_on_one_line_and_numbers_do_not_overflow(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_rm2", role="superadmin")
    no = "MQ-202611-172"
    _seed_widths(no, "SR-S-VMS-Mini2-516-AID04", "主機", 86100)
    page = e2e_browser.new_page()
    inject_login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/quotation-form.html?id={no}")
    page.wait_for_function("() => document.body.innerText.includes('欄寬客戶')", timeout=20000)
    page.evaluate(f"{DATA_JS}.openPreview('external')")
    m = _frame(page).evaluate(_FIT)
    assert m["fixed"] == "fixed" and m["cols"] == 7, m
    assert m["brandLines"][0] == 1, ("SR-S-VMS-Mini2-516-AID04 不可拆行", m)
    assert m["overflowX"] <= 1 and not any(m["numOverflow"]), m
    # 欄寬真的被調過：廠牌欄 > 預設 110，數字欄不比預設 120 寬（預覽 iframe 有縮放，比例換算）
    scale = m["widths"][2] / max(m["widths"][1], 1)
    assert m["widths"][2] > 110 * 0.6 and m["widths"][5] <= m["widths"][2] * 1.2, (m, scale)

    # 內部版：9 欄、不溢出
    page.evaluate(f"{DATA_JS}.previewMode = 'internal'")
    page.wait_for_function(f"() => {DATA_JS}.previewHtml.includes('30.0%')", timeout=20000)
    time.sleep(0.5)
    m2 = _frame(page).evaluate(_FIT)
    assert m2["cols"] == 9 and m2["overflowX"] <= 1 and not any(m2["numOverflow"]), m2


@pytest.mark.e2e
def test_short_part_numbers_keep_the_default_table(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_rm3", role="superadmin")
    no = "MQ-202611-173"
    _seed_widths(no, "HDD-8TB", "硬碟", 7800)
    page = e2e_browser.new_page()
    inject_login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/quotation-form.html?id={no}")
    page.wait_for_function("() => document.body.innerText.includes('欄寬客戶')", timeout=20000)
    page.evaluate(f"{DATA_JS}.openPreview('external')")
    m = _frame(page).evaluate(_FIT)
    assert m["fixed"] == "auto" and m["cols"] == 7, m


@pytest.mark.e2e
def test_big_amounts_with_long_part_number_do_not_overflow(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_rm4", role="superadmin")
    no = "MQ-202611-174"
    _seed_widths(no, "ABCDEFGHIJ-0123456789", "超大專案", 98765432)
    page = e2e_browser.new_page()
    inject_login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/quotation-form.html?id={no}")
    page.wait_for_function("() => document.body.innerText.includes('欄寬客戶')", timeout=20000)
    for mode in ("external", "internal"):
        page.evaluate(f"{DATA_JS}.openPreview('{mode}')")
        if mode == "internal":
            page.wait_for_function(f"() => {DATA_JS}.previewHtml.includes('30.0%')", timeout=20000)
            time.sleep(0.5)
        m = _frame(page).evaluate(_FIT)
        # 客戶版：料號一行；內部版欄多（含成本／毛利率）又是千萬級金額，料號允許在「-」處換成兩行（不溢出、不拆字中間）
        assert m["overflowX"] <= 1 and not any(m["numOverflow"]) and m["brandLines"][0] <= (1 if mode == "external" else 2), (mode, m)


# ───────────── 備註排版：編輯畫面切「依輸入換行／連成一行」→ 存檔 → 重新載入 → 預覽 ─────────────
def _stored(quote_no):
    import db
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()["data_json"])
    finally:
        c.close()


@pytest.mark.e2e
def test_note_layout_toggle_saves_reloads_and_renders_in_preview(live_server, make_user, e2e_browser):
    username, password = make_user(username="e2e_rm5", role="superadmin")
    no = "MQ-202611-175"
    import db
    items = [{"id": 1, "description": "品項甲", "brand": "A", "qty": 1, "unit": "台", "cost": 100, "margin": 0.3,
              "unitPrice": 143, "amount": 143, "notes": "第一行說明\n第二行說明\n第三行說明"},
             {"id": 2, "description": "品項乙", "brand": "B", "qty": 1, "unit": "台", "cost": 100, "margin": 0.3,
              "unitPrice": 143, "amount": 143, "notes": "乙一\n乙二"}]
    data = {"quoteNo": no, "customerName": "排版客戶", "projectName": "排版專案", "status": "草稿", "items": items,
            "tot": {"total": 300, "pretax": 286, "directMarginPct": 0, "netMarginPct": 0}}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
                     "created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (no, "草稿", "排版客戶", "排版專案", 300, 286, json.dumps(data, ensure_ascii=False),
                      "2026-11-01T00:00:00", "2026-11-01T00:00:00", "", "2026-11-01"))
        conn.commit()
    finally:
        conn.close()

    page = e2e_browser.new_page()
    inject_login(page, live_server, username, password)
    page.goto(f"{live_server}/pages/quotation-form.html?id={no}")
    page.wait_for_function("() => document.body.innerText.includes('排版客戶')", timeout=20000)

    # 每個有備註的品項都有切換；預設＝「依輸入換行」
    tog = page.locator('[data-testid="qf-note-layout"]')
    assert tog.count() == 2
    assert page.locator('[data-testid="qf-note-layout-wrap"]').first.get_attribute("aria-pressed") == "true"
    assert page.locator('[data-testid="qf-note-layout-inline"]').first.get_attribute("aria-pressed") == "false"
    # 只動第一項：切成「連成一行」
    page.locator('[data-testid="qf-note-layout-inline"]').first.click()
    page.wait_for_function("() => { const b = document.querySelectorAll('[data-testid=\"qf-note-layout-inline\"]'); "
                           "return b.length === 2 && b[0].getAttribute('aria-pressed') === 'true' && b[1].getAttribute('aria-pressed') === 'false' }", timeout=5000)
    assert page.locator('[data-testid="qf-note-layout-inline"]').first.get_attribute("aria-pressed") == "true"
    assert page.locator('[data-testid="qf-note-layout-inline"]').nth(1).get_attribute("aria-pressed") == "false"
    page.evaluate(f"() => {DATA_JS}.saveDraft()")
    page.wait_for_function(f"() => !{DATA_JS}.isDirty", timeout=10000)

    st = _stored(no)["items"]
    assert st[0]["notesLayout"] == "inline" and "notesLayout" not in st[1]               # 沒動的品項不多出鍵

    # 重新載入後切換狀態還在，預覽：第一項一行、第二項照換行
    page.reload()
    page.wait_for_function("() => document.body.innerText.includes('排版客戶')", timeout=20000)
    assert page.locator('[data-testid="qf-note-layout-inline"]').first.get_attribute("aria-pressed") == "true"
    page.evaluate(f"{DATA_JS}.openPreview('external')")
    boxes = _frame(page).evaluate("() => [...document.querySelectorAll('#root .rbox')].map(b => b.innerHTML)")
    assert boxes[0].endswith("第一行說明　第二行說明　第三行說明") and "<br>" not in boxes[0], boxes
    assert boxes[1].endswith("乙一<br>乙二"), boxes

    # 切回「依輸入換行」→ 存檔（先關掉預覽視窗，否則遮住按鈕）
    page.evaluate(f"() => {DATA_JS}.previewMode = null")
    page.locator('.modal-overlay').first.wait_for(state='hidden', timeout=5000)
    page.locator('[data-testid="qf-note-layout-wrap"]').first.click()
    page.evaluate(f"() => {DATA_JS}.saveDraft()")
    page.wait_for_function(f"() => !{DATA_JS}.isDirty", timeout=10000)
    assert _stored(no)["items"][0]["notesLayout"] == "wrap"
    # 伺服器：不認得的值存檔時清成預設（直接送 API 帶來的髒值）
    page.evaluate(f"() => {{ {DATA_JS}.q.items[0].notesLayout = 'bogus'; {DATA_JS}.setDirty() }}")
    page.evaluate(f"() => {DATA_JS}.saveDraft()")
    page.wait_for_function(f"() => !{DATA_JS}.isDirty", timeout=10000)
    assert "notesLayout" not in _stored(no)["items"][0]
