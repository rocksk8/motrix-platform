# -*- coding: utf-8 -*-
"""營業稅 401：銷進項彙總、對帳、期末稅額結轉草稿（proposal-gl/05-tax401.md）。

**401 由總帳彙總，不另讀單據**：來源＝該雙月期間已過帳、未作廢的傳票分錄（`voucher_lines.tax_code`＋科目類別），
單一資料來源避免「401 一份、帳一份」。欄位代號來自 `gl_tax401_map`（可設定；二手轉載，實作時以當期官方格式核對）。
- 銷售額／銷項稅額：稅碼 `OUT-*` 的收入科目貸方淨額／銷項稅額科目貸方淨額；零稅率銷售額落『零稅率』欄。
- 進項金額／稅額：稅碼 `IN-*` 的借方淨額（非進項稅額科目／進項稅額科目）；`IN-ADJ` 為進貨退出折讓（減項）。
- 稅額計算：101 銷項合計、107 得扣抵進項合計、108 上期累積留抵、110 小計、111 本期應實繳、112 本期申報留抵。
- 對帳：101＝銷項稅額科目本期淨額、107＝進項稅額科目本期淨額（不含稅額結轉傳票）、與應收應付模組的發票逐項加總對比；估計稅額與免稅銷售另列警示。
所有函式不 commit。
"""
import calendar
import datetime as _dt

from modules.accounting.ledger import periods as _periods
from modules.accounting.ledger import roles as _roles

#: 預設欄位對照（可在 gl_tax401_map 覆寫）：(稅碼, 發票種類) → (銷售額或進項金額, 稅額, 零稅率銷售額)
DEFAULT_MAP = (
    ("OUT-5", "einvoice", "OUT", "5", "6", "7", "三聯式收銀機發票及電子發票（預設發票媒介：電子發票）"),
    ("OUT-0", "einvoice", "OUT", "", "", "7", "零稅率銷售額（電子發票）"),
    ("OUT-ADJ", "", "OUT", "17", "18", "19", "減：退回及折讓"),
    ("IN-5", "", "IN", "28", "29", "", "三聯式發票扣抵聯（進貨及費用）"),
    ("IN-FA", "", "IN", "30", "31", "", "三聯式發票扣抵聯（固定資產）"),
    ("IN-ADJ", "", "IN", "40", "41", "", "減：進貨退出、折讓"),
)
_R_OUT, _R_IN, _R_CARRY, _R_PAYABLE = "OUTPUT_TAX", "INPUT_TAX", "TAX_CARRY", "TAX_PAYABLE"     # 帳務角色名（常數，非使用者角色）
_CARRY_ORIGIN = "gl:E14"


class TaxError(ValueError):
    pass


def ensure_map(conn):
    for code, kind, side, a, t, z, note in DEFAULT_MAP:
        conn.execute("INSERT OR IGNORE INTO gl_tax401_map(tax_code, invoice_kind, side, field_amt, field_tax, field_zero, note) VALUES (?,?,?,?,?,?,?)",
                     (code, kind, side, a, t, z, note))


def bimonthly(year, n):
    """第 n 期（1～6）＝ (2n-1)～2n 月 ⇒ (起日, 迄日)。"""
    if not (isinstance(n, int) and 1 <= n <= 6):
        raise TaxError("申報期別要是 1～6（每二月一期）。")
    last = calendar.monthrange(year, 2 * n)[1]
    return "%04d-%02d-01" % (year, 2 * n - 1), "%04d-%02d-%02d" % (year, 2 * n, last)


def _acct(conn, role, on):
    return _roles.resolve_role(conn, role, on_date=on) or ""


def _lines(conn, lo, hi):
    """期間內已過帳、未作廢、非稅額結轉傳票的分錄（含科目類別）。"""
    return conn.execute(
        "SELECT l.account_code, l.debit, l.credit, l.tax_code, l.doc_no, v.voucher_no, v.voucher_date, COALESCE(m.acct_type,'') AS typ"
        " FROM voucher_lines l JOIN vouchers_all v ON v.id=l.voucher_id LEFT JOIN gl_account_meta m ON m.code=l.account_code"
        " WHERE v.status='已過帳' AND v.voided_at='' AND v.kind <> 'closing' AND v.origin <> ? AND substr(v.voucher_date,1,10) BETWEEN ? AND ?"
        " AND l.tax_code <> ''", (_CARRY_ORIGIN, lo, hi)).fetchall()


