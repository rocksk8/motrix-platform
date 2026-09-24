"""案件金額欄位遮蔽（CM13，2026-09-24 使用者裁示「要，後端移除金額欄位」）。

沒有 `helpers/auth.py::can_see_financial()` 的帳號，後端不回金額、毛利、單價、成本。
值換成 None（不是 0：0 是「金額為零」，None 才是「看不到」），並加 `moneyMasked: True`
讓畫面顯示「—」。純函式，呼叫端決定要不要套。
"""

#: quotations 表上的金額欄位（清單、結案檢核）
QUOTATION_MONEY_COLS = ("total", "pretax", "direct_margin_pct", "net_margin_pct")


def mask_row(row: dict, cols=QUOTATION_MONEY_COLS) -> dict:
    """清單列：金額欄位回 None。只改 row 裡確實存在的鍵。"""
    for k in cols:
        if k in row:
            row[k] = None
    row["moneyMasked"] = True
    return row
