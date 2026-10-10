# -*- coding: utf-8 -*-
"""帳簿報表：試算表、總分類帳、明細分類帳、序時帳簿（日記簿）。設計：proposal-gl/04-reports.md §1–§2。

資料範圍：`vouchers_all.status='已過帳' AND voided_at=''`（`include_drafts=True` 時含所有未作廢傳票，畫面要標「含未過帳」）；
`kind='closing'` 的結轉傳票預設不計（P5 才有）。

期初的算法（03 §6.1）：以「起算日」為界，之前的傳票不計入——
- 資產負債科目：最近一次**已過帳的期初傳票**（gl_opening_batches）的日期；沒有就從頭累計（未啟用期初的舊部署行為不變）。
- 損益科目：max(該會計年度起日, 上述期初日)。
損益科目換年度歸零；上年度損益若尚未結轉，試算表補一列「以前年度損益（尚未結轉）」使借貸仍平衡，並保留真實差額不被吸收
（不平衡的資料照樣顯示 `balanced=False`）。
"""
from modules.accounting.ledger import periods as _periods
from modules.accounting.voucher import voucher_order_sql          # 第 54 班：單號流水 ≥1000 位時的排序（字串排序會排錯）
from modules.accounting.ledger.roles import PL_TYPES, ensure_meta

_UNPOSTED = ("草稿", "待審核", "簽核中", "已核准")


def _statuses(include_drafts):
    return ("已過帳",) + _UNPOSTED if include_drafts else ("已過帳",)


def _fy_start(conn, date):
    row = conn.execute("SELECT start_date FROM gl_fiscal_years WHERE ? BETWEEN start_date AND end_date", (date,)).fetchone()
    if row:
        return row[0]
    sm = _periods.fiscal_start_month(conn)
    y = int(date[:4])
    return "%04d-%02d-01" % (y if int(date[5:7]) >= sm else y - 1, sm)


def bases(conn, date):
    """回 `(bs_base, pl_base)`：截至 date，兩類科目的累計起算日（含）。"""
    row = conn.execute(
        "SELECT MAX(b.opening_date) FROM gl_opening_batches b JOIN vouchers_all v ON v.id=b.voucher_id"
        " WHERE b.undone_at='' AND v.status='已過帳' AND v.voided_at='' AND b.opening_date <= ?", (date,)).fetchone()
    op = row[0] or ""
    return op, max(_fy_start(conn, date), op)


def _meta(conn):
    ensure_meta(conn)
    return {r["code"]: dict(r) for r in conn.execute(
        "SELECT m.*, a.name AS name, a.parent_code AS parent_code FROM gl_account_meta m JOIN account_items a ON a.code=m.code")}


def _sums(conn, lo, hi, statuses, include_closing, codes=None):
    """`{account: [debit, credit]}`：lo ≤ 傳票日 ≤ hi（hi 為 None＝不設上限；lo 為空＝不設下限；lo>hi 回空）。"""
    if lo and hi and lo > hi:
        return {}
    where, args = ["v.voided_at=''", "v.status IN (%s)" % ",".join("?" * len(statuses))], list(statuses)
    if not include_closing:
        where.append("v.kind <> 'closing'")
    if lo:
        where.append("substr(v.voucher_date,1,10) >= ?")
        args.append(lo)
    if hi:
        where.append("substr(v.voucher_date,1,10) <= ?")
        args.append(hi)
    if codes is not None:
        if not codes:
            return {}
        where.append("l.account_code IN (%s)" % ",".join("?" * len(codes)))
        args += list(codes)
    q = ("SELECT l.account_code, COALESCE(SUM(l.debit),0), COALESCE(SUM(l.credit),0) FROM voucher_lines l"
         " JOIN vouchers_all v ON v.id=l.voucher_id WHERE " + " AND ".join(where) + " GROUP BY l.account_code")
    return {r[0]: [r[1], r[2]] for r in conn.execute(q, args)}


