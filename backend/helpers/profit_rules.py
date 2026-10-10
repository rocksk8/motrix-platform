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


def admin_cost(pretax, direct_profit, pct=None, ver=None) -> int:
    """管銷分攤。ver 1：稅前 × 10%；ver 2：max(直接毛利,0) × pct%（直接毛利為負 ⇒ 0）。"""
    ver = ACTIVE_VER if ver is None else ver
    if ver == LEGACY_VER:
        return round_half_up(pretax, LEGACY_ADMIN_RATE)
    p = DEFAULT_OVERHEAD_PCT if pct is None else pct
    return round_half_up(max(direct_profit, 0), pct_rate(p))


def _basis(ver, basis):
    """實際採用的公益基數：只有 ver 2 才可能是 total；ver 1 一律 direct。"""
    ver = ACTIVE_VER if ver is None else ver
    b = ACTIVE_CHARITY_BASIS if basis is None else basis
    if b not in (CHARITY_DIRECT, CHARITY_TOTAL):
        raise ValueError("公益捐款基數只能是 direct 或 total：%r" % (basis,))
    return b if (b == CHARITY_TOTAL and ver != LEGACY_VER) else CHARITY_DIRECT


def charity(direct_profit, total=None, basis=CHARITY_DIRECT) -> int:
    """公益捐款。`direct`（預設，舊算法）＝直接毛利 × 1%，不為負（虧損案以 0 計）；
    `total`＝報價含稅金額 × 1%（只在含稅金額上設下限 0；`total` 必填）。"""
    if basis == CHARITY_TOTAL:
        if total is None:
            raise ValueError("公益捐款基數 total 需要報價含稅金額")
        return max(0, round_half_up(total, CHARITY_RATE))        # 以收入為基：不看直接毛利；含稅金額為負 ⇒ 0（不可變成收入）
    return max(0, round_half_up(direct_profit, CHARITY_RATE))


def quote_profit(pretax, total_cost, input_vat, indirect_items, pct=None, ver=None, total=None, charity_basis=None) -> dict:
    """報價單損益：`indirect_items`＝運輸物流、安裝施工、差異項、保固預估、其他費用（依序，缺＝0）；**只有舊口徑（ver 1）計入**，新口徑（ver 2）一律忽略。"""
    direct = pretax - total_cost - input_vat
    direct_pct = direct / pretax * 100 if pretax > 0 else 0
    admin = admin_cost(pretax, direct, pct, ver)
    ch = charity(direct, total, _basis(ver, charity_basis))
    total_indirect = admin + ch
    if (ACTIVE_VER if ver is None else ver) == LEGACY_VER:          # 新口徑不再計入五項間接成本（使用者 2026-10-09：費用一律走請款申請）；舊口徑照舊
        for x in indirect_items:
            total_indirect = total_indirect + (x or 0)
    net = direct - total_indirect
    net_pct = net / pretax * 100 if pretax > 0 else 0
    return {"directProfit": direct, "directMarginPct": direct_pct, "adminCost": admin, "charityDonation": ch,
            "totalIndirect": total_indirect, "netProfit": net, "netMarginPct": net_pct}


def settlement_profit(pretax, actual_cost, pct=None, ver=None, frozen_charity=None, quoted_total=None, charity_basis=None) -> dict:
    """精算損益（實際側）：毛利＝稅前 − 實際總成本；`frozen_charity`＝已完結精算的存檔公益金（不回頭改寫）；
    `quoted_total`＝報價含稅金額（公益基數 total 時用，不隨實際成本變動）。"""
    gross = pretax - actual_cost
    gross_pct = gross / pretax * 100 if pretax > 0 else 0
    admin = admin_cost(pretax, gross, pct, ver)
    ch = frozen_charity if frozen_charity is not None else charity(gross, quoted_total, _basis(ver, charity_basis))
    net = gross - admin - ch
    net_pct = net / pretax * 100 if pretax > 0 else 0
    return {"grossProfit": gross, "grossMarginPct": gross_pct, "adminCost": admin, "charityDonation": ch,
            "netProfit": net, "netMarginPct": net_pct}

