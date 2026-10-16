# -*- coding: utf-8 -*-
"""T68 Q1：利潤口徑三個數字（管銷後備 25／公益比率 1%／目標利潤率 12）改由設定帶入；預設＝今天（等值）。

守的事：① 不傳新參數 ⇒ 與既有黃金向量逐位相同（既有 test_profit_rules_t48 另守）② 傳了比率 ⇒ 對拍獨立 Decimal 算式 ③ 前端 configure() 與後端同一組案例逐位相同（node）
④ 設定 profit_rules.charity_rate_pct 預設 1、調低＝放寬（D-K1：待生效＋第二位最高管理者）、讀不到／不合法 ⇒ 1 ⑤ 端點多回兩個鍵 ⑥ 標籤字樣預設不變。
"""
import json
import pathlib
import shutil
import subprocess
from decimal import ROUND_HALF_UP, Decimal

import pytest

from helpers import profit_rules as P
from helpers import profit_warning as PW
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as SR

ROOT = pathlib.Path(__file__).resolve().parents[3]
CASES = [  # (fn, args, kwargs)
    ("charity", (37000, None, "direct"), {"rate_pct": 0.5}),
    ("charity", (37000, 109000, "total"), {"rate_pct": 2.5}),
    ("charity", (-500, None, "direct"), {"rate_pct": 3}),
    ("charity", (999, -5000, "total"), {"rate_pct": 3}),
    ("charity", (123456, None, "direct"), {"rate_pct": 0}),
    ("charity", (123456, None, "direct"), {"rate_pct": 0.05}),
    ("adminCost", (100000, 40000, None, 2), {"default_pct": 30}),
    ("adminCost", (100000, 40000, 20, 2), {"default_pct": 30}),          # 有給 pct ⇒ 後備值不介入
    ("adminCost", (100000, 40000, None, 1), {"default_pct": 30}),        # 舊口徑不看比率
    ("quote", (100000, 60000, 3000, [0, 0, 0, 0, 0], None, 2, 105000, "total"), {"rate_pct": 2, "default_pct": 30}),
    ("quote", (100000, 60000, 3000, [1000, 2000, 500, 300, 200], None, 1), {"rate_pct": 0.5}),
    ("settlement", (100000, 70000, None, 2, None, 105000, "direct"), {"rate_pct": 1.5, "default_pct": 20}),
    ("settlement", (100000, 70000, None, 2, 123, 105000, "direct"), {"rate_pct": 1.5}),          # 已凍結公益金不重算
]


def _py(c):
    fn, a, kw = c
    rp, dp = kw.get("rate_pct"), kw.get("default_pct")
    if fn == "charity":
        return P.charity(a[0], a[1], a[2], rp)
    if fn == "adminCost":
        return P.admin_cost(a[0], a[1], a[2], a[3], dp)
    if fn == "quote":
        a = list(a) + [None] * (8 - len(a))
        return P.quote_profit(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], rp, dp)
    return P.settlement_profit(a[0], a[1], a[2], a[3], a[4], a[5], a[6], rp, dp)