def _prev_day(d):
    import datetime as dt
    return (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()


def _split(meta, sums, want_pl):
    return {c: v for c, v in sums.items() if (meta.get(c, {}).get("acct_type") in PL_TYPES) == want_pl}


def trial_balance(conn, start, end, include_drafts=False, include_closing=False, include_zero=False):
    if start > end:
        raise ValueError("起日不可晚於迄日。")
    if _fy_start(conn, start) != _fy_start(conn, end):
        raise ValueError("試算表期間不可跨會計年度（損益科目每年度歸零）。")
    meta = _meta(conn)
    st = _statuses(include_drafts)
    bs_b, pl_b = bases(conn, end)
    rows = {}

    def slot(code):
        return rows.setdefault(code, {"op": [0, 0], "pd": [0, 0]})

    for want_pl, base in ((False, bs_b), (True, pl_b)):
        # 期初：base ≤ 日期 < start；本期：max(start, base) ≤ 日期 ≤ end
        for code, (d, c) in _split(meta, _sums(conn, base, _prev_day(start), st, include_closing), want_pl).items():
            s = slot(code)
            s["op"][0] += d
            s["op"][1] += c
        for code, (d, c) in _split(meta, _sums(conn, max(start, base), end, st, include_closing), want_pl).items():
            s = slot(code)
            s["pd"][0] += d
            s["pd"][1] += c
    out = []
    for code in sorted(rows):
        m = meta.get(code) or {"name": "（科目已不存在）", "acct_type": "", "normal_side": "D", "fs_line": ""}
        op_net = rows[code]["op"][0] - rows[code]["op"][1]
        pd_d, pd_c = rows[code]["pd"]
        cl_net = op_net + pd_d - pd_c
        if not include_zero and op_net == 0 and pd_d == 0 and pd_c == 0 and cl_net == 0:
            continue
        out.append(_row(code, m.get("display_name") or m["name"], m["acct_type"], m["normal_side"], op_net, pd_d, pd_c, cl_net))
    # 以前年度損益（尚未結轉）：把 [bs_base, pl_base) 的損益科目淨額補回，讓歷年累計的試算表仍平衡
    prior = 0
    if pl_b > bs_b:
        for d, c in _split(meta, _sums(conn, bs_b, _prev_day(pl_b), st, include_closing), True).values():
            prior += d - c
    prior_row = None
    if prior:
        prior_row = _row("", "以前年度損益（尚未結轉）", "equity", "C", prior, 0, 0, prior)
        out.append(prior_row)
    tot = {k: sum(r[k] for r in out) for k in ("opening_debit", "opening_credit", "period_debit", "period_credit",
                                              "closing_debit", "closing_credit")}
    return {"start": start, "end": end, "include_drafts": include_drafts, "rows": out, "totals": tot,
            "balanced": tot["opening_debit"] == tot["opening_credit"] and tot["period_debit"] == tot["period_credit"]
            and tot["closing_debit"] == tot["closing_credit"],
            "prior_pl": prior, "bases": {"bs": bs_b, "pl": pl_b}}


def _row(code, name, typ, side, op_net, pd_d, pd_c, cl_net):
    return {"code": code, "name": name, "acct_type": typ, "normal_side": side,
            "opening_debit": max(op_net, 0), "opening_credit": max(-op_net, 0),
            "period_debit": pd_d, "period_credit": pd_c,
            "closing_debit": max(cl_net, 0), "closing_credit": max(-cl_net, 0)}


def _descendants(meta, code):
    kids = {}
    for c, m in meta.items():
        kids.setdefault(m.get("parent_code"), []).append(c)
    out, stack = set(), [code]
    while stack:
        c = stack.pop()
        if c in out:
            continue
        out.add(c)
        stack.extend(kids.get(c, []))
    return out


def general_ledger(conn, account, start, end, include_drafts=False, include_closing=False, dimension=None, key=None):
    """單一科目（含其下所有子科目）的分類帳：期初、逐筆（帶餘額）、期末。`dimension`／`key` 可再篩明細維度。"""
    meta = _meta(conn)
    if account not in meta:
        return None
    codes = sorted(_descendants(meta, account))
    st = _statuses(include_drafts)
    typ = meta[account]["acct_type"]
    bs_b, pl_b = bases(conn, end)
    base = pl_b if typ in PL_TYPES else bs_b
    extra, eargs = "", []
    if dimension:
        if dimension not in ("party_key", "case_no", "doc_no", "counterparty"):
            raise ValueError("不支援的維度：%s" % dimension)
        extra, eargs = " AND l.%s = ?" % dimension, [key or ""]
    where = ["v.voided_at=''", "v.status IN (%s)" % ",".join("?" * len(st)),
             "l.account_code IN (%s)" % ",".join("?" * len(codes))]
    args = list(st) + codes
    if not include_closing:
        where.append("v.kind <> 'closing'")
    if base:
        where.append("substr(v.voucher_date,1,10) >= ?")
        args.append(base)
    op = conn.execute("SELECT COALESCE(SUM(l.debit),0), COALESCE(SUM(l.credit),0) FROM voucher_lines l JOIN vouchers_all v ON v.id=l.voucher_id"
                      " WHERE " + " AND ".join(where) + " AND substr(v.voucher_date,1,10) < ?" + extra, args + [start] + eargs).fetchone()
    opening = op[0] - op[1]
    lines = conn.execute(
        "SELECT v.voucher_date, v.voucher_no, v.status, v.kind, l.line_no, l.account_code, l.summary, l.debit, l.credit,"
        " l.case_no, l.party_key, l.doc_no, l.counterparty, v.id AS voucher_id FROM voucher_lines l JOIN vouchers_all v ON v.id=l.voucher_id"
        " WHERE " + " AND ".join(where) + " AND substr(v.voucher_date,1,10) BETWEEN ? AND ?" + extra
        + " ORDER BY substr(v.voucher_date,1,10), " + voucher_order_sql("v.voucher_no") + ", l.line_no", args + [max(start, base or start), end] + eargs).fetchall()
    run, out = opening, []
    for r in lines:
        run += r["debit"] - r["credit"]
        d = dict(r)
        d["balance"] = run
        out.append(d)
    return {"account": account, "name": meta[account]["name"], "normal_side": meta[account]["normal_side"], "start": start,
            "end": end, "opening": opening, "lines": out, "closing": run,
            "period_debit": sum(x["debit"] for x in out), "period_credit": sum(x["credit"] for x in out)}


def subledger(conn, account, dimension, start, end, include_drafts=False):
    """明細分類帳（依維度彙總）：每個 party_key／case_no／doc_no 一列，期初、本期借貸、期末。"""
    if dimension not in ("party_key", "case_no", "doc_no", "counterparty"):
        raise ValueError("不支援的維度：%s" % dimension)
    meta = _meta(conn)
    if account not in meta:
        return None
    codes = sorted(_descendants(meta, account))
    st = _statuses(include_drafts)
    typ = meta[account]["acct_type"]
    bs_b, pl_b = bases(conn, end)
    base = pl_b if typ in PL_TYPES else bs_b
    base_sql = " AND substr(v.voucher_date,1,10) >= ?" if base else ""
    q = ("SELECT l.%s AS k, COALESCE(SUM(CASE WHEN substr(v.voucher_date,1,10) < ? THEN l.debit-l.credit ELSE 0 END),0) AS op,"
         " COALESCE(SUM(CASE WHEN substr(v.voucher_date,1,10) BETWEEN ? AND ? THEN l.debit ELSE 0 END),0) AS pd,"
         " COALESCE(SUM(CASE WHEN substr(v.voucher_date,1,10) BETWEEN ? AND ? THEN l.credit ELSE 0 END),0) AS pc"
         " FROM voucher_lines l JOIN vouchers_all v ON v.id=l.voucher_id WHERE v.voided_at='' AND v.kind <> 'closing'"
         " AND v.status IN (%s) AND l.account_code IN (%s)%s AND substr(v.voucher_date,1,10) <= ? GROUP BY l.%s ORDER BY l.%s"
         % (dimension, ",".join("?" * len(st)), ",".join("?" * len(codes)), base_sql, dimension, dimension))
    s2 = max(start, base or start)
    args = [start, s2, end, s2, end] + list(st) + codes + ([base] if base else []) + [end]
    rows = []
    for r in conn.execute(q, args):
        cl = r["op"] + r["pd"] - r["pc"]
        if r["op"] == 0 and r["pd"] == 0 and r["pc"] == 0 and cl == 0:
            continue
        rows.append({"key": r["k"], "opening": r["op"], "period_debit": r["pd"], "period_credit": r["pc"], "closing": cl})
    return {"account": account, "dimension": dimension, "start": start, "end": end, "rows": rows,
            "total_closing": sum(x["closing"] for x in rows)}


def journal(conn, start, end, include_drafts=False, limit=2000):
    """序時帳簿：期間內傳票依日期／號碼，附分錄。"""
    st = _statuses(include_drafts)
    sql = ("SELECT id, voucher_no, voucher_date, category, kind, summary, status FROM vouchers_all WHERE voided_at=''"
           " AND status IN (%s) AND substr(voucher_date,1,10) BETWEEN ? AND ? ORDER BY substr(voucher_date,1,10), "
           % ",".join("?" * len(st))) + voucher_order_sql("voucher_no") + " LIMIT ?"
    vs = conn.execute(sql, list(st) + [start, end, int(limit)]).fetchall()
    out = []
    for v in vs:
        d = dict(v)
        d["lines"] = [dict(r) for r in conn.execute(
            "SELECT l.line_no, l.account_code, a.name AS account_name, l.summary, l.debit, l.credit, l.case_no, l.party_key, l.doc_no"
            " FROM voucher_lines l LEFT JOIN account_items a ON a.code=l.account_code WHERE l.voucher_id=? ORDER BY l.line_no", (v["id"],))]
        out.append(d)
    return {"start": start, "end": end, "vouchers": out, "truncated": len(vs) >= int(limit)}
