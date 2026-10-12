# -*- coding: utf-8 -*-
"""M3 T5／T6（T57）：quotation-form.html 的擇一方案接線（靜態檢查；e2e 由閘門跑）。
計算規則本身的前後端等值在 test_quote_alt_t3_2026_10_13（黃金向量）。"""
import pathlib
import re

FORM = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "pages" / "quotation-form.html").read_text(encoding="utf-8")


def test_form_loads_alt_items_before_use():
    assert FORM.index('static/alt-items.js') < FORM.index("const FORM_VERSION")
    assert "static/profit-rules.js" in FORM


def test_calc_totals_goes_through_counted_items():
    m = re.search(r"calcTotals\(\) \{\s*const items = (.*)", FORM)
    assert m and "MotrixAltItems.countedItems(this.q)" in m.group(1)


def test_totals_cells_use_template_text_only_when_flagged_and_unpicked():
    assert "altTotalsText() || tot.pretax.toLocaleString()" in FORM and "altTotalsText() || tot.total.toLocaleString()" in FORM
    assert "altTotalsText() { return this.altUnpicked() > 0" in FORM
    assert 'type="checkbox" :checked="q.totalsByAlt === true"' in FORM         # 使用者 2026-10-11 裁示的總開關
    assert "勾選「合計依方案選擇」後，擇一品項才會依客戶選定的方案計入合計" in FORM


def test_unpicked_state_is_neutral_not_green():
    assert "altUnpicked() ? '' : MotrixMargin.tone(tot.directMarginPct)" in FORM
    assert "還沒選定，下面的毛利是不含擇一品項的暫估" in FORM


def test_plan_panel_is_cost_gated_and_front_end_does_not_compute():
    panel = FORM[FORM.index('data-testid="qf-alt-plan"') - 200: FORM.index('data-testid="qf-alt-plan"') + 6000]
    assert 'x-show="showCostCols' in panel
    assert "/plan-view" in FORM and "plan.data" in panel
    assert "reduce(" not in panel                       # 面板只呈現後端回傳，不自算


def test_notes_preview_uses_single_pass_replace_not_format():
    seg = FORM[FORM.index("altNotePreview() {"): FORM.index("async loadAltConfig")]
    assert r".replace(/\{(items|group)\}/g" in seg and "format(" not in seg and "innerHTML" not in seg


def test_picks_are_never_written_by_the_form():
    assert not re.search(r"\.altPicks\s*=", FORM) and not re.search(r"altPicks\[[^\]]+\]\s*=", FORM)


def test_form_version_bumped_to_v3_23():
    assert "const FORM_VERSION = 'V3.23'" in FORM


def test_alt_group_toggle_removes_key_and_texts_are_plain_language():
    assert "delete item.altGroup" in FORM
    for w in ("擇一方案", "合計依方案選擇", "擇一方案比較", "展開組合比較"):
        assert w in FORM
    seg = FORM[FORM.index('data-testid="qf-alt-row"'): FORM.index('data-testid="qf-alt-row"') + 1200]
    assert "altGroup" in seg and "quote_alt" not in FORM


# --- 行為（node 載入頁面元件，同 test_overhead_s3_form_t48 的做法）--------------------------
import shutil

import pytest

from tests.test_money_round_half_up_2026_09_26 import _page

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="沒有 node")

_SETUP = """
  const it = (id, qty, price, cost, g) => Object.assign({ id, type: 'item', qty, unitPrice: price, amount: qty * price, cost, description: id }, g ? { altGroup: g } : {})
  o.q = { items: [it('a', 1, 1000, 600), it('x1', 1, 3000, 2000, '投影機'), it('x2', 1, 5000, 3500, '投影機')], discount: 0, freight: 0, taxRate: 5, totalsByAlt: true }
  o.setDirty = () => {}
"""


@needs_node
def test_calc_totals_counts_only_picked_alt_item_and_matches_plain_quote():
    got = _page("quotation-form.html", "quotationForm", _SETUP + """
      o.calcTotals(); const none = { sub: o.tot.subtotal, cost: o.tot.totalCost }
      o.q.altPicks = { '投影機': 'x2' }; o.calcTotals(); const picked = { sub: o.tot.subtotal, cost: o.tot.totalCost, total: o.tot.total }
      return { none, picked, unpicked: o.altUnpicked(), dropped: o.altIsDropped(o.q.items[1]), kept: o.altIsDropped(o.q.items[2]) }""")
    assert got["none"] == {"sub": 1000, "cost": 600}
    assert got["picked"] == {"sub": 6000, "cost": 4100, "total": 6300}
    assert got["unpicked"] == 0 and got["dropped"] is True and got["kept"] is False


@needs_node
def test_total_text_and_note_preview_and_issues():
    got = _page("quotation-form.html", "quotationForm", _SETUP + """
      const t1 = o.altTotalsText(); const t0 = ''
      o.q.altPicks = { '投影機': 'x1' }; const t2 = o.altTotalsText(); delete o.q.altPicks
      o.q.items[1].altGroup = '{items}'      // 組名含大括號不可被當範本
      const notes = o.altNotePreview()
      o.q.items[2].altGroup = '別組'
      return { t0, t1, t2, notes, issues: o.altIssues() }""")
    assert got["t1"] == "依方案選擇" and got["t2"] == ""
    assert got["notes"] == ["項次2為{items}擇一方案選擇", "項次3為投影機擇一方案選擇"]
    assert len(got["issues"]) == 2 and "只有 1 個品項" in got["issues"][0]


@needs_node
def test_toggle_adds_and_removes_group_without_leaving_empty_key():
    got = _page("quotation-form.html", "quotationForm", _SETUP + """
      const b = { type: 'item', id: 'n', qty: 1, unitPrice: 1, amount: 1, cost: 0 }
      o.q.items.push(b); o.altToggle(b, true); const g = b.altGroup; o.altToggle(b, false)
      return { g, has: 'altGroup' in b }""")
    assert got == {"g": "投影機", "has": False}


@needs_node
def test_switch_off_makes_groups_inert_in_the_form():
    got = _page("quotation-form.html", "quotationForm", _SETUP + """
      o.q.altPicks = { '投影機': 'x1' }
      o.q.totalsByAlt = false; o.calcTotals()
      return { sub: o.tot.subtotal, unpicked: o.altUnpicked(), txt: o.altTotalsText(), dropped: o.altIsDropped(o.q.items[2]), notes: o.altNotePreview() }""")
    assert got == {"sub": 9000, "unpicked": 0, "txt": "", "dropped": False, "notes": []}


def test_sign_dialog_requires_every_group_and_posts_picks():
    assert 'data-testid="qf-alt-sign-dialog"' in FORM and "altSignReady()" in FORM
    seg = FORM[FORM.index("async confirmAltSign()"): FORM.index("async uploadQuotationSignedFiles")]
    assert "action: 'sign'" in seg and "picks: this.signPick.picks" in seg
    assert "MotrixAltItems.active(this.q) && this.altGroupNames().length" in FORM        # 只有擇一方案單才走對話框


def test_sign_dialog_needs_saved_form_and_uses_toast_not_alert():
    seg = FORM[FORM.index("async toggleQuotationSigned(action)"): FORM.index("async confirmAltSign()")]
    assert "if (this.isDirty)" in seg and "this.toast(" in seg
    conf = FORM[FORM.index("async confirmAltSign()"): FORM.index("async uploadQuotationSignedFiles")]
    assert "alert(" not in conf and "this.toast(" in conf
