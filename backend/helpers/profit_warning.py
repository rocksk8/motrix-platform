# -*- coding: utf-8 -*-
"""T64 A：利潤提醒色帶與報價單預設有效天數的讀取（只讀設定；預設＝各畫面今天寫死的數字）。

[單位] helper:profit_warning    [層] L1    [穩定度] 實驗
[公開介面] DEFAULTS, bands, default_valid_days, DEFAULT_VALID_DAYS
[不變式] ①只影響畫面／PDF 的顏色與新報價單的預設有效天數；不擋存檔、不改金額、不改送審判斷（送審門檻是 quote_approval.*，伺服器重算）。
    ②設定讀不到、不是有限數字、超出範圍、或「紅線 > 達標線」⇒ 整組回今天的數字（不是半套）。
設計：設定群組在 helpers/settings_groups_profit.py。
[契約題] backend/tests/platform/test_profit_warning_t64.py
"""
import math

DEFAULT_VALID_DAYS = 30
DEFAULTS = {
    "quote_form_low": 12.0, "quote_form_good": 20.0,       # 報價單表單：低於紅線＝紅，低於達標線＝黃，其餘綠
    "report_low": 10.0, "report_good": 20.0,               # 報表頁分項：同上
    "case_floor": 0.0, "case_good": 20.0,                  # 案件頁／結算摘要／結算 PDF：低於 floor＝紅，低於達標線＝黃，其餘綠
    "settlement_good": 20.0,                               # 結算頁：達標線以上綠，其餘紅
}
_PAIRS = (("quote_form_low", "quote_form_good"), ("report_low", "report_good"), ("case_floor", "case_good"))


def _valid(vals):
    for k, d in DEFAULTS.items():
        v = vals.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            return False
        if not (-100 <= float(v) <= 100):
            return False
    return all(float(vals[lo]) <= float(vals[hi]) for lo, hi in _PAIRS)


def bands(conn=None) -> dict:
    """七個色帶門檻（float）。任何不合法 ⇒ 整組回 DEFAULTS（今天的數字）。"""
    try:
        from helpers import settings_registry as sr
        vals = sr.get_group("profit_warning", conn=conn)
        if _valid(vals):
            return {k: float(vals[k]) for k in DEFAULTS}
    except Exception:                                                                    # noqa: BLE001 — 純顯示，讀不到不可影響頁面
        pass
    return dict(DEFAULTS)


def default_valid_days(conn=None) -> int:
    """新報價單沒帶 validDays 時的預設天數。讀不到／不合法 ⇒ 30（今天的值）。"""
    try:
        from helpers import settings_registry as sr
        v = sr.get("quote_defaults", "valid_days", conn=conn)
        if not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(float(v)) and 1 <= float(v) <= 365:
            return int(v)
    except Exception:                                                                    # noqa: BLE001
        pass
    return DEFAULT_VALID_DAYS