def _hu(amount, rate):
    return int((Decimal(str(amount)) * Decimal(str(rate))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def test_defaults_without_new_params_equal_the_builtin_numbers():
    assert P.CHARITY_RATE == 0.01 and P.DEFAULT_OVERHEAD_PCT == 25 and P.TARGET_MARGIN_PCT == 12
    for g, t in [(37000, 109000), (-5, 10), (123456, 0), (999, 1)]:
        assert P.charity(g, t, "direct") == P.charity(g, t, "direct", 1) == max(0, _hu(g, "0.01"))
        assert P.charity(g, t, "total") == P.charity(g, t, "total", 1) == max(0, _hu(t, "0.01"))
    assert P.admin_cost(0, 80000, None, 2) == P.admin_cost(0, 80000, None, 2, 25) == 20000
    q0 = P.quote_profit(100000, 60000, 3000, [0] * 5, 25, 2, 105000, "total")
    assert q0 == P.quote_profit(100000, 60000, 3000, [0] * 5, 25, 2, 105000, "total", 1, 25)
    s0 = P.settlement_profit(100000, 70000, 25, 2, None, 105000, "direct")
    assert s0 == P.settlement_profit(100000, 70000, 25, 2, None, 105000, "direct", 1, 25)


@pytest.mark.parametrize("rate", [0, 0.05, 0.5, 1, 1.5, 2.5, 10])
def test_charity_rate_matches_an_independent_oracle(rate):
    for g in (-1000, 0, 37000, 123457):
        assert P.charity(g, None, "direct", rate) == max(0, _hu(g, Decimal(str(rate)) / 100)), (g, rate)
    for t in (-5000, 0, 105000, 99999):
        assert P.charity(0, t, "total", rate) == max(0, _hu(t, Decimal(str(rate)) / 100)), (t, rate)


def test_default_pct_only_fills_a_missing_pct():
    assert P.admin_cost(100000, 40000, None, 2, 30) == 12000
    assert P.admin_cost(100000, 40000, 20, 2, 30) == 8000
    assert P.admin_cost(100000, 40000, None, 1, 30) == 10000, "舊口徑固定稅前 10%"


def test_rate_flows_through_quote_and_settlement():
    q = P.quote_profit(100000, 60000, 3000, [0] * 5, None, 2, 105000, "total", 2, 30)
    assert q["charityDonation"] == 2100 and q["adminCost"] == 11100          # 含稅 105000×2%；直接毛利 37000×30%
    s = P.settlement_profit(100000, 70000, None, 2, None, 105000, "direct", 1.5, 20)
    assert s["charityDonation"] == 450 and s["adminCost"] == 6000
    s2 = P.settlement_profit(100000, 70000, None, 2, 123, 105000, "direct", 1.5, 20)
    assert s2["charityDonation"] == 123, "已完結精算的存檔公益金不重算"


# ── 前端 configure()：同一組案例，node 載入 profit-rules.js 比對 ──────────────────────
NODE = shutil.which("node")
_JS = r"""
const fs = require('fs'); global.window = {}
eval(fs.readFileSync(process.argv[2], 'utf8')); global.MotrixLegalRound = window.MotrixLegalRound
const P = require(process.argv[3])
const cases = JSON.parse(fs.readFileSync(process.argv[4], 'utf8'))
const out = cases.map(c => {
  P.configure({ defaultPct: c.dp, charityRatePct: c.rp, targetMarginPct: 12 })
  const a = c.args
  if (c.fn === 'charity') return P.charity(a[0], a[1], a[2])
  if (c.fn === 'adminCost') return P.adminCost(a[0], a[1], a[2], a[3])
  if (c.fn === 'quote') return P.quote(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7])
  return P.settlement(a[0], a[1], a[2], a[3], a[4], a[5], a[6])
})
const t = []
for (const cfg of [undefined, {}, { defaultPct: 30, charityRatePct: 0.5, targetMarginPct: 15 }, { defaultPct: 'x', charityRatePct: -1, targetMarginPct: NaN },
                   { charityRatePct: 11 }, { charityRatePct: 1e-7 }, { defaultPct: 101 }]) {
  P.configure(cfg); t.push([P.DEFAULT_OVERHEAD_PCT, P.TARGET_MARGIN_PCT, P.charityRateText()])
}
P.configure({ charityRatePct: 1 }); const text1 = P.charityRateText()
P.configure({ charityRatePct: 0.5 }); const text2 = P.charityRateText()
P.configure({ charityRatePct: 2.5 }); const text3 = P.charityRateText()
process.stdout.write(JSON.stringify({ out: out, cfg: t, text: [text1, text2, text3] }))
"""


@pytest.mark.skipif(not NODE, reason="沒有 node：前端等值題略過（同 profit-rules 前例）")
def test_frontend_configure_equals_python(tmp_path):
    cases = [{"fn": c[0], "args": list(c[1]), "rp": c[2].get("rate_pct"), "dp": c[2].get("default_pct")} for c in CASES]
    runner = tmp_path / "run.js"
    runner.write_text(_JS, encoding="utf-8")
    data = tmp_path / "cases.json"
    data.write_text(json.dumps(cases), encoding="utf-8")
    cp = subprocess.run([NODE, str(runner), str(ROOT / "frontend/static/legal-round.js"), str(ROOT / "frontend/static/profit-rules.js"), str(data)],
                        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert cp.returncode == 0, cp.stderr
    got = json.loads(cp.stdout)
    want = [_py(c) for c in CASES]
    bad = [(c, g, w) for c, g, w in zip(CASES, got["out"], want) if g != w]
    assert len(got["out"]) == len(want) and not bad, bad[:3]
    # configure 的退路：缺漏／不合法 ⇒ 該欄回內建值（不是半套）
    assert got["cfg"] == [[25, 12, "1"], [25, 12, "1"], [30, 15, "0.5"], [25, 12, "1"], [25, 12, "1"], [25, 12, "1"], [25, 12, "1"]]
    assert got["text"] == ["1", "0.5", "2.5"]


# ── 設定與讀取 ───────────────────────────────────────────────────────────────
def test_setting_default_is_one_percent_and_loosening_needs_the_second_approver():
    f = SR._g("profit_rules")["fields"]["charity_rate_pct"]
    assert f.default == 1 and f.type == "float" and (f.min, f.max) == (0, 10)
    assert f.risk == "money" and f.loosen == "down", "調低＝少扣公益金＝放寬 ⇒ 走確認期間＋第二位最高管理者（D-K1）"
    assert SR.groups()["profit_rules"]["owner"] == "core" and SR._g("profit_rules")["sensitive"] is True
    for txt in (f.question, f.label, f.help, f.impact):
        assert "_" not in txt and "charity_rate_pct" not in txt, "說明用白話，不露鍵名"


def test_reader_falls_back_to_one_percent(monkeypatch):
    for bad in (None, True, "1", -1, 10.5, float("nan"), float("inf")):
        monkeypatch.setattr(SR, "get", lambda g, f, _b=bad, **kw: _b)
        assert PW.charity_rate_pct() == 1.0
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: (_ for _ in ()).throw(RuntimeError("db locked")))
    assert PW.charity_rate_pct() == 1.0
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: 0.5)
    assert PW.charity_rate_pct() == 0.5 and PW.charity_rate_text() == "0.5"
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: 2)
    assert PW.charity_rate_text() == "2"


