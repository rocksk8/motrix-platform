# -*- coding: utf-8 -*-
"""會計年度、期間、結帳鎖定與稽核軌跡。設計：proposal-gl/03-periods-close.md §2–§4。

狀態：open → closed（可重開）→ locked（只有 superadmin 可解鎖）。期間資料為空 ＝ 全部視為開放（舊部署行為不變）。
鎖定三層：這裡的 `lock_error`（API 友善訊息）、`ledger.engine`（P2）、migration 的 DB 觸發器（縱深防禦）。
所有函式不 commit（由呼叫端／API 決定交易邊界）。
"""
import calendar
import datetime as _dt
import hashlib
import json
import sqlite3

OPEN, CLOSED, LOCKED = "open", "closed", "locked"

#: 會被結帳前檢查擋下的「未過帳」狀態（作廢的不算）
UNPOSTED_STATUSES = ("草稿", "待審核", "簽核中", "已核准")


class PeriodError(ValueError):
    """給使用者看的中文訊息。"""


def _now():
    return _dt.datetime.now().isoformat(timespec="seconds")


def get_setting(conn, key, default=""):
    row = conn.execute("SELECT value FROM gl_settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn, key, value):
    conn.execute("INSERT INTO gl_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, str(value)))


def fiscal_start_month(conn):
    try:
        m = int(get_setting(conn, "fiscal_year_start_month", "1"))
    except ValueError:
        m = 1
    return m if 1 <= m <= 12 else 1


def _month_range(year, month):
    last = calendar.monthrange(year, month)[1]
    return "%04d-%02d-01" % (year, month), "%04d-%02d-%02d" % (year, month, last)


def year_bounds(year, start_month=1):
    """會計年度 `year`（起始年）的起訖日。"""
    s = "%04d-%02d-01" % (year, start_month)
    end_y, end_m = (year, start_month - 1) if start_month > 1 else (year, 12)
    if start_month > 1:
        end_y = year + 1
    return s, _month_range(end_y, end_m)[1]


def create_year(conn, year, user=""):
    """建立會計年度與 12 個期間（可建到任意過去年度，補登用）。已存在 ⇒ PeriodError。"""
    if not 1911 <= int(year) <= 2200:
        raise PeriodError("年度不合理：%s" % year)
    year = int(year)
    if conn.execute("SELECT 1 FROM gl_fiscal_years WHERE year=?", (year,)).fetchone():
        raise PeriodError("%d 年度已經建立。" % year)
    sm = fiscal_start_month(conn)
    y_start, y_end = year_bounds(year, sm)
    now = _now()
    conn.execute("INSERT INTO gl_fiscal_years(year,start_date,end_date,status,opening_mode,created_by,created_at)"
                 " VALUES(?,?,?, 'open','carry',?,?)", (year, y_start, y_end, user, now))
    for i in range(12):
        m0 = sm - 1 + i
        s, e = _month_range(year + m0 // 12, m0 % 12 + 1)
        conn.execute("INSERT INTO gl_periods(year,period_no,start_date,end_date) VALUES(?,?,?,?)", (year, i + 1, s, e))
    log(conn, "create", user, year=year, detail={"start": y_start, "end": y_end})
    return year


def log(conn, action, actor, period_id=None, year=None, reason="", tb_before="", tb_after="", detail=None):
    conn.execute(
        "INSERT INTO gl_period_log(period_id,year,action,reason,actor,at,tb_hash_before,tb_hash_after,detail_json)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (period_id, year, action, reason or "", actor or "", _now(), tb_before, tb_after,
         json.dumps(detail or {}, ensure_ascii=False)))


def period_of(conn, date):
    """日期所在期間（dict）或 None。"""
    row = conn.execute("SELECT * FROM gl_periods WHERE ? BETWEEN start_date AND end_date", ((date or "")[:10],)).fetchone()
    return dict(row) if row else None


def lock_error(conn, date):
    """日期落在非開放期間 ⇒ 回給使用者看的訊息；開放或沒有期間資料 ⇒ None。"""
    try:
        p = period_of(conn, date)
    except sqlite3.OperationalError:           # 模組 migration 尚未跑（gl_periods 不存在）＝沒有期間資料＝開放
        return None
    if p and p["status"] != OPEN:
        return "%s 屬於已%s的會計期間（%d 年度第 %d 期，%s～%s）。" % (
            (date or "")[:10], "鎖定" if p["status"] == LOCKED else "結帳",
            p["year"], p["period_no"], p["start_date"], p["end_date"])
    return None


def list_years(conn):
    out = []
    for y in conn.execute("SELECT * FROM gl_fiscal_years ORDER BY year DESC"):
        d = dict(y)
        d["periods"] = [dict(p) for p in conn.execute(
            "SELECT * FROM gl_periods WHERE year=? ORDER BY period_no", (d["year"],))]
        out.append(d)
    return out


def tb_hash(conn, through_date):
    """截至 through_date（含）已過帳、未作廢傳票的『科目→借貸合計』雜湊，結帳當下留證，重開後重結可比對。"""
    rows = conn.execute(
        "SELECT l.account_code, COALESCE(SUM(l.debit),0), COALESCE(SUM(l.credit),0) FROM voucher_lines l"
        " JOIN vouchers_all v ON v.id=l.voucher_id WHERE v.status='已過帳' AND v.voided_at=''"
        " AND substr(v.voucher_date,1,10) <= ? GROUP BY l.account_code ORDER BY l.account_code", (through_date,)).fetchall()
    return hashlib.sha256(json.dumps([list(r) for r in rows]).encode("utf-8")).hexdigest()


def checklist(conn, period):
    """期末檢查（P1 子集，03 §4）：回 `{"blockers": [...], "warnings": [...], "counts": {...}}`。
    blockers 不解決不可結帳；warnings 可帶理由結帳。"""
    s, e = period["start_date"], period["end_date"]
    unposted = conn.execute(
        "SELECT status, COUNT(*) FROM vouchers_all WHERE voided_at='' AND status IN (%s)"
        " AND substr(voucher_date,1,10) BETWEEN ? AND ? GROUP BY status" % ",".join("?" * len(UNPOSTED_STATUSES)),
        UNPOSTED_STATUSES + (s, e)).fetchall()
    counts = {r[0]: r[1] for r in unposted}
    bal = conn.execute(
        "SELECT COALESCE(SUM(l.debit),0), COALESCE(SUM(l.credit),0) FROM voucher_lines l JOIN vouchers_all v ON v.id=l.voucher_id"
        " WHERE v.status='已過帳' AND v.voided_at='' AND substr(v.voucher_date,1,10) <= ?", (e,)).fetchone()
    blockers, warnings = [], []
    if bal[0] != bal[1]:
        blockers.append("試算表借貸不平衡（借 %d、貸 %d，差 %d）：資料損壞，不可結帳。" % (bal[0], bal[1], bal[0] - bal[1]))
    n_unposted = sum(counts.values())
    if n_unposted:
        warnings.append("本期間還有 %d 張未過帳傳票（%s）；結帳後它們無法過帳到本期間。" % (
            n_unposted, "、".join("%s %d" % (k, v) for k, v in counts.items())))
    earlier = conn.execute(
        "SELECT COUNT(*) FROM gl_periods WHERE start_date < ? AND status='open'", (s,)).fetchone()[0]
    if earlier:
        warnings.append("更早的期間還有 %d 期未結帳。" % earlier)
    return {"blockers": blockers, "warnings": warnings, "counts": counts}


def close_period(conn, period_id, user, accept_warnings=False, reason=""):
    p = _get(conn, period_id)
    if p["status"] != OPEN:
        raise PeriodError("這個期間現在是「%s」，只有開放的期間可以結帳。" % _label(p["status"]))
    chk = checklist(conn, p)
    if chk["blockers"]:
        raise PeriodError(chk["blockers"][0])
    if chk["warnings"] and not accept_warnings:
        raise PeriodError("結帳前檢查有提醒，需確認後才能結帳：" + " ".join(chk["warnings"]))
    h = tb_hash(conn, p["end_date"])
    conn.execute("UPDATE gl_periods SET status='closed', closed_by=?, closed_at=?, tb_hash=?, stale=0 WHERE id=?",
                 (user, _now(), h, period_id))
    log(conn, "close", user, period_id, p["year"], reason, p["tb_hash"], h, {"warnings": chk["warnings"]})
    return h


def reopen_period(conn, period_id, user, reason):
    p = _get(conn, period_id)
    if not (reason or "").strip():
        raise PeriodError("重開期間必須填寫理由。")
    if p["status"] == LOCKED:
        raise PeriodError("這個期間已鎖定，請先由 superadmin 解鎖。")
    if p["status"] != CLOSED:
        raise PeriodError("這個期間目前是開放的，不需要重開。")
    conn.execute("UPDATE gl_periods SET status='open' WHERE id=?", (period_id,))
    # 後面已結帳的期間因此過期（03 §5）：需要重新結帳
    later = conn.execute("UPDATE gl_periods SET stale=1 WHERE start_date > ? AND status IN ('closed','locked')",
                         (p["end_date"],)).rowcount
    log(conn, "reopen", user, period_id, p["year"], reason, p["tb_hash"], "", {"stale_later_periods": later})
    return later


def lock_period(conn, period_id, user):
    p = _get(conn, period_id)
    if p["status"] != CLOSED:
        raise PeriodError("只有已結帳的期間可以鎖定（現在是「%s」）。" % _label(p["status"]))
    conn.execute("UPDATE gl_periods SET status='locked' WHERE id=?", (period_id,))
    log(conn, "lock", user, period_id, p["year"])


def unlock_period(conn, period_id, user, reason):
    p = _get(conn, period_id)
    if not (reason or "").strip():
        raise PeriodError("解鎖必須填寫理由。")
    if p["status"] != LOCKED:
        raise PeriodError("這個期間不是鎖定狀態。")
    conn.execute("UPDATE gl_periods SET status='closed' WHERE id=?", (period_id,))
    log(conn, "unlock", user, period_id, p["year"], reason)


def _label(status):
    return {"open": "開放", "closed": "已結帳", "locked": "已鎖定"}.get(status, status)


def _get(conn, period_id):
    row = conn.execute("SELECT * FROM gl_periods WHERE id=?", (period_id,)).fetchone()
    if row is None:
        raise PeriodError("找不到這個期間。")
    return dict(row)


def read_log(conn, year=None, limit=200):
    q, args = "SELECT * FROM gl_period_log", []
    if year:
        q += " WHERE year=?"
        args.append(year)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) for r in conn.execute(q, args)]
