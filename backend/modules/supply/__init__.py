# -*- coding: utf-8 -*-
"""M03 採購・庫存・出貨（supply）：供應商、庫存（入庫批次、序號、採購建議）、出貨單。只 import core／helpers／db（L1），不 import 其他 L2 模組。"""
from core.registry import ModuleSpec

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
        # IP-10／approval.reassign（M01-PLAN §3-7）：M01「待我簽核」佇列與轉簽的出貨單
        ("approval.queue_items", "shipping_note"): shipping_notes._queue_items,
        ("approval.reassign", "shipping_note"): shipping_notes.REASSIGN,
        ("approval.detail", "shipping_note"): shipping_notes._queue_detail,
    },
)
