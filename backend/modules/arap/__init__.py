# -*- coding: utf-8 -*-
"""M05 應收應付（arap）：出納（待付款／待收款／執行歷史／銀行對帳）、開票申請、請款單，以及收款與銷項發票的資料收集。
只 import core／helpers／db（L1），不 import 其他 L2 模組（M04 的付款憑據走 IP-14、M07 的獎金走 IP-8）。"""
from core.registry import ModuleSpec

from modules.arap import receivables
from modules.arap.api import cashier, invoice_vouchers, payment_requests

MODULE = ModuleSpec(
    key="arap",
    routers=[invoice_vouchers.router, payment_requests.router, cashier.router],
    providers={
        # 收款明細（已收款品項落在區間內）：M08 營運報表的現金口徑收入（當月／今年度／季）
        ("receivables.income_items", "arap"): receivables.collect_income_items,
        # 銷項發票清單（已填發票號碼的收款品項）：M08 稅務匯出、M06 T100 收款事件
        ("receivables.tax_invoices", "arap"): receivables.collect_tax_invoices,
        # IP-10／approval.reassign（M01-PLAN §3-7）：M01「待我簽核」佇列與轉簽的開票申請、請款單
        ("approval.queue_items", "invoice_voucher"): invoice_vouchers.queue_items,
        ("approval.queue_items", "payment_request"): payment_requests.queue_items,
        ("approval.reassign", "invoice_voucher"): invoice_vouchers.REASSIGN,
        ("approval.reassign", "payment_request"): payment_requests.REASSIGN,
        ("approval.detail", "invoice_voucher"): invoice_vouchers.queue_detail,
        ("approval.detail", "payment_request"): payment_requests.queue_detail,
    },
)
