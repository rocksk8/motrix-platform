# -*- coding: utf-8 -*-
"""報價單／精算的利潤規則（第 48 班 S1；設計稿 docs/platform/plans/OVERHEAD-25PCT-OPERATING-PROFIT-DESIGN-T48.md）。

**唯一來源**：管銷分攤、公益捐款、間接成本合計、營業利益（舊稱淨利）、營業利益率的算式只寫在這裡；
前端 `frontend/static/profit-rules.js`（`MotrixProfitRules`）是同一套算法的 JS 版，兩邊用同一份黃金向量
`tests/data/profit_rules_vectors.json` 比對（等值測試）。守門：`tests/platform/test_profit_rule_single_source.py`。

兩種口徑（`ver`）：
- `LEGACY_VER = 1`：管銷分攤 ＝ 報價稅前 × 10%（固定；第 47 班以前的所有資料）。
- `FORMULA_VER = 2`：管銷分攤 ＝ max(直接毛利, 0) × `pct`%（預設 25；每張報價單可調，只有最高管理者能改）。
  精算端的「直接毛利」＝精算實際毛利（稅前 − 實際總成本）。

公益捐款基數（`charity_basis`，第 52 班；設計 docs/platform/plans/CHARITY-QUOTE-1PCT-DESIGN-T52.md）：
- `CHARITY_DIRECT = "direct"`：公益捐款 ＝ max(0, 直接毛利 × 1%)（第 51 班以前；ver 1 永遠用這個）。
- `CHARITY_TOTAL = "total"`：公益捐款 ＝ 報價**含稅**金額（`tot.total`＝稅前＋稅額）× 1%，四捨五入到元；下限只在『含稅金額』上（負的金額不可變成收入：`max(0, …)`），**不看直接毛利、虧損案照扣**（只在 ver 2 生效）。
  含稅金額由呼叫端傳入（`total`／`quoted_total`）；基數是 total 卻沒給金額 ⇒ ValueError（不悄悄當 0）。

**可設定的三個數字**（T68 Q1）：公益捐款比率（`charity_rate_pct`，設定中心 `profit_rules.charity_rate_pct`，預設 1）、管銷比率後備值（`default_pct`，
`overhead_default_pct`，預設 25）、營業利益率目標（`profit_warning.quote_form_low`，預設 12）。本檔仍是**純函式**——不讀設定；呼叫端把目前的值傳進來，
不傳＝內建預設（`CHARITY_RATE`／`DEFAULT_OVERHEAD_PCT`／`TARGET_MARGIN_PCT`，與今天逐位相同）。前端 `profit-rules.js` 的 `configure()` 是同一件事。

**S1（本班第一步）零行為變更**：`ACTIVE_VER` 仍是 1；呼叫端不傳 `ver` 就走舊口徑。S2 才把 `ACTIVE_VER` 換成 2 並接資料模型。
回傳的數字都是**未四捨五入的原始值**（與舊 `calcTotals`／`calcSummary` 同）；顯示用的進位由呼叫端照舊處理。
"""
from decimal import Decimal

from helpers.legal_params import round_half_up

LEGACY_VER = 1
FORMULA_VER = 2
ACTIVE_VER = LEGACY_VER                      # S2 改成 FORMULA_VER（唯一的切換點）
CHARITY_DIRECT = "direct"
CHARITY_TOTAL = "total"
ACTIVE_CHARITY_BASIS = CHARITY_DIRECT        # 第 52 班：預設舊基；伺服器依 charity_basis_mode 明確傳入，這裡是『不傳』時的預設
LEGACY_ADMIN_RATE = 0.10
DEFAULT_OVERHEAD_PCT = 25
CHARITY_RATE = 0.01
TARGET_MARGIN_PCT = 12                       # 營業利益率目標警示門檻（<12 紅）


def pct_rate(pct) -> str:
    """百分比 → 費率字串（小數點左移兩位，不經浮點：7.1 → '0.071'）。"""
    return format(Decimal(str(pct).strip()).scaleb(-2), "f")


def admin_cost(pretax, direct_profit, pct=None, ver=None, default_pct=None) -> int:
    """管銷分攤。ver 1：稅前 × 10%；ver 2：max(直接毛利,0) × pct%（直接毛利為負 ⇒ 0）。
    `pct` 沒給時的後備值＝`default_pct`（呼叫端傳目前的全域預設）；兩者都沒給才用程式內建的 `DEFAULT_OVERHEAD_PCT`（25）。"""
    ver = ACTIVE_VER if ver is None else ver
    if ver == LEGACY_VER:
        return round_half_up(pretax, LEGACY_ADMIN_RATE)
    p = (DEFAULT_OVERHEAD_PCT if default_pct is None else default_pct) if pct is None else pct
    return round_half_up(max(direct_profit, 0), pct_rate(p))


def _basis(ver, basis):
    """實際採用的公益基數：只有 ver 2 才可能是 total；ver 1 一律 direct。"""
    ver = ACTIVE_VER if ver is None else ver
    b = ACTIVE_CHARITY_BASIS if basis is None else basis
    if b not in (CHARITY_DIRECT, CHARITY_TOTAL):
        raise ValueError("公益捐款基數只能是 direct 或 total：%r" % (basis,))
    return b if (b == CHARITY_TOTAL and ver != LEGACY_VER) else CHARITY_DIRECT


def _charity_rate(rate_pct):
    """公益捐款比率：沒給（None）＝內建 1%（`CHARITY_RATE`）；給了＝百分比（例 0.5 ⇒ 0.005，不經浮點）。"""
    return CHARITY_RATE if rate_pct is None else pct_rate(rate_pct)


