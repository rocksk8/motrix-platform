# -*- coding: utf-8 -*-
"""M06 會計（accounting）：傳票（建立、簽核、過帳、作廢重開、PDF、附件帶入）、會計科目、T100 傳票匯出。
只 import core／helpers／db（L1），不 import 其他 L2 模組：案件、派工、開票、進貨的資料都經串接點取得
（IP-1 dispatch.row、IP-14 contractor_voucher.*、IP-20 inventory.paid_batches、IP-21 attachments.for_document、
receivables.tax_invoices）；暫時直讀別組表的例外列在 tests/platform/test_accounting_foreign_reads.py（到期守門）。"""
from core.registry import ModuleSpec

from modules.accounting.api import account_items, accounting_export, vouchers

MODULE = ModuleSpec(
    key="accounting",
    routers=[accounting_export.router, account_items.router, vouchers.router],
    providers={
        # IP-2：M07 獎金傳票草稿與科目檢查
        ("voucher.draft", "accounting"): vouchers._provide_voucher_draft,
        ("voucher.account_check", "accounting"): accounting_export.validate_account_code,
        # IP-3：M07 撥付銀行選項
        ("accounting.settings", "accounting"): accounting_export._provide_accounting_settings,
        # IP-4：M07 作廢草稿、查傳票狀態
        ("voucher.void_draft", "accounting"): vouchers._provide_voucher_void_draft,
        ("voucher.status", "accounting"): vouchers._provide_voucher_status,
        # IP-22（暫定號）：M01 案件整包的傳票段
        ("voucher.by_case", "accounting"): vouchers.vouchers_by_case,
    },
)
