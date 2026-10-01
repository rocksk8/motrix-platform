# -*- coding: utf-8 -*-
"""`ledger.month_totals` 提供者（IP-107 暫定號）：總帳逐月的收入／費用彙總，給營運分析『與總帳差異』頁（MONEY-FLOWS §9 L4）。

`fn(conn, year) -> {"available": True, "year", "months": {"YYYY-MM": {...}}, "events": {"YYYY-MM": {drift, orphan, blocked}}}`
每個月份有四組，各組 `{revenue, expense, tax_out, tax_in}`（整數元）：
- `engine_posted`／`engine_unposted`：總帳引擎產生的傳票（`origin LIKE 'gl:%'`，含反向傳票）已過帳／尚未過帳（草稿、待審、簽核中、已核准）
- `bonus_posted`：獎金模組開立的傳票（`origin LIKE 'bonus%'`）已過帳
- `manual_posted`：其餘（手工）傳票已過帳
另有 `by_origin_posted`：`{origin: expense}`（已過帳、費用類科目行、依傳票來源），給報表分類對照；
`tax_in_by_origin_posted`：`{origin: 進項稅額}`（已過帳、只含總帳引擎傳票 `gl:…`），給類別層級的稅額分桶（只增鍵，舊使用者不受影響）。
收入＝收入類科目（revenue／other_income）貸方−借方；費用＝cost／expense／other_expense 借方−貸方；`tax_out`＝銷項稅額科目貸−借；
`tax_in`＝進項稅額科目借−貸（科目 `tax_role` 是 `output_tax`／`input_tax`）。不含 `kind='closing'` 結轉傳票、不含已作廢。
只讀、不寫、不 commit；表不存在 ⇒ `available: False` 並說明，不是 0。"""
from modules.accounting.ledger.roles import ensure_meta

_UNPOSTED = ("草稿", "待審核", "簽核中", "已核准")
_REV = ("revenue", "other_income")
_EXP = ("cost", "expense", "other_expense")
_ZERO = {"revenue": 0, "expense": 0, "tax_out": 0, "tax_in": 0}


def _group(origin, posted):
    if (origin or "").startswith("gl:"):
        return "engine_posted" if posted else "engine_unposted"
    if not posted:
        return None                                      # 手工／獎金的未過帳不進任何一組（差異頁只解釋引擎草稿）
    return "bonus_posted" if (origin or "").startswith("bonus") else "manual_posted"


def month_totals(conn, year):
    try:
        ensure_meta(conn)
        rows = conn.execute(
            "SELECT substr(v.voucher_date,1,7) AS mo, v.origin AS origin, (v.status='已過帳') AS posted, m.acct_type AS t, m.tax_role AS tr,"
            " SUM(l.debit) AS d, SUM(l.credit) AS c FROM voucher_lines l"
            " JOIN vouchers_all v ON v.id = l.voucher_id JOIN gl_account_meta m ON m.code = l.account_code"
            " WHERE v.voided_at = '' AND v.kind <> 'closing' AND substr(v.voucher_date,1,4) = ?"
            " AND v.status IN ('已過帳', %s) GROUP BY mo, v.origin, posted, m.acct_type, m.tax_role" % ",".join("?" * len(_UNPOSTED)),
            ("%04d" % int(year),) + _UNPOSTED).fetchall()
        ev = conn.execute(
            "SELECT substr(event_date,1,7) AS mo, status, COUNT(*) AS n FROM gl_source_events"
            " WHERE substr(event_date,1,4) = ? AND status IN ('drift','orphan','blocked_closed','blocked_no_account','blocked_inventory')"
            " GROUP BY mo, status", ("%04d" % int(year),)).fetchall()
    except Exception as e:                               # noqa: BLE001 — 總帳表還沒建（模組剛裝）／舊庫
        return {"available": False, "notice": "總帳資料讀取失敗：%s" % type(e).__name__}
    months = {}
    for r in rows:
        g = _group(r["origin"], bool(r["posted"]))
        if g is None:
            continue
        slot = months.setdefault(r["mo"], {}).setdefault(g, dict(_ZERO))
        d, c = int(r["d"] or 0), int(r["c"] or 0)
        if r["t"] in _REV:
            slot["revenue"] += c - d
        elif r["t"] in _EXP:
            slot["expense"] += d - c
        if r["tr"] == "output_tax":
            slot["tax_out"] += c - d
        elif r["tr"] == "input_tax":
            slot["tax_in"] += d - c
        if r["posted"] and r["t"] in _EXP:
            bo = months[r["mo"]].setdefault("by_origin_posted", {})
            bo[r["origin"] or ""] = bo.get(r["origin"] or "", 0) + (d - c)
        if r["posted"] and r["tr"] == "input_tax" and g == "engine_posted":
            ti = months[r["mo"]].setdefault("tax_in_by_origin_posted", {})
            ti[r["origin"] or ""] = ti.get(r["origin"] or "", 0) + (d - c)
    events = {}
    for r in ev:
        e = events.setdefault(r["mo"], {"drift": 0, "orphan": 0, "blocked": 0})
        e["drift" if r["status"] == "drift" else "orphan" if r["status"] == "orphan" else "blocked"] += int(r["n"])
    return {"available": True, "year": int(year), "months": months, "events": events}