def charity(direct_profit, total=None, basis=CHARITY_DIRECT, rate_pct=None) -> int:
    """公益捐款。`direct`（預設，舊算法）＝直接毛利 × 比率（預設 1%），不為負（虧損案以 0 計）；
    `total`＝報價含稅金額 × 比率（只在含稅金額上設下限 0；`total` 必填）。`rate_pct`＝比率的百分數（None＝1）。"""
    rate = _charity_rate(rate_pct)
    if basis == CHARITY_TOTAL:
        if total is None:
            raise ValueError("公益捐款基數 total 需要報價含稅金額")
        return max(0, round_half_up(total, rate))        # 以收入為基：不看直接毛利；含稅金額為負 ⇒ 0（不可變成收入）
    return max(0, round_half_up(direct_profit, rate))


def quote_profit(pretax, total_cost, input_vat, indirect_items, pct=None, ver=None, total=None, charity_basis=None,
                 charity_rate_pct=None, default_pct=None) -> dict:
    """報價單損益：`indirect_items`＝運輸物流、安裝施工、差異項、保固預估、其他費用（依序，缺＝0）；**只有舊口徑（ver 1）計入**，新口徑（ver 2）一律忽略。"""
    direct = pretax - total_cost - input_vat
    direct_pct = direct / pretax * 100 if pretax > 0 else 0
    admin = admin_cost(pretax, direct, pct, ver, default_pct)
    ch = charity(direct, total, _basis(ver, charity_basis), charity_rate_pct)
    total_indirect = admin + ch
    if (ACTIVE_VER if ver is None else ver) == LEGACY_VER:          # 新口徑不再計入五項間接成本（使用者 2026-10-09：費用一律走請款申請）；舊口徑照舊
        for x in indirect_items:
            total_indirect = total_indirect + (x or 0)
    net = direct - total_indirect
    net_pct = net / pretax * 100 if pretax > 0 else 0
    return {"directProfit": direct, "directMarginPct": direct_pct, "adminCost": admin, "charityDonation": ch,
            "totalIndirect": total_indirect, "netProfit": net, "netMarginPct": net_pct}


def settlement_profit(pretax, actual_cost, pct=None, ver=None, frozen_charity=None, quoted_total=None, charity_basis=None,
                      charity_rate_pct=None, default_pct=None) -> dict:
    """精算損益（實際側）：毛利＝稅前 − 實際總成本；`frozen_charity`＝已完結精算的存檔公益金（不回頭改寫）；
    `quoted_total`＝報價含稅金額（公益基數 total 時用，不隨實際成本變動）。"""
    gross = pretax - actual_cost
    gross_pct = gross / pretax * 100 if pretax > 0 else 0
    admin = admin_cost(pretax, gross, pct, ver, default_pct)
    ch = frozen_charity if frozen_charity is not None else charity(gross, quoted_total, _basis(ver, charity_basis), charity_rate_pct)
    net = gross - admin - ch
    net_pct = net / pretax * 100 if pretax > 0 else 0
    return {"grossProfit": gross, "grossMarginPct": gross_pct, "adminCost": admin, "charityDonation": ch,
            "netProfit": net, "netMarginPct": net_pct}



# ── 專案毛利%（M3 之後；設計 docs/platform/plans/QUOTE-PROJECT-GROSS-MARGIN-T56.md）────────────────────
# 專案毛利% ＝ (未稅營業收入 − 未稅品項成本) ÷ 未稅營業收入 × 100。成本只算品項『成本單價 × 數量』，**不扣**進項稅、攤分保留款、公益金、管銷、營業稅。
# 與直接毛利率的差異恰為進項稅（direct = pretax − cost − inputVat）。衍生值：讀取時計算，不寫進 tot、不加 SQL 欄。
# 進位：精確的有理數運算後『四捨五入到 0.1、平手一律遠離零』（12.25 → 12.3、−12.25 → −12.3），與前端 `MotrixProfitRules.projectMargin` 孿生，共用黃金向量。

def _is_number(x) -> bool:
    import math
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _pm_ok(x) -> bool:
    """專案毛利的輸入必須是 0 或 1e-6 ≤ |x| < 1e15 的有限數字：落在其他區間（指數記法的極端值）一律當無效（pct 為 None），
    前後端同一條規則——JS 的 String(x) 在 |x| < 1e-6 或 ≥ 1e21 才會改用指數記法，這個範圍內兩邊的十進位展開逐位相同。"""
    return _is_number(x) and (x == 0 or 1e-6 <= abs(x) < 1e15)


def uncosted_items(items) -> int:
    """成本未填的品項數：非標題、且 cost 缺鍵／None／空字串／非數字。`cost = 0` 是合法的零成本（如贈品），不算未填。"""
    n = 0
    for i in items or []:
        if not isinstance(i, dict) or i.get("type") == "header":
            continue
        c = i.get("cost")
        if not _is_number(c):
            n += 1
    return n


def project_margin(pretax, total_cost, uncosted=0) -> dict:
    """回 `{amount, pct, uncosted_items}`。pct 為 None 的情況：pretax／total_cost 不是有限數字，或 pretax ≤ 0（None 不是 0）。虧損回負數、不補零。"""
    from fractions import Fraction
    out = {"amount": None, "pct": None, "uncosted_items": int(uncosted or 0)}
    if not _pm_ok(pretax) or not _pm_ok(total_cost):
        return out
    p, c = Fraction(Decimal(repr(pretax))), Fraction(Decimal(repr(total_cost)))
    a = p - c
    out["amount"] = float(a) if a.denominator != 1 else int(a)
    if p <= 0:
        return out
    x = a * 1000 / p                                    # 以 0.1% 為單位
    n, d = abs(x.numerator), x.denominator
    tenths = (2 * n + d) // (2 * d)                      # 四捨五入，平手遠離零
    out["pct"] = (-tenths if x < 0 else tenths) / 10
    return out