def _account_net(conn, code, lo, hi, side):
    """某科目期間淨額（side='C' 貸方淨額，'D' 借方淨額），不含稅額結轉傳票、結轉傳票。"""
    if not code:
        return 0
    r = conn.execute(
        "SELECT COALESCE(SUM(l.debit),0), COALESCE(SUM(l.credit),0) FROM voucher_lines l JOIN vouchers_all v ON v.id=l.voucher_id"
        " WHERE v.status='已過帳' AND v.voided_at='' AND v.kind <> 'closing' AND v.origin <> ? AND l.account_code=?"
        " AND substr(v.voucher_date,1,10) BETWEEN ? AND ?", (_CARRY_ORIGIN, code, lo, hi)).fetchone()
    return int(r[1] - r[0]) if side == "C" else int(r[0] - r[1])


def carry_before(conn, start):
    """上期累積留抵稅額＝留抵科目在本期開始前的借方餘額（不小於 0）。"""
    code = _acct(conn, _R_CARRY, start)
    if not code:
        return 0
    r = conn.execute(
        "SELECT COALESCE(SUM(l.debit),0), COALESCE(SUM(l.credit),0) FROM voucher_lines l JOIN vouchers_all v ON v.id=l.voucher_id"
        " WHERE v.status='已過帳' AND v.voided_at='' AND l.account_code=? AND substr(v.voucher_date,1,10) < ?", (code, start)).fetchone()
    return max(0, int(r[0] - r[1]))


