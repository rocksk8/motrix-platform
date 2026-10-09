# -*- coding: utf-8 -*-
"""第 48 班 S3：報價單頁（quotation-form.html）管銷分攤——口徑開關、比率輸入驗證、偏離預設、已精算案凍結。
用 node 載入頁面元件直接呼叫方法（同 test_money_round_half_up 的做法；沒有 node ⇒ skip）。"""
import shutil

import pytest

from tests.test_money_round_half_up_2026_09_26 import _page

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="沒有 node")

_SETUP = """
  o.q = { items: [{ type: 'item', qty: 1, unitPrice: 100000, amount: 100000, cost: 60000 }], discount: 0, freight: 0, taxRate: 5 }
  const run = () => { o.calcTotals(); const t = o.tot; return { admin: t.adminCost, charity: t.charityDonation, indirect: t.totalIndirect, net: t.netProfit, pct: t.netMarginPct, ver: t.formulaVer, oh: t.overheadPct } }
"""


@needs_node
def test_legacy_mode_keeps_the_ten_percent_numbers():
    got = _page("quotation-form.html", "quotationForm", _SETUP + "return run()")
    assert got == {"admin": 10000, "charity": 370, "indirect": 10370, "net": 26630, "pct": 26.6}          # legacy：tot 不帶 formulaVer／overheadPct（JSON 省略 undefined）


@needs_node
def test_v2_mode_uses_direct_profit_times_pct_and_stamps_version():
    got = _page("quotation-form.html", "quotationForm", _SETUP + "o.oh = { mode: 'v2', defaultPct: 25 }; return run()")
    assert got == {"admin": 9250, "charity": 370, "indirect": 9620, "net": 27380, "pct": 27.4, "ver": 2, "oh": 25}
    got = _page("quotation-form.html", "quotationForm", _SETUP + "o.oh = { mode: 'v2', defaultPct: 25 }; o.q.overheadPct = 12.5; return run()")
    assert got["admin"] == 4625 and got["oh"] == 12.5


@needs_node
def test_v2_negative_direct_profit_has_zero_overhead():
    got = _page("quotation-form.html", "quotationForm", _SETUP + """
        o.oh = { mode: 'v2', defaultPct: 25 }
        o.q.items[0].cost = 99000
        return run()""")
    assert got["admin"] == 0 and got["charity"] == 0


@needs_node
def test_settled_quote_is_not_recomputed_with_the_new_formula():
    got = _page("quotation-form.html", "quotationForm", _SETUP + """
        o.oh = { mode: 'v2', defaultPct: 25 }
        o.q.dealTag = '已結案'                       // 舊單（沒有 formulaVer）⇒ 維持舊口徑
        const a = run()
        o.q.tot = { formulaVer: 2 }; o.q.overheadPct = 30    // 新口徑蓋過戳記的已結案單 ⇒ 照存的口徑與比率
        const b = run()
        return { a: a.admin, b: b.admin, bv: b.ver }""")
    assert got == {"a": 10000, "b": 11100, "bv": 2}


@needs_node
def test_pct_input_validation_deviation_warning_and_reset():
    got = _page("quotation-form.html", "quotationForm", _SETUP + """
        o.oh = { mode: 'v2', defaultPct: 25 }
        o.setDirty = () => {}                       // 真的 setDirty 會排自動存檔計時器，node 不會結束
        const alerts = []; globalThis.alert = (m) => alerts.push(m)
        o.setOhPct('abc'); o.setOhPct('101'); o.setOhPct('12.34'); o.setOhPct('')
        const afterBad = { pct: o.ohPct(), n: alerts.length }
        o.setOhPct('30')
        const dev = o.ohDeviates()
        const admin30 = o.tot.adminCost
        o.resetOhPct()
        return { afterBad, dev, admin30, afterReset: o.ohPct(), devAfter: o.ohDeviates() }""")
    assert got == {"afterBad": {"pct": 25, "n": 4}, "dev": True, "admin30": 11100, "afterReset": 25, "devAfter": False}


