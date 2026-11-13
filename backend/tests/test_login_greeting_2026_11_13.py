# -*- coding: utf-8 -*-
"""登入問候語（UX P1.5；UX-BUSINESS-PAGES-PROPOSAL §3.1.2，使用者 2026-11-13 裁示）契約題。

涵蓋：優先順序、時區（台北）、農曆日期表（含到期守門）、自訂覆蓋、關閉、久未登入天數邊界、第一次登入、同日重複登入、
節慶與其他情境的優先順序、內容守則、單一端點（含權限）。
"""
import json
import pathlib
from datetime import date, datetime, timedelta, timezone

import pytest

import helpers.settings_groups  # noqa: F401  登錄「登入問候語」群組
from helpers import greeting_calendar as GC
from helpers import greeting_phrases as GP
from helpers import login_greeting as LG

REPO = pathlib.Path(__file__).resolve().parents[2]
TZ8 = timezone(timedelta(hours=8))


def at(y, m, d, h=9, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=TZ8)


def iso(y, m, d, h=9, mi=0):
    return at(y, m, d, h, mi).isoformat()


def build(now, *, last=None, prev=None, n=5, style="formal", custom=None, todo=None, pending=0, new_quotes=0, uid=1, name="王小明"):
    return LG.build_greeting(now=now, user_id=uid, name=name, style=style, state={"last": last, "prev": prev, "n": n},
                             custom=custom, todo=todo, pending=pending, new_quotes=new_quotes)


# ── 農曆日期表 ──────────────────────────────────────────────────────────────
def test_lunar_table_covers_through_2030_at_least():
    assert GC.COVERED_UNTIL_YEAR >= 2030
    for y in range(2026, GC.COVERED_UNTIL_YEAR + 1):
        assert y in GC._LUNAR and set(GC._LUNAR[y]) == {"cny", "lantern", "dragon_boat", "qixi", "mid_autumn"}


def test_lunar_table_expiry_guard():
    """🔴 守門：日期表快到期（涵蓋年的前一年 7/1 起）這題就紅燈——逼人在過期前補表。補法見 greeting_calendar.py 檔頭。"""
    assert GC.coverage_warning(date.today()) is None, GC.coverage_warning(date.today())


def test_expiry_guard_logic_itself():
    assert GC.coverage_warning(date(GC.COVERED_UNTIL_YEAR - 1, 6, 30)) is None
    assert GC.coverage_warning(date(GC.COVERED_UNTIL_YEAR - 1, 7, 1))
    assert GC.coverage_warning(date(GC.COVERED_UNTIL_YEAR + 1, 1, 1))


def test_lunar_table_is_plausible_and_internally_consistent():
    prev = None
    for y in range(2026, GC.COVERED_UNTIL_YEAR + 1):
        cny = GC.spring_festival(y)
        assert date(y, 1, 21) <= cny <= date(y, 2, 20), (y, cny)
        if prev:
            assert (cny - prev).days in (354, 355, 383, 384), (y, (cny - prev).days)        # 農曆年長度只有這四種
        prev = cny
        r = GC._LUNAR[y]
        lantern = date(y, *r["lantern"])
        assert (lantern - cny).days == 14                                                      # 元宵＝初一後 14 天
        assert date(y, 5, 20) <= date(y, *r["dragon_boat"]) <= date(y, 6, 25)
        assert date(y, 7, 28) <= date(y, *r["qixi"]) <= date(y, 8, 28)
        assert date(y, 9, 8) <= date(y, *r["mid_autumn"]) <= date(y, 10, 8)


def test_lunar_table_matches_official_calendar_2026_2027():
    """用行政院人事行政總處辦公日曆表（helpers/holidays_tw.json）逐年對：春節初一、端午、中秋。"""
    data = json.loads((pathlib.Path(GC.__file__).with_name("holidays_tw.json")).read_text(encoding="utf-8"))["years"]
    for y in (2026, 2027):
        hol = data[str(y)]["holidays"]
        cny_days = sorted(k for k, v in hol.items() if v == "春節")
        eve = [k for k, v in hol.items() if v == "農曆除夕"][0]
        assert date.fromisoformat(eve) == GC.spring_festival(y) - timedelta(days=1)
        # 初一落在週末時辦公日曆表不列（2027 初一是週六）⇒ 不能拿「第一個標春節的日子」當初一；改驗：標「春節」的日子都在初一～初五內
        for k in cny_days:
            assert GC.spring_festival(y) <= date.fromisoformat(k) <= GC.spring_festival(y) + timedelta(days=4), (y, k)
        assert [k for k, v in hol.items() if v == "端午節"] == [date(y, *GC._LUNAR[y]["dragon_boat"]).isoformat()]
        assert [k for k, v in hol.items() if v == "中秋節"] == [date(y, *GC._LUNAR[y]["mid_autumn"]).isoformat()]