def summarize(conn, year, n, invoices=None):
    """401 彙總＋對帳＋警示。`invoices`＝應收應付模組的發票明細（None ⇒ 不做發票對比並說明）。回 dict。"""
    ensure_map(conn)
    lo, hi = bimonthly(year, n)
    out_acct, in_acct = _acct(conn, _R_OUT, hi), _acct(conn, _R_IN, hi)
    maps = {(r["tax_code"], r["invoice_kind"]): dict(r) for r in conn.execute("SELECT * FROM gl_tax401_map")}
    by_code = {}
    for r in _lines(conn, lo, hi):
        code = r["tax_code"]
        slot = by_code.setdefault(code, {"amount": 0, "tax": 0, "lines": 0})
        slot["lines"] += 1
        if code.startswith("OUT-"):
            if r["account_code"] == out_acct:
                slot["tax"] += int(r["credit"] - r["debit"])
            elif r["typ"] == "revenue":
                slot["amount"] += int(r["credit"] - r["debit"])
        elif code.startswith("IN-"):
            if r["account_code"] == in_acct:
                slot["tax"] += int(r["debit"] - r["credit"])
            elif r["typ"] in ("cost", "expense", "asset"):
                slot["amount"] += int(r["debit"] - r["credit"])
    rows, unmapped = [], []
    for code, v in sorted(by_code.items()):
        mp = [m for (c, k), m in maps.items() if c == code]
        if code == "OUT-EX":
            continue
        if not mp:
            unmapped.append(code)
            continue
        m = sorted(mp, key=lambda x: x["invoice_kind"])[0]
        zero = v["amount"] if m["field_zero"] and not m["field_amt"] else 0
        rows.append({"tax_code": code, "invoice_kind": m["invoice_kind"], "side": m["side"], "note": m["note"],
                     "field_amt": m["field_amt"], "field_tax": m["field_tax"], "field_zero": m["field_zero"],
                     "amount": 0 if zero else v["amount"], "tax": v["tax"], "zero_amount": zero})
    out_tax = sum(r["tax"] for r in rows if r["side"] == "OUT" and r["tax_code"] != "OUT-ADJ") - sum(r["tax"] for r in rows if r["tax_code"] == "OUT-ADJ")
    in_tax = sum(r["tax"] for r in rows if r["side"] == "IN" and r["tax_code"] != "IN-ADJ") - sum(r["tax"] for r in rows if r["tax_code"] == "IN-ADJ")
    sales_total = sum(r["amount"] + r["zero_amount"] for r in rows if r["tax_code"] in ("OUT-5", "OUT-0", "OUT-LEGACY"))
    carry_prev = carry_before(conn, lo)
    sub = in_tax + carry_prev
    calc = {"101": out_tax, "107": in_tax, "108": carry_prev, "110": sub,
            "111": max(0, out_tax - sub), "112": max(0, sub - out_tax), "25": sales_total}
    checks = []
    acct_out = _account_net(conn, out_acct, lo, hi, "C")
    acct_in = _account_net(conn, in_acct, lo, hi, "D")
    checks.append({"key": "output_tax_vs_account", "label": "101 銷項稅額合計 ＝ 銷項稅額科目本期淨額", "left": out_tax, "right": acct_out, "ok": out_tax == acct_out})
    checks.append({"key": "input_tax_vs_account", "label": "107 得扣抵進項稅額合計 ＝ 進項稅額科目本期淨額", "left": in_tax, "right": acct_in, "ok": in_tax == acct_in})
    if invoices is None:
        checks.append({"key": "invoices", "label": "與應收應付模組發票逐項對比", "left": None, "right": None, "ok": None, "note": "應收應付模組未安裝或未提供發票明細：未對比"})
    else:
        inv = [i for i in invoices if lo <= (i.get("invoiceDate") or "")[:10] <= hi]
        pre, tax = sum(int(round(float(i.get("amountPretax") or 0))) for i in inv), sum(int(round(float(i.get("taxAmount") or 0))) for i in inv)
        led_pre = sum(r["amount"] + r["zero_amount"] for r in rows if r["tax_code"] in ("OUT-5", "OUT-0", "OUT-LEGACY"))
        led_tax = sum(r["tax"] for r in rows if r["tax_code"] in ("OUT-5", "OUT-0", "OUT-LEGACY"))
        checks.append({"key": "invoices_pretax", "label": "銷售額 ＝ 發票未稅合計（%d 張）" % len(inv), "left": led_pre, "right": pre, "ok": led_pre == pre})
        checks.append({"key": "invoices_tax", "label": "銷項稅額 ＝ 發票稅額合計", "left": led_tax, "right": tax, "ok": led_tax == tax})
    warnings = []
    ex = conn.execute("SELECT COUNT(*) FROM voucher_lines l JOIN vouchers_all v ON v.id=l.voucher_id WHERE l.tax_code='OUT-EX' AND v.status='已過帳' "
                      "AND v.voided_at='' AND substr(v.voucher_date,1,10) BETWEEN ? AND ?", (lo, hi)).fetchone()[0]
    if ex:
        warnings.append({"key": "exempt", "level": "red", "text": "本期含免稅銷售額（%d 筆分錄）：401 不涵蓋免稅，應使用 403 表。" % ex})
    est = conn.execute("SELECT COUNT(*) FROM gl_source_events WHERE event_date BETWEEN ? AND ? AND status IN ('drafted','posted','drift') "
                       "AND payload_json LIKE '%\"tax_estimated\": true%'", (lo, hi)).fetchone()[0]
    if est:
        warnings.append({"key": "estimated", "level": "amber", "text": "%d 筆進項稅額是估計值（發票稅額未補登）：請到來源憑證補登實際稅額，否則 107 不可靠。" % est})
    if unmapped:
        warnings.append({"key": "unmapped", "level": "red", "text": "稅碼 %s 沒有 401 欄位對照（gl_tax401_map）：未列入彙總。" % "、".join(unmapped)})
    return {"year": year, "period": n, "start": lo, "end": hi, "rows": rows, "calc": calc, "checks": checks, "warnings": warnings,
            "reconciled": all(c["ok"] is not False for c in checks), "settlement": settlement_row(conn, lo, hi)}


def settlement_row(conn, lo, hi):
    r = conn.execute("SELECT * FROM gl_tax_settlements WHERE period_start=? AND period_end=?", (lo, hi)).fetchone()
    return dict(r) if r else None


