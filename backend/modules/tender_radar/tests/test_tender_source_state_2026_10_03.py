# -*- coding: utf-8 -*-
"""2026-10-03 標案雷達正式機告警調查（使用者貼的信：成功解析 0 筆／解析失敗 1 筆／本次總筆數 1 筆）。

調查結論（對現行網站 live 驗證）：
  ① 列表頁版面沒變，現行格式照樣解得出來（fixtures/tender_list_20261003_current_format.html）。
  ② 當日沒有公告（週末、假日）時，網站回一列 `<td colspan="10">無符合條件資料</td>`；舊解析器把它算成 dropped=1，
     `suspect_redesign(0, 1)` 為真 ⇒ 寄「來源網站格式異動」（誤報）——與使用者收到的信的數字完全相同。
  ③ 詳細頁現在先要「驗證碼檢核」（撲克牌）：偵測、停止、記下、顯示狀態；不解、不繞、不重試。
fixtures 皆取自 2026-10-03 現行網站的公開頁面（已去掉導覽與腳本，不含個資）。
"""
import time as _time
from datetime import date, datetime
from pathlib import Path

import pytest

import modules.tender_radar.source as ts
from modules.tender_radar import notify as tender_notify

USES_REAL_CALENDAR = True        # tests/conftest.py 的 _mail_day_independent_of_the_real_weekday 不介入：本檔自己注入日期

FX = Path(__file__).parent / "fixtures"
EMPTY = (FX / "tender_list_empty_20261003.html").read_text(encoding="utf-8")
CUR = (FX / "tender_list_20261003_current_format.html").read_text(encoding="utf-8")
CAPTCHA = (FX / "tender_detail_captcha_20261003.html").read_text(encoding="utf-8")
DETAIL_OK = (FX / "tender_detail_20260921.html").read_text(encoding="utf-8")


def _day(monkeypatch, iso, hour=9):
    d = date.fromisoformat(iso)
    monkeypatch.setattr(ts, "today", lambda: d)
    monkeypatch.setattr(ts, "now_dt", lambda: datetime(d.year, d.month, d.day, hour, 0, 0))
    return d


# ══════════════════ A．空結果頁不是解析失敗 ══════════════════

def test_empty_result_page_is_a_recognised_empty_result_not_a_dropped_row():
    items, dropped, recognised = ts.parse_list(EMPTY)
    assert (items, dropped, recognised) == ([], 0, True)
    assert ts.suspect_redesign(len(items), dropped) is False
    assert ts.is_empty_result(EMPTY) is True
    assert ts.is_empty_result(CUR) is False                      # 有資料的頁不是「空」


def test_regression_the_users_alert_numbers_parsed0_dropped1_no_longer_suspect(monkeypatch):
    """使用者 2026-10-03 09:00 收到：成功解析 0／解析失敗 1／總筆數 1。舊行為（空列算 dropped）會得到 suspect=True。"""
    monkeypatch.setattr(ts, "_is_empty_result_row", lambda cells: False)     # 還原舊行為
    items, dropped, _ = ts.parse_list(EMPTY)
    assert (len(items), dropped) == (0, 1) and ts.suspect_redesign(len(items), dropped) is True   # ← 誤報的來源
    monkeypatch.undo()
    items, dropped, _ = ts.parse_list(EMPTY)
    assert (len(items), dropped) == (0, 0) and ts.suspect_redesign(0, 0) is False


def test_current_site_format_parses_with_the_current_parser():
    items, dropped, recognised = ts.parse_list(CUR)
    assert recognised is True and dropped == 0 and len(items) == 3
    for it in items:
        assert it["case_no"] and it["org"] and it["name"] and it["url"].startswith("https://web.pcc.gov.tw/prkms/urlSelector/")
        assert it["published_at"] and it["deadline"] and isinstance(it["budget"], int)
    assert items[0]["case_no"] == "STAT115-0918" and items[0]["budget"] == 2775000 and items[0]["published_at"] == "2026-10-06"


def _table_with(rows_html):
    head = CUR[:CUR.index("<tbody") + len("<tbody>")] if "<tbody" in CUR else CUR[:CUR.index("<tr", CUR.index("</tr>")) ]
    return head + "".join(rows_html) + "</tbody></table>"


