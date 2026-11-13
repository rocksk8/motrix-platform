# -*- coding: utf-8 -*-
"""IP-118（暫定號，列車定號）`stock.receive`：一站式到貨的「入庫那一半」（M01 案件 → M03 庫存；一條龍 P2a，旗標 `onepipe.receive_ledger`）。

[單位] supply:receive    [層] L2    [穩定度] 實驗
[公開介面] can_receive, receive, MAX_SERIALS_PER_LINE
[不變式] 吃**呼叫端的連線、不 commit**（比照 `stock.serial` 的 `claim`／`release`）：呼叫端（案件側到貨確認）先 `begin_write` 拿寫鎖，
         案件那一半（確認到貨）與這裡的庫存寫入在同一筆交易、同時成立或同時撤回；本檔不 import 任何其他 L2 模組。
         旗標 `onepipe.receive_ledger` 關 ⇒ 一律不動（回 `{"ok": False, "reason": "DISABLED"}`）。
         沒有入庫權限 ⇒ 不寫任何庫存（回 `{"ok": False, "reason": "NO_PERMISSION"}`），呼叫端只做案件那一半並明示（D9）。
         逐列回報：重複序號、空白序號、已存在於庫存的序號**不寫、不擋其他列**；一列最多 `MAX_SERIALS_PER_LINE` 筆（超過 ⇒ 該列整列不寫）。
         入庫權限：目前＝管理員（與 `POST /api/inventory/batches` 相同）；P2-pre（`onepipe.receive_permission`）上線後由 `can_receive` 一處放寬，其他地方不必改。
"""
from datetime import datetime

from db import next_entity_code
from modules.supply import stock_events

MAX_SERIALS_PER_LINE = 50
_MODES = ("stock", "direct")


def can_receive(user) -> bool:
    """這個人能不能入庫（建立進貨批次）。與 `inventory._require_admin` 同一規則（P2-pre 之後由這裡放寬）。"""
    return bool(user) and user.get("role") in ("superadmin", "admin")


def _reject_all(line_rows, serials, reason):
    return [{"serialNo": (s.get("serialNo") or s.get("serial_no") or "").strip(), "status": "rejected", "reason": reason} for s in serials]


def receive(conn, quote_no, lines, caller=None) -> dict:
    """⇒ `{"ok": True, "batches": [{"batchNo", "partNo", "materialItemId", "poDocCode", "mode", "written": N, "rows": [{"serialNo", "status": "written"|"rejected", "reason"}]}],
    "written": 總台數, "rejected": 總拒收數}`；整體做不了 ⇒ `{"ok": False, "reason": "DISABLED"|"NO_PERMISSION"|"NO_CASE"}`。

    `lines`：`[{"partNo", "materialItemId", "poDocCode", "supplierId", "invoiceNo", "cost", "note", "mode": "stock"|"direct", "serials": [{"serialNo", "mac", "note"}]}]`。
    `direct`（D1＝A 直送客戶現場）：不建序號列，只留一筆批次表頭（`delivery_mode='direct'`）供對帳；序號之後在案件設備清單登載。"""
    if not stock_events.ledger_on(conn):
        return {"ok": False, "reason": "DISABLED"}
    qn = str(quote_no or "").strip()
    if not qn:
        return {"ok": False, "reason": "NO_CASE"}
    if caller is not None and not can_receive(caller):
        return {"ok": False, "reason": "NO_PERMISSION"}
    actor = ((caller or {}).get("display_name") or (caller or {}).get("username") or "") if caller else ""
    now = datetime.now().isoformat()
    out = {"ok": True, "batches": [], "written": 0, "rejected": 0}
    for ln in (lines or []):
        mode = (ln.get("mode") or "stock").strip()
        part_no = (ln.get("partNo") or ln.get("part_no") or "").strip()
        mid = str(ln.get("materialItemId") or "").strip()
        po = str(ln.get("poDocCode") or "").strip()
        serials = [s for s in (ln.get("serials") or []) if isinstance(s, dict)]
        res = {"batchNo": "", "partNo": part_no, "materialItemId": mid, "poDocCode": po, "mode": mode if mode in _MODES else "stock", "written": 0, "rows": []}
        out["batches"].append(res)
        if mode not in _MODES:
            res["rows"] = _reject_all(None, serials, "不支援的到貨方式")
        elif mode == "direct":
            _direct(conn, qn, ln, res, actor, now)
        elif not part_no:
            res["rows"] = _reject_all(None, serials, "料號不得為空")
        elif len(serials) > MAX_SERIALS_PER_LINE:
            res["rows"] = _reject_all(None, serials, "一次最多 %d 筆序號" % MAX_SERIALS_PER_LINE)
        elif not serials:
            res["rows"] = []
        else:
            _stock(conn, qn, ln, part_no, mid, po, serials, res, actor, now)
        out["written"] += res["written"]
        out["rejected"] += sum(1 for r in res["rows"] if r["status"] == "rejected")
    return out


