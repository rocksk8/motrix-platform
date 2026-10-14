# -*- coding: utf-8 -*-
"""財務報表的可調參數（財務盤點第一個切片；設計 docs/platform/plans/FINANCE-FRAMEWORK-INVENTORY-T62.md §4）。

[單位] helper:finance_params    [層] L1    [穩定度] 實驗（旗標 finance_reports.custom_aging 關＝所有報表與今天逐位元相同）
[公開介面] DEFAULT_CUTS, BAND_KEYS, GROUP, aging_cuts, aging_band, aging_labels
[不變式] ①應收帳齡的區間切點預設 30／60／90 天（今天寫死在 reports.py 的值）；旗標 `finance_reports.custom_aging` 為 1 才採用管理者設定的切點，
    切點不合法（非整數、不遞增、超出 1～3650）一律回預設，不丟例外；
    ②區間的 key（"0-30"／"31-60"／"61-90"／"90+"）是**位置代號**，不是天數：切點改了，key 不變（前端上色與其他消費者依 key），只有標籤與判定改變；
    ③這裡的參數都不是金額；報表端點本身的金額權限（_require_reports_access）不受影響；
    ④讀設定失敗（群組未登記、資料庫錯誤）⇒ 預設切點（財務報表的區間不是安全閘門，失敗退回今天的行為即可）。
[契約題] backend/tests/test_finance_params_2026_10_14.py
"""
DEFAULT_CUTS = (30, 60, 90)
BAND_KEYS = ("0-30", "31-60", "61-90", "90+")
GROUP = "finance_reports"
_MAX_DAY = 3650


def _valid(cuts) -> bool:
    try:
        a, b, c = cuts
    except (TypeError, ValueError):
        return False
    return all(isinstance(x, int) and not isinstance(x, bool) for x in (a, b, c)) and 1 <= a < b < c <= _MAX_DAY


def aging_cuts(conn=None) -> tuple:
    """目前生效的帳齡切點 `(d1, d2, d3)`。旗標關／讀不到／不合法 ⇒ `DEFAULT_CUTS`。"""
    try:
        from helpers import settings_registry as SR
        if int(SR.get(GROUP, "custom_aging", conn=conn)) != 1:
            return DEFAULT_CUTS
        cuts = tuple(int(float(SR.get(GROUP, k, conn=conn))) for k in ("aging_day1", "aging_day2", "aging_day3"))
    except Exception:                                                  # noqa: BLE001
        return DEFAULT_CUTS
    return cuts if _valid(cuts) else DEFAULT_CUTS


def aging_band(days, cuts=DEFAULT_CUTS) -> str:
    """經過天數 ⇒ 區間 key。邊界與今天相同：`days > d3` 為最後一區，`> d2`、`> d1` 依序，其餘為第一區。"""
    d1, d2, d3 = cuts
    return "90+" if days > d3 else "61-90" if days > d2 else "31-60" if days > d1 else "0-30"


def aging_labels(cuts=DEFAULT_CUTS) -> dict:
    """區間 key ⇒ 顯示標籤。預設逐字等於今天的『0–30 天／31–60 天／61–90 天／90+ 天』。"""
    d1, d2, d3 = cuts
    return {"0-30": "0–%d 天" % d1, "31-60": "%d–%d 天" % (d1 + 1, d2), "61-90": "%d–%d 天" % (d2 + 1, d3), "90+": "%d+ 天" % d3}