def _good_row():
    rows = ts._TR_RE.findall(ts._find_result_table(CUR))
    return rows[1]


def _garble(row):
    """把機關欄換成日期＝欄序對調的壞法（形狀驗證會擋）。"""
    cells = ts._TD_RE.findall(row)
    return row.replace(cells[1], "<td>115/10/06</td>") if cells[1] in row else row


def test_genuinely_garbled_rows_still_count_as_dropped_and_still_trigger_suspect():
    """(a) 十列裡九列壞 ⇒ dropped=9、parsed=1 ⇒ suspect=True（空列規則不可以把真正的改版放行）。"""
    good = _good_row()
    garbled = _garble(good)
    assert garbled != good
    items, dropped, rec = ts.parse_list(_table_with([good] + [garbled] * 9))
    assert rec is True and len(items) == 1 and dropped == 9
    assert ts.suspect_redesign(len(items), dropped) is True


def test_an_empty_result_row_mixed_with_garbled_rows_does_not_hide_them():
    items, dropped, _ = ts.parse_list(_table_with(['<tr><td colspan="10">無符合條件資料</td></tr>'] + [_garble(_good_row())] * 3))
    assert len(items) == 0 and dropped == 3 and ts.suspect_redesign(0, 3) is True


def test_a_single_cell_row_with_other_text_still_counts_as_dropped():
    items, dropped, _ = ts.parse_list(_table_with(['<tr><td colspan="10">系統訊息：請稍後再試</td></tr>']))
    assert len(items) == 0 and dropped == 1 and ts.is_empty_result(_table_with(['<tr><td colspan="10">系統訊息</td></tr>'])) is False


# ══════════════════ B．驗證碼頁 ══════════════════

def test_captcha_page_is_detected_but_a_normal_detail_page_is_not():
    assert ts.is_captcha_page(CAPTCHA) is True
    assert ts.is_captcha_page(DETAIL_OK) is False
    assert ts.is_captcha_page("") is False and ts.is_captcha_page(None) is False
    # 兩個字樣都要有：只提到驗證碼的普通頁面不算
    assert ts.is_captcha_page("<html>驗證碼檢核說明</html>") is False
    # 有標案欄位 id 的頁面即使文字提到撲克牌也不算
    assert ts.is_captcha_page('<div id="fkPmsExecuteLocation">桃園市</div> 驗證碼檢核 撲克牌') is False


class _Resp:
    def __init__(self, body):
        self._b = body.encode("utf-8")

    def read(self):
        return self._b

    def geturl(self):
        return "https://web.pcc.gov.tw/tps/QueryTender/query/searchTenderDetail?pkPmsMain=X"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_detail_returns_the_captcha_error_not_html_and_passes_normal_pages_through(monkeypatch):
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    monkeypatch.setattr(ts.urllib.request, "urlopen", lambda *a, **k: _Resp(CAPTCHA))
    assert ts.fetch_detail("https://web.pcc.gov.tw/x") == (None, ts.CAPTCHA_ERROR)
    monkeypatch.setattr(ts.urllib.request, "urlopen", lambda *a, **k: _Resp(DETAIL_OK))
    html, final = ts.fetch_detail("https://web.pcc.gov.tw/x")
    assert html == DETAIL_OK and final.endswith("pkPmsMain=X")


# ══════════════════ C．資料庫：偵測就停、當天不重試、隔天只試一次 ══════════════════

def _seed_tenders(n_watch_kw="工程"):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tender_watches (name, keywords, enabled) VALUES (?,?,1)", ("工程", n_watch_kw))
        items, _, _ = ts.parse_list(CUR)
        ids, _hits = ts._store(conn, items)
        conn.commit()
        return ids
    finally:
        conn.close()


def _locations():
    import db
    conn = db.get_db()
    try:
        return [r["location"] for r in conn.execute("SELECT location FROM tenders ORDER BY id").fetchall()]
    finally:
        conn.close()


def _detail_calls(monkeypatch, result):
    calls = []

    def fake(url):
        calls.append(url)
        return result
    monkeypatch.setattr(ts, "fetch_detail", fake)
    return calls


