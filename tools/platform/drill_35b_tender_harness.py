# -*- coding: utf-8 -*-
"""第 35b 班演練：標案雷達的「程式層」檢查（在安裝目錄的程式上跑；全部用模組自己的 fixtures 與替身）。

用法（由 drill_train35b.py 呼叫；cwd＝<安裝>/backend）：
  python drill_35b_tender_harness.py unit            → 在資料庫副本上跑，印一行 JSON（逐項 ok／detail）
  python drill_35b_tender_harness.py state <list> <detail>   → 把掃描狀態寫進**安裝的資料庫**（給頁面狀態列檢查用；list／detail 可為 '-'）

紅線：不連網（urllib.request.urlopen 一律換成替身；smtplib 一律換成會丟例外的替身）；寄信函式換成記錄器；
`unit` 模式只動資料庫副本（臨時檔，結束即刪）。
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, os.getcwd())
os.environ.setdefault("PYTHONUTF8", "1")
os.environ["MOTRIX_TENDER_RADAR"] = "0"              # 演練：雷達開關預設關；需要 run_scan 時用 TENDER_RADAR_ENABLED 替身

import smtplib  # noqa: E402


class _NoSmtp:
    def __init__(self, *a, **k):
        raise AssertionError("演練不可以真的寄信（smtplib 被呼叫了）")


smtplib.SMTP = _NoSmtp
smtplib.SMTP_SSL = _NoSmtp

import db  # noqa: E402
import modules.tender_radar.source as ts  # noqa: E402
from modules.tender_radar import calendar_tw  # noqa: E402
from modules.tender_radar import notify as tender_notify  # noqa: E402

FX = Path(os.environ.get("DRILL_FIXTURES") or (Path(os.getcwd()) / "modules" / "tender_radar" / "tests" / "fixtures"))


def _fx(name):
    return (FX / name).read_text(encoding="utf-8")


def _day(iso, hour=9):
    d = date.fromisoformat(iso)
    ts.today = lambda: d
    ts.now_dt = lambda: datetime(d.year, d.month, d.day, hour, 0, 0)
    return d


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


def unit():
    res = {}
    EMPTY, CUR, CAPTCHA, DETAIL_OK = (_fx("tender_list_empty_20261003.html"), _fx("tender_list_20261003_current_format.html"),
                                      _fx("tender_detail_captcha_20261003.html"), _fx("tender_detail_20260921.html"))
    tmp = tempfile.mkdtemp(prefix="d5-35b-tender-")
    try:
        src_db = db.DB_PATH
        copy = os.path.join(tmp, "copy.db")
        shutil.copy(src_db, copy)
        for ext in ("-wal", "-shm"):
            if os.path.exists(src_db + ext):
                shutil.copy(src_db + ext, copy + ext)
        db.DB_PATH = copy
        net = []

        def no_net(*a, **k):
            net.append(a)
            raise AssertionError("演練不可以連網（urlopen 被呼叫了）")
        ts.urllib.request.urlopen = no_net
        ts.TENDER_RADAR_ENABLED = True
        mails = []
        tender_notify.notify_tender_source_changed = lambda p, d: mails.append(("source_changed", p, d))
        tender_notify.notify_tender_fetch_failed = lambda e, since="": mails.append(("fetch_failed", e))
        tender_notify.notify_tender_detail_blocked = lambda: mails.append(("detail_blocked",))

        # ① 空結果頁：被認得、不是 suspected、沒有 source_changed 信
        items, dropped, recognised = ts.parse_list(EMPTY)
        _day("2026-10-05")                                     # 週一
        ts.fetch_raw = lambda params=None: (EMPTY, None)
        prev = {"failed": False, "suspected": False, "detail_blocked": False}
        r = ts.run_scan()
        ts._notify_health(r, prev)
        conn = db.get_db()
        try:
            susp = conn.execute("SELECT suspected FROM tender_fetch_log ORDER BY id DESC LIMIT 1").fetchone()["suspected"]
            state = ts._load_scan_state(conn)
        finally:
            conn.close()
        res["t1_empty_page_recognised_not_suspected_no_mail"] = (
            (items, dropped, recognised) == ([], 0, True) and ts.is_empty_result(EMPTY) is True and r["recognised"] is True and r["suspect_redesign"] is False
            and r["list_state"] == "empty_day" and susp == 0 and state.get("list") == "empty_day" and not [m for m in mails if m[0] == "source_changed"],
            {"parse": [len(items), dropped, recognised], "run_scan": {k: r.get(k) for k in ("recognised", "parsed", "dropped", "suspect_redesign", "list_state")},
             "fetch_log_suspected": susp, "mails": list(mails)})

        # ② 正對照：真的改版（十列壞九列）仍判 suspected、會寄 source_changed（證明上面的「沒信」不是替身壞掉）
        rows = ts._TR_RE.findall(ts._find_result_table(CUR))
        good = rows[1]
        cells = ts._TD_RE.findall(good)
        garbled = good.replace(cells[1], "<td>115/10/06</td>")
        head = CUR[:CUR.index("<tbody") + len("<tbody>")]
        bad_page = head + good + garbled * 9 + "</tbody></table>"
        mails.clear()
        _day("2026-10-06")                                     # 週二（換一天，避開一天一封的限制）
        ts.fetch_raw = lambda params=None: (bad_page, None)
        r2 = ts.run_scan()
        ts._notify_health(r2, prev)
        res["t2_positive_control_garbled_list_still_suspected_and_mails"] = (
            r2["suspect_redesign"] is True and r2["list_state"] == "format_changed" and mails == [("source_changed", r2["parsed"], r2["dropped"])],
            {"suspect": r2["suspect_redesign"], "list_state": r2["list_state"], "parsed": r2["parsed"], "dropped": r2["dropped"], "mails": list(mails)})

        # ③ 不寄信日：週六、週日、國定假日（平日）都不寄、記待寄；下一個上班日條件仍成立才補寄一封
        suspect = {"recognised": True, "error": None, "parsed": 1, "dropped": 9, "suspect_redesign": True, "detail_blocked": False}
        holiday = None
        d = date(2026, 10, 12)
        while d <= date(2027, 1, 31):
            nm, why = calendar_tw.no_mail_day(d)
            if nm and d.weekday() < 5:
                holiday = (d, why)
                break
            d = date.fromordinal(d.toordinal() + 1)
        out3 = {}
        for label, iso in (("saturday", "2026-10-17"), ("sunday", "2026-10-18")):
            conn = db.get_db()
            try:
                conn.execute("DELETE FROM system_settings WHERE key LIKE '%alert%' OR key LIKE '%pending%'")
                conn.commit()
            finally:
                conn.close()
            mails.clear()
            _day(iso)
            nm, why = calendar_tw.no_mail_day(date.fromisoformat(iso))
            ts._notify_health(suspect, prev)
            out3[label] = {"no_mail_day": nm, "why": why, "mails": list(mails), "pending": sorted(ts._pending_alerts())}
        ok3 = all(v["no_mail_day"] and v["mails"] == [] and "tender_source_changed" in v["pending"] for v in out3.values())
        res["t3_saturday_and_sunday_do_not_mail"] = (ok3, out3)
        if holiday:
            conn = db.get_db()
            try:
                conn.execute("DELETE FROM system_settings WHERE key LIKE '%alert%' OR key LIKE '%pending%'")
                conn.commit()
            finally:
                conn.close()
            mails.clear()
            _day(holiday[0].isoformat())
            ts._notify_health(suspect, prev)
            held = {"date": holiday[0].isoformat(), "why": holiday[1], "mails": list(mails), "pending": sorted(ts._pending_alerts())}
            nxt = calendar_tw.next_mail_day(holiday[0])
            _day(nxt.isoformat())
            ts._notify_health(suspect, {**prev, "suspected": True})      # 條件仍成立 ⇒ 補寄一封
            held["next_mail_day"] = nxt.isoformat()
            held["mails_after_next_mail_day"] = list(mails)
            held["pending_after"] = sorted(ts._pending_alerts())
            res["t3b_national_holiday_weekday_holds_then_mails_next_working_day"] = (
                held["mails"] == [] and "tender_source_changed" in held["pending"] and held["mails_after_next_mail_day"] == [("source_changed", 1, 9)]
                and held["pending_after"] == [], held)
        else:
            res["t3b_national_holiday_weekday_holds_then_mails_next_working_day"] = (False, "假日表在 2026-10-12～2027-01-31 找不到平日國定假日")

        # ④ 假日表：檔案在、已載入、涵蓋範圍
        hp = Path(os.getcwd()) / "modules" / "tender_radar" / "holidays_tw.json"
        cov = calendar_tw.coverage()
        res["t4_holidays_table_present_and_loaded"] = (
            hp.is_file() and cov is not None and calendar_tw.covered(date(2026, 10, 5)) and calendar_tw.days_until_expiry(date(2026, 10, 5)) is not None,
            {"file": str(hp), "bytes": hp.stat().st_size if hp.is_file() else None, "coverage": [str(x) for x in cov] if cov else None,
             "days_until_expiry": calendar_tw.days_until_expiry(date(2026, 10, 5))})

        # ⑤ 驗證碼頁：fetch_detail 回 CAPTCHA_ERROR、迴圈只請求一次就停、當天不重試、隔天只試一次
        ts.urllib.request.urlopen = lambda *a, **k: _Resp(CAPTCHA)
        fd = ts.fetch_detail("https://web.pcc.gov.tw/x")
        ts.urllib.request.urlopen = no_net
        _day("2026-10-20")
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM tenders")
            conn.execute("INSERT INTO tender_watches (name, keywords, enabled) VALUES (?,?,1)", ("工程", "工程"))
            items, _, _ = ts.parse_list(CUR)
            ids, _h = ts._store(conn, items)
            conn.commit()
        finally:
            conn.close()
        calls = []

        def fake(url):
            calls.append(url)
            return (None, ts.CAPTCHA_ERROR)
        ts.fetch_detail = fake
        totals = []
        for day in ("2026-10-20", "2026-10-20", "2026-10-21"):
            _day(day)
            conn = db.get_db()
            try:
                ts._log_fetch(conn, 1, 0, "", suspected=0)
                ts._fetch_details(conn, ids)
                conn.commit()
                st = ts._load_scan_state(conn)
                locs = [r["location"] for r in conn.execute("SELECT location FROM tenders ORDER BY id").fetchall()]
            finally:
                conn.close()
            totals.append(len(calls))
        res["t5_captcha_page_stops_the_detail_loop"] = (
            fd == (None, ts.CAPTCHA_ERROR) and len(ids) == 3 and totals == [1, 1, 2] and st.get("detail") == "captcha" and locs == [None, None, None],
            {"fetch_detail_result": [fd[0], fd[1]], "tenders": len(ids), "detail_requests_cumulative_by_day": totals, "state_detail": st.get("detail"), "locations": locs})
        res["t0_no_network_was_attempted"] = (net == [], {"urlopen_calls": len(net)})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return res


def state(list_state, detail_state):
    conn = db.get_db()
    try:
        fields = {"parsed": 0, "dropped": 0}
        if list_state != "-":
            fields["list"] = list_state
        if detail_state != "-":
            fields["detail"] = detail_state
        if list_state == "format_changed":
            fields.update(parsed=1, dropped=9)
        ts._save_scan_state(conn, **fields)
        conn.commit()
    finally:
        conn.close()
    return {"saved": fields}


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    mode = sys.argv[1]
    out = unit() if mode == "unit" else state(sys.argv[2], sys.argv[3])
    print("::JSON::" + json.dumps({k: (list(v) if isinstance(v, tuple) else v) for k, v in out.items()}, ensure_ascii=False, default=str))
