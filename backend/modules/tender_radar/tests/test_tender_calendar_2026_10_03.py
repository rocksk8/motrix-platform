# -*- coding: utf-8 -*-
"""2026-10-03 標案雷達「不寄信日」：週六、週日、國定假日（使用者：「未來六日跟國定假日，直接不寄信」）。

資料 `holidays_tw.json` 取自官方「中華民國政府行政機關辦公日曆表」（人事行政總處；來源網址、取得日期、涵蓋範圍、原檔 sha256 都在檔內）。
下面的「錨點」都是官方 CSV 的原始列（2026／2027），不是憑記憶寫的。
"""
import json
from datetime import date

import pytest

from modules.tender_radar import calendar_tw as C

DATA = C.load()


def _ids(y):
    return DATA["years"][str(y)]


# ── 判定規則（日期由呼叫端給＝可注入；不讀時鐘）──────────────────────────────

def test_saturday_and_sunday_are_no_mail_days():
    assert C.no_mail_day(date(2026, 10, 3)) == (True, "週末")        # 週六
    assert C.no_mail_day(date(2026, 10, 4)) == (True, "週末")        # 週日


def test_a_normal_weekday_is_a_mail_day():
    assert C.no_mail_day(date(2026, 10, 5)) == (False, None)         # 週一
    assert C.no_mail_day(date(2026, 10, 2)) == (False, None)         # 週五


def test_a_national_holiday_on_a_weekday_is_a_no_mail_day_with_its_name():
    assert C.no_mail_day(date(2026, 9, 28)) == (True, "國定假日：孔子誕辰紀念日/教師節")   # 週一
    assert C.no_mail_day(date(2026, 1, 1)) == (True, "國定假日：開國紀念日")


def test_makeup_saturday_is_a_working_day_so_mail_is_allowed():
    """官方 2026、2027 都沒有補班日，所以用合成資料驗規則：補班日（週末但要上班）可寄信；其餘週末照樣不寄。"""
    data = {"years": {"2026": {"holidays": {}, "makeup_workdays": ["2026-10-03"]}}}
    assert C.no_mail_day(date(2026, 10, 3), data) == (False, None)           # 補班的週六
    assert C.no_mail_day(date(2026, 10, 10), data) == (True, "週末")         # 一般週六
    assert C.no_mail_day(date(2026, 10, 4), data) == (True, "週末")


def test_makeup_day_wins_even_if_it_were_also_listed_as_a_holiday():
    data = {"years": {"2026": {"holidays": {"2026-10-05": "X"}, "makeup_workdays": ["2026-10-05"]}}}
    assert C.no_mail_day(date(2026, 10, 5), data) == (False, None)


def test_year_outside_the_table_only_recognises_weekends_and_says_it_is_uncovered():
    assert date(2028, 1, 1).weekday() == 5 and date(2028, 1, 3).weekday() == 0
    assert C.covered(date(2028, 1, 3)) is False
    assert C.no_mail_day(date(2028, 1, 1)) == (True, "週末")                 # 表外的週六：仍認得
    assert C.no_mail_day(date(2028, 1, 3)) == (False, None)                  # 表外的平日：不猜、當平日（頁面要明說未涵蓋）


