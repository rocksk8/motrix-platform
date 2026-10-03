# -*- coding: utf-8 -*-
"""35c 精算頁二之一：已對應的材料申請／額外支出要看得出已對應（使用者 2026-10-03 截圖：
「已經被帶入了，但額外支出還有顯示不對應，已採用也未消失」）。

根因（用真瀏覽器重現）：報價品項的 id 是**數字**（`id: 8`）時，二之一下拉的 `:selected="it.id === u.itemId"` 是 number === string ⇒ false，
而且 `:value` 在選項還沒畫出來時就綁了 ⇒ 已對應的列一律顯示「（不對應，計入額外支出）」，但品項列的「額外支出 NT$…」與 API 都證明它已對應。
金額沒有重複計算（見 test_settlement_assigned_numbers_2026_10_03.py）；這是顯示問題。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._requires import requires_module  # noqa: E402
from tests.test_e2e_case_concurrent_edit_2026_09_24 import _login  # noqa: F401

pytestmark = requires_module("case", "本檔的題讀寫 M01（案件）的資料與頁面")

NO = "MQ-E2E-SC-1"


def _order(iid, name, total, **kw):
    d = {"itemId": iid, "itemName": name, "quantity": 2, "unit": "批", "unitPrice": total / 2, "totalPrice": total, "paidStatus": "pending",
         "paidAmount": 0, "paidDate": "", "invoiceDate": "2026-10-02", "notes": "備註-" + iid}
    d.update(kw)
    return d


def seed(item_ids=(7, 8), saved_items=None):
    """兩個報價品項（id 可為數字或字串）；材料申請 X 未對應、N 連到品項 2（link）、M 手動對應到品項 1；
    額外支出 1 手動對應到品項 2、2 未對應。回傳 (品項1 id, 品項2 id)。"""
    import db
    i1, i2 = item_ids
    items = [{"id": i1, "description": "交換器 24埠 PoE", "qty": 10, "unit": "台", "unitPrice": 2000, "amount": 20000, "cost": 1000},
             {"id": i2, "description": "線材 Cat6", "qty": 100, "unit": "米", "unitPrice": 10, "amount": 1000, "cost": 5}]
    data = {"items": items, "dealTag": "已成案",
            "caseRecord": {"materialOrders": [_order("X", "未對應料X", 250), _order("N", "連結料N", 800, quoteItemId=str(i2)), _order("M", "手動對應料M", 300)]},
            "settlement": {"status": "draft", "items": saved_items or [],
                           "offsets": [{"kind": "material", "ref": "M", "itemId": str(i1)}, {"kind": "extra", "ref": "1", "itemId": str(i2)}]}}
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", 21000, 21000, json.dumps(data), "2026-10-02T00:00:00", "2026-10-02T00:00:00", "已成案", "sc_sc"))
        for mid in ("X", "N", "M"):
            c.execute("INSERT INTO case_material_approvals (quote_no, item_id, status) VALUES (?,?,?)", (NO, mid, "已核准"))
        for desc, cost, note in (("已被對應的支出", 700, "附註1"), ("還沒對應的支出", 900, "附註2")):
            c.execute("INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no, files_json, "
                      "created_by, created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name, status, approval_json) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,?,'{}')",
                      (NO, "其他", desc, 1, "式", cost, cost, note, "2026-10-02", "", "sc_sc", "sc_sc", "sc_sc", "sc_sc",
                       "2026-10-02T00:00:00", "2026-10-02T00:00:00", "sc_sc", "已核准"))
        c.commit()
    finally:
        c.close()
    return i1, i2


def open_page(live_server, e2e_browser, sa):
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 1300}).new_page()
    _login(page, live_server, *sa)
    page.goto("%s/pages/settlement.html?no=%s" % (live_server, NO))
    page.locator('[data-testid="stl-unassigned"]').wait_for(state="visible", timeout=20000)
    return page


@pytest.mark.e2e
def test_mapped_rows_show_their_target_item_when_quote_item_ids_are_numbers(live_server, make_user, e2e_browser):
    """品項 id 是數字（真實報價單的樣子）：已對應的列的下拉必須顯示它對應到的品項；未對應的列仍是「不對應」。"""
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=(7, 8))
    page = open_page(live_server, e2e_browser, sa)
    sel = lambda kind, ref: page.locator('[data-testid="stl-offset-%s-%s"]' % (kind, ref))   # noqa: E731
    assert sel("material", "M").input_value() == "7", "材料申請 M 已對應到品項 7，下拉卻顯示 %r" % sel("material", "M").input_value()
    assert sel("extra", "1").input_value() == "8", "額外支出 #1 已對應到品項 8，下拉卻顯示 %r" % sel("extra", "1").input_value()
    assert sel("material", "X").input_value() == "" and sel("extra", "2").input_value() == ""


S = "Alpine.$data(document.body)"
#: 在 origin/platform（5d76b528，改版前）用同一份 seed 量到的頁面數字（品項 id 數字、兩個品項都預設採用）：
#: 品項 7＝材料 M 300；品項 8＝材料 N 800＋額外支出 #1 700；未對應：材料 X 250、額外支出 #2 900
PRE_CHANGE = {"itemActualTotal": 1800, "extraTotal": 1150, "purchasedTotal": 2950, "totalActualCost": 2950}


def _totals(page):
    return page.evaluate("() => { const s = %s.summary; return {itemActualTotal: s.itemActualTotal, extraTotal: s.extraTotal, purchasedTotal: s.purchasedTotal, totalActualCost: s.totalActualCost} }" % S)


@pytest.mark.e2e
def test_totals_are_identical_to_the_pre_change_page_and_offsets_are_saved_in_the_same_shape(live_server, make_user, e2e_browser):
    """守恆：同一份 seed 在改版前的頁面量到的總額＝現在；存草稿時 offsets 的儲存格式不變（只有 kind／ref／itemId 三鍵、全字串）。"""
    import db
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=(7, 8))
    page = open_page(live_server, e2e_browser, sa)
    assert _totals(page) == PRE_CHANGE, _totals(page)
    page.locator('[data-testid="stl-save-draft"]').click()
    page.wait_for_function("() => !%s.saving" % S, timeout=15000)
    c = db.get_db()
    try:
        saved = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["settlement"]
    finally:
        c.close()
    assert saved["offsets"] == [{"kind": "material", "ref": "M", "itemId": "7"}, {"kind": "extra", "ref": "1", "itemId": "8"}]
    assert all(set(o) == {"kind", "ref", "itemId"} and all(isinstance(v, str) for v in o.values()) for o in saved["offsets"])


@pytest.mark.e2e
def test_mapped_rows_move_to_the_mapped_list_with_target_amount_badge_and_tint(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=(7, 8))
    page = open_page(live_server, e2e_browser, sa)
    un = page.locator('[data-testid^="stl-un-"]')
    assert sorted(un.evaluate_all("els => els.map(e => e.getAttribute('data-testid'))")) == ["stl-un-extra-2", "stl-un-material-X"], "未對應表只該有真正未對應的兩列"
    mapped = page.locator("tr.stl-row--mapped")
    assert sorted(mapped.evaluate_all("els => els.map(e => e.getAttribute('data-testid'))")) == ["stl-mapped-extra-1", "stl-mapped-material-M", "stl-mapped-material-N"]
    assert page.locator('[data-testid="stl-mapped-to-material-M"]').inner_text().strip() == "#1 交換器 24埠 PoE"        # 品項號碼＋名稱
    assert page.locator('[data-testid="stl-mapped-to-extra-1"]').inner_text().strip() == "#2 線材 Cat6"
    assert page.locator('[data-testid="stl-mapped-to-material-N"]').inner_text().strip() == "#2 線材 Cat6"
    row_m = page.locator('[data-testid="stl-mapped-material-M"]').inner_text()
    assert "手動對應料M" in row_m and "300" in row_m and "已對應" in row_m and "備註：備註-M" in row_m and "已計入該品項的實際成本" in row_m
    row_e = page.locator('[data-testid="stl-mapped-extra-1"]').inner_text()
    assert "已被對應的支出" in row_e and "700" in row_e and "附註：附註1" in row_e
    # 連結來的材料申請：唯讀（沒有下拉），標示由材料申請連結
    assert "由材料申請連結（唯讀）" in page.locator('[data-testid="stl-linked-material-N"]').inner_text()
    assert page.locator('[data-testid="stl-offset-material-N"]').count() == 0
    # 顏色：已對應列的底色與未對應列不同（淺綠 vs 無底色／白），而且有文字徽章（不只靠顏色）與圖例
    bg = lambda sel: page.locator(sel).locator("td").first.evaluate("e => getComputedStyle(e).backgroundColor")   # noqa: E731
    assert bg('[data-testid="stl-mapped-extra-1"]') != bg('[data-testid="stl-un-extra-2"]')
    assert page.locator('[data-testid="stl-badge-mapped"]').count() == 3
    assert "已對應" in page.locator('[data-testid="stl-legend"]').inner_text() and "尚未對應" in page.locator('[data-testid="stl-legend"]').inner_text()
    # 未對應表沒有已對應的列（不重複顯示）
    for ref in ("material-M", "extra-1", "material-N"):
        assert page.locator('[data-testid="stl-un-%s"]' % ref).count() == 0


@pytest.mark.e2e
def test_unmap_and_remap_conserve_the_money_and_keep_one_offset_per_row(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=(7, 8))
    page = open_page(live_server, e2e_browser, sa)
    # 取消對應 extra #1：回到未對應（700 回到額外支出）；採購類總額不變（錢只是換地方，不增不減）
    page.locator('[data-testid="stl-offset-extra-1"]').select_option("")
    page.wait_for_function("() => %s.summary.extraTotal === 1850" % S, timeout=10000)
    t = _totals(page)
    assert t["purchasedTotal"] == PRE_CHANGE["purchasedTotal"] and t["itemActualTotal"] == 1100 and t["totalActualCost"] == 1100 + 1850
    assert page.locator('[data-testid="stl-un-extra-1"]').count() == 1 and page.locator('[data-testid="stl-mapped-extra-1"]').count() == 0
    # 改對應到另一個品項：每一列只有一個 offset；回到改版前的總額
    page.locator('[data-testid="stl-offset-extra-1"]').select_option("7")
    page.wait_for_function("() => %s.summary.extraTotal === 1150" % S, timeout=10000)
    assert page.evaluate("() => %s.offsets.filter(o => o.kind === 'extra' && o.ref === '1')" % S) == [{"kind": "extra", "ref": "1", "itemId": "7"}]
    assert page.locator('[data-testid="stl-mapped-to-extra-1"]').inner_text().strip() == "#1 交換器 24埠 PoE"
    assert _totals(page)["purchasedTotal"] == PRE_CHANGE["purchasedTotal"]
    page.locator('[data-testid="stl-offset-extra-1"]').select_option("8")
    page.wait_for_function("() => %s.summary.itemActualTotal === 1800" % S, timeout=10000)
    assert _totals(page) == PRE_CHANGE


@pytest.mark.e2e
def test_an_unadopted_item_says_its_mapped_money_is_not_counted_yet_and_totals_are_unchanged(live_server, make_user, e2e_browser):
    """D8 規則不變：品項未採用＝手填取代、採購不另加。已對應表照實說「目前不計入」，總額與改版前相同（在 5d76b528 量到 7,750）。"""
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=(7, 8), saved_items=[{"id": "8", "adoptSystem": False, "actualQty": 1, "actualUnitCost": 6300, "actualCostTaxMode": "pretax", "actualTotalCost": 6300}])
    page = open_page(live_server, e2e_browser, sa)
    assert _totals(page) == {"itemActualTotal": 6600, "extraTotal": 1150, "purchasedTotal": 2950, "totalActualCost": 7750}
    assert "該品項未採用：這筆金額目前不計入實際成本" in page.locator('[data-testid="stl-mapped-extra-1"]').inner_text()
    assert "已計入該品項的實際成本" in page.locator('[data-testid="stl-mapped-material-M"]').inner_text()          # 品項 7 仍採用
    page.locator('[data-testid="stl-adopt-8"]').click()
    page.wait_for_function("() => %s.summary.totalActualCost === 2950" % S, timeout=10000)
    assert "已計入該品項的實際成本" in page.locator('[data-testid="stl-mapped-extra-1"]').inner_text()
    assert page.evaluate("() => %s.summary.extraTotal" % S) == 1150            # 採用不動「額外支出」：已對應的錢本來就不在裡面


@pytest.mark.e2e
def test_string_item_ids_still_work_after_the_fix(live_server, make_user, e2e_browser):
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=("a", "b"))
    page = open_page(live_server, e2e_browser, sa)
    assert page.locator('[data-testid="stl-offset-material-M"]').input_value() == "a" and page.locator('[data-testid="stl-offset-extra-1"]').input_value() == "b"
    assert _totals(page) == PRE_CHANGE


# ── 深色模式對比（0c M1）──────────────────────────────────────────────────────────────────────
# 全站深色＝body 的子元素整塊 filter: invert(1) hue-rotate(180deg)；getComputedStyle 看不到 filter，所以量到的前景／背景色要自己套同一個 filter 再算 WCAG 對比。
_HUE180 = ((-0.574, 1.430, 0.144), (0.426, 0.430, 0.144), (0.426, 1.430, -0.856))

_MEASURE_JS = """() => {
  const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); const p = m[1].split(',').map(x => parseFloat(x)); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1} }
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c.a > 0.99) return c } return {r: 255, g: 255, b: 255, a: 1} }
  const out = []
  document.querySelectorAll('tr.stl-row--mapped').forEach(tr => {
    tr.querySelectorAll('td, td *').forEach(el => {
      const own = Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim())
      if (!own && !['SELECT', 'INPUT', 'TEXTAREA'].includes(el.tagName)) return
      if (el.offsetParent === null) return
      const cs = getComputedStyle(el), fg = parse(cs.color)
      out.push({tag: el.tagName, text: (el.textContent || el.value || '').trim().slice(0, 20), badge: el.classList.contains('stl-badge-mapped'), fg: [fg.r, fg.g, fg.b], bg: (() => { const b = bgOf(el); return [b.r, b.g, b.b] })()})
    })
  })
  return out
}"""


def _lum(rgb):
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _dark(rgb):
    inv = [255 - v for v in rgb]
    return [min(255.0, max(0.0, sum(m * v for m, v in zip(row, inv)))) for row in _HUE180]


def _contrast(fg, bg):
    a, b = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


@pytest.mark.e2e
@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("finalized", [False, True])
def test_mapped_rows_text_and_badge_keep_readable_contrast_in_light_and_dark_theme(live_server, make_user, e2e_browser, dark, finalized):
    """已對應列（淺綠底）在深色模式（整頁 invert）下，列內文字與「已對應」徽章對比都要 ≥ 4.5:1；草稿（有下拉）與已完結（唯讀文字）兩種畫面都量。"""
    sa = make_user(username="sc_sc", role="superadmin")
    seed(item_ids=(7, 8))
    page = open_page(live_server, e2e_browser, sa)
    if finalized:
        page.evaluate("() => { Alpine.$data(document.body).settlement.status = 'finalized' }")
        page.wait_for_timeout(300)
    rows = page.evaluate(_MEASURE_JS)
    assert rows, "沒有量到任何已對應列的文字"
    assert any(r["badge"] for r in rows), "沒有量到「已對應」徽章"
    bad = []
    for r in rows:
        fg, bg = (_dark(r["fg"]), _dark(r["bg"])) if dark else (r["fg"], r["bg"])
        c = _contrast(fg, bg)
        if c < 4.5:
            bad.append("%s %r badge=%s fg=%s bg=%s ⇒ %.2f:1" % (r["tag"], r["text"], r["badge"], r["fg"], r["bg"], c))
    assert not bad, "已對應列對比不足（dark=%s finalized=%s）：\n%s" % (dark, finalized, "\n".join(bad))
