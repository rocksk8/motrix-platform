# -*- coding: utf-8 -*-
"""權益變動表（B3）。設計：proposal-gl/04-reports.md §5。

欄：股本、資本公積、保留盈餘、其他權益、庫藏股票、合計。列：期初餘額、本期淨利（保留盈餘欄）、其他綜合損益（其他權益欄）、
其他變動（增資、盈餘分配、庫藏股等，依權益科目在期間內的真實分錄，排除結轉傳票）、期末餘額。
期初／期末＝資產負債表在 start 前一天／end 的權益（含尚未結轉的損益）；`unexplained` 為對不起來的差額（應為 0；
期間內有期初傳票、壞帳等會出現，必須明說）。期間不可跨會計年度。
"""
import datetime as _dt

from modules.accounting.ledger import reports as _reports
from modules.accounting.ledger import roles as _roles
from modules.accounting.ledger import statements as _st

COLUMNS = [("capital", "股本", "BS_EQ_CAPITAL"), ("surplus", "資本公積", "BS_EQ_CAPSURPLUS"),
           ("re", "保留盈餘", "BS_EQ_RE"), ("other", "其他權益", "BS_EQ_OTHER"), ("treasury", "庫藏股票", "BS_EQ_TREASURY")]


def snapshot(conn, as_of, include_drafts=False):
    """某日的權益各欄（貸方為正）。保留盈餘欄＝保留盈餘科目＋以前年度未結轉損益＋本年度未結轉損益（不含其他綜合損益）；
    其他權益欄＝其他權益科目＋本年度未結轉的其他綜合損益。"""
    bs = _st.balance_sheet(conn, as_of, include_drafts)
    lines = bs["equity_lines"]
    cols = {k: lines.get(code, 0) for k, _label, code in COLUMNS}
    cols["re"] += bs["prior_pl"] + bs["current_pl"] - bs["current_oci"]
    cols["other"] += bs["current_oci"]
    cols["total"] = sum(cols[k] for k, _l, _c in COLUMNS)
    return cols, bs


def _movements(conn, start, end, include_drafts):
    """期間內權益科目的真實分錄（排除結轉傳票）：{欄鍵: [{code,name,amount}]}，貸方為正。"""
    meta = {r["code"]: dict(r) for r in conn.execute(
        "SELECT m.code, m.fs_line, a.name FROM gl_account_meta m JOIN account_items a ON a.code=m.code WHERE m.fs_line LIKE 'BS_EQ_%'")}
    st = _reports._statuses(include_drafts)
    rows = conn.execute(
        "SELECT l.account_code, COALESCE(SUM(l.credit - l.debit),0) FROM voucher_lines l JOIN vouchers_all v ON v.id=l.voucher_id"
        " WHERE v.voided_at='' AND v.kind <> 'closing' AND v.status IN (%s) AND substr(v.voucher_date,1,10) BETWEEN ? AND ?"
        " AND l.account_code IN (%s) GROUP BY l.account_code" % (",".join("?" * len(st)), ",".join("?" * len(meta) or "?")),
        list(st) + [start, end] + list(meta)).fetchall() if meta else []
    by_col = {k: [] for k, _l, _c in COLUMNS}
    code_to_col = {c: k for k, _l, c in COLUMNS}
    for code, amt in rows:
        if amt:
            m = meta[code]
            by_col[code_to_col[m["fs_line"]]].append({"code": code, "name": m["name"], "amount": amt})
    return by_col


def equity_statement(conn, start, end, include_drafts=False):
    if start > end:
        raise ValueError("起日不可晚於迄日。")
    if _reports._fy_start(conn, start) != _reports._fy_start(conn, end):
        raise ValueError("權益變動表期間不可跨會計年度。")
    _roles.ensure_meta(conn)
    prev = (_dt.date.fromisoformat(start) - _dt.timedelta(days=1)).isoformat()
    opening, _bs0 = snapshot(conn, prev, include_drafts)
    closing, bs1 = snapshot(conn, end, include_drafts)
    inc = _st.income_statement(conn, start, end, include_drafts)
    ni = inc["net_income"]["period"]
    oci = next((l["period"] for l in inc["lines"] if l["code"] == "IS_OCI"), 0)
    moves = _movements(conn, start, end, include_drafts)
    other_row = {k: sum(x["amount"] for x in moves[k]) for k, _l, _c in COLUMNS}
    ni_row = {k: (ni if k == "re" else 0) for k, _l, _c in COLUMNS}
    oci_row = {k: (oci if k == "other" else 0) for k, _l, _c in COLUMNS}

    def total(d):
        d = dict(d)
        d["total"] = sum(d[k] for k, _l, _c in COLUMNS)
        return d
    unexplained = {k: closing[k] - opening[k] - ni_row[k] - oci_row[k] - other_row[k] for k, _l, _c in COLUMNS}
    unexplained["total"] = sum(unexplained[k] for k, _l, _c in COLUMNS)
    rows = [
        {"key": "opening", "label": "期初餘額", "amounts": opening},
        {"key": "ni", "label": "本期淨利", "amounts": total(ni_row)},
        {"key": "oci", "label": "其他綜合損益", "amounts": total(oci_row)},
        {"key": "other", "label": "其他變動（增資、盈餘分配、庫藏股等）", "amounts": total(other_row),
         "details": {k: v for k, v in moves.items() if v}},
        {"key": "closing", "label": "期末餘額", "amounts": closing},
    ]
    return finalize({"start": start, "end": end, "include_drafts": include_drafts,
            "columns": [{"key": k, "label": lbl} for k, lbl, _c in COLUMNS] + [{"key": "total", "label": "合計"}],
            "rows": rows, "unexplained": unexplained,
            "checks": {"closing_equals_balance_sheet": closing["total"] == bs1["totals"]["equity"],
                       "reconciled": unexplained["total"] == 0 and all(unexplained[k] == 0 for k, _l, _c in COLUMNS),
                       "income_statement_balanced": inc["checks"]["balanced"], "balance_sheet_balanced": bs1["checks"]["balanced"],
                       "balanced": None}})


def finalize(res):
    c = res["checks"]
    c["balanced"] = bool(c["closing_equals_balance_sheet"] and c["reconciled"] and c["income_statement_balanced"] and c["balance_sheet_balanced"])
    return res
