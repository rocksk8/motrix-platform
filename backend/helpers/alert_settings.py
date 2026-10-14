# -*- coding: utf-8 -*-
"""設定中心的數字（census #7、#8）：到期預警天數、密碼最短長度、登入有效天數。讀不到設定一律回程式預設（＝今天的數字）。

[單位] helper:alert_settings    [層] L1    [穩定度] 實作
[公開介面] DEFAULTS, LOGIN_DAYS_FALLBACK, PolicyUnreadable, cert_warn_days, login_days, min_password_len, warranty_mail_days, warranty_report_days
[不變式] 預設值＝今天寫死的數字（保固報表 90 天、保固郵件 7／30 天、簽章確認檔到期提醒 30 天、密碼至少 8 碼、登入有效 30 天），沒改設定時行為逐位元相同。
    安全類只准加嚴：密碼最短長度**不得低於 8**（下限寫死在程式裡，設定值只能往上調）；登入有效天數**不得超過 30**（只能縮短）。
    安全類兩項是**嚴格讀取**（`helpers/settings_strict`，不經 `settings_registry.get`——它永不丟例外，失敗會回預設 8／30＝悄悄放寬）：
    讀不到設定時，密碼規則 ⇒ `PolicyUnreadable`（設定／更改密碼的端點回 503，不寫入新密碼）；登入有效天數 ⇒ 最後一次讀到的值，沒有就保守的 7 天。
    密碼最短長度**只套用在設定／更改密碼**（`routers/auth.py` 的 `_min_pw()`）；登入時的弱密碼判斷維持常數 8（調高門檻不會把既有使用者鎖在門外）。
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


LOGIN_DAYS_FALLBACK = 7              # 讀不到設定、又沒有『最後一次讀到的值』時的保守登入天數（不是 30）
_last_login_days = None              # 最後一次成功讀到的登入天數（每個行程）


class PolicyUnreadable(Exception):
    """安全類設定讀不到（資料庫鎖住、格式不對、超出範圍）。呼叫端必須往『更嚴』的一邊處理，不可退回預設。"""


def _strict_int(group, key, lo, hi, conn=None) -> int:
    """嚴格讀取：讀不到／型別不對／超出 [lo, hi] ⇒ PolicyUnreadable（不退回預設）。"""
    try:
        from helpers.settings_strict import strict_value
        own = conn is None
        c = conn
        if own:
            from db import get_db
            c = get_db()
        try:
            v = strict_value(c, group, key)
        finally:
            if own:
                c.close()
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError("不合法的值：%r" % (v,))
        return v
    except Exception as e:                                   # noqa: BLE001
        raise PolicyUnreadable("%s.%s 讀不到" % (group, key)) from e


def min_password_len(conn=None) -> int:
    """設定／更改密碼時的最短長度：永遠不低於 8（寫死的下限）；設定只能往上調。讀不到 ⇒ PolicyUnreadable（呼叫端回 503，不放行）。"""
    return _strict_int("account_security", "password_min_len", _PASSWORD_FLOOR, 64, conn)


def login_days(conn=None) -> int:
    """登入（session）有效天數：永遠不超過 30（寫死的上限）；設定只能往下調。讀不到 ⇒ 最後一次讀到的值，沒有就 7 天（保守，不是 30）。"""
    global _last_login_days
    try:
        _last_login_days = _strict_int("account_security", "login_days", 1, _LOGIN_CEILING, conn)
        return _last_login_days
    except PolicyUnreadable:
        import logging
        logging.getLogger(__name__).warning("account_security: 讀不到登入有效天數，改用 %s 天", _last_login_days or LOGIN_DAYS_FALLBACK, exc_info=True)
        return _last_login_days or LOGIN_DAYS_FALLBACK
