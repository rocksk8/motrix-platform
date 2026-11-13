# -*- coding: utf-8 -*-
"""IP-118（暫定號，列車定號）`stock.receive`：一站式到貨的「入庫那一半」（M01 案件 → M03 庫存；一條龍 P2a，旗標 `onepipe.receive_ledger`）。

[單位] supply:receive    [層] L2    [穩定度] 實驗
[公開介面] can_receive, receive, undo_receipt（IP-122 `stock.receive_undo`）, MAX_SERIALS_PER_LINE
[不變式] 吃**呼叫端的連線、不 commit**（比照 `stock.serial` 的 `claim`／`release`）：呼叫端（案件側到貨確認）先 `begin_write` 拿寫鎖，
         案件那一半（確認到貨）與這裡的庫存寫入在同一筆交易、同時成立或同時撤回；本檔不 import 任何其他 L2 模組。
         旗標 `onepipe.receive_ledger` 關 ⇒ 一律不動（回 `{"ok": False, "reason": "DISABLED"}`）。
         沒有入庫權限 ⇒ 不寫任何庫存（回 `{"ok": False, "reason": "NO_PERMISSION"}`），呼叫端只做案件那一半並明示（D9）。
         逐列回報：重複序號、空白序號、已存在於庫存的序號**不寫、不擋其他列**；一列最多 `MAX_SERIALS_PER_LINE` 筆（超過 ⇒ 該列整列不寫）。
         `caller=None` ＝**可信的內部呼叫端**（不檢查入庫權限）：API 處理函式一律要傳入目前使用者，不可傳 None。
         入庫權限：目前＝管理員（與 `POST /api/inventory/batches` 相同）；P2-pre（`onepipe.receive_permission`）上線後由 `can_receive` 一處放寬，其他地方不必改。
"""
from datetime import datetime

from db import next_entity_code
from modules.supply import stock_events

MAX_SERIALS_PER_LINE = 50
_MODES = ("stock", "direct", "consumable")
_HEADER_PREFIX = {"direct": "DR", "consumable": "CN"}      # 只留批次表頭、不建序號列的到貨方式


def can_receive(user) -> bool:
    """這個人能不能入庫（建立進貨批次）。與 `inventory._require_admin` 同一規則（P2-pre 之後由這裡放寬）。"""
    return bool(user) and user.get("role") in ("superadmin", "admin")


def _reject_all(line_rows, serials, reason):
    return [{"serialNo": (s.get("serialNo") or s.get("serial_no") or "").strip(), "status": "rejected", "reason": reason} for s in serials]


def receive(conn, quote_no, lines, caller=None) -> dict:
    """⇒ `{"ok": True, "batches": [{"batchNo", "partNo", "materialItemId", "poDocCode", "mode", "written": N, "rows": [{"serialNo", "status": "written"|"rejected", "reason"}]}],
    "written": 總台數, "rejected": 總拒收數}`；整體做不了 ⇒ `{"ok": False, "reason": "DISABLED"|"NO_PERMISSION"|"NO_CASE"}`。

    `lines`：`[{"partNo", "materialItemId", "poDocCode", "supplierId", "invoiceNo", "cost", "note", "mode": "stock"|"direct", "serials": [{"serialNo", "mac", "note"}]}]`。
    `direct`（D1＝A 直送客戶現場）：不建序號列，只留一筆批次表頭（`delivery_mode='direct'`）供對帳；序號之後在案件設備清單登載。
    `consumable`（D2＋D8＝A 耗材到貨即現場領用）：同樣只留一筆表頭（`delivery_mode='consumable'`），讓對帳表視為「已處理」；**不需入庫權限**（沒有庫存可動）。"""
    if not stock_events.ledger_on(conn):
        return {"ok": False, "reason": "DISABLED"}
    qn = str(quote_no or "").strip()
    if not qn:
        return {"ok": False, "reason": "NO_CASE"}
    only_consumable = bool(lines) and all((ln.get("mode") or "stock").strip() == "consumable" for ln in lines)
    if caller is not None and not only_consumable and not can_receive(caller):
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
        problem = _line_problem(conn, qn, mid, mode, ln)
        if mode not in _MODES:
            res["rows"] = _reject_all(None, serials, "不支援的到貨方式")
        elif problem:
            res["error"] = problem
            res["rows"] = _reject_all(None, serials, problem)
        elif mode in _HEADER_PREFIX:
            _direct(conn, qn, ln, res, actor, now, mode)
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


