# -*- coding: utf-8 -*-
"""年度結轉與決算（B5）。設計：proposal-gl/03-periods-close.md §5。

流程（會計）：①1～11 期逐期結帳 ②產生結轉傳票（兩張草稿：損益結轉入 3353 本期損益；3353 轉 3351 累積盈虧）→走一般簽核、過帳
（傳票日期＝會計年度末日，所以第 12 期要還開著才過得了帳）③決算：四大表全部對帳通過才可決算，寫凍結快照、關第 12 期、年度標記 closed
④要更正：年度重開（superadmin＋理由）→ 期間全部回 open、結轉傳票作廢（已過帳者以作廢處理，稽核軌跡保留）、後面年度已結帳的期間標 stale。
下一年度的期初不存表：損益科目換年度歸零、資產負債科目累計（reports.bases），結轉傳票已把損益搬進 3351，所以不需要另外「結轉期初」。
所有函式不 commit。
"""
import datetime as _dt
import json

from modules.accounting.ledger import periods as _periods
from modules.accounting.ledger import reports as _reports
from modules.accounting.ledger import roles as _roles
from modules.accounting.ledger import statements as _st

PL_TYPES = _roles.PL_TYPES


class ClosingError(ValueError):
    """給使用者看的中文訊息。"""


def _year(conn, year):
    y = conn.execute("SELECT * FROM gl_fiscal_years WHERE year=?", (int(year),)).fetchone()
    if y is None:
        raise ClosingError("%s 年度尚未建立。" % year)
    return dict(y)


def _pl_nets(conn, start, end, include_closing=False):
    """損益科目在年度內的淨額（貸方為正）：{code: (name, net)}，只列非零。只算已過帳、未作廢。"""
    tb = _reports.trial_balance(conn, start, end, include_closing=include_closing, include_zero=True)
    meta = {r["code"]: r["acct_type"] for r in conn.execute("SELECT code, acct_type FROM gl_account_meta")}
    out = {}
    for r in tb["rows"]:
        if r["code"] and meta.get(r["code"]) in PL_TYPES:
            net = r["closing_credit"] - r["closing_debit"]
            if net:
                out[r["code"]] = (r["name"], net)
    return out


def closing_vouchers(conn, year, statuses=None):
    y = _year(conn, year)
    q = ("SELECT id, voucher_no, voucher_date, status, summary, origin FROM vouchers_all WHERE kind='closing' AND voided_at=''"
         " AND substr(voucher_date,1,10) BETWEEN ? AND ?")
    args = [y["start_date"], y["end_date"]]
    if statuses:
        q += " AND status IN (%s)" % ",".join("?" * len(statuses))
        args += list(statuses)
    return [dict(r) for r in conn.execute(q + " ORDER BY id", args)]


def preview(conn, year):
    """結轉預覽：兩張傳票的分錄、本期淨利、前置條件（未滿足者逐項列出）。不寫入。"""
    y = _year(conn, year)
    _roles.ensure_meta(conn)
    _roles.ensure_default_roles(conn)
    pl3 = _roles.resolve_role(conn, "PL_SUMMARY", on_date=y["end_date"])
    re3 = _roles.resolve_role(conn, "RETAINED", on_date=y["end_date"])
    problems = []
    if not pl3:
        problems.append("尚未設定科目角色 PL_SUMMARY（本期損益，預設 3353）。")
    if not re3:
        problems.append("尚未設定科目角色 RETAINED（累積盈虧，預設 3351）。")
    # 只算尚未被結轉的損益（不含既有結轉傳票）
    nets = _pl_nets(conn, y["start_date"], y["end_date"], include_closing=False)
    ni = sum(n for _nm, n in nets.values())
    lines1 = [{"account_code": c, "name": nm, "debit": n if n > 0 else 0, "credit": -n if n < 0 else 0} for c, (nm, n) in sorted(nets.items())]
    if ni and pl3:
        lines1.append({"account_code": pl3, "name": "本期損益", "debit": -ni if ni < 0 else 0, "credit": ni if ni > 0 else 0})
    lines2 = []
    if ni and pl3 and re3:
        lines2 = [{"account_code": pl3, "name": "本期損益", "debit": ni if ni > 0 else 0, "credit": -ni if ni < 0 else 0},
                  {"account_code": re3, "name": "累積盈虧", "debit": -ni if ni < 0 else 0, "credit": ni if ni > 0 else 0}]
    prereq = []
    open_early = conn.execute("SELECT period_no FROM gl_periods WHERE year=? AND period_no<12 AND status='open' ORDER BY period_no", (y["year"],)).fetchall()
    if open_early:
        prereq.append("第 %s 期還沒結帳。" % "、".join(str(r[0]) for r in open_early))
    p12 = conn.execute("SELECT status FROM gl_periods WHERE year=? AND period_no=12", (y["year"],)).fetchone()
    if p12 is None:
        prereq.append("這個年度沒有第 12 期。")
    elif p12[0] != "open":
        prereq.append("第 12 期已經不是開放狀態，結轉傳票（日期＝年度末日）無法過帳；請先重開第 12 期。")
    if y["status"] != "open":
        prereq.append("年度目前是「%s」，要先重開年度才能重新結轉。" % y["status"])
    existing = closing_vouchers(conn, year)
    return {"year": y["year"], "start": y["start_date"], "end": y["end_date"], "net_income": ni, "problems": problems,
            "prerequisites_unmet": prereq, "pl_accounts": len(nets), "vouchers": [
                {"key": "pl_to_summary", "summary": "%d 年度損益結轉（入本期損益）" % y["year"], "lines": lines1},
                {"key": "summary_to_retained", "summary": "%d 年度本期損益轉累積盈虧" % y["year"], "lines": lines2}],
            "existing": existing}


