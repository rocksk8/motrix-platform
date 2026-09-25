"""Date arithmetic utilities."""
import calendar
from datetime import date, timedelta

from fastapi import HTTPException


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


# 2026-09-26 自 M01 helpers/recognition.py 下沉（M04 搬遷：外包工班、叫料、額外支出都要驗日期欄，`AC2`）
def normalize_date(v, label="日期"):
    """'' ＝未登錄；否則必須是 YYYY-MM-DD 的真實日期。回正規化後的字串。"""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise HTTPException(400, "%s格式不正確，需為 YYYY-MM-DD" % label)
    v = v.strip()
    # 日期欄可能是 datetime 字串以外的東西；只接受整 10 碼的日期
    if v == "":
        return ""
    if len(v) != 10:
        raise HTTPException(400, "%s格式不正確，需為 YYYY-MM-DD" % label)
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise HTTPException(400, "%s格式不正確，需為 YYYY-MM-DD" % label)