def _line_problem(conn, qn, mid, mode, ln):
    """這一列不能寫的原因（空字串＝可以）。
    1. 有給 `materialItemId` 時，那筆材料申請必須屬於這個案件且已確認到貨（經 `material.shippable` 提供者；M01 不在就略過這項檢查）。
    2. 直送／耗材：同一筆材料申請已經有同方式的批次 ⇒ 擋下（避免重複送出；分批到貨由呼叫端明確帶 `additional=True`，數量上限由案件側管）。"""
    if mid:
        from core import registry
        fn = registry.single_provider("material.shippable")
        if fn is not None:
            try:
                known = {str(r.get("materialItemId")) for r in (fn(conn, qn) or [])}
            except Exception:                                                            # noqa: BLE001 — 提供者出錯不擋入庫（對帳表仍會列出）
                known = None
            if known is not None and mid not in known:
                return "這筆材料申請不屬於這個案件，或尚未確認到貨"
    if mode in _HEADER_PREFIX and mid and not ln.get("additional"):
        if conn.execute("SELECT 1 FROM stock_batches WHERE quote_no=? AND material_item_id=? AND delivery_mode=?", (qn, mid, mode)).fetchone():
            return "這筆材料申請已經登載過%s，請勿重複送出" % ("直送" if mode == "direct" else "耗材")
    return ""


def _direct(conn, qn, ln, res, actor, now, mode="direct"):
    batch_no = next_entity_code(conn, "stock_batches", _HEADER_PREFIX[mode], code_col="batch_no")
    sid = ln.get("supplierId")
    sname = ""
    if sid:
        row = conn.execute("SELECT name FROM suppliers WHERE id=?", (sid,)).fetchone()
        sname = row["name"] if row else ""
    conn.execute("INSERT INTO stock_batches (batch_no, part_no, supplier_id, supplier_name, invoice_no, note, created_by, created_at, updated_at,"
                 " quote_no, po_doc_code, material_item_id, delivery_mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (batch_no, res["partNo"], sid, sname, (ln.get("invoiceNo") or "").strip(), ln.get("note") or "", actor, now, now, qn, res["poDocCode"], res["materialItemId"], mode))
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


def undo_receipt(conn, quote_no, item_id, caller=None) -> dict:
    """IP-122（暫定號）`stock.receive_undo`：案件側撤銷「確認到貨」時，把庫存那一半一起收回（吃呼叫端連線、不 commit）。
    ⇒ `{"ok": True, "removed": N}`（N＝刪掉的批次表頭數：直送／耗材／沒有序號列的入庫表頭）｜`{"ok": False, "reason": "DISABLED"}`｜
    `{"ok": False, "reason": "BLOCKED", "message": …}`＝已有為這筆材料申請入庫的序號（不論現在狀態），或批次已登記付款 ⇒ **不動任何東西**，請先在庫存處理（出貨單／刪除序號／取消付款）。
    直送、耗材沒有序號，撤銷時直接刪表頭，讓「重新登載」不會被「已登載過直送」擋住、對帳表也不留殘影。"""
    if not stock_events.ledger_on(conn):
        return {"ok": False, "reason": "DISABLED"}
    qn, mid = str(quote_no or "").strip(), str(item_id or "").strip()
    if not qn or not mid:
        return {"ok": True, "removed": 0}
    if conn.execute("SELECT 1 FROM stock_items si JOIN stock_batches sb ON sb.batch_no = si.batch_no WHERE sb.quote_no=? AND si.material_item_id=? LIMIT 1", (qn, mid)).fetchone():
        return {"ok": False, "reason": "BLOCKED", "message": "這筆材料申請已有入庫的序號，請先在庫存處理（出貨或刪除序號）後再撤銷到貨"}
    if conn.execute("SELECT 1 FROM stock_batches WHERE quote_no=? AND material_item_id=? AND (is_paid=1 OR COALESCE(paid_at,'')<>'') LIMIT 1", (qn, mid)).fetchone():
        return {"ok": False, "reason": "BLOCKED", "message": "此到貨批次已登記付款，請先在庫存取消付款後再撤銷到貨"}
    cur = conn.execute("DELETE FROM stock_batches WHERE quote_no=? AND material_item_id=?", (qn, mid))
    return {"ok": True, "removed": cur.rowcount}

