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
import json

from modules.accounting.ledger import periods as _periods
from modules.accounting.ledger import roles as _roles

_KIND_BY_ROLE = {"WITHHOLD_TAX": "income_tax", "WITHHOLD_NHI": "nhi"}
KIND_LABEL = {"income_tax": "代扣所得稅", "nhi": "二代健保補充保費"}
_LABOR = "EXP_LABOR"
_SOURCE_EVENT = "E06"


class WithholdingError(ValueError):
    pass


MAX_IDS = 500                         # 一次登記／取消的上限
REPORT_LIMIT = 2000                   # 不指定月份時報表最多列數（超過標 truncated）
_today = lambda: _dt.date.today()     # noqa: E731  測試可換掉


def _ids(ids):
    if not isinstance(ids, list) or not ids or len(ids) > MAX_IDS:
        raise WithholdingError("請選擇 1～%d 筆項目（ids 要是整數清單）。" % MAX_IDS)
    try:
        out = [int(i) for i in ids]
    except (TypeError, ValueError):
        raise WithholdingError("ids 要是整數清單。")
    if any(isinstance(i, bool) for i in ids):
        raise WithholdingError("ids 要是整數清單。")
    return out


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


def record_native(conn, ev):
    """來源自己開了傳票的事件（例：獎金發放 E07b，mode=native）帶 `meta.withholding`＝[{kind, party_key, gross, amount}] 與 `meta.wh_prefix` ⇒ 記入清單；
    同一來源前綴下、這次沒有的未繳庫列移除（人員或金額變了）。"""
    m = ev.get("meta") or {}
    prefix = m.get("wh_prefix")
    if not prefix:
        return
    now = _dt.datetime.now().isoformat(timespec="seconds")
    keep = set()
    for it in m.get("withholding") or []:
        if it.get("kind") not in KIND_LABEL or not int(it.get("amount") or 0):
            continue
        key = "%s%s" % (prefix, it.get("party_key") or "")
        keep.add((it["kind"], key))
        conn.execute(
            "INSERT INTO gl_withholding_items(kind, source_type, source_key, party_key, income_type, gross, amount, period_ym, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(kind, source_type, source_key) DO UPDATE SET"
            " party_key=excluded.party_key, income_type=excluded.income_type, gross=excluded.gross, amount=excluded.amount, period_ym=excluded.period_ym"
            " WHERE gl_withholding_items.remitted_at=''",
            (it["kind"], ev["source_type"], key, it.get("party_key") or "", str(it.get("income_type") or "bonus"), int(it.get("gross") or 0), int(it["amount"]),
             ev["event_date"][:7], now))
    for r in conn.execute("SELECT id, kind, source_key FROM gl_withholding_items WHERE source_type=? AND source_key LIKE ? AND remitted_at=''",
                          (ev["source_type"], prefix + "%")).fetchall():
        if (r["kind"], r["source_key"]) not in keep:
            conn.execute("DELETE FROM gl_withholding_items WHERE id=?", (r["id"],))


def forget_native(conn, ev):
    """native 事件指向的傳票已不存在／已作廢 ⇒ 該來源前綴下未繳庫的扣繳列移除。"""
    prefix = (ev.get("meta") or {}).get("wh_prefix")
    if prefix:
        conn.execute("DELETE FROM gl_withholding_items WHERE source_type=? AND source_key LIKE ? AND remitted_at=''", (ev["source_type"], prefix + "%"))


def forget(conn, row):
    """事件列（gl_source_events 一列）消失／被取代／草稿被作廢 ⇒ 刪除該來源『未繳庫』的扣繳列。"""
    if row.get("event_code") != _SOURCE_EVENT:
        return
    conn.execute("DELETE FROM gl_withholding_items WHERE source_type=? AND source_key=? AND remitted_at=''", (row["source_type"], row["source_key"]))


def _names(conn, items):
    """每個項目加 `party_name`（畫面顯示姓名，不要只有『C1』這種編號）：先取來源事件裡的對象姓名（勞報單事件的 party.name），
    沒有就用使用者顯示名稱（獎金發放的對象是帳號），再沒有就退回編號。只讀。"""
    users = {}
    for it in items:
        name = ""
        r = conn.execute("SELECT payload_json FROM gl_source_events WHERE source_type=? AND source_key=? ORDER BY rev DESC LIMIT 1",
                         (it["source_type"], it["source_key"])).fetchone()
        if r:
            try:
                name = ((json.loads(r["payload_json"] or "{}").get("party") or {}).get("name") or "").strip()
            except ValueError:
                name = ""
        if not name and it["party_key"]:
            if it["party_key"] not in users:
                u = conn.execute("SELECT display_name FROM users WHERE username=?", (it["party_key"],)).fetchone()
                users[it["party_key"]] = (u["display_name"] if u else "") or ""
            name = users[it["party_key"]]
        it["party_name"] = name or it["party_key"]


