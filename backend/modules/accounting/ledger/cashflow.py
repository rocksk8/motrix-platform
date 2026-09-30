# -*- coding: utf-8 -*-
"""現金流量表，間接法（B4）。設計：proposal-gl/04-reports.md §5。

做法（雙式簿記恆等式，不靠估算）：每張傳票借貸相等 ⇒ 現金科目的淨變動＝本期淨利＋其他綜合損益－Σ(非現金資產負債科目的借貸淨額)。
所以：營業活動＝本期淨利＋其他綜合損益＋分類為營業的科目變動；投資、籌資活動＝該類科目變動；三者相加必等於現金淨變動。
科目的分類來自 `gl_account_meta.cashflow_class`（B1 設定）；有變動卻沒分類的科目列入 `unclassified`（報表不可信，明說）。
資料範圍＝期間內已過帳（或含草稿）、未作廢、非結轉傳票的分錄（結轉傳票只是損益搬進保留盈餘，不是現金事件）。期間不可跨會計年度。
"""
import datetime as _dt
import re

from modules.accounting.ledger import fs_lines as _fs
from modules.accounting.ledger import reports as _reports
from modules.accounting.ledger import roles as _roles
from modules.accounting.ledger import statements as _st

_ACCUM = re.compile(r"累計(折舊|攤銷|折耗|減損)|備抵")
_ACTIVITY = {"operating": "營業活動", "investing": "投資活動", "financing": "籌資活動"}


def _movements(conn, start, end, include_drafts):
    st = _reports._statuses(include_drafts)
    return conn.execute(
        "SELECT l.account_code AS code, m.acct_type, m.cashflow_class, m.fs_line, a.name,"
        " COALESCE(SUM(l.debit),0) AS d, COALESCE(SUM(l.credit),0) AS c FROM voucher_lines l"
        " JOIN vouchers_all v ON v.id=l.voucher_id JOIN gl_account_meta m ON m.code=l.account_code JOIN account_items a ON a.code=l.account_code"
        " WHERE v.voided_at='' AND v.kind <> 'closing' AND v.status IN (%s) AND substr(v.voucher_date,1,10) BETWEEN ? AND ?"
        " GROUP BY l.account_code" % ",".join("?" * len(st)), list(st) + [start, end]).fetchall()


def cash_flow_statement(conn, start, end, include_drafts=False):
    if start > end:
        raise ValueError("起日不可晚於迄日。")
    if _reports._fy_start(conn, start) != _reports._fy_start(conn, end):
        raise ValueError("現金流量表期間不可跨會計年度。")
    _roles.ensure_meta(conn)
    fs_label = {r["code"]: r["label"] for r in conn.execute("SELECT code, label FROM gl_fs_lines")}
    ni = oci = cash_net = 0
    groups = {"operating": {}, "investing": {}, "financing": {}}
    unclassified = []
    for r in _movements(conn, start, end, include_drafts):
        net = r["d"] - r["c"]
        if net == 0:
            continue
        typ, cf = r["acct_type"], r["cashflow_class"]
        if typ in _roles.PL_TYPES:
            if typ == "oci":
                oci += -net
            else:
                ni += -net
            continue
        if typ == "summary":
            continue
        if cf == "cash":
            cash_net += net
            continue
        if cf not in groups:
            unclassified.append({"code": r["code"], "name": r["name"], "net": net})
            continue
        if typ == "asset" and _ACCUM.search(r["name"] or ""):
            label = "折舊、攤銷、減損及備抵（累計科目變動）"
        else:
            label = fs_label.get(r["fs_line"], r["fs_line"] or "其他")
        g = groups[cf].setdefault(label, {"label": label, "amount": 0, "accounts": []})
        g["amount"] += -net
        g["accounts"].append({"code": r["code"], "name": r["name"], "amount": -net})
    sections = []
    for key in ("operating", "investing", "financing"):
        lines = []
        if key == "operating":
            lines.append({"label": "本期淨利", "amount": ni, "accounts": []})
            if oci:
                lines.append({"label": "其他綜合損益（非現金）", "amount": oci, "accounts": []})
        lines += sorted((g for g in groups[key].values() if g["amount"]), key=lambda g: g["label"])
        sections.append({"key": key, "title": _ACTIVITY[key] + "之現金流量", "lines": lines, "total": sum(l["amount"] for l in lines)})
    total = sum(s["total"] for s in sections)
    prev = (_dt.date.fromisoformat(start) - _dt.timedelta(days=1)).isoformat()
    cash_open = _cash_balance(conn, prev, include_drafts)
    cash_close = _cash_balance(conn, end, include_drafts)
    inc = _st.income_statement(conn, start, end, include_drafts)
    checks = {
        "activities_equal_cash_change": total == cash_net,                     # 恆等式：不成立＝有未分類科目或帳不平
        "cash_reconciles_to_balance_sheet": cash_open + cash_net == cash_close,  # 期初現金＋淨變動＝期末現金（＝資產負債表現金）
        "net_income_matches_income_statement": ni == inc["net_income"]["period"],
        "no_unclassified_accounts": not unclassified,
    }
    checks["balanced"] = all(checks.values())
    return {"start": start, "end": end, "include_drafts": include_drafts, "sections": sections,
            "net_change": total, "cash_change": cash_net, "cash_opening": cash_open, "cash_closing": cash_close,
            "unclassified": unclassified, "checks": checks}


def _cash_balance(conn, as_of, include_drafts):
    bs = _st.balance_sheet(conn, as_of, include_drafts)
    for it in bs["sections"]["current_assets"]["items"]:
        if it["code"] == "BS_CA_CASH":
            return it["amount"]
    return 0
