# -*- coding: utf-8 -*-
"""第 52 班：報價單頁（quotation-form.html）公益捐款基數——total＝報價含稅 1%、不看毛利；direct＝舊算法；已結案單照自己的戳記。
用 node 載入頁面元件（同 test_overhead_s3_form_t48；沒有 node ⇒ skip）。"""
import shutil

import pytest

from tests.test_money_round_half_up_2026_09_26 import _page

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="沒有 node")

_SETUP = """
  o.q = { items: [{ type: 'item', qty: 1, unitPrice: 100000, amount: 100000, cost: 60000 }], discount: 0, freight: 0, taxRate: 5 }
  const run = () => { o.calcTotals(); const t = o.tot; return { admin: t.adminCost, charity: t.charityDonation, indirect: t.totalIndirect, net: t.netProfit, pct: t.netMarginPct, ver: t.formulaVer, basis: t.charityBasis, label: o.charityBasis() } }
"""


@needs_node
def test_total_basis_in_v2_uses_the_tax_inclusive_total():
    got = _page("quotation-form.html", "quotationForm", _SETUP + "o.oh = { mode: 'v2', defaultPct: 25, charityBasis: 'total' }; return run()")
    assert got == {"admin": 9250, "charity": 1050, "indirect": 10300, "net": 26700, "pct": 26.7, "ver": 2, "basis": "total", "label": "total"}


@needs_node
def test_direct_basis_in_v2_is_unchanged_and_carries_no_stamp():
    got = _page("quotation-form.html", "quotationForm", _SETUP + "o.oh = { mode: 'v2', defaultPct: 25, charityBasis: 'direct' }; return run()")
    assert got == {"admin": 9250, "charity": 370, "indirect": 9620, "net": 27380, "pct": 27.4, "ver": 2, "label": "direct"}


@needs_node
def test_total_basis_never_applies_on_the_legacy_ten_percent_basis():
    got = _page("quotation-form.html", "quotationForm", _SETUP + "o.oh = { mode: 'legacy', defaultPct: 25, charityBasis: 'total' }; return run()")
    assert got == {"admin": 10000, "charity": 370, "indirect": 10370, "net": 26630, "pct": 26.6, "label": "direct"}


@needs_node
def test_total_basis_loss_case_pays_charity_and_no_floor_note():
    got = _page("quotation-form.html", "quotationForm", _SETUP + """
        o.oh = { mode: 'v2', defaultPct: 25, charityBasis: 'total' }
        o.q.items[0].cost = 120000
        return run()""")
    assert got["admin"] == 0 and got["charity"] == 1050 and got["net"] < 0 and got["basis"] == "total"


@needs_node
def test_settled_quote_follows_its_own_stamp_not_the_current_mode():
    got = _page("quotation-form.html", "quotationForm", _SETUP + """
        o.oh = { mode: 'v2', defaultPct: 25, charityBasis: 'total' }
        o.q.dealTag = '已結案'
        o.q.tot = { formulaVer: 2 }                                  // 新管銷口徑、但沒有公益戳記 ⇒ 舊基
        const a = run()
        o.q.tot = { formulaVer: 2, charityBasis: 'total' }
        const b = run()
        o.q.tot = {}                                                  // 最舊口徑 ⇒ 舊基
        const c = run()
        return { a: a.charity, b: b.charity, c: c.charity, cver: c.ver || 1 }""")
    assert got == {"a": 370, "b": 1050, "c": 370, "cver": 1}


@needs_node
def test_label_text_follows_the_basis_in_the_page_source():
    src = open(__import__("os").path.join(__import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.dirname(__file__))),
                                          "frontend", "pages", "quotation-form.html"), encoding="utf-8").read()
    assert "公益捐款（報價含稅 1%）" in src and "公益捐款（直接毛利 1%）" in src and "qf-charity-label" in src
    assert "charityBasis() !== 'total'" in src, "新基沒有『虧損案以 0 計』提示"
