# -*- coding: utf-8 -*-
"""supply v1（T85，一條龍 P2a「入庫底層」）：到貨入庫與案件材料申請的外鍵欄位＋序號異動紀錄表。

提案 docs/platform/plans/PROCUREMENT-FLOW-ONEPIPE-PROPOSAL-v3.md §2.3／§2.4：外鍵由 supply **自己的** migration 加，不走 core migration；
案件模組不直查庫存表，所以案件與庫存的對應記在庫存這一側：
- `stock_batches.quote_no`／`po_doc_code`／`material_item_id`：這一批貨是為哪個案件、哪張採購單、哪筆材料申請入庫的（沒填＝舊資料，與今天相同）。
- `stock_batches.delivery_mode`：`stock`（入庫，預設）／`direct`（直送客戶現場，D1＝A；直送沒有序號庫存列，只留這一筆批次表頭供對帳）。
- `stock_items.material_item_id`：序號列對應的材料申請（「已入庫但還沒被案件認領」的外鍵）。
- `stock_item_events`：序號異動紀錄（入庫／出貨／安裝／釋放／退回在庫／報廢…；退換貨 P7 要查歷史，所以自 P3 提前到這裡）。**只有旗標 `onepipe.receive_ledger` 開著才寫、只有從啟用日起才有歷史、不回補**。
只新增、冪等；不動任何既有欄位的值；不自己 commit。
"""


def _cols(conn, table):
    return {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()}


def _add(conn, table, col, ddl):
    if col not in _cols(conn, table):
        conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, ddl))


def up(conn):
    for col in ("quote_no", "po_doc_code", "material_item_id"):
        _add(conn, "stock_batches", col, "TEXT NOT NULL DEFAULT ''")
    _add(conn, "stock_batches", "delivery_mode", "TEXT NOT NULL DEFAULT 'stock'")
    _add(conn, "stock_items", "material_item_id", "TEXT DEFAULT ''")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS stock_item_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_item_id INTEGER NOT NULL DEFAULT 0,
            part_no TEXT NOT NULL DEFAULT '',
            serial_no TEXT NOT NULL DEFAULT '',
            event TEXT NOT NULL DEFAULT '',
            from_status TEXT NOT NULL DEFAULT '',
            to_status TEXT NOT NULL DEFAULT '',
            quote_no TEXT NOT NULL DEFAULT '',
            ref TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '')""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_events_serial ON stock_item_events(part_no, serial_no, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_events_item ON stock_item_events(stock_item_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_batches_quote ON stock_batches(quote_no)")