def generate(conn, year, user, regenerate=False):
    """產生兩張結轉傳票草稿（kind='closing'）。已有未作廢的結轉傳票 ⇒ 預設拒絕；regenerate=True 只作廢「草稿」後重產（已過帳者要走年度重開）。"""
    from modules.accounting.api import vouchers as _v                   # 同模組；晚 import 避免載入循環
    pv = preview(conn, year)
    if pv["problems"]:
        raise ClosingError(pv["problems"][0])
    if pv["prerequisites_unmet"]:
        raise ClosingError(pv["prerequisites_unmet"][0])
    existing = pv["existing"]
    if existing:
        non_draft = [e for e in existing if e["status"] != "草稿"]
        if non_draft:
            raise ClosingError("已經有結轉傳票 %s（%s）；要重做請先「年度重開」。" % (non_draft[0]["voucher_no"], non_draft[0]["status"]))
        if not regenerate:
            raise ClosingError("已經有結轉傳票草稿 %s；要重新產生請選「重新產生」（會作廢舊草稿）。" % existing[0]["voucher_no"])
        now = _dt.datetime.now().isoformat()
        for e in existing:
            conn.execute("UPDATE vouchers_all SET voided_at=?, voided_by=?, void_reason=? WHERE id=? AND status='草稿'",
                         (now, user, "重新產生結轉傳票", e["id"]))
    if not pv["net_income"] and not pv["pl_accounts"]:
        raise ClosingError("這個年度沒有任何損益科目的餘額，不需要結轉。")
    now = _dt.datetime.now().isoformat()
    made = []
    for spec in pv["vouchers"]:
        if not spec["lines"]:
            continue
        lines = [{"account_code": ln["account_code"], "summary": spec["summary"], "debit": ln["debit"], "credit": ln["credit"],
                  "source_type": "", "source_key": ""} for ln in spec["lines"]]
        vid, no = _v.insert_draft_voucher(conn, pv["end"], spec["summary"], lines, user, now, "轉", manual=1)
        conn.execute("UPDATE vouchers_all SET kind='closing', origin='year_closing' WHERE id=?", (vid,))
        made.append({"id": vid, "voucher_no": no, "summary": spec["summary"]})
    _periods.log(conn, "closing_generate", user, year=pv["year"], detail={"vouchers": [m["voucher_no"] for m in made], "net_income": pv["net_income"]})
    return made


def _statements(conn, y, include_drafts=False):
    from modules.accounting.ledger import cashflow as _cf
    from modules.accounting.ledger import equity as _eq
    end, start = y["end_date"], y["start_date"]
    return {"balance_sheet": _st.balance_sheet(conn, end, include_drafts),
            "income_statement": _st.income_statement(conn, start, end, include_drafts),
            "equity_statement": _eq.equity_statement(conn, start, end, include_drafts),
            "cash_flow": _cf.cash_flow_statement(conn, start, end, include_drafts)}


def statements_ok(stm):
    """四表對帳是否全過（決算的前置）。回 (ok, 問題清單)。"""
    bad = []
    for key, label in (("balance_sheet", "資產負債表"), ("income_statement", "綜合損益表"), ("equity_statement", "權益變動表"), ("cash_flow", "現金流量表")):
        if not stm[key]["checks"].get("balanced"):
            bad.append("%s對帳未通過" % label)
    return (not bad), bad


