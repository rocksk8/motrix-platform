# -*- coding: utf-8 -*-
"""設定值的**嚴格**讀取（安全把關專用；BP-2／T62）。

[單位] helper:settings_strict    [層] L1    [穩定度] 實驗
[公開介面] strict_value
[不變式] ①資料庫讀不到、內容格式不對 ⇒ **丟例外**（呼叫端決定『不知道』時要往哪個方向收；通常是往更嚴的一邊）；
    ②不經 `settings_registry.get`：它『永不丟例外』，讀取失敗會回快取或程式預設，等於悄悄換掉管理者設定的值；
       `MOTRIX_SETTINGS_DEFAULTS_ONLY=1` 也不影響本函式（照管理者已儲存的值判斷）；
    ③沒有儲存過的欄位 ⇒ 程式預設（這是正常情況，不是錯誤）；已到時的待生效值（例如放寬後的新值）會套上。
[契約題] backend/tests/test_t62_preview_gate_optin_2026_10_14.py、test_quote_approval_margin_2026_10_14.py
"""
from datetime import datetime

from core import definitions as D


def strict_value(conn, group, field):
    """⇒ 該欄位目前生效的值（未驗證型別／範圍，由呼叫端驗）。"""
    from helpers import settings_registry as SR
    row = D.get(conn, SR.KIND, group, SR.SCOPE)                        # 資料庫錯誤在此丟出，不吞
    val = SR._defaults(group)[field]
    if row is not None:
        vals = (row.get("body") or {}).get("values")
        if not isinstance(vals, dict):
            raise ValueError("設定群組 %s 的內容格式不對" % group)
        if field in vals:
            val = vals[field]
    for r in SR._due_pending(conn, group, datetime.now().isoformat(timespec="seconds")):
        if r["field"] == field:
            val = r["new"]
    return val
