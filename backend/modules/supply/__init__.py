# -*- coding: utf-8 -*-
"""M03 採購・庫存・出貨（supply）：供應商、庫存（入庫批次、序號、採購建議）、出貨單。只 import core／helpers／db（L1），不 import 其他 L2 模組。"""
from core.registry import ModuleSpec

from modules.supply import attachments
from modules.supply import gl_events
from modules.supply import material_link
from modules.supply.api import inventory, shipping_notes, suppliers

MODULE = ModuleSpec(
    key="supply",
    routers=[suppliers.router, shipping_notes.router, inventory.router],
    providers={
        # IP-6：行事曆事件 id 由擁有模組回寫（出貨單）
        ("calendar.writeback", "shipping_note"): shipping_notes._calendar_writeback,
        # IP-18：M01 案件整包的出貨單段
        ("shipping.list_for_case", "supply"): shipping_notes.list_shipping_notes_for_case,
        # IP-19：M01 案件設備序號認領／釋放庫存
        ("stock.serial", "supply"): inventory._StockSerials,
        # IP-20：M06 T100 付款傳票的料件進貨段
        ("inventory.paid_batches", "supply"): inventory.paid_batches,
        # IP-GL1（W4 總帳 C4）：進貨批次入庫 E08、進貨發票進項稅額 E08b、進貨付款 E09；唯讀
        ("gl.events", "supply"): gl_events.gl_events,
        # IP-10／approval.reassign（M01-PLAN §3-7）：M01「待我簽核」佇列與轉簽的出貨單
        ("approval.queue_items", "shipping_note"): shipping_notes._queue_items,
        ("approval.reassign", "shipping_note"): shipping_notes.REASSIGN,
        ("approval.detail", "shipping_note"): shipping_notes._queue_detail,
        # 33-S1：出貨單連動材料申請——已占用／已出貨量（M01 取消阻擋與三格數量用；M03 不讀 M01，可出貨量取自 M01 的 material.shippable）
        ("shipping.material_shipped", "supply"): material_link.material_shipped,
        # 34：同一份資料的單一數字版（reserved＋shipped；M01 變更申請「不得低於已出貨」用）
        ("shipping.material_shipped_qty", "supply"): material_link.material_shipped_qty,
        # IP-104：上傳檔的讀取權限（出貨單回簽附件；2026-09-30 P0）
        ("uploads.path_access", "supply"): shipping_notes._ShippingPathAccess,
        # IP-105：附件目錄（attachments.catalog，2026-09-30 P2）
        ("attachments.catalog", "supply"): attachments._SupplyCatalog,
    },
)