def test_rules_config_payload_defaults():
    assert PW.rules_config() == {"charityRatePct": 1.0, "targetMarginPct": 12.0}


def test_labels_keep_todays_wording_by_default():
    import pdf_gen
    from modules.payroll import bonus
    assert pdf_gen.charity_cost_label({}) == "公益捐款（直接毛利 1%）"
    assert pdf_gen.charity_cost_label({"charityBasis": "total"}) == "公益捐款（報價含稅 1%）"
    assert bonus.row_label("charityDonation", "公益捐款（1%）", {}) == "公益捐款（直接毛利 1%）"
    assert bonus.row_label("charityDonation", "公益捐款（1%）", {"charityBasis": "total"}) == "公益捐款（報價含稅 1%）"


def test_labels_follow_the_documents_own_stamp_not_the_current_setting(monkeypatch):
    """完結後改比率：標籤仍是單據當時的比率（沒有戳記＝當時是 1），不看目前設定。"""
    import pdf_gen
    from modules.payroll import bonus
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: 0.5)                               # 目前設定 0.5%
    assert pdf_gen.charity_cost_label({}) == "公益捐款（直接毛利 1%）", "舊單據沒有戳記 ⇒ 當時是 1%"
    assert pdf_gen.charity_cost_label({"charityRatePct": 2}) == "公益捐款（直接毛利 2%）"
    assert pdf_gen.charity_cost_label({"charityRatePct": 2.5, "charityBasis": "total"}) == "公益捐款（報價含稅 2.5%）"
    assert pdf_gen.charity_cost_label({"charityRatePct": 2, "origCharityRatePct": 3}, orig=True) == "公益捐款（直接毛利 3%）"
    assert pdf_gen.charity_cost_label({"charityRatePct": 2}, orig=True) == "公益捐款（直接毛利 1%）"
    assert bonus.row_label("charityDonation", "公益捐款（1%）", {"charityRatePct": 2, "charityBasis": "total"}) == "公益捐款（報價含稅 2%）"
    assert bonus.row_label("charityDonation", "公益捐款（1%）", {}) == "公益捐款（直接毛利 1%）"
    for bad in (None, -1, True, "2", float("nan")):
        assert PW.rate_text(bad) == "1"


def test_rate_stamp_is_absent_at_the_default_and_present_otherwise(monkeypatch):
    from modules.case import profit_guard as PG
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: 1)
    assert PW.charity_rate_stamp() is None
    tot = {"charityRatePct": 9}                                                           # 用戶端送的值一律丟棄
    PG._stamp_charity_rate(tot)
    assert "charityRatePct" not in tot
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: 2)
    PG._stamp_charity_rate(tot)
    assert tot["charityRatePct"] == 2.0
    assert "charityRatePct" in PG.STAMP_KEYS, "已精算／結案單沿用資料庫現值"