@pytest.mark.parametrize("d,keys", [
    (date(2026, 1, 1), ["new_year"]), (date(2026, 2, 16), ["cny_eve"]), (date(2026, 2, 17), ["cny_1"]),
    (date(2026, 2, 21), ["cny_5"]), (date(2026, 2, 22), []), (date(2026, 2, 23), ["reopen"]),
    (date(2026, 3, 3), ["lantern"]), (date(2026, 5, 1), ["labor_day"]), (date(2026, 6, 19), ["dragon_boat"]),
    (date(2026, 8, 19), ["qixi"]), (date(2026, 9, 25), ["mid_autumn"]), (date(2026, 10, 10), ["national_day"]),
    (date(2026, 12, 25), ["christmas"]), (date(2026, 12, 31), ["new_year_eve"]), (date(2026, 11, 13), []),
    (date(2030, 2, 2), ["cny_eve"]), (date(2030, 9, 12), ["mid_autumn"]),
])
def test_festival_keys(d, keys):
    assert GC.festival_keys_on(d) == keys


def test_reopen_day_skips_weekends_and_holidays():
    assert GC.reopen_day(2026) == date(2026, 2, 23)          # 初五 2/21 是週六 → 下週一
    for y in range(2026, GC.COVERED_UNTIL_YEAR + 1):
        d = GC.reopen_day(y)
        assert d > GC.spring_festival(y) + timedelta(days=4)
        assert d.weekday() < 5


def test_outside_table_lunar_festivals_silently_absent_but_solar_remain():
    far = date(GC.COVERED_UNTIL_YEAR + 5, 1, 1)
    assert GC.festival_keys_on(far) == ["new_year"]
    assert GC.festival_keys_on(date(GC.COVERED_UNTIL_YEAR + 5, 2, 10)) == []


# ── 句庫與內容守則 ───────────────────────────────────────────────────────────
def test_every_category_has_both_styles_and_every_festival_has_phrases():
    for cat, v in GP.BUILTIN.items():
        assert v.get("formal") and v.get("humor"), cat
        assert cat in GP.CATEGORY_LABELS, cat
    assert set(GC.FESTIVAL_LABELS) <= set(GP.BUILTIN)


def test_all_builtin_phrases_pass_content_guard():
    bad = [(c, t, GP.check_phrase(t)) for c, v in GP.BUILTIN.items() for ls in v.values() for t in ls if GP.check_phrase(t)]
    assert not bad, bad


@pytest.mark.parametrize("t", ["你年紀不小了", "男生都這樣", "今天很帥", "業績要加油", "別再摸魚", "x" * 61, "", "   ", "<b>", "a\nb",
                               "你好{unknown}", "你好{name", "你好name}", "你{name}好{"])
def test_content_guard_rejects(t):
    assert GP.check_phrase(t)


@pytest.mark.parametrize("t", ["今天天氣很好", "歡迎回來，{name}！", "待簽核 {pending} 張，離開 {days} 天"])
def test_content_guard_accepts(t):
    assert GP.check_phrase(t) == ""


def test_formal_phrases_have_no_jokey_markers():
    """正式版不開玩笑：不含驚嘆號堆疊／「～」「XD」這類輕浮記號（粗檢；真正的語氣由人審）。"""
    for c, v in GP.BUILTIN.items():
        for t in v["formal"]:
            assert "XD" not in t and "～" not in t and "！！" not in t, (c, t)


# ── 優先順序 ─────────────────────────────────────────────────────────────────
def test_priority_first_login_beats_festival():
    d = at(2026, 1, 1)                                          # 元旦
    g = build(d, last=d.isoformat(), prev=None, n=1)
    assert g["kind"] == "first_login" and g["action"] == {"label": "開始使用", "href": LG.START_HREF}