def generate_settlement(conn, year, n, user, invoices=None):
    """期末稅額結轉草稿（E14）：借銷項稅額／貸進項稅額，應實繳貸應付營業稅、留抵借（貸）留抵稅額。
    對帳不平不可產生（先修帳）；已有草稿 ⇒ 作廢重建；已過帳 ⇒ 拒絕（請先沖轉）。"""
    from modules.accounting.ledger import engine as _engine
    s = summarize(conn, year, n, invoices)
    if not s["reconciled"]:
        bad = [c["label"] for c in s["checks"] if c["ok"] is False]
        raise TaxError("401 對帳未通過，不能產生稅額結轉：%s" % "；".join(bad))
    lo, hi = s["start"], s["end"]
    lock = _periods.lock_error(conn, hi)
    if lock:
        raise TaxError(lock)
    S, I, C = s["calc"]["101"], s["calc"]["107"], s["calc"]["108"]
    if S == 0 and I == 0:
        raise TaxError("本期沒有銷項與進項稅額，不需要結轉。")
    X = S - I - C
    lines = []
    if S:
        lines.append({"role": _R_OUT, "side": "D", "amount": S, "memo": "稅額結轉 銷項稅額"})
    if I:
        lines.append({"role": _R_IN, "side": "C", "amount": I, "memo": "稅額結轉 進項稅額"})
    if X > 0:
        if C:
            lines.append({"role": _R_CARRY, "side": "C", "amount": C, "memo": "稅額結轉 用完留抵"})
        lines.append({"role": _R_PAYABLE, "side": "C", "amount": X, "memo": "本期應實繳營業稅"})
        new_carry = 0
    else:
        new_carry = -X
        delta = new_carry - C
        if delta > 0:
            lines.append({"role": _R_CARRY, "side": "D", "amount": delta, "memo": "稅額結轉 新增留抵"})
        elif delta < 0:
            lines.append({"role": _R_CARRY, "side": "C", "amount": -delta, "memo": "稅額結轉 減少留抵"})
    old = settlement_row(conn, lo, hi)
    if old and old.get("voucher_id"):
        v = conn.execute("SELECT status, voided_at FROM vouchers_all WHERE id=?", (old["voucher_id"],)).fetchone()
        if v and not v["voided_at"]:
            if v["status"] != "草稿":
                raise TaxError("這一期的稅額結轉傳票已過帳／審核中；要重做請先沖轉或退回。")
            _engine._void_draft(conn, old["voucher_id"], user, "重新產生稅額結轉")
    ev = {"source_module": "accounting", "source_type": "tax_settlement", "source_key": "%s:%d" % (year, n), "event_code": "E14",
          "event_date": hi, "doc_no": "營業稅%04d年第%d期" % (year, n), "case_no": "", "party": {"key": "", "name": ""}, "tax_code": "",
          "mode": "snapshot", "lines": lines}
    resolved = _engine._resolve(conn, ev)
    vid, no = _engine._make_draft(conn, ev, resolved, user, event_id=0)
    conn.execute("UPDATE vouchers_all SET origin=? WHERE id=?", (_CARRY_ORIGIN, vid))
    now = _dt.datetime.now().isoformat(timespec="seconds")
    if old:
        conn.execute("UPDATE gl_tax_settlements SET output_tax=?, input_tax=?, carry_prev=?, payable=?, carry_new=?, voucher_id=?, status='draft', created_by=?, created_at=? WHERE id=?",
                     (S, I, C, max(0, X), new_carry, vid, user, now, old["id"]))
    else:
        conn.execute("INSERT INTO gl_tax_settlements(period_start, period_end, output_tax, input_tax, carry_prev, payable, carry_new, refund_amount, voucher_id, status, created_by, created_at)"
                     " VALUES (?,?,?,?,?,?,?,0,?,'draft',?,?)", (lo, hi, S, I, C, max(0, X), new_carry, vid, user, now))
    return {"voucher_id": vid, "voucher_no": no, "output_tax": S, "input_tax": I, "carry_prev": C, "payable": max(0, X), "carry_new": new_carry}