def close_year(conn, year, user, accept_warnings=False):
    """決算：前置全部成立才做——1～11 期已結帳、結轉傳票已過帳且損益科目歸零、四大表對帳通過。寫凍結快照、關第 12 期、年度標 closed。"""
    y = _year(conn, year)
    if y["status"] != "open":
        raise ClosingError("年度目前是「%s」，只有開放的年度可以決算。" % y["status"])
    open_early = conn.execute("SELECT period_no FROM gl_periods WHERE year=? AND period_no<12 AND status='open'", (y["year"],)).fetchall()
    if open_early:
        raise ClosingError("第 %s 期還沒結帳，不能決算。" % "、".join(str(r[0]) for r in open_early))
    remaining = _pl_nets(conn, y["start_date"], y["end_date"], include_closing=True)
    if remaining:
        raise ClosingError("損益科目還有餘額（%s 等 %d 個科目）：請先產生結轉傳票並過帳。" % (sorted(remaining)[0], len(remaining)))
    unposted = closing_vouchers(conn, year, statuses=("草稿", "待審核", "簽核中", "已核准"))
    if unposted:
        raise ClosingError("結轉傳票 %s 還沒過帳。" % unposted[0]["voucher_no"])
    stm = _statements(conn, y)
    ok, bad = statements_ok(stm)
    if not ok:
        raise ClosingError("四大表對帳沒有全部通過，不能決算：%s。" % "；".join(bad))
    p12 = conn.execute("SELECT id, status FROM gl_periods WHERE year=? AND period_no=12", (y["year"],)).fetchone()
    if p12 is None:
        raise ClosingError("這個年度沒有第 12 期。")
    if p12["status"] == "open":
        _periods.close_period(conn, p12["id"], user, accept_warnings=accept_warnings, reason="年度決算")
    conn.execute("INSERT INTO gl_statement_snapshots(kind, fy, period_end, payload_json, frozen, created_by, created_at) VALUES ('year_close', ?, ?, ?, 1, ?, ?)",
                 (y["year"], y["end_date"], json.dumps(stm, ensure_ascii=False), user, _dt.datetime.now().isoformat()))
    conn.execute("UPDATE gl_fiscal_years SET status='closed' WHERE year=?", (y["year"],))
    _periods.log(conn, "year_close", user, year=y["year"], tb_after=_periods.tb_hash(conn, y["end_date"]),
                 detail={"net_income": stm["income_statement"]["net_income"]["ytd"]})
    return {"year": y["year"], "net_income": stm["income_statement"]["net_income"]["ytd"]}


def reopen_year(conn, year, user, reason):
    """年度重開：期間全部回 open、結轉傳票作廢（已過帳者以作廢處理，紀錄保留）、後面年度已結帳期間標 stale。理由必填；有鎖定期間要先解鎖。"""
    y = _year(conn, year)
    if not (reason or "").strip():
        raise ClosingError("重開年度必須填寫理由。")
    locked = conn.execute("SELECT period_no FROM gl_periods WHERE year=? AND status='locked' ORDER BY period_no", (y["year"],)).fetchall()
    if locked:
        raise ClosingError("第 %s 期已鎖定，請先由最高管理者解鎖。" % "、".join(str(r[0]) for r in locked))
    if y["status"] == "open" and not closing_vouchers(conn, year):
        raise ClosingError("這個年度是開放的，且沒有結轉傳票，不需要重開。")
    tb_before = _periods.tb_hash(conn, y["end_date"])
    conn.execute("UPDATE gl_periods SET status='open', stale=0 WHERE year=?", (y["year"],))        # 先開期間，後面作廢已過帳傳票才不會被鎖定擋下
    now = _dt.datetime.now().isoformat()
    voided = []
    for v in closing_vouchers(conn, year):
        conn.execute("UPDATE vouchers_all SET voided_at=?, voided_by=?, void_reason=? WHERE id=?",
                     (now, user, "年度重開：%s" % reason.strip(), v["id"]))
        voided.append(v["voucher_no"])
    conn.execute("UPDATE gl_fiscal_years SET status='open' WHERE year=?", (y["year"],))
    later = conn.execute("UPDATE gl_periods SET stale=1 WHERE start_date > ? AND status IN ('closed','locked')", (y["end_date"],)).rowcount
    _periods.log(conn, "year_reopen", user, year=y["year"], reason=reason.strip(), tb_before=tb_before,
                 detail={"voided_closing_vouchers": voided, "stale_later_periods": later})
    return {"year": y["year"], "voided": voided, "stale_later_periods": later}
