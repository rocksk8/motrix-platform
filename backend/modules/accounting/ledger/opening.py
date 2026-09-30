# -*- coding: utf-8 -*-
"""期初餘額匯入（開帳）。設計：proposal-gl/03-periods-close.md §6。

匯入＝一個批次（gl_opening_batches）＋一張 `kind='opening'` 的傳票草稿（走既有簽核與過帳）。
過帳前可整批撤銷；**過帳是不可回溯的動作，由會計／使用者按下**，本檔不自動過帳。
帳簿只從「已過帳的期初傳票」日期起算（reports.bases）：該日期之前的既有傳票視為 legacy、不入餘額。
"""
import datetime as _dt

from modules.accounting.ledger import periods as _periods
from modules.accounting.voucher import parse_amount


class OpeningError(ValueError):
    """給使用者看的中文訊息。"""


def _clean_rows(conn, rows):
    if not rows:
        raise OpeningError("沒有任何期初餘額列。")
    codes = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT code, name, is_active FROM account_items")}
    merged, problems = {}, []
    for i, r in enumerate(rows, start=1):
        code = str(r.get("account_code") or "").strip()
        if code not in codes:
            problems.append("第 %d 列：找不到科目「%s」" % (i, code))
            continue
        d, err1 = parse_amount(r.get("debit"))
        c, err2 = parse_amount(r.get("credit"))
        if err1 or err2:
            problems.append("第 %d 列（%s）：%s" % (i, code, err1 or err2))
            continue
        if d and c:
            problems.append("第 %d 列（%s）：借方與貸方不可同時有金額" % (i, code))
            continue
        m = merged.setdefault(code, [0, 0])
        m[0] += d
        m[1] += c
    if problems:
        raise OpeningError("；".join(problems[:10]) + ("（還有 %d 項）" % (len(problems) - 10) if len(problems) > 10 else ""))
    out = [{"account_code": k, "debit": v[0], "credit": v[1], "name": codes[k][0]}
           for k, v in sorted(merged.items()) if v[0] or v[1]]
    if not out:
        raise OpeningError("期初餘額全部是 0。")
    return out


def _clean_items(items, balances):
    """未結明細（選填）：某科目若提供明細，明細合計必須等於該科目期初淨額（借−貸，取絕對值）。"""
    if not items:
        return []
    by_acct, out = {}, []
    for i, it in enumerate(items, start=1):
        code = str(it.get("account_code") or "").strip()
        amt, err = parse_amount(it.get("amount"))
        if err or not code or not str(it.get("doc_no") or "").strip():
            raise OpeningError("未結明細第 %d 列不完整（需要科目、單號、金額）：%s" % (i, err or ""))
        by_acct[code] = by_acct.get(code, 0) + amt
        out.append({"account_code": code, "party_key": str(it.get("party_key") or "").strip(),
                    "doc_no": str(it["doc_no"]).strip(), "doc_date": str(it.get("doc_date") or "")[:10], "amount": amt})
    net = {b["account_code"]: abs(b["debit"] - b["credit"]) for b in balances}
    for code, total in by_acct.items():
        if net.get(code) != total:
            raise OpeningError("科目 %s 的未結明細合計 %d，與期初餘額 %d 不符。" % (code, total, net.get(code, 0)))
    return out


def preview(conn, rows, items=None):
    """驗證並回試算結果（不寫入）。借貸不平衡也回結果（`balanced=False` ＋差額），讓畫面顯示差多少。"""
    cleaned = _clean_rows(conn, rows)
    _clean_items(items, cleaned)
    d, c = sum(r["debit"] for r in cleaned), sum(r["credit"] for r in cleaned)
    return {"rows": cleaned, "debit": d, "credit": c, "diff": d - c, "balanced": d == c}


