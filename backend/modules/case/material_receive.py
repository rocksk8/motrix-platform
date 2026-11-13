# -*- coding: utf-8 -*-
"""一條龍 P2b「一站式到貨」：在已核准的材料申請上登載到貨（旗標 `onepipe.receive_wizard`）。

[單位] case:material_receive    [層] L2    [穩定度] 實驗
[公開介面] receive_stock, parse_serials, MODES, MAX_SERIALS
[決策] D1＝A 到貨二選一（入庫／直送客戶現場）、D2＋D8＝A 耗材到貨即視為現場領用（不進庫存、不做領料單）、D7＝A 已到數量分批累計。
[不變式] 吃**呼叫端的連線、不 commit**：案件這一半（已到數量、到貨日）與庫存那一半（經 IP-118 `stock.receive`）在同一筆交易，
         庫存那一半的整列被擋（直送重複、材料申請不屬於該案）⇒ 整筆回滾（呼叫端不 commit 就關連線）。
         本檔不 import 任何其他 L2 模組（庫存只經 registry 的 `stock.receive`）；沒有庫存模組或呼叫者無入庫權限 ⇒ 只做案件這一半並明示（D9），
         之後由入庫對帳表（IP-119）列出供管理員補入庫（`supplement=True`）。
[預設（決策紀錄沒寫、本檔自訂）] 超收（累計超過申請數量）⇒ 409 擋下；到貨日記最近一次登載的日期；序號一次最多 50 筆（超過整筆 400、什麼都不寫）；
         序號筆數不得多於這次到貨數量；`supplement`（補入庫）不動已到數量與到貨日、只寫庫存那一半，用於「已全數確認到貨、庫存還沒有」的清單。
"""
import re
from datetime import datetime

from core import registry
from helpers.validation import body_flag
from modules.case import material_approval as MA
from modules.case import purchase_items as PI

MODES = ("stock", "direct", "consumable")
MAX_SERIALS = 50
_SPLIT = re.compile(r"[\r\n,;，；\t]+")


def parse_serials(body) -> list:
    """`body.serials`（字串或 `{serialNo, mac}` 的清單）或 `body.serialsText`（貼上的多行／逗號／分號／Tab 分隔文字）⇒ `[{"serialNo", "mac"}]`（保留順序；空白列略過、重複留給庫存那一半逐列回報）。
    文字裡一行 `序號<Tab>MAC` 也行（CSV 貼上）。"""
    out = []
    raw = body.get("serials")
    if isinstance(raw, list):
        for s in raw:
            if isinstance(s, dict):
                sn, mac = str(s.get("serialNo") or "").strip(), str(s.get("mac") or "").strip()
            else:
                sn, mac = str(s or "").strip(), ""
            if sn:
                out.append({"serialNo": sn, "mac": mac})
    text = body.get("serialsText")
    if isinstance(text, str) and text.strip():
        for line in text.splitlines():
            parts = [p.strip() for p in re.split(r"[\t,;，；]", line) if p.strip()]
            if not parts:
                continue
            if len(parts) == 2 and re.fullmatch(r"[0-9A-Fa-f]{2}([:\-.]?[0-9A-Fa-f]{2}){5}", parts[1]):
                out.append({"serialNo": parts[0], "mac": parts[1]})
            else:
                out.extend({"serialNo": p, "mac": ""} for p in parts)
    return out


