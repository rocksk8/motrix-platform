# -*- coding: utf-8 -*-
"""財務報表的可調參數（財務盤點第一個切片；設計 docs/platform/plans/FINANCE-FRAMEWORK-INVENTORY-T62.md §4）。

[單位] helper:finance_params    [層] L1    [穩定度] 實驗（旗標 finance_reports.custom_aging 關＝所有報表與今天逐位元相同）
[公開介面] DEFAULT_CUTS, BAND_KEYS, GROUP, aging_cuts, aging_band, aging_labels, CASHIER_GROUP, DEFAULT_BANK_ALIASES, DEFAULT_DUE_SOON, parse_aliases, aliases_text, bank_aliases, CLOSE_GATE_GROUP, CLOSE_GATE_OPTIONS, close_gate_options
[不變式] ①應收帳齡的區間切點預設 30／60／90 天（今天寫死在 reports.py 的值）；旗標 `finance_reports.custom_aging` 為 1 才採用管理者設定的切點，
    切點不合法（非整數、不遞增、超出 1～3650）一律回預設，不丟例外；
    ②區間的 key（"0-30"／"31-60"／"61-90"／"90+"）是**位置代號**，不是天數：切點改了，key 不變（前端上色與其他消費者依 key），只有標籤與判定改變；
    ③這裡的參數都不是金額；報表端點本身的金額權限（_require_reports_access）不受影響；
    ④讀設定失敗（群組未登記、資料庫錯誤）⇒ 預設切點（財務報表的區間不是安全閘門，失敗退回今天的行為即可）。
[契約題] backend/tests/test_finance_params_2026_10_14.py、backend/tests/test_finance_cashier_gates_2026_10_14.py
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


# ── 出納：銀行對帳單欄位別名、到期提醒天數（F2／F3）──────────────────────────────────────────────────────
CASHIER_GROUP = "finance_cashier"
DEFAULT_BANK_ALIASES = {
    "date": ["交易日期", "日期", "過帳日", "轉帳日期", "交易日", "date", "Date"],
    "amount": ["金額", "提出金額", "支出金額", "轉出金額", "付款金額", "提款金額", "amount", "Amount", "Debit", "withdrawal"],
    "desc": ["摘要", "備註", "說明", "對方戶名", "附言", "memo", "Description", "Memo"],
}
DEFAULT_DUE_SOON = {"payable": 7, "planned": 3}
_MAX_ALIASES, _MAX_ALIAS_LEN = 20, 30


def parse_aliases(text):
    """設定裡的別名文字（逗號、全形逗號或頓號分隔）⇒ 別名清單（保留順序、去重、去空白）；空白或超出上限 ⇒ None（呼叫端用預設）。"""
    if not isinstance(text, str):
        return None
    import re
    out = []
    for part in re.split(r"[,，、\n]", text):
        a = part.strip()
        if not a:
            continue
        if len(a) > _MAX_ALIAS_LEN:
            return None
        if a not in out:
            out.append(a)
    return out if 0 < len(out) <= _MAX_ALIASES else None


def aliases_text(lst) -> str:
    return ",".join(lst)


def bank_aliases(conn=None) -> dict:
    """銀行對帳單三種欄位的別名清單 `{"date": [...], "amount": [...], "desc": [...]}`。旗標關／讀不到／內容不合法 ⇒ 預設（今天的清單）。
    順序有意義：越前面的別名越優先（`_pick_csv_header` 先精準比對、再包含比對，都依此順序）。"""
    out = {k: list(v) for k, v in DEFAULT_BANK_ALIASES.items()}
    try:
        from helpers import settings_registry as SR
        if int(SR.get(CASHIER_GROUP, "custom_bank_aliases", conn=conn)) != 1:
            return out
        for k in out:
            parsed = parse_aliases(SR.get(CASHIER_GROUP, "bank_alias_" + k, conn=conn))
            if parsed:
                out[k] = parsed
    except Exception:                                                  # noqa: BLE001
        return {k: list(v) for k, v in DEFAULT_BANK_ALIASES.items()}
    return out


# ── 案件結案閘門的『只收緊』選項（S-C1）──────────────────────────────────────────────────────────────────
CLOSE_GATE_GROUP = "case_close_gates"
CLOSE_GATE_OPTIONS = ("require_stages", "require_payment_items", "require_settlement", "count_extra_expense_drafts")


def _strict(conn, group, field):
    try:
        from helpers.settings_strict import strict_value as f
    except ImportError:                                                # 尚未合併 settings_strict 的列車：用 definitions 內的同款嚴格讀取
        from routers.definitions import _strict_setting as f
    return f(conn, group, field)


def close_gate_options(conn) -> dict:
    """結案閘門的收緊選項 `{選項: bool}`。主開關 `enabled` 不是 1 ⇒ 全部 False（今天的行為）。
    **讀不到／格式不對 ⇒ 全部 True（往更嚴的一邊收，不悄悄放寬）**：這些選項只會讓更多案件不能結案，錯在嚴的一邊只是多擋一次、可立即處理。"""
    strictest = {k: True for k in CLOSE_GATE_OPTIONS}
    try:
        if _strict(conn, CLOSE_GATE_GROUP, "enabled") != 1:
            return {k: False for k in CLOSE_GATE_OPTIONS}
        out = {}
        for k in CLOSE_GATE_OPTIONS:
            v = _strict(conn, CLOSE_GATE_GROUP, k)
            if v not in (0, 1) or isinstance(v, bool):
                return strictest
            out[k] = v == 1
        return out
    except Exception:                                                  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("finance_params: 讀不到結案閘門選項，採最嚴設定", exc_info=True)
        return strictest