def report(conn, ym=None, kind=None, today=None):
    """清單＋依（種類，所屬月）彙總＋逾期旗標＋與 2252 貸方發生額對帳。ym 給 'YYYY-MM' 只看該月。"""
    today = today or _dt.date.today().isoformat()
    q, args = "SELECT * FROM gl_withholding_items WHERE 1=1", []
    if ym:
        q, args = q + " AND period_ym=?", args + [ym]
    if kind:
        q, args = q + " AND kind=?", args + [kind]
    items = [dict(r) for r in conn.execute(q + " ORDER BY period_ym, kind, id" + ("" if ym else " LIMIT %d" % (REPORT_LIMIT + 1)), args)]
    truncated = len(items) > REPORT_LIMIT and not ym
    items = items[:REPORT_LIMIT] if truncated else items
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
    _names(conn, items)
    out = {"items": items, "groups": sorted(groups.values(), key=lambda x: (x["period_ym"], x["kind"])), "checks": [], "truncated": truncated}
    if ym:
        code = _roles.resolve_role(conn, "WITHHOLD_TAX", on_date=ym + "-28") or ""
        lo, hi = ym + "-01", "%s-%02d" % (ym, calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1])
        credit = conn.execute(
            "SELECT COALESCE(SUM(l.credit),0) FROM voucher_lines l JOIN vouchers_all v ON v.id=l.voucher_id WHERE v.status='已過帳' AND v.voided_at=''"
            " AND v.kind<>'closing' AND l.account_code=? AND substr(v.voucher_date,1,10) BETWEEN ? AND ?", (code, lo, hi)).fetchone()[0] if code else 0
        listed = sum(i["amount"] for i in items)
        if code:
            out["checks"].append({"key": "vs_account", "label": "清單合計 ＝ 代扣科目 %s 當月貸方發生額" % code, "left": int(listed), "right": int(credit),
                                  "ok": int(listed) == int(credit),
                                  "note": "不符多半是尚未進清單的來源（例：獎金代扣）或該月傳票尚未過帳。"})
        else:                                                              # 沒有代扣科目可對：明說怎麼辦（不是拿 0 去比一個看不懂的不符）
            out["checks"].append({"key": "vs_account", "label": "清單合計 ＝ 代扣科目當月貸方發生額（代扣科目尚未設定）", "left": int(listed), "right": 0, "ok": False,
                                  "note": "請先到「總帳設定」把角色「代扣所得稅」對應到代扣科目（通常是 2252），再回到這裡核對。"})
    return out


def mark_remitted(conn, ids, remitted_at, voucher_no=""):
    """登記繳庫。驗證（D4）：繳庫日不可在未來、不可早於該筆所屬月、不可落在已結帳／鎖定期間；連了傳票單號就必須是已過帳、未作廢、
    且有借記代扣科目（2252）的傳票。"""
    try:
        d = _dt.date.fromisoformat(str(remitted_at)).isoformat()
    except ValueError:
        raise WithholdingError("繳庫日要是 YYYY-MM-DD。")
    ids = _ids(ids)
    if d > _today().isoformat():
        raise WithholdingError("繳庫日 %s 在未來：只能登記已經發生的繳庫。" % d)
    lock = _periods.lock_error(conn, d)
    if lock:
        raise WithholdingError(lock + "繳庫日落在已結帳期間，請重開期間或改用當期日期。")
    rows = conn.execute("SELECT id, period_ym, remitted_at FROM gl_withholding_items WHERE id IN (%s)" % ",".join("?" * len(ids)), ids).fetchall()
    early = [r["id"] for r in rows if d < r["period_ym"] + "-01"]
    if early:
        raise WithholdingError("繳庫日 %s 早於所屬月份（項目 %s）。" % (d, "、".join(str(x) for x in early[:5])))
    vid = None
    if voucher_no:
        r = conn.execute("SELECT id, status, voided_at FROM vouchers_all WHERE voucher_no=?", (voucher_no,)).fetchone()
        if r is None or r["voided_at"]:
            raise WithholdingError("查無有效的傳票單號 %s。" % voucher_no)
        if r["status"] != "已過帳":
            raise WithholdingError("傳票 %s 尚未過帳（%s）：繳庫要連到已過帳的付款傳票。" % (voucher_no, r["status"]))
        codes = {c for c in (_roles.resolve_role(conn, "WITHHOLD_TAX", on_date=d), _roles.resolve_role(conn, "WITHHOLD_NHI", on_date=d)) if c}
        if not codes or not conn.execute("SELECT 1 FROM voucher_lines WHERE voucher_id=? AND debit>0 AND account_code IN (%s) LIMIT 1" % ",".join("?" * len(codes)),
                                         [r["id"]] + sorted(codes)).fetchone():
            raise WithholdingError("傳票 %s 沒有借記代扣科目（%s）：這不是繳庫傳票。" % (voucher_no, "、".join(sorted(codes)) or "未設定"))
        vid = r["id"]
    n = 0
    for i in ids:
        n += conn.execute("UPDATE gl_withholding_items SET remitted_at=?, remit_voucher_id=? WHERE id=? AND remitted_at=''", (d, vid, i)).rowcount
    return n


def unmark_remitted(conn, ids, reason=""):
    """取消繳庫登記：必填原因；該筆原繳庫日落在已結帳／鎖定期間 ⇒ 拒絕。回 `{"updated": n, "previous": [(id, 原繳庫日, 原傳票id)]}`（給稽核記舊狀態）。"""
    if not str(reason or "").strip():
        raise WithholdingError("取消繳庫要填原因。")
    ids = _ids(ids)
    prev = [(r["id"], r["remitted_at"], r["remit_voucher_id"]) for r in conn.execute(
        "SELECT id, remitted_at, remit_voucher_id FROM gl_withholding_items WHERE id IN (%s) AND remitted_at<>''" % ",".join("?" * len(ids)), ids)]
    for _id, at, _v in prev:
        lock = _periods.lock_error(conn, at)
        if lock:
            raise WithholdingError("項目 %d 的繳庫日 %s 落在已結帳期間：%s" % (_id, at, lock))
    n = sum(conn.execute("UPDATE gl_withholding_items SET remitted_at='', remit_voucher_id=NULL WHERE id=? AND remitted_at<>''", (i,)).rowcount for i in ids)
    return {"updated": n, "previous": prev}