def test_missing_or_broken_table_degrades_to_weekends_only(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{not json", encoding="utf-8")
    assert C.load(bad) is None
    assert C.no_mail_day(date(2026, 10, 3), {}) == (True, "週末")           # 沒有表（{}）⇒ 仍認得週末
    assert C.no_mail_day(date(2026, 10, 5), {}) == (False, None)
    assert C.coverage({}) is None and C.covered(date(2026, 10, 5), {}) is False
    assert C.days_until_expiry(date(2026, 10, 5), {}) is None


def test_next_mail_day_skips_weekend_and_holidays():
    assert C.next_mail_day(date(2026, 10, 3)) == date(2026, 10, 5)            # 週六 ⇒ 週一
    assert C.next_mail_day(date(2026, 2, 14)) == date(2026, 2, 23)            # 農曆新年連假 ⇒ 2/23（週一）
    assert C.next_mail_day(date(2026, 10, 5)) == date(2026, 10, 5)


# ── 錨點：官方資料本身 ─────────────────────────────────────────────────────────

def test_anchor_2026_lunar_new_year_block_and_makeup_holidays():
    """官方 115 年：2/16 農曆除夕、2/17～2/19 春節、2/20 補假、2/27 補假（2/28 和平紀念日在週六）。"""
    h = _ids(2026)["holidays"]
    assert h["2026-02-16"] == "農曆除夕"
    assert [h["2026-02-17"], h["2026-02-18"], h["2026-02-19"]] == ["春節"] * 3
    assert h["2026-02-20"] == "補假" and h["2026-02-27"] == "補假"
    for d in ("2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-27"):
        assert C.no_mail_day(date.fromisoformat(d))[0] is True


def test_anchor_national_day_2026_falls_on_saturday_and_is_observed_on_friday_10_09():
    """國慶日 2026-10-10 是週六 ⇒ 官方補假在 10/09（週五）。"""
    assert date(2026, 10, 10).weekday() == 5
    assert _ids(2026)["holidays"]["2026-10-09"] == "補假"
    assert C.no_mail_day(date(2026, 10, 9)) == (True, "國定假日：補假")
    assert C.no_mail_day(date(2026, 10, 12)) == (False, None)                 # 週一照常


def test_anchor_national_day_2027_falls_on_sunday_and_is_observed_on_monday_10_11():
    """國慶日 2027-10-10 是週日 ⇒ 官方補假在 10/11（週一）。"""
    assert date(2027, 10, 10).weekday() == 6
    assert _ids(2027)["holidays"]["2027-10-11"] == "補假"
    assert C.no_mail_day(date(2027, 10, 11))[0] is True
    assert C.no_mail_day(date(2027, 10, 12)) == (False, None)


def test_anchor_2027_lunar_new_year_block():
    h = _ids(2027)["holidays"]
    assert h["2027-02-04"] == "小年夜" and h["2027-02-05"] == "農曆除夕"
    assert h["2027-02-08"] == "春節" and h["2027-02-09"] == "補假" and h["2027-02-10"] == "補假"


@pytest.mark.parametrize("year", [2026, 2027])
def test_data_invariants_makeup_days_are_weekend_and_never_holidays(year):
    y = _ids(year)
    for d in y["makeup_workdays"]:
        assert date.fromisoformat(d).weekday() >= 5, d + " 補班日必須是週末"
        assert d not in y["holidays"], d + " 不可同時是放假日"
    for d in y["holidays"]:
        assert date.fromisoformat(d).weekday() < 5, d + " 表內只存平日放假日（週末本來就不寄）"
        assert d.startswith(str(year))


def test_official_2026_and_2027_have_no_makeup_workdays():
    """官方原檔：旗標 0 的週末列＝0 筆（備註：此規則仍由合成資料驗證）。若之後官方公告補班日，這題要跟著更新並改為錨點。"""
    assert _ids(2026)["makeup_workdays"] == [] and _ids(2027)["makeup_workdays"] == []


def test_provenance_and_coverage_are_recorded_in_the_data_file():
    s = DATA["source"]
    assert s["agency"].startswith("行政院人事行政總處") and s["dataset_url"].startswith("https://data.gov.tw/dataset/")
    assert s["retrieved"] == "2026-10-03"
    for y in ("2026", "2027"):
        f = s["files"][y]
        assert f["url"].startswith("https://www.dgpa.gov.tw/") and len(f["sha256"]) == 64 and f["rows"] == 365
    assert DATA["coverage"] == {"from": "2026-01-01", "to": "2027-12-31"}
    assert C.coverage() == (date(2026, 1, 1), date(2027, 12, 31))


def test_expiry_helper_counts_days_to_the_end_of_coverage():
    assert C.days_until_expiry(date(2027, 12, 31)) == 0
    assert C.days_until_expiry(date(2027, 11, 1)) == 60
    assert C.days_until_expiry(date(2028, 1, 1)) == -1
    assert C.covered(date(2027, 12, 31)) is True and C.covered(date(2028, 1, 1)) is False
