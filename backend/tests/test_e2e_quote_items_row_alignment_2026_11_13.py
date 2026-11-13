"""2026-11-13：報價單表單「品項明細」同一列的輸入框要對齊（使用者回報）。

症狀：品名／廠牌貼列首，數量／單位／成本／毛利率／售價卻在列中間（列因為「＋備註」「擇一方案」變高）；
區段標題列（item-header-row）少了成本／毛利率／單項毛利三格，底色只到「售價」附近、沒有鋪滿整列。
釘住：① 同一列所有輸入框（textarea／input）的上緣差距 ≤ 2px，且貼列首（和品名第一行同高）；
      ② 區段標題列的格數與表頭欄數相同、底色一路鋪到最右；③ 窄螢幕（卡片版面）不被影響（不量上緣，只確認可操作）。
"""
import json
import os
from pathlib import Path

import pytest

from tests._requires import requires_module  # noqa: E402

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

pytestmark = requires_module("case", "本檔打 M01（案件）的頁面與資料")

_MAKE_USER_DEFAULT_ROLE = "superadmin"
SHOTS = os.environ.get("QF_ALIGN_SHOTS")           # 設了才存截圖（人工比對前後用）；不設＝只量測


def _seed(no="MQ-202611-777"):
    import db
    items = [
        {"id": 1, "type": "header", "description": "WiFi 7 無線AP"},
        {"id": 2, "description": "U7 Pro Max\n室內型 Wi-Fi 7 AP", "brand": "Unifi", "qty": 4, "unit": "台", "cost": 5200, "margin": 0.3,
         "unitPrice": 7430, "amount": 29720, "notes": "含 PoE 注入器", "altGroup": "A"},
        {"id": 3, "description": "網路線 CAT6", "brand": "Belden", "qty": 100, "unit": "米", "cost": 12, "margin": 0.4,
         "unitPrice": 20, "amount": 2000},
    ]
    data = {"quoteNo": no, "customerName": "對齊客戶", "projectName": "對齊專案", "status": "草稿", "quoteDate": "2026-11-13",
            "items": items, "tot": {"total": 31720, "pretax": 30210, "directMarginPct": 0, "netMarginPct": 0}}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, quote_date) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, "草稿", "對齊客戶", "對齊專案", 31720, 30210, json.dumps(data, ensure_ascii=False),
             "2026-11-13T00:00:00", "2026-11-13T00:00:00", "", "2026-11-13"))
        conn.commit()
    finally:
        conn.close()
    return no


_MEASURE = """() => {
  const rows = [...document.querySelectorAll('.items-table tbody tr')]
  const out = []
  for (const tr of rows) {
    // 每一欄（td）只取它的「主要輸入框」（第一個可見的 textarea／input）：備註、擇一方案的組別名稱是同欄往下長的附屬框，不算「同一行」
    const fields = []
    const tds = [...tr.children].filter(n => n.tagName === 'TD')          // Alpine 的 <template> 標籤也是 tr 的子節點，不算格
    for (const td of tds) {
      const e = [...td.querySelectorAll('textarea, input:not([type=checkbox]):not([type=hidden])')]
        .find(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden' })
      if (e) fields.push({ cls: e.className.slice(0, 40), top: Math.round(e.getBoundingClientRect().top * 10) / 10 })
    }
    const trr = tr.getBoundingClientRect()
    out.push({ header: tr.classList.contains('item-header-row'), cells: tds.length, fields,
               right: Math.round(Math.max(...tds.map(t => t.getBoundingClientRect().right))), trRight: Math.round(trr.right) })
  }
  const ths = document.querySelectorAll('.items-table thead th').length
  return { rows: out, ths }
}"""


def _open(live_server, make_user, e2e_browser, width, name):
    u = make_user(username="qf_align_" + name)
    no = _seed()
    page = e2e_browser.new_context(viewport={"width": width, "height": 1000}).new_page()
    inject_login(page, live_server, *u)
    page.goto(f"{live_server}/pages/quotation-form.html?id={no}")
    page.wait_for_selector(".items-table tbody tr", timeout=20000)
    page.wait_for_function("() => document.querySelectorAll('.items-table tbody tr textarea').length >= 3", timeout=20000)   # Alpine 把每列渲染完
    return page


@pytest.mark.e2e
def test_item_row_fields_share_one_top_line_and_header_row_fills_the_table(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, 1440, "w1440")
    # 顯示成本欄（預設可能收合）：要驗 11 欄的寬表
    if not page.locator(".items-table.with-cost").count():
        page.click("text=顯示成本欄")
        page.wait_for_selector(".items-table.with-cost")
    page.wait_for_function("() => document.querySelectorAll('.items-table thead th').length >= 11 && "
                           "[...document.querySelectorAll('.items-table tbody tr.item-header-row')].every(tr => [...tr.children].filter(n => n.tagName === 'TD').length >= 11)", timeout=10000)
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.locator(".items-table").scroll_into_view_if_needed()
        page.screenshot(path=str(Path(SHOTS) / "items_1440.png"), full_page=True)
    m = page.evaluate(_MEASURE)
    bad = []
    for i, r in enumerate(m["rows"]):
        if r["header"]:
            continue
        tops = [f["top"] for f in r["fields"]]
        if tops and max(tops) - min(tops) > 2:
            bad.append("第 %d 列：輸入框上緣差 %.1fpx（%s）" % (i + 1, max(tops) - min(tops), [(f["cls"], f["top"]) for f in r["fields"]]))
    assert not bad, "同一列輸入框沒有對齊：\n" + "\n".join(bad)
    hdr = [r for r in m["rows"] if r["header"]]
    assert hdr, "測試資料要有區段標題列"
    for r in hdr:
        assert r["cells"] == m["ths"], "區段標題列格數 %d ≠ 表頭欄數 %d（少格 ⇒ 底色只到一半）" % (r["cells"], m["ths"])
        assert r["right"] >= r["trRight"] - 1, "區段標題列底色沒鋪到最右（%d < %d）" % (r["right"], r["trRight"])


@pytest.mark.e2e
def test_item_rows_stay_usable_on_a_phone(live_server, make_user, e2e_browser):
    page = _open(live_server, make_user, e2e_browser, 390, "w390")
    if not page.locator(".items-table.with-cost").count():
        page.click("text=顯示成本欄")
        page.wait_for_selector(".items-table.with-cost")
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.locator(".items-table").scroll_into_view_if_needed()
        page.screenshot(path=str(Path(SHOTS) / "items_390.png"), full_page=True)
    m = page.evaluate(_MEASURE)
    assert m["rows"], "手機版仍要有品項列"
    ov = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert ov <= 1, "手機版品項區造成橫向捲動 %dpx" % ov
    # 標題列補的空格（desktop 為了鋪滿底色）在卡片版面必須是隱藏的，不能多出空白區塊
    shown = page.evaluate("() => [...document.querySelectorAll('.items-table tr.item-header-row td.qf-c-hfill')].filter(td => td.getBoundingClientRect().height > 0).length")
    assert shown == 0, "手機版標題列的補格不該顯示（%d 個可見）" % shown