def test_priority_festival_beats_away():
    d = at(2026, 5, 1)                                          # 勞動節
    g = build(d, last=d.isoformat(), prev=iso(2026, 4, 1))
    assert g["kind"] == "festival" and g["category"] == "labor_day" and g["awayLine"] == ""


def test_priority_away_beats_weekday():
    d = at(2026, 11, 13)                                        # 週五
    g = build(d, last=d.isoformat(), prev=iso(2026, 11, 2))
    assert g["kind"] == "away" and g["category"] == "away_7"


def test_priority_weekday_beats_month_edge_and_season():
    assert build(at(2026, 6, 1), last=None)["category"] == "weekday_mon"          # 週一＋月初＋梅雨
    assert build(at(2026, 7, 31), last=None)["category"] == "weekday_fri"         # 週五＋月底＋夏


def test_priority_month_edge_beats_season():
    assert build(at(2026, 7, 1), last=None)["category"] == "month_start"          # 週三、夏
    assert build(at(2026, 1, 30), last=None)["category"] == "weekday_fri"            # 月底但週五：星期先贏
    assert build(at(2026, 7, 30), last=None)["category"] == "month_end"           # 週四


def test_priority_season_then_time():
    assert build(at(2026, 6, 10), last=None)["category"] == "plum_rain"           # 週三
    assert build(at(2026, 7, 8), last=None)["category"] == "summer"
    assert build(at(2026, 12, 9), last=None)["category"] == "winter"
    assert build(at(2026, 11, 11, 9), last=None)["category"] == "time_morning"    # 週三、無季節
    assert build(at(2026, 11, 11, 12), last=None)["category"] == "time_noon"
    assert build(at(2026, 11, 11, 15), last=None)["category"] == "time_afternoon"
    assert build(at(2026, 11, 11, 19), last=None)["category"] == "time_evening"
    assert build(at(2026, 11, 11, 23), last=None)["category"] == "time_late"
    assert build(at(2026, 11, 11, 3), last=None)["category"] == "time_late"


def test_season_boundaries():
    assert LG.season_category(date(2026, 5, 14)) is None
    assert LG.season_category(date(2026, 5, 15)) == "plum_rain"
    assert LG.season_category(date(2026, 6, 15)) == "plum_rain"
    assert LG.season_category(date(2026, 6, 16)) == "summer"
    assert LG.season_category(date(2026, 8, 31)) == "summer"
    assert LG.season_category(date(2026, 9, 1)) is None
    assert LG.season_category(date(2026, 11, 30)) is None
    assert LG.season_category(date(2026, 12, 1)) == "winter"
    assert LG.season_category(date(2027, 2, 28)) == "winter"
    assert LG.season_category(date(2027, 3, 1)) is None


def test_month_end_handles_leap_february():
    assert LG._months_last_day(date(2028, 2, 1)) == 29 and LG._months_last_day(date(2027, 2, 1)) == 28
    assert LG._months_last_day(date(2026, 12, 1)) == 31
    # 2027-02-27（週六）：星期優先；2027-02-26 是週五同理——挑一個週二：2030-02-27（週三、月底前一天）
    assert LG.choose_category(at(2030, 2, 27), first=False, logged_today=False, prev_date=None)[1] in ("month_end", "winter")         and LG.choose_category(at(2030, 2, 27), first=False, logged_today=False, prev_date=None)[0] != "weekday"
    assert LG.choose_category(at(2030, 2, 27), first=False, logged_today=False, prev_date=None)[1] == "month_end"


# ── 久未登入：天數邊界 ───────────────────────────────────────────────────────
@pytest.mark.parametrize("gap,want", [(0, None), (1, None), (2, None), (7, "away_7"), (13, "away_7"), (14, "away_14"), (29, "away_14"),
                                      (30, "away_30"), (89, "away_30"), (90, "away_90"), (400, "away_90")])
def test_away_buckets_boundaries(gap, want):
    today = date(2026, 11, 13)
    assert LG.away_category(today - timedelta(days=gap), today) == want


