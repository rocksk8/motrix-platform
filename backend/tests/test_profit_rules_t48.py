# -*- coding: utf-8 -*-
"""第 48 班 S1：利潤規則（helpers/profit_rules.py ＋ static/profit-rules.js）。

三道：① 黃金向量（Python）② 與『舊的內嵌算式』獨立對拍（證明 S1 零行為變更：ver 1 逐位等於第 47 班的 calcTotals／calcSummary／
settlement_actuals 算式）與 ver 2 的獨立 Decimal 對拍 ③ node 載入前端檔、同一份向量比對（沒有 node ⇒ skip，同 legal-round 前例）。
突變檢查見 docs/platform/plans/OVERHEAD-25PCT-OPERATING-PROFIT-DESIGN-T48.md §9。
"""
import json
import pathlib
import shutil
import subprocess
from decimal import ROUND_HALF_UP, Decimal

import pytest

from helpers import profit_rules as P

ROOT = pathlib.Path(__file__).resolve().parents[2]
VECTORS = json.loads((pathlib.Path(__file__).parent / "data" / "profit_rules_vectors.json").read_text(encoding="utf-8"))["cases"]


def _run(c):
    fn, a, ver, pct = c["fn"], c["args"], c["ver"], c["pct"]
    if fn == "quote":
        return P.quote_profit(a[0], a[1], a[2], a[3], pct, ver, c.get("total"), c.get("basis"))
    if fn == "settlement":
        return P.settlement_profit(a[0], a[1], pct, ver, a[2], c.get("total"), c.get("basis"))
    if fn == "adminCost":
        return P.admin_cost(a[0], a[1], pct, ver)
    if fn == "charity":
        return P.charity(a[0], c.get("total"), c.get("basis") or "direct")
    return P.pct_rate(a[0])


def test_vectors_python():
    assert len(VECTORS) >= 200
    bad = [c for c in VECTORS if _run(c) != c["expect"]]
    assert not bad, bad[:3]


