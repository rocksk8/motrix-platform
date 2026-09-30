# -*- coding: utf-8 -*-
"""M05 應收應付（arap）：出納（待付款／待收款／執行歷史／銀行對帳）、開票申請、請款單，以及收款與銷項發票的資料收集。
只 import core／helpers／db（L1），不 import 其他 L2 模組（M04 的付款憑據走 IP-14、M07 的獎金走 IP-8）。"""
from core.registry import ModuleSpec

from modules.arap import attachments, gl_events, receivables
from modules.arap.api import cashier, invoice_vouchers, payment_requests

MODULE = ModuleSpec(
    key="arap",
    routers=[invoice_vouchers.router, payment_requests.router, cashier.router],
    providers={
        # 收款明細（已收款品項落在區間內）：M08 營運報表的現金口徑收入（當月／今年度／季）
        ("receivables.income_items", "arap"): receivables.collect_income_items,
        # 銷項發票清單（已填發票號碼的收款品項）：M08 稅務匯出、M06 T100 收款事件
        ("receivables.tax_invoices", "arap"): receivables.collect_tax_invoices,
        # IP-GL1（2026-09-30，總帳 C1）：銷項發票（E01）與客戶收款（E03）事件；M06 引擎收集後產生傳票草稿
        ("gl.events", "arap"): gl_events.gl_events,
        # IP-9（2026-09-30）：客戶內扣的收款手續費列營運報表支出（收款日、類別「收款手續費」）
        ("expense.entries", "receipt_fee"): receivables.expense_entries,
        # IP-10／approval.reassign（M01-PLAN §3-7）：M01「待我簽核」佇列與轉簽的開票申請、請款單
        ("approval.queue_items", "invoice_voucher"): invoice_vouchers.queue_items,
        ("approval.queue_items", "payment_request"): payment_requests.queue_items,
        ("approval.reassign", "invoice_voucher"): invoice_vouchers.REASSIGN,
        ("approval.reassign", "payment_request"): payment_requests.REASSIGN,
        ("approval.detail", "invoice_voucher"): invoice_vouchers.queue_detail,
        ("approval.detail", "payment_request"): payment_requests.queue_detail,
        # IP-104：上傳檔的讀取權限（開票申請已開立檔案；2026-09-30 P0）
        ("uploads.path_access", "arap"): invoice_vouchers._InvoiceVoucherPathAccess,
        # IP-105：附件目錄（attachments.catalog，2026-09-30 P2）
        ("attachments.catalog", "arap"): attachments._ArapCatalog,
    },
)