@pytest.mark.parametrize("prev,today,want", [
    (date(2026, 11, 9), date(2026, 11, 13), "away_3"),            # 週一 → 週五：漏了週二～四，3 天級
    (date(2026, 11, 6), date(2026, 11, 12), "away_3"),            # 週五 → 下週四（6 天）
    (date(2026, 11, 6), date(2026, 11, 9), None),                 # 週五 → 週一：正常週末，不算久未登入
    (date(2026, 11, 6), date(2026, 11, 10), "away_3"),            # 週五 → 週二：漏了週一
    (date(2026, 4, 2), date(2026, 4, 7), "post_holiday"),         # 清明連假（4/3 補假～4/6）後第一個上班日
    (date(2026, 4, 3), date(2026, 4, 7), None),                   # 連假中才登入過、中間只有週末與補假、gap=4 → 上一次在連假內… 見下一行
])
def test_away_three_to_six_days_needs_a_missed_workday(prev, today, want):
    got = LG.away_category(prev, today)
    if (prev, today) == (date(2026, 4, 3), date(2026, 4, 7)):
        assert got == "post_holiday"        # 4/4～4/6 全是非上班日（含補假）→ 連假後第一個上班日
    else:
        assert got == want


def test_long_absence_overrides_holiday_phrase():
    assert LG.away_category(date(2026, 2, 10), date(2026, 2, 23)) == "away_7"     # 春節整個假期 + 前後：13 天 → 7 天級


def test_same_day_second_login_does_not_trigger_away():
    now = at(2026, 11, 11, 15)
    g = build(now, last=iso(2026, 11, 11, 14), prev=iso(2026, 11, 11, 9))
    assert g["kind"] != "away" and g["awayLine"] == ""


def test_away_only_on_login_day_not_on_later_days_of_the_session():
    """session 最長 30 天：隔天開首頁不能說他『久未登入』。"""
    g = build(at(2026, 11, 12), last=iso(2026, 11, 11), prev=iso(2026, 10, 1))
    assert g["kind"] != "away"


def test_first_login_only_on_login_day():
    assert build(at(2026, 11, 11), last=iso(2026, 11, 11), prev=None, n=1)["kind"] == "first_login"
    assert build(at(2026, 11, 12), last=iso(2026, 11, 11), prev=None, n=1)["kind"] != "first_login"
    assert build(at(2026, 11, 11), last=iso(2026, 11, 11), prev=iso(2026, 11, 10), n=2)["kind"] != "first_login"


def test_away_summary_both_styles_and_content():
    now = at(2026, 11, 11)
    for style in ("formal", "humor"):
        g = build(now, last=now.isoformat(), prev=iso(2026, 10, 1), style=style, pending=lambda: 4, new_quotes=lambda: 2)
        assert g["kind"] == "away" and g["category"] == "away_30"
        assert g["awayLine"] == "離開期間：新增 2 張報價單；4 張單據等您簽核。"
    g = build(now, last=now.isoformat(), prev=iso(2026, 10, 1), pending=0, new_quotes=None)
    assert g["awayLine"] == "離開期間沒有需要您補辦的事項。"
    g = build(now, last=now.isoformat(), prev=iso(2026, 10, 1), pending=3, new_quotes=None)
    assert g["awayLine"] == "離開期間：3 張單據等您簽核。"


def test_summary_queries_only_run_when_needed_and_failures_are_swallowed():
    calls = []
    now = at(2026, 11, 11)                                             # 週三、無節慶
    build(now, last=None, pending=lambda: calls.append("p") or 1, new_quotes=lambda: calls.append("q") or 1)
    assert calls == []                                                 # 不是久未登入 ⇒ 完全不查
    g = build(now, last=now.isoformat(), prev=iso(2026, 10, 1), pending=lambda: 1 / 0, new_quotes=lambda: 1 / 0)
    assert g["awayLine"] == "離開期間沒有需要您補辦的事項。"          # 查失敗 ⇒ 不丟例外


# ── 時區 ─────────────────────────────────────────────────────────────────────
def test_timezone_is_taipei_not_utc():
    # UTC 2026-11-13 16:30 ＝ 台北 2026-11-14（週六）00:30
    utc = datetime(2026, 11, 13, 16, 30, tzinfo=timezone.utc)
    g = build(utc, last=None)
    assert g["category"] == "weekday_sat" and g["title"].startswith("晚安")
    # UTC 2026-11-12 23:30 ＝ 台北 11-13（週五）07:30
    g = build(datetime(2026, 11, 12, 23, 30, tzinfo=timezone.utc), last=None)
    assert g["category"] == "weekday_fri" and g["title"].startswith("早安")


