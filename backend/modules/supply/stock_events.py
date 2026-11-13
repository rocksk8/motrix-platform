# -*- coding: utf-8 -*-
"""序號異動紀錄（一條龍 P2a；表 `stock_item_events` 由 supply migration v1 建立）。

[單位] supply:stock_events    [層] L2    [穩定度] 實驗
[公開介面] record, history, ledger_on
[不變式] 只有旗標 `onepipe.receive_ledger` 開著才寫（關＝與今天逐位元相同：不多一列資料）；**寫在呼叫端的連線上、不 commit**
         （與庫存狀態變更同一筆交易）；寫入失敗不擋主流程（紀錄是輔助，不可以讓入庫／出貨／存檔失敗）；只有從啟用日起才有歷史、不回補。
"""
from datetime import datetime


def ledger_on(conn) -> bool:
    from helpers.onepipe_flags import flag_on
    return flag_on("receive_ledger", conn=conn)


def record(conn, *, event, part_no="", serial_no="", stock_item_id=0, from_status="", to_status="", quote_no="", ref="", reason="", actor="", now=None) -> bool:
    """寫一筆異動；旗標關或寫入失敗 ⇒ False（不丟例外）。"""
    try:
        if not ledger_on(conn):
            return False
        conn.execute(
            "INSERT INTO stock_item_events (stock_item_id, part_no, serial_no, event, from_status, to_status, quote_no, ref, reason, actor, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (int(stock_item_id or 0), part_no or "", serial_no or "", event, from_status or "", to_status or "", quote_no or "", ref or "", reason or "", actor or "",
             now or datetime.now().isoformat(timespec="seconds")))
        return True
    except Exception:                                                # noqa: BLE001 — 紀錄是輔助
        return False


def history(conn, part_no, serial_no) -> list:
    """一個序號從啟用日起的異動（舊到新）。沒有 ⇒ `[]`。"""
    rows = conn.execute("SELECT event, from_status, to_status, quote_no, ref, reason, actor, created_at FROM stock_item_events"
                        " WHERE part_no=? AND serial_no=? ORDER BY id", (part_no or "", serial_no or "")).fetchall()
    return [dict(r) for r in rows]


def record_for_ids(conn, ids, *, event, from_status="", to_status="", quote_no="", ref="", reason="", actor="", now=None) -> int:
    """一批序號列（以 id 指定）各寫一筆同樣的異動（出貨核准／撤銷用）；旗標關 ⇒ 不查不寫、回 0。"""
    try:
        if not ids or not ledger_on(conn):
            return 0
        n = 0
        for sid in ids:
            r = conn.execute("SELECT part_no, serial_no FROM stock_items WHERE id=?", (sid,)).fetchone()
            if r and record(conn, event=event, part_no=r["part_no"], serial_no=r["serial_no"], stock_item_id=sid, from_status=from_status, to_status=to_status,
                            quote_no=quote_no, ref=ref, reason=reason, actor=actor, now=now):
                n += 1
        return n
    except Exception:                                                # noqa: BLE001
        return 0
