# -*- coding: utf-8 -*-
"""設定中心的數字（census #7、#8）：到期預警天數、密碼最短長度、登入有效天數。讀不到設定一律回程式預設（＝今天的數字）。

[單位] helper:alert_settings    [層] L1    [穩定度] 實作
[公開介面] DEFAULTS, cert_warn_days, login_days, min_password_len, warranty_mail_days, warranty_report_days
[不變式] 預設值＝今天寫死的數字（保固報表 90 天、保固郵件 7／30 天、簽章確認檔到期提醒 30 天、密碼至少 8 碼、登入有效 30 天），沒改設定時行為逐位元相同。
    安全類只准加嚴：密碼最短長度**不得低於 8**（下限寫死在程式裡，設定值只能往上調）；登入有效天數**不得超過 30**（只能縮短）。
    兩層保固郵件的『緊急天數』一定小於『提前天數』（設定不合理時自動夾住）。
[契約題] tests/platform/test_settings_numbers_t62.py
"""
DEFAULTS = {
    "warranty_report_days": 90,
    "warranty_mail_early_days": 30,
    "warranty_mail_urgent_days": 7,
    "cert_warn_days": 30,
    "password_min_len": 8,
    "login_days": 30,
}
_PASSWORD_FLOOR = 8       # 寫死的下限（設定只能往上）
_LOGIN_CEILING = 30       # 寫死的上限（設定只能往下）


def _int(group, key, lo, hi, conn=None):
    """讀設定中心的整數；讀不到／型別不對／超出範圍 ⇒ 夾到 [lo, hi]；任何錯誤 ⇒ 預設。"""
    default = DEFAULTS[key]
    try:
        from helpers import settings_registry as SR
        v = SR.get(group, key, conn=conn)
        if isinstance(v, bool) or not isinstance(v, int):
            return default
        return max(lo, min(hi, v))
    except Exception:                                        # noqa: BLE001
        return default


def warranty_report_days(conn=None) -> int:
    """營運報表『保固到期預警』的天數窗口。"""
    return _int("alerts", "warranty_report_days", 30, 365, conn)


def warranty_mail_days(conn=None):
    """⇒ (緊急天數, 提前天數)：保固到期郵件的兩個階段（預設 7、30）。緊急天數一定小於提前天數。"""
    early = _int("alerts", "warranty_mail_early_days", 8, 180, conn)
    urgent = _int("alerts", "warranty_mail_urgent_days", 1, 30, conn)
    return min(urgent, early - 1), early


def cert_warn_days(conn=None) -> int:
    """開發者簽章確認檔到期前幾天開始提醒。"""
    return _int("alerts", "cert_warn_days", 7, 90, conn)


def min_password_len(conn=None) -> int:
    """密碼最短長度：永遠不低於 8（寫死的下限）；設定只能往上調。"""
    return _int("account_security", "password_min_len", _PASSWORD_FLOOR, 64, conn)


def login_days(conn=None) -> int:
    """登入（session）有效天數：永遠不超過 30（寫死的上限）；設定只能往下調。"""
    return _int("account_security", "login_days", 1, _LOGIN_CEILING, conn)