def test_no_literal_charity_rate_left_in_the_call_sites():
    """伺服器端呼叫利潤規則的地方都要把設定值傳進去（不傳＝內建 1%/25，會悄悄忽略管理者設定）。"""
    import re
    for rel in ("backend/modules/case/profit_guard.py", "backend/modules/case/settlement_actuals.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        for m in re.finditer(r"profit_rules\.(?:settlement_profit|quote_profit)\(|PR\.quote_profit\(", src):
            call = src[m.start():m.start() + 400]
            assert "charity_rate_pct" in call and "default_pct" in call, (rel, call[:120])


def test_lowering_charity_rate_is_pending_with_a_second_approver_and_raising_is_immediate(client, make_user):
    """D-K1：調低公益比率＝少扣公益金＝營業利益變高＝放寬 ⇒ 待生效（確認期間）＋需要第二位最高管理者核准；調高＝多扣＝收緊 ⇒ 立即生效。"""
    import db
    make_user(username="t68q1_sa1", role="superadmin")
    make_user(username="t68q1_sa2", role="superadmin")
    c = db.get_db()
    try:
        up = SR.publish("profit_rules", {"charity_rate_pct": 2}, reason="t68", user="t68q1_sa1", conn=c)
        c.commit()
        assert not up["pending"] and SR.get("profit_rules", "charity_rate_pct", conn=c) == 2 and PW.charity_rate_pct(c) == 2.0
        down = SR.publish("profit_rules", {"charity_rate_pct": 0.5}, reason="t68", user="t68q1_sa1", conn=c)
        c.commit()
        assert down["pending"] and [p["approvalsRequired"] for p in down["pending"]] == [1], "放寬要第二位最高管理者核准"
        assert SR.get("profit_rules", "charity_rate_pct", conn=c) == 2, "待生效：現值不變"
        assert PW.charity_rate_pct(c) == 2.0
    finally:
        c.close()


def test_legacy_quote_recompute_uses_one_percent_not_the_live_rate(monkeypatch):
    """沒有戳記的舊報價單（當時是 1%）：補算原始側公益金時用 1%，不用目前設定。"""
    from modules.case import settlement_actuals as SA
    monkeypatch.setattr(SR, "get", lambda g, f, **kw: 3)
    assert SA._tot_rate_pct({}) == 1.0 and SA._tot_rate_pct(None) == 1.0
    assert SA._tot_rate_pct({"charityRatePct": 2}) == 2.0
    for bad in (True, "2", -1, 11, None):
        assert SA._tot_rate_pct({"charityRatePct": bad}) == 1.0


def test_customer_signback_recompute_keeps_the_documents_own_rate(monkeypatch):
    """回簽（alt_sign.recompute_tot）不吃目前設定：戳記≠目前設定的兩個方向都要用單據自己的比率，戳記不被重蓋。"""
    import copy
    from modules.case import alt_sign
    base = {"items": [{"qty": 1, "unitPrice": 100000, "cost": 60000}], "taxRate": 5, "overheadPct": 25,
            "tot": {"formulaVer": 2, "overheadPct": 25}}

    def run(stamp, live):
        monkeypatch.setattr(PW, "charity_rate_pct", lambda conn=None: live)      # 只換目前比率，其餘設定照舊
        d = copy.deepcopy(base)
        if stamp is not None:
            d["tot"]["charityRatePct"] = stamp
        return alt_sign.recompute_tot(d)

    t1 = run(None, 2.0)                                                           # 無戳記（＝當時 1%）、目前 2%
    assert t1["charityDonation"] == max(0, _hu(t1["directProfit"], "0.01")) and "charityRatePct" not in t1
    t2 = run(2.0, 1.0)                                                            # 戳記 2%、目前 1%（戳記≠目前，能分辨「吃目前設定」）
    assert t2["charityDonation"] == max(0, _hu(t2["directProfit"], "0.02")) and t2["charityRatePct"] == 2.0


def test_plan_view_uses_the_documents_rate_when_settled(monkeypatch):
    from modules.case import alt_options
    monkeypatch.setattr(PW, "charity_rate_pct", lambda conn=None: 3.0)
    assert alt_options.rate_of({"tot": {}}, settled=True) == 1.0
    assert alt_options.rate_of({"tot": {"charityRatePct": 2}}, settled=True) == 2.0
    assert alt_options.rate_of({"tot": {}}, settled=False) == 3.0, "未精算 ⇒ 目前設定"