def test_festival_follows_taipei_date_at_midnight_boundary():
    # UTC 2025-12-31 16:00 ＝ 台北 2026-01-01 00:00（元旦）
    g = build(datetime(2025, 12, 31, 16, 0, tzinfo=timezone.utc), last=None)
    assert g["category"] == "new_year"
    g = build(datetime(2025, 12, 31, 15, 59, tzinfo=timezone.utc), last=None)           # 台北 23:59 還是 12/31
    assert g["category"] == "new_year_eve"


def test_login_day_is_computed_in_taipei():
    # 登入時間 UTC 11-12 20:00（＝台北 11-13 04:00），現在 UTC 11-13 01:00（＝台北 11-13 09:00）→ 同一個台北日
    now = datetime(2026, 11, 13, 1, 0, tzinfo=timezone.utc)
    g = build(now, last=datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc).isoformat(), prev=iso(2026, 10, 1))
    assert g["kind"] == "away"


def test_title_words_match_old_dashboard_rule():
    for h, w in [(0, "晚安"), (4, "晚安"), (5, "早安"), (10, "早安"), (11, "午安"), (17, "午安"), (18, "晚安"), (23, "晚安")]:
        assert build(at(2026, 11, 11, h), last=None)["title"].startswith(w), h


# ── 風格、關閉、自訂 ─────────────────────────────────────────────────────────
def test_off_returns_nothing():
    g = build(at(2026, 1, 1), last=None, style="off", n=1)
    assert g["kind"] == "off" and g["title"] == "" and g["line"] == "" and g["action"] is None


def test_effective_style_matrix():
    E = LG.effective_style
    assert E(0, "humor") == "off" and E(0, "follow") == "off"                  # 公司關閉＝全關
    assert E(1, "follow") == "formal" and E(1, None) == "formal" and E(1, "humor") == "humor" and E(1, "off") == "off"
    assert E(2, "follow") == "humor" and E(2, "formal") == "formal" and E(2, "bogus") == "humor"


def test_styles_use_their_own_phrases():
    d = at(2026, 5, 1)
    f = build(d, last=None, style="formal")["line"]
    h = build(d, last=None, style="humor")["line"]
    assert f in GP.BUILTIN["labor_day"]["formal"] and h in GP.BUILTIN["labor_day"]["humor"]


def test_custom_phrases_replace_builtin_and_fill_placeholders():
    custom = {"labor_day": {"formal": ["{name}，勞動節快樂，今天{pending}張待簽。"]}}
    g = build(at(2026, 5, 1), last=None, custom=custom, pending=lambda: 7)
    assert g["line"] == "王小明，勞動節快樂，今天7張待簽。"
    h = build(at(2026, 5, 1), last=None, custom=custom, style="humor")                 # 只改了 formal，humor 仍是內建
    assert h["line"] in GP.BUILTIN["labor_day"]["humor"]


def test_invalid_custom_lines_are_ignored_at_read_time():
    custom = {"labor_day": {"formal": ["你年紀不小了", "<b>"]}}                       # 全部不合格 ⇒ 回內建
    assert build(at(2026, 5, 1), last=None, custom=custom)["line"] in GP.BUILTIN["labor_day"]["formal"]
    custom = {"labor_day": {"formal": ["你年紀不小了", "勞動節快樂"]}}               # 混著 ⇒ 只用合格的
    assert build(at(2026, 5, 1), last=None, custom=custom)["line"] == "勞動節快樂"


def test_todo_lines_zero_and_many_only():
    now = at(2026, 11, 11)
    assert build(now, last=None, todo=0)["todoLine"] in GP.BUILTIN["todo_zero"]["formal"]
    assert build(now, last=None, todo=11)["todoLine"] in GP.BUILTIN["todo_many"]["formal"]
    for n in (1, 5, 10):
        assert build(now, last=None, todo=n)["todoLine"] == ""
    assert build(now, last=None, todo=None)["todoLine"] == ""
    assert build(now, last=None, todo=True)["todoLine"] == ""                           # bool 不是數字