# ── 獨立對拍（不 import 被測模組的算式）──────────────────────────────────────────────
def _hu(amount, rate):
    return int((Decimal(repr(amount)) * Decimal(str(rate))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _old_quote(pretax, cost, vat, five):
    """第 47 班 quotation-form.html calcTotals 的算式（逐行照抄）。"""
    direct = pretax - cost - vat
    admin = _hu(pretax, 0.10)
    charity = max(0, _hu(direct, 0.01))
    total_indirect = admin + charity + (five[0] or 0) + (five[1] or 0) + (five[2] or 0) + (five[3] or 0) + (five[4] or 0)
    net = direct - total_indirect
    return admin, charity, total_indirect, net, (net / pretax * 100 if pretax > 0 else 0)


def test_ver1_equals_the_inline_formulas_of_train_47():
    n = 0
    for c in VECTORS:
        if c["fn"] != "quote" or c["ver"] != 1:
            continue
        a = c["args"]
        r = P.quote_profit(a[0], a[1], a[2], a[3])               # 不傳 ver ⇒ ACTIVE_VER
        admin, ch, ti, net, npct = _old_quote(*a)
        assert (r["adminCost"], r["charityDonation"], r["totalIndirect"], r["netProfit"], r["netMarginPct"]) == (admin, ch, ti, net, npct), a
        n += 1
    assert n >= 10
    assert P.ACTIVE_VER == P.LEGACY_VER, "S1 不改行為；S2 才切 ACTIVE_VER"
    # 精算端：admin = halfUp(稅前,0.10)、charity = max(0, halfUp(毛利,0.01))、net = 毛利 − admin − charity
    for pretax, cost in [(100000, 70000), (100000, 105000), (35000, 20001), (0, 0), (777777, 123456.5)]:
        gross = pretax - cost
        s = P.settlement_profit(pretax, cost)
        assert (s["adminCost"], s["charityDonation"], s["netProfit"]) == (_hu(pretax, 0.10), max(0, _hu(gross, 0.01)), gross - _hu(pretax, 0.10) - max(0, _hu(gross, 0.01)))


def test_ver2_matches_an_independent_decimal_oracle():
    for pretax, cost, vat in [(100000, 60000, 3000), (35000, 20001, 1000), (100000, 99000, 4950), (1250, 0, 0), (10010, 0, 0)]:
        direct = pretax - cost - vat
        for pct in ("25", "12.5", "7.1", "0", "100"):
            expect = int((Decimal(max(direct, 0)) * Decimal(pct) / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            assert P.admin_cost(pretax, direct, pct, 2) == expect, (direct, pct)
    assert P.admin_cost(100000, -5000, 25, 2) == 0, "直接毛利為負 ⇒ 管銷 0（Q2）"
    assert P.admin_cost(100000, 2, 25, 2) == 1 and P.admin_cost(100000, 6, 25, 2) == 2     # 0.5 進位、1.5 進位
    assert P.admin_cost(100000, 40000, 25, 2) == P.admin_cost(100000, 0, 0, 1) == 10000, "打平點：直毛率 40% ⇒ 兩種口徑相同"


def test_default_pct_and_target_constants():
    assert P.DEFAULT_OVERHEAD_PCT == 25 and P.TARGET_MARGIN_PCT == 12
    assert P.admin_cost(0, 80000, None, 2) == 20000, "ver 2 沒給 pct ⇒ 預設 25"


# ── 前端（node）────────────────────────────────────────────────────────────────────
NODE = shutil.which("node")
_JS = r"""
const fs = require('fs'); global.window = {}
eval(fs.readFileSync(process.argv[2], 'utf8')); global.MotrixLegalRound = window.MotrixLegalRound
const P = require(process.argv[3])
const cases = JSON.parse(fs.readFileSync(process.argv[4], 'utf8')).cases
const out = cases.map(c => {
  const a = c.args
  if (c.fn === 'quote') return P.quote(a[0], a[1], a[2], a[3], c.pct, c.ver, c.total, c.basis)
  if (c.fn === 'settlement') return P.settlement(a[0], a[1], c.pct, c.ver, a[2], c.total, c.basis)
  if (c.fn === 'adminCost') return P.adminCost(a[0], a[1], c.pct, c.ver)
  if (c.fn === 'charity') return P.charity(a[0], c.total, c.basis || 'direct')
  return P.pctRate(a[0])
})
process.stdout.write(JSON.stringify(out))
"""


@pytest.mark.skipif(not NODE, reason="沒有 node：前端等值題略過（同 legal-round 前例）")
def test_frontend_js_equals_python_vectors(tmp_path):
    runner = tmp_path / "run_profit_rules.js"
    runner.write_text(_JS, encoding="utf-8")
    cp = subprocess.run([NODE, str(runner), str(ROOT / "frontend/static/legal-round.js"), str(ROOT / "frontend/static/profit-rules.js"),
                         str(pathlib.Path(__file__).parent / "data" / "profit_rules_vectors.json")],
                        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert cp.returncode == 0, cp.stderr
    got = json.loads(cp.stdout)
    bad = [(c, g) for c, g in zip(VECTORS, got) if g != c["expect"]]
    assert len(got) == len(VECTORS) and not bad, bad[:3]



def test_new_basis_ignores_the_five_indirect_items_old_basis_counts_them():
    """使用者 2026-10-09：運輸物流／安裝施工／差異項／保固預估／其他費用 不再輸入，新口徑（ver 2）一律不計；舊口徑（ver 1，含已精算／結案單）照舊。"""
    five = [1000, 2000, 500, 300, 200]
    old = P.quote_profit(100000, 60000, 3000, five, ver=1)
    new = P.quote_profit(100000, 60000, 3000, five, pct=25, ver=2)
    assert old["totalIndirect"] == 10000 + 370 + 4000 and old["netProfit"] == 37000 - 14370
    assert new["totalIndirect"] == 9250 + 370 and new["netProfit"] == 37000 - 9620
    assert new == P.quote_profit(100000, 60000, 3000, [0] * 5, pct=25, ver=2), "新口徑：給不給五項結果都一樣"


# ── 第 52 班：公益捐款基數 total（報價含稅 × 1%，不設下限）──────────────────────
def test_charity_total_basis_matches_an_independent_oracle_and_has_no_floor():
    for total in (0, 49, 50, 149, 150, 1050, 105000, 999999):
        expect = int((Decimal(total) * Decimal("0.01")).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        assert P.charity(-123456, total, "total") == expect == P.charity(999, total, "total"), "total 基數與直接毛利無關"
    assert P.charity(5000, -5000, "total") == 0, "負的含稅金額不可變成收入（下限只設在含稅金額上）"
    r = P.quote_profit(100000, 120000, 6000, [0] * 5, pct=25, ver=2, total=105000, charity_basis="total")
    assert r["directProfit"] == -26000 and r["adminCost"] == 0 and r["charityDonation"] == 1050, "虧損案照扣（不再下限 0）"
    assert r["netProfit"] == -26000 - 0 - 1050
    s = P.settlement_profit(100000, 105000, 25, 2, None, 105000, "total")
    assert s["charityDonation"] == 1050 and s["netProfit"] == -5000 - 0 - 1050


def test_old_basis_and_ver1_are_bit_identical_to_before():
    for c in VECTORS:
        if c["fn"] == "quote" and c.get("basis") is None:
            a = c["args"]
            assert P.quote_profit(a[0], a[1], a[2], a[3], c["pct"], c["ver"]) == c["expect"]
    # ver 1 即使被要求 total 基數也維持直接毛利基（最舊口徑不可被悄悄改）
    a = P.quote_profit(100000, 60000, 3000, [0] * 5, ver=1)
    assert a == P.quote_profit(100000, 60000, 3000, [0] * 5, ver=1, total=105000, charity_basis="total")
    assert P.ACTIVE_CHARITY_BASIS == "direct", "預設舊基：上線零行為變更"
    # 預設不傳基數時 ver 2 仍是舊基
    assert P.quote_profit(100000, 60000, 3000, [0] * 5, pct=25, ver=2)["charityDonation"] == 370


def test_total_basis_requires_the_amount_and_rejects_unknown_basis():
    with pytest.raises(ValueError):
        P.charity(1000, None, "total")
    with pytest.raises(ValueError):
        P.quote_profit(100000, 60000, 3000, [0] * 5, pct=25, ver=2, charity_basis="total")      # 沒給含稅金額
    with pytest.raises(ValueError):
        P.quote_profit(100000, 60000, 3000, [0] * 5, pct=25, ver=2, charity_basis="oops")
