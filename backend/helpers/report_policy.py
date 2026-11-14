# -*- coding: utf-8 -*-
"""自訂報表的設定讀取（旗標＋四項設定）（T87 B2；後端每次請求都經這裡讀當下值，前端隱藏不是防線）。

[單位] helper:report_policy    [層] L1    [穩定度] 實驗
[公開介面] DEFAULTS, GROUP, EXPORT_SAME_AS_USE, EXPORT_ADMIN_ONLY, EXPORT_OFF, enabled, export_allowed, export_scope, quote_money_wide, recycle_deleted, sharing_enabled
[不變式] ①讀不到／壞值 ⇒ 出廠預設（較嚴格的一邊；`settings_registry.get` 永不丟例外，這裡再包一層保險）。
    ②`export_allowed(user)` 只回答「這個人在目前設定下能不能匯出」；能不能『使用』自訂報表、看得到哪些欄位與列，是別的層（report_runner／row_access）。
    ③最高管理者＝`role == "superadmin"`（同設定中心的改設定者）；沒有其他放行路徑。
[契約題] backend/tests/platform/test_custom_reports_settings_t87.py
"""
import logging

_log = logging.getLogger(__name__)

GROUP = "custom_reports"
EXPORT_SAME_AS_USE = 0
EXPORT_ADMIN_ONLY = 1
EXPORT_OFF = 2
DEFAULTS = {"enabled": 0, "export_scope": EXPORT_SAME_AS_USE, "sharing": 0, "recycle_deleted": 0, "quote_money_scope": 0}


def _get(field, conn=None):
    try:
        from helpers import settings_registry as sr
        v = sr.get(GROUP, field, conn=conn)
        return DEFAULTS[field] if v is None else v
    except Exception:                                          # noqa: BLE001 — 讀不到 ⇒ 出廠預設
        _log.warning("custom_reports 設定讀取失敗：%s；使用預設值", field, exc_info=True)
        return DEFAULTS[field]


def enabled(conn=None) -> bool:
    """旗標：關（預設、讀不到、壞值）⇒ 路由 404、不讀寫表。"""
    return _get("enabled", conn) == 1


def export_scope(conn=None) -> int:
    v = _get("export_scope", conn)
    return v if v in (EXPORT_SAME_AS_USE, EXPORT_ADMIN_ONLY, EXPORT_OFF) else DEFAULTS["export_scope"]


def export_allowed(user, conn=None) -> bool:
    """目前設定下，這位使用者可不可以匯出（不含『能不能使用』的判斷）。"""
    scope = export_scope(conn)
    if scope == EXPORT_OFF:
        return False
    if scope == EXPORT_ADMIN_ONLY:
        return (user or {}).get("role") == "superadmin"
    return True


def sharing_enabled(conn=None) -> bool:
    return _get("sharing", conn) == 1


def recycle_deleted(conn=None) -> bool:
    return _get("recycle_deleted", conn) == 1


def quote_money_wide(conn=None) -> bool:
    """D7：True＝報價單金額欄比照既有報價單內頁（持出納模組者整份可見；報價單清單本身只給業務／管理員／財務）；False（預設）＝只依欄位自己的天花板。"""
    return _get("quote_money_scope", conn) == 1
