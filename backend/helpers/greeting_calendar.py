# -*- coding: utf-8 -*-
"""登入問候語用的台灣節慶日曆（內建日期表，不連外網）。

[單位] helper:greeting_calendar    [層] L1    [穩定度] 實驗
[公開介面] festival_keys_on(d)、spring_festival(year)、reopen_day(year)、COVERED_UNTIL_YEAR、coverage_warning(today)
[不變式] 國曆節日（元旦、勞動節、國慶、聖誕、12/31）用固定月日算；農曆節日（除夕～初五、元宵、端午、七夕、中秋）
    用下面 `_LUNAR` 的**內建日期表**（不依賴任何套件或網路），涵蓋 2026～`COVERED_UNTIL_YEAR`（2032）。
    表外的年份：國曆節日照常、農曆節日**不出節慶句**（只會落到下一個優先順序，不會出錯）；
    守門測試在到期前半年以上就會紅燈，逼人補表（tests/test_login_greeting_2026_11_13.py）。
    日期表的產生：Meeus《Astronomical Algorithms》第49章朔與太陽黃經，以台北時間（UTC+8）逐年推算，
    2024～2027 與行政院人事行政總處辦公日曆表（helpers/holidays_tw.json）逐日核對一致後才採用；
    2026、2027 年另有測試比對辦公日曆表，之後有人改壞或補表補錯會立刻紅燈。
    「開工日」＝初五之後的第一個上班日（週末／國定假日／補假順延，用 helpers.business_days）。
[契約題] tests/test_login_greeting_2026_11_13.py
"""
from datetime import date, timedelta

#: 內建日期表涵蓋到這一年（含）。補表時同步改這個數字與下面的表。
COVERED_UNTIL_YEAR = 2032

#: 農曆日期表（國曆月日）。年份 → 春節（初一）、元宵、端午、七夕、中秋。
_LUNAR = {
    2026: {"cny": (2, 17), "lantern": (3, 3),  "dragon_boat": (6, 19), "qixi": (8, 19), "mid_autumn": (9, 25)},
    2027: {"cny": (2, 6),  "lantern": (2, 20), "dragon_boat": (6, 9),  "qixi": (8, 8),  "mid_autumn": (9, 15)},
    2028: {"cny": (1, 26), "lantern": (2, 9),  "dragon_boat": (5, 28), "qixi": (8, 26), "mid_autumn": (10, 3)},
    2029: {"cny": (2, 13), "lantern": (2, 27), "dragon_boat": (6, 16), "qixi": (8, 16), "mid_autumn": (9, 22)},
    2030: {"cny": (2, 3),  "lantern": (2, 17), "dragon_boat": (6, 5),  "qixi": (8, 5),  "mid_autumn": (9, 12)},
    2031: {"cny": (1, 23), "lantern": (2, 6),  "dragon_boat": (6, 24), "qixi": (8, 24), "mid_autumn": (10, 1)},
    2032: {"cny": (2, 11), "lantern": (2, 25), "dragon_boat": (6, 12), "qixi": (8, 12), "mid_autumn": (9, 19)},
}

#: 國曆固定節日：(月, 日) → 鍵
_SOLAR = {
    (1, 1): "new_year",
    (5, 1): "labor_day",
    (10, 10): "national_day",
    (12, 25): "christmas",
    (12, 31): "new_year_eve",
}

#: 節慶鍵 → 中文名稱（設定畫面與測試用；也是句庫的類別名稱）
FESTIVAL_LABELS = {
    "new_year": "元旦", "cny_eve": "除夕", "cny_1": "春節初一", "cny_2": "春節初二", "cny_3": "春節初三",
    "cny_4": "春節初四", "cny_5": "春節初五", "reopen": "春節後開工", "lantern": "元宵節", "labor_day": "勞動節",
    "dragon_boat": "端午節", "qixi": "七夕", "mid_autumn": "中秋節", "national_day": "國慶日",
    "christmas": "聖誕節", "new_year_eve": "跨年夜（12/31）",
}


def _md(year: int, key: str):
    row = _LUNAR.get(year)
    if not row or key not in row:
        return None
    m, d = row[key]
    return date(year, m, d)


def spring_festival(year: int):
    """該年春節初一的國曆日期；表外回 None。"""
    return _md(year, "cny")


def reopen_day(year: int):
    """該年春節後的開工日（初五之後的第一個上班日）；表外回 None。"""
    cny = spring_festival(year)
    if cny is None:
        return None
    from helpers.business_days import is_working_day
    d = cny + timedelta(days=5)          # 初五
    for _ in range(20):                    # 防呆上限；正常最多順延 10 天以內
        d += timedelta(days=1)
        if is_working_day(d):
            return d
    return None


def festival_keys_on(d: date) -> list:
    """該日的節慶鍵（可能有 0～2 個；已依「較特別的在前」排序）。"""
    out = []
    cny = spring_festival(d.year)
    if cny is not None:
        delta = (d - cny).days
        if delta == -1:
            out.append("cny_eve")
        elif 0 <= delta <= 4:
            out.append("cny_%d" % (delta + 1))
        if reopen_day(d.year) == d:
            out.append("reopen")
    for key in ("lantern", "dragon_boat", "qixi", "mid_autumn"):
        if _md(d.year, key) == d:
            out.append(key)
    s = _SOLAR.get((d.month, d.day))
    if s:
        out.append(s)
    return out


def coverage_warning(today: date):
    """日期表快到期時回一句白話提醒，否則 None（守門測試用；不在執行期擋任何功能）。
    到期前半年（涵蓋年的前一年 7/1 起）就提醒——補表要查官方資料、改這支檔，不能等到過期才發現。"""
    if today >= date(COVERED_UNTIL_YEAR - 1, 7, 1):
        return ("節慶日期表只涵蓋到 %d 年，今天 %s 起已進入補表期限："
                "請依 greeting_calendar.py 檔頭的方法補上後續年份，並同步改 COVERED_UNTIL_YEAR。" % (COVERED_UNTIL_YEAR, today))
    return None
