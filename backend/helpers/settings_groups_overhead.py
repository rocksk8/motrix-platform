# -*- coding: utf-8 -*-
"""T69 設定群組：管銷分攤比率的全域預設值（overhead.default_pct）。**預設值＝上線前的 25（`profit_rules.DEFAULT_OVERHEAD_PCT`）**，部署零行為變更。

[單位] helper:settings_groups_overhead    [層] L1    [穩定度] 實驗
[公開介面] register
[不變式] 只決定『之後新建的報價單』的管銷預設比率；既有報價單的比率（每案存值）不回改。調低＝放寬（營業利益與獎金基數變大，金額外流風險）：
    確認期間後才生效，且需另一位最高管理者核准；調高立即生效。舊鍵 `overhead_default_pct`（純量）與本設定雙寫同值（`SCALAR_LEGACY`），
    舊入口 `PUT /api/overhead/settings` 的 `defaultPct` 也改走 `settings_registry.publish`（不可繞過第二人核准）。口徑切換（ruleMode／charityMode）不在這裡。
[契約題] backend/modules/case/tests/test_overhead_default_pct_t69.py
"""


def _one_decimal(values):
    """管銷比率最多 1 位小數（與 profit_guard.parse_pct 同一判斷）。"""
    v = values.get("default_pct")
    if v is None:
        return []
    from decimal import Decimal, InvalidOperation
    try:
        d = Decimal(repr(v))
    except (InvalidOperation, ValueError):
        return []
    if d.is_finite() and d != d.quantize(Decimal("0.1")):
        return ["管銷分攤比率最多 1 位小數。"]
    return []


def register(S, _register_core):
    _register_core(
        "overhead", "管銷分攤比率",
        [
            S("default_pct", "float", 25, min=0, max=100, unit="%", legacy="=", risk="money", loosen="down", recommended=25,
              risk_text="【高影響】調低管銷預設比率後，之後新建的報價單營業利益會變高、獎金基數變大；已建立的報價單與已完結的精算不會被改寫。",
              impact_scope={"documents": ["之後新建的報價單", "精算", "營運報表"], "roles": ["業務", "最高管理者", "財務"],
                            "amounts": "改變之後新建報價單的管銷分攤與營業利益（報價 PDF、精算頁、營運報表同步）；不改已建立的報價單與已完結精算的存檔值。",
                            "reversible": True, "effective": "pending"},
              question="新建報價單的管銷分攤，預設要抽直接毛利的百分之幾？", label="管銷分攤預設比率",
              help="新建報價單時，管銷分攤預設＝直接毛利 × 這個比率（最多 1 位小數）。每張報價單仍可由最高管理者在精算頁個別調整。預設 25％（＝目前的做法）。",
              impact="調高＝多抽管銷、營業利益變低（立即生效）；調低＝少抽管銷、營業利益與獎金基數變高（放寬，需第二位最高管理者核准並經確認期間）。只影響設定生效之後新建的報價單；已建立的報價單與已完結精算不回頭改寫。"),
        ],
        sensitive=True, risk="money", legacy_key="overhead_default_pct", cross_check=_one_decimal,
        help="新建報價單的管銷分攤預設比率；管銷口徑切換（舊／新口徑、公益基數）仍在精算相關的管銷設定入口，不在這裡。",
    )
