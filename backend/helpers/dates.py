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


# ── 2026-09-26 自 M01 helpers/quotations 下沉（M01-PLAN §3-2）──

def norm_at(s: str) -> str:
    """統一時間格式（部分表用 'YYYY-MM-DDTHH:MM:SS[.ffffff]'，部分用空白分隔且無
    微秒），確保跨來源合併排序正確。2026-08-28：抽成共用函式——原本 dashboard.py
    的活動動態（首頁）跟 quotations.py::list_case_updates()（案件管理「動態」Tab）
    是同一種「合併多張表、依 created_at 字串排序」的動態牆邏輯，前者已經套用這個
    正規化，後者原本只對其中一個來源（audit_log）做了同樣的處理、其餘四個來源
    （case_updates／work_logs／daily_task_completions／dev_logs）維持各自原始格式
    直接排序——dev_logs 存的是空白分隔格式，跟其餘多數來源的 'T' 分隔格式排序時
    永遠排在同一天其他來源之前（ASCII 空白 0x20 < 'T' 0x54），不管實際時間點是
    幾點，導致同一天有業務開發記錄時動態牆順序會錯亂。兩處統一改呼叫這支共用
    函式，不要再各自處理一部分來源就以為排序沒問題。"""
    return (s or "").replace("T", " ")[:19]
