# -*- coding: utf-8 -*-
"""報價單金額欄（quotations.total／pretax）的防禦性轉數字（模組內版本：arap）。

舊資料的金額可能存成文字（"12,345"）；直接 float()／相加會 ValueError／TypeError ⇒ 500。
規則與 `helpers/tax_calc._parse_money`、`analytics/api/reports._num_or_bad` 同一條（逐項比對見 `tests/test_quote_total_text_500_2026_11_17.py`）：
None／空白／布林／NaN／inf／無法解析 ⇒ default；數字原樣；數字字串（含千分位逗號）轉數字。

TODO（下次升核心版時收斂）：把 `tax_calc._parse_money` 公開成 L1 函式，arap／case／analytics 三份改用它，本檔刪除
（helpers 底下每個檔都必須歸屬 L1 或某個模組，新增 helper＝改 L1 介面＝升核心版，所以本批先放在模組內）。
"""
import math


def money_num(v, default=0):
    if v is None or isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else default
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if not s:
            return default
        try:
            f = float(s)
        except ValueError:
            return default
        if not math.isfinite(f):
            return default
        return int(f) if f.is_integer() else f
    return default
