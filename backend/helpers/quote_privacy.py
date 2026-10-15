# -*- coding: utf-8 -*-
"""報價單個人資料欄位的設定使用端（T63 Q0）：客戶電子郵件／傳真能不能被管理者隱藏。

[單位] helper:quote_privacy    [層] L1    [穩定度] 實驗
[公開介面] forced_core（載入時向 core.catalog 登記；L0 不 import 本檔）
[不變式] ①預設（兩個設定都是『可隱藏』）⇒ 回 False ⇒ 版面可自訂點與今天完全相同；②設定改成『不可隱藏』⇒ 該欄位的點變成核心欄位
    （隱藏／顯示／改名的操作被版面守門擋下；已發布的隱藏操作在執行時不套用、列在 dropped，畫面恢復顯示）；③只影響畫面，不刪、不改任何已存的內容。
設計：docs/platform/plans/T63-Q0-SETTINGS-SPEC.md。
"""
#: (可自訂點的 entity, 欄位鍵) ⇒ 設定欄位（群組 quote_privacy）
_SWITCH = {("qcustomer", "contactEmail"): "contact_email_hideable", ("qcustomer", "contactFax"): "contact_fax_hideable"}
_MODULE = "case"


def forced_core(module_key, entity, field) -> bool:
    """這個欄位現在是否被設定強制成核心欄位（不可隱藏）。永不丟例外；讀不到 ⇒ 沿用登記的樣子（False）。"""
    if module_key != _MODULE:
        return False
    sw = _SWITCH.get((entity, field))
    if not sw:
        return False
    try:
        from helpers import settings_registry as SR
        return int(SR.get("quote_privacy", sw)) == 0
    except Exception:                                                                    # noqa: BLE001
        return False


def _register():
    from core import catalog
    catalog.register_privacy_core_provider(forced_core)


_register()
