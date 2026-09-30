# -*- coding: utf-8 -*-
"""扣繳（代扣所得稅、二代健保補充保費）應繳未繳清單（C5；proposal-gl/02 E06、09 #18/#20）。

- 來源：引擎為勞報單應付（E06）產生草稿時，把該事件的 `WITHHOLD_TAX`／`WITHHOLD_NHI` 行記入 `gl_withholding_items`
  （鍵＝種類＋來源類型＋來源鍵，冪等；未繳庫的可隨來源更新，來源消失／草稿被作廢 ⇒ 刪除未繳庫的列；已繳庫的列保留）。
- 期限（採用值，待使用者確認）：所得稅代扣款次月 10 日前（所得稅法 §92）、補充保費次月底前（全民健康保險法 §31）。
- 繳庫：出納／會計實際繳款後在這裡登記繳庫日（可連到繳庫傳票單號）；分錄本身由會計以手工傳票（借 2252／貸銀行）處理。
- 對帳：清單合計 vs 代扣科目（2252）當月貸方發生額（獎金代扣尚未進清單，會在差額中看得到，不會被掩蓋）。
所有函式不 commit。
"""
import calendar
import datetime as _dt

from modules.accounting.ledger import roles as _roles

_KIND_BY_ROLE = {"WITHHOLD_TAX": "income_tax", "WITHHOLD_NHI": "nhi"}
KIND_LABEL = {"income_tax": "代扣所得稅", "nhi": "二代健保補充保費"}
_LABOR = "EXP_LABOR"
_SOURCE_EVENT = "E06"


class WithholdingError(ValueError):
    pass


def due_date(kind, period_ym):
    """繳庫期限：所得稅＝次月 10 日；補充保費＝次月底。"""
    y, m = int(period_ym[:4]), int(period_ym[5:7])
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    return "%04d-%02d-10" % (y2, m2) if kind == "income_tax" else "%04d-%02d-%02d" % (y2, m2, calendar.monthrange(y2, m2)[1])


def record(conn, ev):
    """事件（已產生草稿）⇒ 記入扣繳清單。只處理勞報單應付 E06；已繳庫的列不動。"""
    if ev.get("event_code") != _SOURCE_EVENT:
        return
    gross = sum(l["amount"] for l in ev.get("lines", []) if l.get("role") == _LABOR and l.get("side") == "D")
    meta = ev.get("meta") or {}
    now = _dt.datetime.now().isoformat(timespec="seconds")
    for l in ev.get("lines", []):
        kind = _KIND_BY_ROLE.get(l.get("role"))
        if not kind or not l.get("amount"):
            continue
        conn.execute(
            "INSERT INTO gl_withholding_items(kind, source_type, source_key, party_key, income_type, gross, amount, period_ym, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(kind, source_type, source_key) DO UPDATE SET"
            " party_key=excluded.party_key, income_type=excluded.income_type, gross=excluded.gross, amount=excluded.amount, period_ym=excluded.period_ym"
            " WHERE gl_withholding_items.remitted_at=''",
            (kind, ev["source_type"], ev["source_key"], (ev.get("party") or {}).get("key") or "", str(meta.get("income_type") or ""),
             int(gross), int(l["amount"]), ev["event_date"][:7], now))


def forget(conn, row):
    """事件列（gl_source_events 一列）消失／被取代／草稿被作廢 ⇒ 刪除該來源『未繳庫』的扣繳列。"""
    if row.get("event_code") != _SOURCE_EVENT:
        return
    conn.execute("DELETE FROM gl_withholding_items WHERE source_type=? AND source_key=? AND remitted_at=''", (row["source_type"], row["source_key"]))


def report(conn, ym=None, kind=None, today=None):
    """清單＋依（種類，所屬月）彙總＋逾期旗標＋與 2252 貸方發生額對帳。ym 給 'YYYY-MM' 只看該月。"""
    today = today or _dt.date.today().isoformat()
    q, args = "SELECT * FROM gl_withholding_items WHERE 1=1", []
    if ym:
        q, args = q + " AND period_ym=?", args + [ym]
    if kind:
        q, args = q + " AND kind=?", args + [kind]
    items = [dict(r) for r in conn.execute(q + " ORDER BY period_ym, kind, id", args)]
    groups = {}
    for it in items:
        g = groups.setdefault((it["period_ym"], it["kind"]), {"period_ym": it["period_ym"], "kind": it["kind"], "label": KIND_LABEL.get(it["kind"], it["kind"]),
                                                                "due": due_date(it["kind"], it["period_ym"]), "count": 0, "total": 0, "unremitted": 0})
        g["count"] += 1
        g["total"] += it["amount"]
        if not it["remitted_at"]:
            g["unremitted"] += it["amount"]
    for g in groups.values():
        g["overdue"] = bool(g["unremitted"] and today > g["due"])
    out = {"items": items, "groups": sorted(groups.values(), key=lambda x: (x["period_ym"], x["kind"])), "checks": []}
    if ym:
        code = _roles.resolve_role(conn, "WITHHOLD_TAX", on_date=ym + "-28") or ""
        lo, hi = ym + "-01", "%s-%02d" % (ym, calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1])
        credit = conn.execute(
            "SELECT COALESCE(SUM(l.credit),0) FROM voucher_lines l JOIN vouchers_all v ON v.id=l.voucher_id WHERE v.status='已過帳' AND v.voided_at=''"
            " AND v.kind<>'closing' AND l.account_code=? AND substr(v.voucher_date,1,10) BETWEEN ? AND ?", (code, lo, hi)).fetchone()[0] if code else 0
        listed = sum(i["amount"] for i in items)
        out["checks"].append({"key": "vs_account", "label": "清單合計 ＝ 代扣科目 %s 當月貸方發生額" % (code or "（未設定）"), "left": int(listed), "right": int(credit),
                              "ok": int(listed) == int(credit),
                              "note": "不符多半是尚未進清單的來源（例：獎金代扣）或該月傳票尚未過帳。"})
    return out


def mark_remitted(conn, ids, remitted_at, voucher_no=""):
    try:
        _dt.date.fromisoformat(str(remitted_at))
    except ValueError:
        raise WithholdingError("繳庫日要是 YYYY-MM-DD。")
    ids = [int(i) for i in ids]
    if not ids:
        raise WithholdingError("請選擇要登記繳庫的項目。")
    vid = None
    if voucher_no:
        r = conn.execute("SELECT id, voided_at FROM vouchers_all WHERE voucher_no=?", (voucher_no,)).fetchone()
        if r is None or r["voided_at"]:
            raise WithholdingError("查無有效的傳票單號 %s。" % voucher_no)
        vid = r["id"]
    n = 0
    for i in ids:
        n += conn.execute("UPDATE gl_withholding_items SET remitted_at=?, remit_voucher_id=? WHERE id=? AND remitted_at=''", (str(remitted_at), vid, i)).rowcount
    return n


def unmark_remitted(conn, ids):
    ids = [int(i) for i in ids]
    return sum(conn.execute("UPDATE gl_withholding_items SET remitted_at='', remit_voucher_id=NULL WHERE id=? AND remitted_at<>''", (i,)).rowcount for i in ids)
