# -*- coding: utf-8 -*-
"""前端的「今天」要用本地日期（使用者 2026-10-01：報價單 MQ-202610-002 在 10/01 01:03 建立，報價日期卻是 2026-09-30）。

成因：`new Date().toISOString().slice(0, 10)` 是 UTC 日期；台灣 UTC+8，每天 00:00–08:00 會得到前一天。
修法：共用 `static/motrix-date.js`（`MotrixDate.today()` 等，本地時區）；30 幾個檔案改走它。

驗（畫面終點，瀏覽器時區 Asia/Taipei、假時鐘固定在台北 2026-10-01 00:30 ＝ UTC 2026-09-30 16:30）：
① `MotrixDate` 各函式（today／ymd／addDays 跨月跨年／monthStart／nowIso／parse／stamp）；
② 新增報價單的預設報價日期 ＝ 2026-10-01（使用者回報的那個）；
③ 另外 6 個頁面／表單的「今天」預設：每日任務日報日期、工作日誌檢視日期、案件管理 today、出納 T100 起迄日、
   營運報表的當月、（有裝的話）住宿紀錄報價日；
④ 反向控制（突變）：把報價單頁的 `MotrixDate.today()` 換回舊寫法 ⇒ 日期變 2026-09-30，斷言必須紅；
⑤ 截圖：D:\\開發測試檔\\shots\\wip-w3-local-date\\（預設寫暫存目錄；設 MOTRIX_SHOTS_DIR 才寫共用資料夾）。
"""
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

TAIPEI = timezone(timedelta(hours=8))
FIXED = datetime(2026, 10, 1, 0, 30, tzinfo=TAIPEI)        # ＝ UTC 2026-09-30 16:30
SHOTS = Path(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "aet27-shots")) / "wip-w3-local-date"

#: 找第一個有這個鍵的 Alpine 元件資料（各頁的根元件不一定是第一個 [x-data]）
FIND = """(key) => { for (const el of document.querySelectorAll('[x-data]')) {
    try { const d = Alpine.$data(el); if (d && key in d) return d[key] } catch (e) {} } return undefined }"""
FIND_Q = """(path) => { for (const el of document.querySelectorAll('[x-data]')) {
    try { let d = Alpine.$data(el); if (!d) continue; let ok = true;
      for (const k of path.split('.')) { if (d && k in d) d = d[k]; else { ok = false; break } }
      if (ok) return d } catch (e) {} } return undefined }"""


def _shot(page, name):
    try:
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / (name + ".png")), full_page=False)
    except Exception:                                            # noqa: BLE001 — 截圖失敗（含 BK19 護欄）不影響判定
        pass


def _page(new_page, login_as, user, path, base):
    page = new_page(timezone_id="Asia/Taipei")
    page.clock.set_fixed_time(FIXED)
    login_as(page, user)
    page.goto(base + path)
    return page


@pytest.mark.e2e
def test_motrix_date_helper_functions_use_the_local_calendar(live_server, make_user, new_page, login_as):
    u = make_user(username="ld_h1", role="superadmin")
    page = _page(new_page, login_as, u, "/pages/quotation-form.html", live_server)
    page.wait_for_function("() => window.MotrixDate")
    r = page.evaluate("""() => ({
      utc: new Date().toISOString().slice(0, 10), today: MotrixDate.today(), month: MotrixDate.thisMonth(),
      start: MotrixDate.monthStart(), now: MotrixDate.nowIso(), stamp: MotrixDate.stamp(),
      add1: MotrixDate.addDays('2026-10-31', 1), add2: MotrixDate.addDays('2026-12-31', 1), add3: MotrixDate.addDays('2026-03-01', -1),
      add4: MotrixDate.addDays('2024-03-01', -1), ymd: MotrixDate.ymd(new Date(2026, 0, 5)), parse: MotrixDate.parse('2026-10-01').getDate(),
      bad: isNaN(MotrixDate.parse('x').getTime()), midnight: MotrixDate.ymd(new Date(2026, 9, 1, 0, 0, 0)) })""")
    assert r["utc"] == "2026-09-30", "前提：UTC 日期還是前一天（舊寫法會錯）"
    assert (r["today"], r["month"], r["start"], r["stamp"]) == ("2026-10-01", "2026-10", "2026-10-01", "20261001"), r
    assert r["now"] == "2026-10-01T00:30:00", r
    assert (r["add1"], r["add2"], r["add3"], r["add4"]) == ("2026-11-01", "2027-01-01", "2026-02-28", "2024-02-29"), r
    assert (r["ymd"], r["parse"], r["bad"], r["midnight"]) == ("2026-01-05", 1, True, "2026-10-01"), r


@pytest.mark.e2e
def test_new_quotation_default_date_is_the_local_today_at_half_past_midnight(live_server, make_user, new_page, login_as):
    u = make_user(username="ld_q1", role="superadmin")
    page = _page(new_page, login_as, u, "/pages/quotation-form.html", live_server)
    page.wait_for_function(FIND_Q, arg="q.quoteDate", timeout=20000)
    assert page.evaluate(FIND_Q, "q.quoteDate") == "2026-10-01"
    _shot(page, "quotation_form_default_date")


@pytest.mark.e2e
def test_reverse_control_the_old_expression_gives_yesterday(live_server, make_user, new_page, login_as):
    """突變：把報價單頁的 `MotrixDate.today()` 換回舊寫法，同一個斷言必須變紅（證明上面那題不是恆真）。"""
    u = make_user(username="ld_r1", role="superadmin")
    page = new_page(timezone_id="Asia/Taipei")
    page.clock.set_fixed_time(FIXED)
    login_as(page, u)

    def mutate(route):
        resp = route.fetch()
        body = resp.text().replace("MotrixDate.today()", "new Date().toISOString().slice(0,10)")
        route.fulfill(response=resp, body=body)
    page.route("**/pages/quotation-form.html", mutate)
    page.goto(live_server + "/pages/quotation-form.html")
    page.wait_for_function(FIND_Q, arg="q.quoteDate", timeout=20000)
    assert page.evaluate(FIND_Q, "q.quoteDate") == "2026-09-30"


@pytest.mark.e2e
@pytest.mark.parametrize("path,keys", [
    ("/pages/daily-tasks.html", [("reportDate", "2026-10-01")]),
    ("/pages/work-log.html", [("viewDate", "2026-10-01")]),
    ("/pages/case-management.html", [("today", "2026-10-01")]),
    ("/pages/cashier.html", [("t100Start", "2026-10-01"), ("t100End", "2026-10-01")]),
    ("/pages/reports.html", [("expensesMonth", "2026-10"), ("receivablesMonth", "2026-10")]),
    ("/pages/legal-params.html", [("today", "2026-10-01")]),
])
def test_other_pages_default_to_the_local_today(live_server, make_user, new_page, login_as, path, keys):
    u = make_user(username="ld_%s" % abs(hash(path)), role="superadmin")
    page = _page(new_page, login_as, u, path, live_server)
    for key, want in keys:
        page.wait_for_function(FIND, arg=key, timeout=20000)
        assert page.evaluate(FIND, key) == want, (path, key)
    _shot(page, "page_" + path.split("/")[-1].replace(".html", ""))