def _direct(conn, qn, ln, res, actor, now):
    batch_no = next_entity_code(conn, "stock_batches", "DR", code_col="batch_no")
    sid = ln.get("supplierId")
    sname = ""
    if sid:
        row = conn.execute("SELECT name FROM suppliers WHERE id=?", (sid,)).fetchone()
        sname = row["name"] if row else ""
    conn.execute("INSERT INTO stock_batches (batch_no, part_no, supplier_id, supplier_name, invoice_no, note, created_by, created_at, updated_at,"
                 " quote_no, po_doc_code, material_item_id, delivery_mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'direct')",
                 (batch_no, res["partNo"], sid, sname, (ln.get("invoiceNo") or "").strip(), ln.get("note") or "", actor, now, now, qn, res["poDocCode"], res["materialItemId"]))
    res["batchNo"] = batch_no


def _stock(conn, qn, ln, part_no, mid, po, serials, res, actor, now):
    part = conn.execute("SELECT part_no, cost FROM parts WHERE part_no=? AND active=1", (part_no,)).fetchone()
    if not part:
        res["rows"] = _reject_all(None, serials, "料號不存在")
        return
    clean, seen = [], set()
    for s in serials:
        sn = (s.get("serialNo") or s.get("serial_no") or "").strip()
        if not sn:
            res["rows"].append({"serialNo": "", "status": "rejected", "reason": "序號空白"})
        elif sn in seen:
            res["rows"].append({"serialNo": sn, "status": "rejected", "reason": "重複（同一次貼上）"})
        else:
            seen.add(sn)
            clean.append({"serial_no": sn, "mac": (s.get("mac") or "").strip(), "note": s.get("note") or ""})
    existing = set()
    if clean:
        marks = ",".join("?" * len(clean))
        existing = {r["serial_no"] for r in conn.execute("SELECT serial_no FROM stock_items WHERE part_no=? AND serial_no IN (%s)" % marks,
                                                         [part_no] + [c["serial_no"] for c in clean]).fetchall()}
    ok = []
    for c in clean:
        if c["serial_no"] in existing:
            res["rows"].append({"serialNo": c["serial_no"], "status": "rejected", "reason": "序號已存在於庫存"})
        else:
            ok.append(c)
    if not ok:
        return
    batch_no = next_entity_code(conn, "stock_items", "PO", code_col="batch_no")
    cost = ln.get("cost")
    if cost is None:
        cost = part["cost"] or 0
    sid = ln.get("supplierId")
    sname = ""
    if sid:
        row = conn.execute("SELECT name FROM suppliers WHERE id=?", (sid,)).fetchone()
        sname = row["name"] if row else ""
    note = ln.get("note") or ""
    for c in ok:
        cur = conn.execute("INSERT INTO stock_items (part_no, serial_no, mac, status, batch_no, cost, note, created_by, created_at, updated_at, material_item_id)"
                           " VALUES (?,?,?,'in_stock',?,?,?,?,?,?,?)",
                           (part_no, c["serial_no"], c["mac"], batch_no, cost, c["note"] or note, actor, now, now, mid))
        stock_events.record(conn, event="receive", part_no=part_no, serial_no=c["serial_no"], stock_item_id=cur.lastrowid, to_status="in_stock",
                            quote_no=qn, ref=batch_no, actor=actor, now=now)
        res["rows"].append({"serialNo": c["serial_no"], "status": "written", "reason": ""})
    conn.execute("INSERT INTO stock_batches (batch_no, part_no, supplier_id, supplier_name, invoice_no, note, created_by, created_at, updated_at,"
                 " quote_no, po_doc_code, material_item_id, delivery_mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'stock')",
                 (batch_no, part_no, sid, sname, (ln.get("invoiceNo") or "").strip(), note, actor, now, now, qn, po, mid))
    res["batchNo"] = batch_no
    res["written"] = len(ok)