def create_batch(conn, year, opening_date, rows, items, filename, user):
    """建立批次＋期初傳票草稿。不 commit。回 `{"batch_id","voucher_id","voucher_no"}`。"""
    from modules.accounting.api import vouchers as _v           # 同模組；晚 import 避免載入循環
    y = conn.execute("SELECT * FROM gl_fiscal_years WHERE year=?", (int(year),)).fetchone()
    if y is None:
        raise OpeningError("%s 年度尚未建立，請先建立年度。" % year)
    try:
        _dt.date.fromisoformat(opening_date)
    except (TypeError, ValueError):
        raise OpeningError("開帳日期格式要是 YYYY-MM-DD。")
    if not y["start_date"] <= opening_date <= y["end_date"]:
        raise OpeningError("開帳日期必須落在 %s 年度（%s～%s）內。" % (year, y["start_date"], y["end_date"]))
    err = _periods.lock_error(conn, opening_date)
    if err:
        raise OpeningError(err + "請先重開該期間才能匯入期初。")
    if conn.execute("SELECT 1 FROM gl_opening_batches WHERE year=? AND undone_at=''", (int(year),)).fetchone():
        raise OpeningError("%s 年度已經有一批期初餘額；要重匯請先撤銷（尚未過帳）或開沖轉傳票。" % year)
    res = preview(conn, rows, items)
    if not res["balanced"]:
        raise OpeningError("期初餘額借貸不平衡：借 %d、貸 %d，差 %d。" % (res["debit"], res["credit"], res["diff"]))
    cleaned = res["rows"]
    now = _dt.datetime.now().isoformat()
    lines = [{"account_code": r["account_code"], "summary": "%s 年度期初餘額" % year,
              "debit": r["debit"], "credit": r["credit"], "source_type": "", "source_key": ""} for r in cleaned]
    vid, no = _v.insert_draft_voucher(conn, opening_date, "%s 年度期初餘額（開帳）" % year, lines, user, now, "轉", manual=1)
    conn.execute("UPDATE vouchers_all SET kind='opening', origin='opening' WHERE id=?", (vid,))
    cur = conn.execute("INSERT INTO gl_opening_batches(year,opening_date,source,filename,voucher_id,created_by,created_at)"
                       " VALUES(?,?, 'import', ?, ?, ?, ?)", (int(year), opening_date, filename or "", vid, user, now))
    bid = cur.lastrowid
    for r in cleaned:
        conn.execute("INSERT INTO gl_opening_balances(batch_id,account_code,debit,credit) VALUES(?,?,?,?)",
                     (bid, r["account_code"], r["debit"], r["credit"]))
    for it in _clean_items(items, cleaned):
        conn.execute("INSERT INTO gl_opening_items(batch_id,account_code,party_key,doc_no,doc_date,amount) VALUES(?,?,?,?,?,?)",
                     (bid, it["account_code"], it["party_key"], it["doc_no"], it["doc_date"], it["amount"]))
    conn.execute("UPDATE gl_fiscal_years SET opening_mode='imported', opening_date=?, opening_batch_id=? WHERE year=?",
                 (opening_date, bid, int(year)))
    _periods.log(conn, "opening_import", user, year=int(year), detail={"batch_id": bid, "voucher_no": no, "rows": len(cleaned)})
    return {"batch_id": bid, "voucher_id": vid, "voucher_no": no}


def undo_batch(conn, batch_id, user):
    """撤銷尚未過帳的期初批次（作廢其傳票草稿）。已過帳 ⇒ OpeningError（不可回溯，請開沖轉傳票）。不 commit。"""
    b = conn.execute("SELECT * FROM gl_opening_batches WHERE id=?", (batch_id,)).fetchone()
    if b is None:
        raise OpeningError("找不到這批期初餘額。")
    if b["undone_at"]:
        raise OpeningError("這批期初餘額已經撤銷過了。")
    v = conn.execute("SELECT id, status, voided_at FROM vouchers_all WHERE id=?", (b["voucher_id"],)).fetchone()
    if v is not None and not v["voided_at"]:
        if v["status"] != "草稿":
            raise OpeningError("這批期初的傳票已經是「%s」，不能撤銷；已過帳的期初只能開沖轉傳票更正。" % v["status"])
        now = _dt.datetime.now().isoformat()
        conn.execute("UPDATE vouchers_all SET voided_at=?, voided_by=?, void_reason=? WHERE id=? AND status='草稿'",
                     (now, user, "撤銷期初餘額批次 %d" % batch_id, v["id"]))
    conn.execute("UPDATE gl_opening_batches SET undone_at=?, undone_by=? WHERE id=?",
                 (_dt.datetime.now().isoformat(), user, batch_id))
    if not conn.execute("SELECT 1 FROM gl_opening_batches WHERE year=? AND undone_at=''", (b["year"],)).fetchone():
        conn.execute("UPDATE gl_fiscal_years SET opening_mode='carry', opening_date='', opening_batch_id=NULL WHERE year=?", (b["year"],))
    _periods.log(conn, "opening_undo", user, year=b["year"], detail={"batch_id": batch_id})


def list_batches(conn):
    out = []
    for b in conn.execute("SELECT b.*, v.voucher_no, v.status AS voucher_status FROM gl_opening_batches b"
                          " LEFT JOIN vouchers_all v ON v.id=b.voucher_id ORDER BY b.id DESC"):
        d = dict(b)
        d["debit"], d["credit"] = conn.execute("SELECT COALESCE(SUM(debit),0), COALESCE(SUM(credit),0)"
                                               " FROM gl_opening_balances WHERE batch_id=?", (b["id"],)).fetchone()
        out.append(d)
    return out