@needs_node
def test_legacy_mode_never_flags_deviation():
    got = _page("quotation-form.html", "quotationForm", _SETUP + "o.q.overheadPct = 40; return { dev: o.ohDeviates(), ver: o.ohVer() }")
    assert got == {"dev": False, "ver": 1}


@needs_node
def test_form_tax_rate_keeps_the_old_semantics_missing_is_five_null_or_blank_is_zero():
    got = _page("quotation-form.html", "quotationForm", _SETUP + """
        const out = {}
        for (const v of [undefined, null, '', 0, 5]) { o.q.taxRate = v; o.calcTotals(); out[String(v)] = o.tot.tax }
        return out""")
    assert got == {"undefined": 5000, "null": 0, "": 0, "0": 0, "5": 5000}, got        # 舊語意不動；後端 effective_tax_rate 對齊（見 test_overhead_s2_t48）


@needs_node
def test_five_indirect_costs_counted_only_on_the_old_basis():
    """報價單頁：五個間接成本輸入已拿掉。舊口徑（legacy 模式、已精算／結案單）既有值照計；新口徑一律不計；唯讀列只在舊口徑且有值時出現。"""
    got = _page("quotation-form.html", "quotationForm", _SETUP + """
        o.q.indirectLogistics = 1000; o.q.indirectOther = 200
        const legacy = run().indirect
        o.oh = { mode: 'v2', defaultPct: 25 }
        const v2 = run().indirect
        o.q.dealTag = '已結案'
        const settled = run().indirect
        return { legacy, v2, settled, sum: o.legacyIndirectSum(), verSettled: o.ohVer() }""")
    assert got == {"legacy": 10370 + 1200, "v2": 9620, "settled": 10370 + 1200, "sum": 1200, "verSettled": 1}, got


def test_the_five_inputs_are_gone_from_the_page_markup():
    from core import source_tree
    html = source_tree.page_file("quotation-form.html").read_text(encoding="utf-8")
    for k in ("indirectLogistics", "indirectInstallation", "indirectTravel", "indirectWarranty", "indirectOther"):
        assert 'data-num="%s"' % k not in html and "setNumField(q, '%s'" % k not in html, k
    assert "qf-legacy-indirect" in html


@needs_node
def test_row_switch_and_deviation_follow_the_quotes_own_basis_not_the_global_mode():
    """稽核 b5：全域 mode=v2 時，已結案的舊口徑單（沒有 formulaVer）仍是 10% 口徑——畫面要顯示『管銷分攤（10%，固定）』那一列、不顯示 25% 那一列，也不出偏離警示。"""
    got = _page("quotation-form.html", "quotationForm", _SETUP + """
        o.oh = { mode: 'v2', defaultPct: 25 }
        o.q.overheadPct = 40
        const unsettled = { ver: o.ohVer(), dev: o.ohDeviates(), admin: run().admin }
        o.q.dealTag = '已結案'                       // 舊單：沒有 formulaVer
        const settledLegacy = { ver: o.ohVer(), dev: o.ohDeviates(), admin: run().admin }
        o.q.tot = { formulaVer: 2 }                 // 已結案但存的是新口徑戳記
        const settledV2 = { ver: o.ohVer(), dev: o.ohDeviates() }
        return { unsettled, settledLegacy, settledV2 }""")
    assert got["unsettled"] == {"ver": 2, "dev": True, "admin": 14800}, got
    assert got["settledLegacy"] == {"ver": 1, "dev": False, "admin": 10000}, got
    assert got["settledV2"] == {"ver": 2, "dev": True}, got


def test_the_two_admin_rows_are_switched_by_the_quotes_basis_in_the_markup():
    import pathlib
    from core import source_tree
    html = source_tree.page_file("quotation-form.html").read_text(encoding="utf-8")
    assert '<div class="cost-row" x-show="ohVer() !== 2">' in html and 'x-show="ohVer() === 2" x-cloak style="flex-wrap:wrap" data-testid="qf-overhead-row"' in html
    assert "x-show=\"oh.mode" not in html, "列的顯示不可以再看全域開關"
    assert "ohDeviates() { return this.ohVer() === 2" in html
