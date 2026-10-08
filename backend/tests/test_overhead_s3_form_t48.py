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