def test_same_user_same_day_is_stable_and_varies_across_days():
    mons = [date(2026, 11, 2) + timedelta(days=7 * i) for i in range(12)]              # 連續 12 個週一
    seen = set()
    for m in mons:
        a = build(at(m.year, m.month, m.day), last=None, uid=3)["line"]
        b = build(at(m.year, m.month, m.day, 16), last=None, uid=3)["line"]
        assert a == b                                                                   # 同人同日：重新整理不換句
        seen.add(a)
    assert seen == set(GP.BUILTIN["weekday_mon"]["formal"])                            # 隔天輪替：兩句都會出現


# ── 登入紀錄＋單一端點 ───────────────────────────────────────────────────────
def _login(client, u):
    r = client.post("/api/auth/login", json={"username": u[0], "password": u[1]})
    assert r.status_code == 200, r.text
    return r.json()["token"], {"Authorization": "Bearer " + r.json()["token"]}


def test_endpoint_requires_login(client):
    assert client.get("/api/auth/greeting").status_code == 401


def test_first_login_then_second_login(client, make_user, monkeypatch):
    u = make_user("alice", role="sales")
    monkeypatch.setattr(LG, "taipei_now", lambda: at(2026, 11, 11, 10))
    _, h = _login(client, u)
    g = client.get("/api/auth/greeting", headers=h).json()
    assert g["kind"] == "first_login" and g["action"]["href"] == LG.START_HREF and g["line"].startswith("歡迎加入，")
    assert client.get("/api/auth/greeting", headers=h).json()["kind"] == "first_login"        # 同一次登入重新整理，仍是歡迎句
    _, h2 = _login(client, u)                                                                # 第二次登入
    assert client.get("/api/auth/greeting", headers=h2).json()["kind"] != "first_login"


def test_record_login_keeps_previous_login(client, make_user):
    u = make_user("bob", role="sales")
    _, h = _login(client, u)
    me = client.get("/api/auth/me", headers=h).json()["userId"]
    st1 = LG.get_state(me)
    assert st1["n"] == 1 and st1["prev"] is None and st1["last"] and "pref" not in st1
    _login(client, u)
    st2 = LG.get_state(me)
    assert st2["n"] == 2 and st2["prev"] == st1["last"]


def test_personal_pref_reads_user_prefs_with_safe_fallback(monkeypatch):
    import sys, types
    fake = types.SimpleNamespace(get=lambda uid, key, default=None: {"login_greeting": "humor"}.get(key, default))
    import helpers
    monkeypatch.setitem(sys.modules, "helpers.user_prefs", fake)
    monkeypatch.setattr(helpers, "user_prefs", fake, raising=False)   # `from helpers import user_prefs` 讀的是套件屬性，不是 sys.modules（先被別的測試匯入過就會拿到真的）
    assert LG.personal_pref(1) == "humor"
    for raw, want in (("follow_company", "follow"), ("formal", "formal"), ("off", "off"), ("亂寫", "follow"), (None, "follow")):
        fake.get = lambda uid, key, default=None, _r=raw: _r
        assert LG.personal_pref(1) == want, raw
    def boom(uid, key, default=None): raise RuntimeError("x")
    fake.get = boom
    assert LG.personal_pref(1) == "follow"                          # 讀不到 ⇒ 跟隨公司


def test_personal_off_and_company_off(client, make_user, monkeypatch):
    _, h = _login(client, make_user("dave", role="sales"))
    monkeypatch.setattr(LG, "personal_pref", lambda uid: "off")
    assert client.get("/api/auth/greeting", headers=h).json()["kind"] == "off"
    monkeypatch.setattr(LG, "personal_pref", lambda uid: "humor")
    g = client.get("/api/auth/greeting", headers=h).json()
    assert g["style"] == "humor" and g["kind"] != "off"
    from helpers import settings_registry as SR
    monkeypatch.setattr(SR, "get_group", lambda grp, **k: {"style": 0} if grp == "login_greeting" else {})
    g = client.get("/api/auth/greeting", headers=h).json()
    assert g["style"] == "off" and g["kind"] == "off" and g["companyStyle"] == 0              # 公司關閉＝個人也不能打開


