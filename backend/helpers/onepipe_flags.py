# -*- coding: utf-8 -*-
"""一條龍（onepipe）各批次的開關讀取。

[單位] helper:onepipe_flags    [層] L1    [穩定度] 實驗
[公開介面] flag_on, GROUP
[契約題] tests/test_onepipe_p0a_links_2026_11_13.py

不變式：預設關；讀不到（群組沒登錄、資料庫錯誤）一律當關——關＝與今天逐位元相同。群組 `onepipe` 的欄位登錄在 helpers/settings_groups_onepipe.py。
"""
GROUP = "onepipe"


def flag_on(field: str, conn=None) -> bool:
    try:
        from helpers import settings_registry as SR
        return int(SR.get(GROUP, field, conn=conn)) == 1
    except Exception:                                                # noqa: BLE001
        return False
