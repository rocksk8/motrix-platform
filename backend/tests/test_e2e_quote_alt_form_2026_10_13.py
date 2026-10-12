# -*- coding: utf-8 -*-
"""M3 擇一方案：報價單表單的瀏覽器驗證（T5／T6；只寫碼，閘門才跑）。
涵蓋：品項勾「擇一方案」→ 組別輸入出現；未選定時合計只算一般品項、合計兩格顯示設定文字、成本分機轉『暫估』中性色；
存檔後內部『擇一方案比較』面板出現且列出各選項；組內只剩 1 項時顯示警示；列印預覽（客戶樣式）不含成本字樣。"""
from tests._requires import requires_module  # noqa: E402
needs_m01 = requires_module("case", "本題打 M01（案件）的端點")

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login as _login  # noqa: E402,F401


def _ready(page):
    page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')"
                           " && Alpine.$data(document.querySelector('[x-data]')).q", timeout=15000)


_ITEMS_JS = """() => {
  const d = Alpine.$data(document.querySelector('[x-data]'));
  const it = (id, desc, price, cost, g) => Object.assign({ id, type: 'item', description: desc, qty: 1, unit: '式', cost, margin: 0.3,
    unitPrice: price, unitPriceOverride: true, amount: price, notes: '' }, g ? { altGroup: g } : {});
  d.q.customerName = '擇一客'; d.q.projectName = '擇一案';
  d.q.items = [it('a', '一般品項', 1000, 600), it('x1', '方案甲', 3000, 2000, '投影機'), it('x2', '方案乙', 5000, 3500, '投影機')];
  d.showCostCols = true; d.calcTotals();
}"""


@needs_m01
@pytest.mark.e2e
def test_alt_group_totals_placeholder_and_cost_panel(live_server, make_user, e2e_browser):
    u, pw = make_user(username="alt_e2e", role="superadmin")
    page = e2e_browser.new_page()
    _login(page, live_server, u, pw)
    page.goto(live_server + "/pages/quotation-form.html")
    _ready(page)
    page.evaluate(_ITEMS_JS)
    # 組別輸入與標記出現；合計只算一般品項
    assert page.locator("[data-testid=qf-alt-row] input[list=alt-group-options]:visible").count() == 2
    got = page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]')); return { sub: d.tot.subtotal, cost: d.tot.totalCost, unpicked: d.altUnpicked(), txt: d.altTotalsText() } }")
    assert got == {"sub": 1000, "cost": 600, "unpicked": 1, "txt": "依方案選擇"}
    # 合計兩格顯示設定文字、成本分機標暫估
    cells = page.locator(".totals-grid .total-row .total-amount, .totals-grid .total-row.grand span:last-child")
    assert "依方案選擇" in page.locator(".totals-grid").inner_text()
    assert page.locator("[data-testid=qf-alt-estimate]").is_visible()
    # 外觀：未選定時毛利率不帶 success／warning／danger 色別
    cls = page.evaluate("() => [...document.querySelectorAll('.cost-row__val')].map(e => e.className).join(' ')")
    assert "success" not in page.locator(".cost-row", has_text="直接毛利率").locator(".cost-row__val").get_attribute("class")
    assert cells.count() >= 1


@needs_m01
@pytest.mark.e2e
def test_single_item_group_warns_and_toggle_off_removes_group(live_server, make_user, e2e_browser):
    u, pw = make_user(username="alt_e2e2", role="superadmin")
    page = e2e_browser.new_page()
    _login(page, live_server, u, pw)
    page.goto(live_server + "/pages/quotation-form.html")
    _ready(page)
    page.evaluate(_ITEMS_JS)
    page.evaluate("() => { const d = Alpine.$data(document.querySelector('[x-data]')); delete d.q.items[2].altGroup }")
    assert "只有 1 個品項" in page.locator("[data-testid=qf-alt-issues]").inner_text()
    page.locator("[data-testid=qf-alt-row] input[type=checkbox]").nth(1).uncheck()
    assert page.evaluate("() => 'altGroup' in Alamo".replace("Alamo", "Alpine.$data(document.querySelector('[x-data]')).q.items[1]")) is False
    assert page.locator("[data-testid=qf-alt-issues]").is_hidden()


@needs_m01
@pytest.mark.e2e
def test_saved_quote_shows_plan_panel_and_preview_has_no_cost(live_server, make_user, e2e_browser):
    u, pw = make_user(username="alt_e2e3", role="superadmin")
    page = e2e_browser.new_page()
    _login(page, live_server, u, pw)
    page.goto(live_server + "/pages/quotation-form.html")
    _ready(page)
    page.evaluate(_ITEMS_JS)
    ok = page.evaluate("async () => { const d = Alpine.$data(document.querySelector('[x-data]')); return await d.saveDraft() }")
    assert ok is not False
    page.wait_for_selector("[data-testid=qf-alt-plan]:visible", timeout=15000)
    page.wait_for_function("() => Alpine.$data(document.querySelector('[x-data]')).plan.data !== null", timeout=15000)
    txt = page.locator("[data-testid=qf-alt-plan]").inner_text()
    assert "方案甲" in txt and "方案乙" in txt
    # 組合預設收合；展開後有列
    assert "展開組合比較" in txt
    page.get_by_role("button", name="展開組合比較").click()
    page.wait_for_function("() => Alpine.$data(document.querySelector('[x-data]')).plan.data.combos !== undefined", timeout=15000)
    # 客戶樣式預覽（伺服器版面）不含成本字樣、合計兩格為設定文字
    html = page.evaluate("""async () => {
      const d = Alpine.$data(document.querySelector('[x-data]'));
      const r = await fetch('/api/quotations/preview-html', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + d.session.token },
        body: JSON.stringify({ quoteNo: d.q.quoteNo, data: JSON.parse(JSON.stringify(d.q)), internal: false }) });
      return r.ok ? (await r.json()).html : '' }""")
    assert html, "預覽端點應回 HTML"
    body = html.split("<body>")[-1]
    assert "依方案選擇" in body and "方案比較" not in body and "毛利" not in body and "管銷" not in body and "成本" not in body