def test_company_style_default_is_formal_and_garbage_falls_back(monkeypatch):
    assert LG.company_style() == LG.STYLE_FORMAL
    from helpers import settings_registry as SR
    for bad in ("x", None, 7, True, -1):
        monkeypatch.setattr(SR, "get_group", lambda g, _b=bad, **k: {"style": _b})
        assert LG.company_style() == LG.STYLE_FORMAL
    monkeypatch.setattr(SR, "get_group", lambda g, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert LG.company_style() == LG.STYLE_FORMAL


def test_away_via_endpoint_uses_server_state_and_same_pending_count_as_badge(client, make_user, monkeypatch):
    from helpers.settings import _set_setting
    u = make_user("erin", role="sales")
    _, h = _login(client, u)
    me = client.get("/api/auth/me", headers=h).json()["userId"]
    now = at(2026, 11, 11, 10)
    monkeypatch.setattr(LG, "taipei_now", lambda: now)
    _set_setting(LG.STATE_PREFIX + str(me), {"last": now.isoformat(), "prev": iso(2026, 10, 20), "n": 9})
    g = client.get("/api/auth/greeting", headers=h).json()
    badge = client.get("/api/approval-queue/count", headers=h).json()["count"]
    assert g["kind"] == "away" and g["category"] == "away_14"
    assert g["awayLine"] == ("離開期間沒有需要您補辦的事項。" if badge == 0 else "離開期間：%d 張單據等您簽核。" % badge)


def test_new_quotes_count_only_for_superadmin(client, make_user, monkeypatch):
    from helpers.settings import _set_setting
    import db
    now = at(2026, 11, 11, 10)
    monkeypatch.setattr(LG, "taipei_now", lambda: now)
    conn = db.get_db()
    conn.execute("INSERT INTO quotations (quote_no, status, created_at) VALUES ('Q-OLD','草稿','2026-10-01T09:00:00')")
    conn.execute("INSERT INTO quotations (quote_no, status, created_at) VALUES ('Q-NEW1','草稿','2026-11-02T09:00:00')")
    conn.execute("INSERT INTO quotations (quote_no, status, created_at) VALUES ('Q-NEW2','草稿','2026-11-05T09:00:00')")
    conn.commit()
    conn.close()
    out = {}
    for name, role in (("sa1", "superadmin"), ("sales1", "sales")):
        _, h = _login(client, make_user(name, role=role))
        me = client.get("/api/auth/me", headers=h).json()["userId"]
        _set_setting(LG.STATE_PREFIX + str(me), {"last": now.isoformat(), "prev": iso(2026, 10, 20), "n": 9})
        out[role] = client.get("/api/auth/greeting", headers=h).json()["awayLine"]
    assert "新增 2 張報價單" in out["superadmin"] and "新增" not in out["sales"]


@pytest.mark.parametrize("how", ["absent", "raises", "ambiguous"])
def test_new_quotes_provider_absent_or_failing_degrades_to_no_line(client, make_user, monkeypatch, how):
    """IP-GR1 降級（hichan-12 抽查補）：案件模組不在／提供者丟例外／多個提供者 ⇒ 問候語照出（200），只是沒有「新增 N 張報價單」。"""
    from core import registry
    from helpers.settings import _set_setting
    now = at(2026, 11, 11, 10)
    monkeypatch.setattr(LG, "taipei_now", lambda: now)

    def single(name, *a, **k):
        if name != "greeting.new_quotes":
            return orig(name, *a, **k)
        if how == "absent":
            return None
        if how == "raises":
            return lambda since: 1 / 0
        raise RuntimeError("多個提供者：greeting.new_quotes")
    orig = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", single)
    _, h = _login(client, make_user("sa_deg_" + how, role="superadmin"))
    me = client.get("/api/auth/me", headers=h).json()["userId"]
    _set_setting(LG.STATE_PREFIX + str(me), {"last": now.isoformat(), "prev": iso(2026, 10, 20), "n": 9})
    r = client.get("/api/auth/greeting", headers=h)
    assert r.status_code == 200 and "新增" not in r.json()["awayLine"]


def test_existing_account_without_state_is_not_treated_as_first_login(client, make_user):
    """升版：舊帳號沒有 login_state，用稽核紀錄回填——不能全公司一起變『第一次登入』。"""
    from helpers.settings import _set_setting
    u = make_user("frank", role="sales")
    _, h = _login(client, u)
    me = client.get("/api/auth/me", headers=h).json()["userId"]
    _set_setting(LG.STATE_PREFIX + str(me), None)                         # 模擬升版前：沒有紀錄（稽核裡還留著上一筆 auth.login）
    _login(client, u)
    st = LG.get_state(me)
    assert st["n"] == 2 and st["prev"], st


def test_record_login_never_breaks_login(client, make_user, monkeypatch):
    import helpers.settings as S
    u = make_user("gina", role="sales")
    monkeypatch.setattr(S, "_set_setting", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    r = client.post("/api/auth/login", json={"username": u[0], "password": u[1]})
    assert r.status_code == 200 and r.json()["token"]


def test_todo_query_is_validated(client, make_user):
    _, h = _login(client, make_user("hank", role="sales"))
    assert client.get("/api/auth/greeting?todo=0", headers=h).json()["todoLine"]
    assert client.get("/api/auth/greeting?todo=-1", headers=h).status_code == 422
    assert client.get("/api/auth/greeting?todo=abc", headers=h).status_code == 422


# ── 句庫自訂 API ─────────────────────────────────────────────────────────────
def test_phrases_api_is_superadmin_only(client, make_user):
    _, hs = _login(client, make_user("sa2", role="superadmin"))
    _, hn = _login(client, make_user("sales2", role="sales"))
    assert client.get("/api/login-greeting/phrases", headers=hn).status_code == 403
    assert client.put("/api/login-greeting/phrases", json={"category": "labor_day", "style": "formal", "lines": ["x"]}, headers=hn).status_code == 403
    assert client.get("/api/login-greeting/phrases").status_code == 401
    r = client.get("/api/login-greeting/phrases", headers=hs)
    assert r.status_code == 200 and len(r.json()["categories"]) == len(GP.BUILTIN) and r.json()["maxLen"] == GP.MAX_LEN


def test_phrases_api_save_reset_validate_and_audit(client, make_user, monkeypatch):
    _, hs = _login(client, make_user("sa3", role="superadmin"))
    put = lambda **kw: client.put("/api/login-greeting/phrases", json=kw, headers=hs)
    assert put(category="nope", style="formal", lines=["x"]).status_code == 400
    assert put(category="labor_day", style="bogus", lines=["x"]).status_code == 400
    assert put(category="labor_day", style="formal", lines=["你年紀不小了"]).status_code == 400            # 內容守則
    assert put(category="labor_day", style="formal", lines=["{bad}"]).status_code == 400
    assert put(category="labor_day", style="formal", lines=["x" * 61]).status_code == 400
    assert put(category="labor_day", style="formal", lines=["ok"] * 21).status_code == 400
    r = put(category="labor_day", style="formal", lines=["  勞動節快樂，{name}  ", "", "辛苦了"])
    assert r.status_code == 200 and r.json()["saved"] == ["勞動節快樂，{name}", "辛苦了"]
    monkeypatch.setattr(LG, "taipei_now", lambda: at(2026, 5, 1))
    me_line = client.get("/api/auth/greeting", headers=hs).json()["line"]
    assert me_line in ("勞動節快樂，" + "sa3", "辛苦了") or me_line.startswith("勞動節快樂，")
    tbl = {c["category"]: c for c in client.get("/api/login-greeting/phrases", headers=hs).json()["categories"]}
    assert tbl["labor_day"]["formal"]["custom"] == ["勞動節快樂，{name}", "辛苦了"] and tbl["labor_day"]["formal"]["builtin"]
    assert put(category="labor_day", style="formal", lines=[]).status_code == 200                      # 清空＝回內建
    assert LG.get_custom() == {}
    import db
    conn = db.get_db()
    n = conn.execute("SELECT COUNT(*) AS n FROM audit_log WHERE action='login_greeting.phrases'").fetchone()["n"]
    conn.close()
    assert n >= 2


# ── 設定與前端 ───────────────────────────────────────────────────────────────
def test_setting_group_registered_with_formal_default():
    from helpers import settings_registry as SR
    f = {x["key"]: x for x in SR.groups()["login_greeting"]["fields"]}["style"]
    assert f["default"] == 1 and f["recommended"] == 1 and {c["value"] for c in f["choices"]} == {0, 1, 2}


def test_dashboard_shows_server_greeting():
    s = (REPO / "frontend/index.html").read_text(encoding="utf-8")
    assert "/auth/greeting" in s and 'data-testid="login-greeting"' in s