def test_captcha_stops_the_detail_loop_records_state_and_keeps_every_tender(client, monkeypatch):
    _day(monkeypatch, "2026-10-05")
    ids = _seed_tenders()
    assert len(ids) == 3
    calls = _detail_calls(monkeypatch, (None, ts.CAPTCHA_ERROR))
    import db
    conn = db.get_db()
    try:
        ts._log_fetch(conn, 1, 0, "", suspected=0)                    # 有一筆抓取紀錄可以被標註
        ts._fetch_details(conn, ids)
        conn.commit()
        st = ts._load_scan_state(conn)
        err = conn.execute("SELECT error FROM tender_fetch_log ORDER BY id DESC LIMIT 1").fetchone()["error"]
    finally:
        conn.close()
    assert len(calls) == 1, "遇到驗證碼就必須停止，不可以對剩下的標案繼續請求：%d" % len(calls)
    assert st["detail"] == "captcha" and st["detail_day"] == "2026-10-05"
    assert err == ts.CAPTCHA_ERROR
    assert _locations() == [None, None, None], "標案照樣留著，地點維持 NULL（未取得）"


def test_after_a_captcha_no_more_detail_requests_the_same_day_but_one_try_the_next_day(client, monkeypatch):
    _day(monkeypatch, "2026-10-05")
    ids = _seed_tenders()
    calls = _detail_calls(monkeypatch, (None, ts.CAPTCHA_ERROR))
    import db
    for day, expect_total in (("2026-10-05", 1), ("2026-10-05", 1), ("2026-10-06", 2)):
        _day(monkeypatch, day)
        conn = db.get_db()
        try:
            ts._log_fetch(conn, 1, 0, "", suspected=0)
            ts._fetch_details(conn, ids)
            conn.commit()
        finally:
            conn.close()
        assert len(calls) == expect_total, (day, len(calls))


def test_a_successful_detail_fetch_after_the_block_marks_the_detail_state_ok(client, monkeypatch):
    _day(monkeypatch, "2026-10-05")
    ids = _seed_tenders()
    import db
    conn = db.get_db()
    try:
        ts._save_scan_state(conn, detail="captcha", detail_at="x", detail_day="2026-10-04")
        conn.commit()
    finally:
        conn.close()
    _detail_calls(monkeypatch, (DETAIL_OK, "https://web.pcc.gov.tw/tps/QueryTender/query/searchTenderDetail?pkPmsMain=A"))
    conn = db.get_db()
    try:
        ts._fetch_details(conn, ids[:1])
        conn.commit()
        assert ts._load_scan_state(conn)["detail"] == "ok"
    finally:
        conn.close()


# ══════════════════ D．run_scan 的狀態 ══════════════════

def test_run_scan_on_an_empty_day_reports_empty_day_and_never_suspects(client, monkeypatch):
    _day(monkeypatch, "2026-10-03")
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    monkeypatch.setattr(ts, "fetch_raw", lambda params=None: (EMPTY, None))
    r = ts.run_scan()
    assert r["recognised"] is True and r["parsed"] == 0 and r["dropped"] == 0
    assert r["suspect_redesign"] is False and r["list_state"] == "empty_day" and r["detail_blocked"] is False
    import db
    conn = db.get_db()
    try:
        assert ts._load_scan_state(conn)["list"] == "empty_day"
        assert conn.execute("SELECT suspected FROM tender_fetch_log ORDER BY id DESC LIMIT 1").fetchone()["suspected"] == 0
    finally:
        conn.close()


def test_run_scan_with_a_captcha_on_details_reports_detail_blocked_once(client, monkeypatch):
    _day(monkeypatch, "2026-10-05")
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO tender_watches (name, keywords, enabled) VALUES ('工程','工程',1)")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(ts, "fetch_raw", lambda params=None: (CUR, None))
    calls = _detail_calls(monkeypatch, (None, ts.CAPTCHA_ERROR))
    r1 = ts.run_scan()
    assert r1["list_state"] == "ok" and r1["detail_blocked"] is True and r1["new_tenders"] == 3
    assert len(calls) == 1
    conn = db.get_db()                      # 同一天再掃一次（換時段）：不再請求詳細頁，也不再宣告「新被擋」
    try:
        conn.execute("DELETE FROM tender_fetch_log")
        conn.commit()
    finally:
        conn.close()
    r2 = ts.run_scan()
    assert r2["detail_blocked"] is False and len(calls) == 1