def _qty(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n == n and n not in (float("inf"), float("-inf")) else None


def _clean(n):
    return int(n) if float(n).is_integer() else round(float(n), 4)


def receive_stock(conn, quote_no, item_id, order, body, user) -> dict:
    """⇒ `{"receivedOn", "receivedQty", "appliedQty", "remaining", "mode", "supplement", "stock": {...}}`；不合法 ⇒ raise `MA.MaterialApprovalError(status, message)`。
    `stock`＝`{"ok": True, "batches": [...], "written", "rejected"}`（逐列回報）｜`{"ok": False, "reason": "NO_PERMISSION"|"DISABLED"|"NO_STOCK_MODULE"|"NO_CASE"|"NO_PART"}`｜`{"skipped": "consumable"}`（耗材但庫存側不可用，只做案件這一半）。
    入庫方式沒給料號（只有案件權限的使用者）⇒ 只做案件這一半、`stock.reason="NO_PART"`（序號不寫，請管理員從對帳表補入庫）。
    案件可見性（`require_case`）與寫鎖（`begin_write`）由呼叫端先做。"""
    body = body or {}
    row = MA.get(conn, quote_no, item_id)
    if row is None or row["status"] != MA.S_APPROVED:
        raise MA.MaterialApprovalError(409, "只有已核准的材料申請才能登載到貨")
    mode = str(body.get("mode") or "stock").strip()
    if mode not in MODES:
        raise MA.MaterialApprovalError(400, "到貨方式只能是入庫、直送客戶現場或耗材")
    supplement = body_flag(body, "supplement")
    serials = parse_serials(body)
    if len(serials) > MAX_SERIALS:
        raise MA.MaterialApprovalError(400, "序號一次最多 %d 筆，請分次登載（目前 %d 筆）" % (MAX_SERIALS, len(serials)))
    if mode == "consumable" and serials:
        raise MA.MaterialApprovalError(400, "耗材沒有序號；有序號的貨請選入庫或直送客戶現場")
    applied = PI._num(order.get("quantity")) if isinstance(order, dict) else 0
    part_no = str(body.get("partNo") or "").strip()
    if mode == "stock" and not part_no and supplement:
        raise MA.MaterialApprovalError(400, "補入庫請先選料號")
    try:
        day = MA.normalize_date(body.get("receivedOn") or datetime.now().strftime("%Y-%m-%d"), "到貨日期")
    except Exception as e:                                                       # noqa: BLE001  HTTPException 或 ValueError：統一成 400
        raise MA.MaterialApprovalError(400, getattr(e, "detail", None) or str(e))

    already = bool(str(row["received_on"] or "").strip())
    prev_raw = row["received_qty"] if "received_qty" in row.keys() else None
    prev = applied if (already and prev_raw is None) else (_qty(prev_raw) or 0.0)          # 舊的「確認到貨」＝全數到貨
    if supplement:
        if not already:
            raise MA.MaterialApprovalError(409, "這筆材料申請尚未確認到貨，請先登載到貨")
        if mode == "consumable":
            raise MA.MaterialApprovalError(400, "耗材不進庫存，沒有補入庫")
        if not serials and mode == "stock":
            raise MA.MaterialApprovalError(400, "補入庫請貼上序號")
        qty, total = 0.0, prev
    else:
        qty = _qty(body.get("qty"))
        if qty is None and serials:
            qty = float(len(serials))
        if qty is None or qty <= 0:
            raise MA.MaterialApprovalError(400, "請填這次到貨的數量")
        if len(serials) > qty:
            raise MA.MaterialApprovalError(400, "序號筆數（%d）不能多於這次到貨數量（%s）" % (len(serials), _clean(qty)))
        total = prev + qty
        if applied <= 0:
            raise MA.MaterialApprovalError(409, "這筆材料申請沒有填申請數量，無法分批累計到貨，請先補上數量")
        if total > applied + 1e-9:
            raise MA.MaterialApprovalError(409, "已到 %s／申請 %s，這次最多還能登載 %s" % (_clean(prev), _clean(applied), _clean(max(applied - prev, 0))))

    now = MA._now()
    if not supplement:
        conn.execute("UPDATE case_material_approvals SET received_on=?, received_by=?, received_at=?, received_qty=?, updated_at=? WHERE quote_no=? AND item_id=?",
                     (day, user["username"], now, total, now, quote_no, str(item_id)))
    stock = _stock_half(conn, quote_no, order, row, mode, part_no, serials, body, user, additional=bool(prev > 0 and not supplement))
    return {"receivedOn": day if not supplement else row["received_on"], "receivedQty": _clean(total), "appliedQty": _clean(applied), "remaining": _clean(max(applied - total, 0)),
            "mode": mode, "supplement": supplement, "stock": stock}


def _stock_half(conn, quote_no, order, row, mode, part_no, serials, body, user, additional) -> dict:
    fn = registry.single_provider("stock.receive")
    if mode == "consumable":                                                      # D2＋D8＝A：耗材到貨即視為現場領用，不進庫存；只留一筆批次表頭讓對帳表視為已處理
        if fn is None:
            return {"skipped": "consumable"}
    elif fn is None:
        return {"ok": False, "reason": "NO_STOCK_MODULE"}
    elif mode == "stock" and not part_no:
        return {"ok": False, "reason": "NO_PART"}
    line = {"partNo": part_no, "materialItemId": str(row["item_id"]), "poDocCode": str((order or {}).get("poDocCode") or ""),
            "supplierId": (order or {}).get("supplierId"), "invoiceNo": str(body.get("invoiceNo") or "").strip(), "note": str(body.get("note") or "").strip(),
            "mode": mode, "additional": additional, "serials": serials}
    cost = _qty(body.get("unitCost"))
    if cost is not None and cost >= 0:
        line["cost"] = cost
    out = fn(conn, quote_no, [line], user)
    if mode == "consumable" and not out.get("ok"):
        return {"skipped": "consumable"}
    if out.get("ok"):
        b = (out.get("batches") or [{}])[0]
        if b.get("error"):                                                        # 整列被擋（直送重複、材料申請歸屬）⇒ 整筆回滾，讓使用者重填
            raise MA.MaterialApprovalError(409, b["error"])
    return out
