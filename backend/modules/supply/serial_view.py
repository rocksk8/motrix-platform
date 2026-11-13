# -*- coding: utf-8 -*-
"""一條龍 P3：序號的兩個唯讀視角（M03 → M01 案件的設備／保固對齊）。

[單位] supply:serial_view    [層] L2    [穩定度] 實驗
[公開介面] shipped_serials（IP-120 `stock.shipped_serials`）、serial_history（IP-121 `stock.serial_history`）
[不變式] **唯讀**：只讀呼叫端傳入的連線、不寫、不 commit；**沒有任何金額欄位**（不回成本）。
         `caller` 有給時要有和「檢視庫存」同一組模組權限（`inventory`／`procurement`／`case_manage`／`netplan_edit`），沒有 ⇒ HTTPException 403；
         None ＝可信的內部呼叫端。⚠️ **案件可見性由案件側先檢查**（本檔不認識案件成員）——新的呼叫端必須先過 `require_case`。
         `serial_history` 只有從 `onepipe.receive_ledger` 啟用日起才有資料（不回補）；旗標 `onepipe.ship_device_warranty` 或 `receive_ledger` 關 ⇒ 兩個函式都回空（不查表）。
"""
_STOCK_MODULES = ("inventory", "procurement", "case_manage", "netplan_edit")


def enabled(conn) -> bool:
    """旗標 `onepipe.ship_device_warranty` 開才有內容（關 ⇒ 回空，與沒有這個功能時相同）；序號歷史另需 `onepipe.receive_ledger`。"""
    from helpers import onepipe_flags
    return onepipe_flags.flag_on("ship_device_warranty", conn)


def _check(caller):
    if caller is not None:
        from helpers import require_any_module
        require_any_module(caller, _STOCK_MODULES, "庫存管理")


def shipped_serials(conn, quote_no, caller=None) -> dict:
    """⇒ `{"serials": [{"partNo", "name", "serialNo", "mac", "shipDate", "noteNo"}], "firstShipDate": "YYYY-MM-DD"|""}`。
    `serials`＝這個案件已出貨、還沒登載成設備（狀態 `shipped`）的序號（出貨日舊到新）；`firstShipDate`＝這個案件最早的出貨日（含已安裝的序號；沒有 ⇒ `""`）。
    供案件頁「出貨核准預填設備」與保固起始日預設（D4）；只預填，寫不寫由案件頁的人決定。"""
    _check(caller)
    out = {"serials": [], "firstShipDate": ""}
    qn = str(quote_no or "").strip()
    if not qn or not enabled(conn):
        return out
    rows = conn.execute(
        "SELECT si.part_no, si.serial_no, si.mac, si.shipping_note_no, COALESCE(p.name, '') AS name, COALESCE(sn.ship_date, '') AS ship_date"
        " FROM stock_items si LEFT JOIN parts p ON p.part_no = si.part_no LEFT JOIN shipping_notes sn ON sn.note_no = si.shipping_note_no"
        " WHERE si.quote_no=? AND si.status='shipped' ORDER BY COALESCE(sn.ship_date, ''), si.part_no, si.serial_no", (qn,)).fetchall()
    out["serials"] = [{"partNo": r["part_no"] or "", "name": r["name"] or "", "serialNo": r["serial_no"] or "", "mac": r["mac"] or "",
                       "shipDate": (r["ship_date"] or "")[:10], "noteNo": r["shipping_note_no"] or ""} for r in rows]
    first = conn.execute("SELECT MIN(sn.ship_date) FROM stock_items si JOIN shipping_notes sn ON sn.note_no = si.shipping_note_no"
                         " WHERE si.quote_no=? AND si.status IN ('shipped','installed') AND COALESCE(sn.ship_date,'')<>''", (qn,)).fetchone()
    out["firstShipDate"] = ((first[0] if first else "") or "")[:10]
    return out


def serial_history(conn, part_no, serial_no, caller=None) -> list:   # part_no 可空（只用序號查）
    """⇒ `[{"event", "fromStatus", "toStatus", "quoteNo", "ref", "reason", "actor", "at"}]`（舊到新）。
    ⚠️ `quoteNo` 是**原樣的案件編號**（可能是別的案件）：呼叫端要依自己的可見性規則遮罩（案件頁只顯示本案編號，其他一律標「其他案件」）。"""
    _check(caller)
    from modules.supply import stock_events
    if not enabled(conn) or not stock_events.ledger_on(conn):
        return []
    if str(part_no or "").strip():
        rows = stock_events.history(conn, part_no, serial_no)
    else:                                                                       # 案件設備只以序號認領庫存（不帶料號）⇒ 只用序號查
        rows = [dict(r) for r in conn.execute("SELECT event, from_status, to_status, quote_no, ref, reason, actor, created_at FROM stock_item_events"
                                              " WHERE serial_no=? ORDER BY id", (serial_no or "",)).fetchall()]
    return [{"event": e["event"], "fromStatus": e["from_status"], "toStatus": e["to_status"], "quoteNo": e["quote_no"], "ref": e["ref"],
             "reason": e["reason"], "actor": e["actor"], "at": e["created_at"]} for e in rows]
