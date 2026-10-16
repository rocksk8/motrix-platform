# -*- coding: utf-8 -*-
"""T64 A：利潤提醒色帶與報價單預設有效天數的讀取（只讀設定；預設＝各畫面今天寫死的數字）。

[單位] helper:profit_warning    [層] L1    [穩定度] 實驗
[公開介面] DEFAULTS, bands, default_valid_days, DEFAULT_VALID_DAYS, CHARITY_RATE_PCT_DEFAULT, charity_rate_pct, charity_rate_text, charity_rate_stamp, rate_text, rules_config
[不變式] ①只影響畫面／PDF 的顏色與新報價單的預設有效天數；不擋存檔、不改金額、不改送審判斷（送審門檻是 quote_approval.*，伺服器重算）。
    ②設定讀不到、不是有限數字、超出範圍、或「紅線 > 達標線」⇒ 整組回今天的數字（不是半套）。
    ③（T68 Q1）公益捐款比率 `profit_rules.charity_rate_pct`：讀不到／不是有限數字／超出 0～10 ⇒ 1（今天的值）；它會改金額（報價單與精算的公益金），
       所以放寬（調低）走『確認期間＋第二位最高管理者核准』（D-K1），調高立即生效；已完結精算的存檔公益金不回頭改寫。
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


CHARITY_RATE_PCT_DEFAULT = 1.0                         # 公益捐款比率（百分數）；1＝今天寫死的 1%
_CHARITY_RATE_MAX = 10.0


def charity_rate_pct(conn=None) -> float:
    """公益捐款比率（百分數，預設 1）。任何讀取失敗／不合法 ⇒ 1（與 profit_rules.CHARITY_RATE 同值，今天的行為）。"""
    try:
        from helpers import settings_registry as sr
        v = sr.get("profit_rules", "charity_rate_pct", conn=conn)
        if not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(float(v)) and 0 <= float(v) <= _CHARITY_RATE_MAX:
            return float(v)
    except Exception:                                                                    # noqa: BLE001
        pass
    return CHARITY_RATE_PCT_DEFAULT


def rate_text(pct) -> str:
    """比率百分數的標籤字樣（'1'、'0.5'…；整數不帶小數點）。不是有限非負數字 ⇒ '1'。"""
    if isinstance(pct, bool) or not isinstance(pct, (int, float)) or not math.isfinite(float(pct)) or pct < 0:
        return "1"
    v = float(pct)
    return str(int(v)) if v == int(v) else ("%g" % v)


def charity_rate_text(conn=None) -> str:
    """目前公益捐款比率的標籤字樣。**已存檔的單據不要用這個**——用單據自己的戳記 `charityRatePct`（沒有＝當時是 1），見 `rate_text`。"""
    return rate_text(charity_rate_pct(conn))


def charity_rate_stamp(conn=None):
    """要蓋在單據上的公益比率戳記：比率等於預設（1）⇒ None（不帶這個鍵，單據形狀與今天完全相同）；不同 ⇒ 該比率。
    已存檔／已完結的單據標籤只看這個戳記（沒有＝1），不看目前設定——否則改了比率後舊單據的標籤會和當時實際扣的金額不符。"""
    v = charity_rate_pct(conn)
    return None if v == CHARITY_RATE_PCT_DEFAULT else v


def rules_config(conn=None) -> dict:
    """前端 `MotrixProfitRules.configure()` 要的後兩個數字：公益比率、營業利益率目標（＝報價單紅線，預設 12）。
    第三個（管銷後備值）是既有的 `defaultPct`（`overhead_default_pct`），端點本來就回。"""
    return {"charityRatePct": charity_rate_pct(conn), "targetMarginPct": bands(conn)["quote_form_low"]}
