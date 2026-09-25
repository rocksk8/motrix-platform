"""Date arithmetic utilities."""

#: G1（MODULE-GUIDE §2）：底線開頭但屬於 L1 公開介面的名稱——改簽章或刪除照介面變更升版。
#: L1 以外只可以用這裡列出的底線名稱（守門：test_l1_interface_snapshot::test_l2_uses_only_declared_l1_underscore_names）。
__l1_public__ = (
    "_add_months",
    "_warranty_expiry",
    "_workdays_elapsed",
)

import calendar
from datetime import date, timedelta


def _add_months(d: date, months: int) -> date:
    m    = d.month - 1 + months
    year = d.year + m // 12
    mon  = m % 12 + 1
    day  = min(d.day, calendar.monthrange(year, mon)[1])
    return date(year, mon, day)


def _workdays_elapsed(start_date: date, end_date: date) -> int:
    """幾個完整工作日已經過去（start_date 不算在內，end_date 算在內），只排除
    週六日，不排除台灣國定假日（系統目前沒有假日行事曆表可用，屬已知限制，
    見 §5.9／§12 簽核逾期催辦說明）。用於簽核逾期催辦判斷「卡了幾個工作日」。"""
    if end_date <= start_date:
        return 0
    n = 0
    d = start_date + timedelta(days=1)
    while d <= end_date:
        if d.weekday() < 5:  # 0=Mon..4=Fri
            n += 1
        d += timedelta(days=1)
    return n


def _warranty_expiry(warranty_start: str, warranty_months) -> tuple:
    if not warranty_start:
        return None, None
    try:
        start = date.fromisoformat(warranty_start[:10])
        exp   = _add_months(start, int(warranty_months or 12))
        return exp, (exp - date.today()).days
    except Exception:
        return None, None