def test_a_garbled_list_still_reports_format_changed(client, monkeypatch):
    _day(monkeypatch, "2026-10-05")
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    page = _table_with([_good_row()] + [_garble(_good_row())] * 9)
    monkeypatch.setattr(ts, "fetch_raw", lambda params=None: (page, None))
    r = ts.run_scan()
    assert r["suspect_redesign"] is True and r["list_state"] == "format_changed"


# ══════════════════ E．告警：不寄信日延後、一天一封 ══════════════════

@pytest.fixture()
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr(tender_notify, "notify_tender_source_changed", lambda p, d: sent.append(("source_changed", p, d)))
    monkeypatch.setattr(tender_notify, "notify_tender_fetch_failed", lambda e, since="": sent.append(("fetch_failed", e)))
    monkeypatch.setattr(tender_notify, "notify_tender_detail_blocked", lambda: sent.append(("detail_blocked",)))
    return sent


PREV_OK = {"failed": False, "suspected": False, "detail_blocked": False}
SUSPECT = {"recognised": True, "error": None, "parsed": 1, "dropped": 9, "suspect_redesign": True, "detail_blocked": False}


def test_a_source_changed_alert_on_a_weekday_mails_once_and_not_again_the_same_day(client, mails, monkeypatch):
    _day(monkeypatch, "2026-10-05")                                      # 週一
    ts._notify_health(SUSPECT, PREV_OK)
    assert mails == [("source_changed", 1, 9)]
    ts._notify_health(SUSPECT, {**PREV_OK, "suspected": True})           # 持續異常：邊緣觸發不再寄
    ts._notify_health(SUSPECT, PREV_OK)                                  # 狀態抖動後再度進入異常：一天一封擋下
    assert len(mails) == 1


def test_on_a_saturday_the_alert_is_not_mailed_but_remembered_and_mailed_on_monday_if_still_true(client, mails, monkeypatch):
    _day(monkeypatch, "2026-10-03")                                      # 週六
    ts._notify_health(SUSPECT, PREV_OK)
    assert mails == [] and "tender_source_changed" in ts._pending_alerts()
    _day(monkeypatch, "2026-10-04")                                      # 週日：條件持續、仍不寄
    ts._notify_health(SUSPECT, {**PREV_OK, "suspected": True})
    assert mails == []
    _day(monkeypatch, "2026-10-05")                                      # 週一：條件仍成立 ⇒ 補寄一封
    ts._notify_health(SUSPECT, {**PREV_OK, "suspected": True})
    assert mails == [("source_changed", 1, 9)] and ts._pending_alerts() == set()
    ts._notify_health(SUSPECT, {**PREV_OK, "suspected": True})
    assert len(mails) == 1


def test_an_alert_that_resolved_over_the_weekend_is_not_mailed_on_monday(client, mails, monkeypatch):
    _day(monkeypatch, "2026-10-03")
    ts._notify_health(SUSPECT, PREV_OK)
    assert "tender_source_changed" in ts._pending_alerts()
    _day(monkeypatch, "2026-10-05")
    healthy = {"recognised": True, "error": None, "parsed": 20, "dropped": 0, "suspect_redesign": False, "detail_blocked": False}
    ts._notify_health(healthy, {**PREV_OK, "suspected": True})
    assert mails == [] and ts._pending_alerts() == set()


def test_national_holiday_is_also_a_no_mail_day_for_alerts(client, mails, monkeypatch):
    _day(monkeypatch, "2026-10-09")                                      # 國慶補假（週五）
    ts._notify_health({"recognised": None, "error": "URLError: boom"}, PREV_OK)
    assert mails == [] and "tender_fetch_failed" in ts._pending_alerts()
    _day(monkeypatch, "2026-10-12")
    ts._notify_health({"recognised": None, "error": "URLError: boom"}, {**PREV_OK, "failed": True})
    assert mails == [("fetch_failed", "URLError: boom")]


