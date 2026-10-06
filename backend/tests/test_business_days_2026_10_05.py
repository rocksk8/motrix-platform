# -*- coding: utf-8 -*-
"""L1 `helpers.business_days`（第44班：自 M11 標案雷達提升）：工作日／假日判斷。
錨點取自官方「政府行政機關辦公日曆表」（2026、2027）；日期由呼叫端給（不讀時鐘）。M11 的 `calendar_tw` 轉出舊名，行為不變。"""
from datetime import date

import pytest

from helpers import business_days as B


def test_weekend_and_weekday_and_holiday():
    assert B.is_working_day(date(2026, 10, 5)) is True            # 週一
    assert B.is_working_day(date(2026, 10, 3)) is False           # 週六
    assert B.is_working_day(date(2026, 10, 4)) is False           # 週日
    assert B.is_working_day(date(2026, 9, 28)) is False           # 孔子誕辰紀念日／教師節（週一，官方放假）
    assert B.is_working_day(date(2026, 1, 1)) is False            # 開國紀念日


def test_makeup_workday_is_a_working_day_with_synthetic_data():
    data = {"years": {"2026": {"holidays": {}, "makeup_workdays": ["2026-10-03"]}}}
    assert B.is_working_day(date(2026, 10, 3), data) is True      # 補班日（週六要上班）
    assert B.is_working_day(date(2026, 10, 4), data) is False


def test_previous_working_day():
    assert B.previous_working_day(date(2026, 10, 5)) == date(2026, 10, 5)      # 本身是上班日 ⇒ 自己
    assert B.previous_working_day(date(2026, 10, 4)) == date(2026, 10, 2)      # 週日 ⇒ 週五
    assert B.previous_working_day(date(2026, 9, 29)) == date(2026, 9, 29)
    assert B.previous_working_day(date(2026, 9, 28)) == date(2026, 9, 24)      # 週一教師節放假；前一個週五 9/25 也是國定假日（中秋節）⇒ 週四
    assert B.previous_working_day(date(2026, 10, 4), {"years": {}}, limit=1) is None, "limit 內找不到 ⇒ None，不無窮迴圈"


def test_year_outside_coverage_only_knows_weekends_and_says_so():
    assert B.covered(date(2026, 10, 5)) is True
    d = date(2035, 1, 3)                                            # 週三，表外
    assert B.covered(d) is False
    assert B.is_working_day(d) is True and B.is_working_day(date(2035, 1, 6)) is False
    assert B.is_working_day(date(2026, 10, 5), None) is True        # data=None ⇒ 讀預設表


def test_missing_or_broken_table_does_not_raise(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{壞掉", encoding="utf-8")
    assert B.load(bad) is None
    assert B.load(tmp_path / "none.json") is None
    assert B.no_mail_day(date(2026, 10, 3), {}) == (True, "週末")


def test_calendar_tw_reexports_the_same_functions():
    """M11 舊名不變、與 L1 是同一支（不是複製）。"""
    from modules.tender_radar import calendar_tw as C
    for name in ("load", "coverage", "covered", "days_until_expiry", "no_mail_day", "next_mail_day"):
        assert getattr(C, name) is getattr(B, name), name
    assert C.DATA_PATH == B.DATA_PATH and B.DATA_PATH.name == "holidays_tw.json" and B.DATA_PATH.parent.name == "helpers"
    assert C.no_mail_day(date(2026, 9, 28)) == (True, "國定假日：孔子誕辰紀念日/教師節")


def test_data_file_is_in_helpers_and_not_left_behind_in_m11():
    from pathlib import Path
    assert B.DATA_PATH.is_file()
    assert not (Path(__file__).resolve().parents[1] / "modules" / "tender_radar" / "holidays_tw.json").exists()


def test_next_mail_day_unchanged():
    assert B.next_mail_day(date(2026, 10, 3)) == date(2026, 10, 5)  # 週六 ⇒ 下週一


def test_datetime_input_is_treated_as_its_date():
    from datetime import datetime
    assert B._iso(datetime(2026, 10, 5, 23, 59)) == "2026-10-05"
    assert B.no_mail_day(datetime(2026, 10, 3, 9, 30)) == B.no_mail_day(date(2026, 10, 3))      # 週六
    assert B.covered(datetime(2026, 10, 5, 8, 0)) == B.covered(date(2026, 10, 5))
