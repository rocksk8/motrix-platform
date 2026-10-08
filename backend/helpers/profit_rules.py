# -*- coding: utf-8 -*-
"""報價單／精算的利潤規則（第 48 班 S1；設計稿 docs/platform/plans/OVERHEAD-25PCT-OPERATING-PROFIT-DESIGN-T48.md）。

**唯一來源**：管銷分攤、公益捐款、間接成本合計、營業利益（舊稱淨利）、營業利益率的算式只寫在這裡；
前端 `frontend/static/profit-rules.js`（`MotrixProfitRules`）是同一套算法的 JS 版，兩邊用同一份黃金向量
`tests/data/profit_rules_vectors.json` 比對（等值測試）。守門：`tests/platform/test_profit_rule_single_source.py`。

兩種口徑（`ver`）：
- `LEGACY_VER = 1`：管銷分攤 ＝ 報價稅前 × 10%（固定；第 47 班以前的所有資料）。
- `FORMULA_VER = 2`：管銷分攤 ＝ max(直接毛利, 0) × `pct`%（預設 25；每張報價單可調，只有最高管理者能改）。
  精算端的「直接毛利」＝精算實際毛利（稅前 − 實際總成本）。

**S1（本班第一步）零行為變更**：`ACTIVE_VER` 仍是 1；呼叫端不傳 `ver` 就走舊口徑。S2 才把 `ACTIVE_VER` 換成 2 並接資料模型。
回傳的數字都是**未四捨五入的原始值**（與舊 `calcTotals`／`calcSummary` 同）；顯示用的進位由呼叫端照舊處理。
"""
from decimal import Decimal

from helpers.legal_params import round_half_up

LEGACY_VER = 1
FORMULA_VER = 2
ACTIVE_VER = LEGACY_VER                      # S2 改成 FORMULA_VER（唯一的切換點）
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


def charity(direct_profit) -> int:
    """公益捐款＝直接毛利 × 1%，不為負（虧損案以 0 計）。"""
    return max(0, round_half_up(direct_profit, CHARITY_RATE))


def quote_profit(pretax, total_cost, input_vat, indirect_items, pct=None, ver=None) -> dict:
    """報價單損益：`indirect_items`＝運輸物流、安裝施工、差異項、保固預估、其他費用（依序，缺＝0）。"""
    direct = pretax - total_cost - input_vat
    direct_pct = direct / pretax * 100 if pretax > 0 else 0
    admin = admin_cost(pretax, direct, pct, ver)
    ch = charity(direct)
    total_indirect = admin + ch
    for x in indirect_items:
        total_indirect = total_indirect + (x or 0)
    net = direct - total_indirect
    net_pct = net / pretax * 100 if pretax > 0 else 0
    return {"directProfit": direct, "directMarginPct": direct_pct, "adminCost": admin, "charityDonation": ch,
            "totalIndirect": total_indirect, "netProfit": net, "netMarginPct": net_pct}


def settlement_profit(pretax, actual_cost, pct=None, ver=None, frozen_charity=None) -> dict:
    """精算損益（實際側）：毛利＝稅前 − 實際總成本；`frozen_charity`＝已完結精算的存檔公益金（不回頭改寫）。"""
    gross = pretax - actual_cost
    gross_pct = gross / pretax * 100 if pretax > 0 else 0
    admin = admin_cost(pretax, gross, pct, ver)
    ch = frozen_charity if frozen_charity is not None else charity(gross)
    net = gross - admin - ch
    net_pct = net / pretax * 100 if pretax > 0 else 0
    return {"grossProfit": gross, "grossMarginPct": gross_pct, "adminCost": admin, "charityDonation": ch,
            "netProfit": net, "netMarginPct": net_pct}