def test_detail_blocked_alert_is_deferred_over_the_weekend_then_mailed_once(client, mails, monkeypatch):
    import db
    _day(monkeypatch, "2026-10-03")
    conn = db.get_db()
    try:
        ts._save_scan_state(conn, detail="captcha", detail_at="t", detail_day="2026-10-03")
        conn.commit()
    finally:
        conn.close()
    blocked = {"recognised": True, "error": None, "parsed": 3, "dropped": 0, "suspect_redesign": False, "detail_blocked": True}
    ts._notify_health(blocked, PREV_OK)
    assert mails == [] and "tender_detail_blocked" in ts._pending_alerts()
    _day(monkeypatch, "2026-10-05")
    ts._notify_health({**blocked, "detail_blocked": False}, {**PREV_OK, "detail_blocked": True})   # 條件仍在（狀態＝captcha）
    assert mails == [("detail_blocked",)]
    ts._notify_health({**blocked, "detail_blocked": False}, {**PREV_OK, "detail_blocked": True})
    assert len(mails) == 1


# ══════════════════ F．彙總信：不寄信日不寄，下一個上班日補上 ══════════════════

def _users_and_watch():
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, email, modules, active, created_at, "
            "must_change_password, notification_muted) VALUES (?,?,?,?,?,?,1,?,0,?)",
            ("tender_boss", "x", "收件人", "superadmin", "boss@example.invalid", "[]", "2026-01-01T00:00:00", "[]"))
        conn.execute("INSERT INTO tender_watches (name, keywords, enabled) VALUES ('工程','工程',1)")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def found_mails(monkeypatch):
    sent = []
    monkeypatch.setattr(tender_notify, "notify_tender_found",
                        lambda tenders, watch_names, **kw: sent.append([t["case_no"] for t in tenders]))
    monkeypatch.setattr(ts, "_in_quiet_period", lambda: False)
    monkeypatch.setattr(ts, "_fetch_details", lambda conn, ids: 0)
    return sent


def test_tenders_found_on_a_saturday_are_not_mailed_then_mailed_on_monday_never_lost(client, monkeypatch, found_mails):
    _users_and_watch()
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    monkeypatch.setattr(ts, "fetch_raw", lambda params=None: (CUR, None))
    _day(monkeypatch, "2026-10-03", hour=18)                             # 週六 18:00＝寄信時段
    ts.run_scheduled_scan()
    assert found_mails == [], "週六不可寄信"
    assert len(ts._load_unnotified_hits()[0]) == 3, "週六掃到的標案命中必須留著（未通知）"
    assert ts._get_setting(ts.NOTIFY_MARK_SETTING) in (None, ""), "沒寄就不能標記這個時段已寄"
    # 週日：掃描照常（空頁），仍不寄
    monkeypatch.setattr(ts, "fetch_raw", lambda params=None: (EMPTY, None))
    _day(monkeypatch, "2026-10-04", hour=18)
    ts.run_scheduled_scan()
    assert found_mails == []
    # 週一 18:00：沒有新標案，但「未通知的命中」是判準 ⇒ 週六那三筆在這裡寄出，且標記已通知
    _day(monkeypatch, "2026-10-05", hour=18)
    ts.run_scheduled_scan()
    assert len(found_mails) == 1 and len(found_mails[0]) == 3
    assert ts._load_unnotified_hits()[0] == []


def test_a_weekday_still_mails_normally(client, monkeypatch, found_mails):
    _users_and_watch()
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    monkeypatch.setattr(ts, "fetch_raw", lambda params=None: (CUR, None))
    _day(monkeypatch, "2026-10-05", hour=18)
    ts.run_scheduled_scan()
    assert len(found_mails) == 1 and len(found_mails[0]) == 3


def test_scans_still_run_on_no_mail_days(client, monkeypatch, found_mails):
    """決策：週末照常掃描、只延後寄信（列表是「當日」查詢，跳過掃描＝日曆表若有錯就永久漏掉）。"""
    _users_and_watch()
    monkeypatch.setattr(ts, "TENDER_RADAR_ENABLED", True)
    seen = []
    monkeypatch.setattr(ts, "fetch_raw", lambda params=None: (seen.append(1), (EMPTY, None))[1])
    _day(monkeypatch, "2026-10-03", hour=9)
    r = ts.run_scheduled_scan()
    assert seen == [1] and r["fetched"] is True
