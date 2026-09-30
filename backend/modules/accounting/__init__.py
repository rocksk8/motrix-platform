# -*- coding: utf-8 -*-
"""M06 會計（accounting）：傳票（建立、簽核、過帳、作廢重開、PDF、附件帶入）、會計科目、T100 傳票匯出。
只 import core／helpers／db（L1），不 import 其他 L2 模組：案件、派工、開票、進貨的資料都經串接點取得
（IP-1 dispatch.row、IP-14 contractor_voucher.*、IP-20 inventory.paid_batches、IP-21 attachments.for_document、
receivables.tax_invoices）；暫時直讀別組表的例外列在 tests/platform/test_accounting_foreign_reads.py（到期守門）。"""
import importlib

from core.registry import ModuleSpec

from modules.accounting import attachments_catalog
from modules.accounting.api import account_items, accounting_export, ledger_annotations, ledger_closing, ledger_engine, ledger_periods, ledger_reports, ledger_settings, ledger_statements, ledger_tax, voucher_providers, vouchers

_m0001 = importlib.import_module("modules.accounting.migrations.0001_ledger_base")

MODULE = ModuleSpec(
    key="accounting",
    routers=[accounting_export.router, ledger_annotations.router, account_items.router, vouchers.router, ledger_periods.router, ledger_reports.router, ledger_engine.router, ledger_settings.router, ledger_tax.router, ledger_statements.router, ledger_closing.router],
    migrations=[(1, _m0001.up)],
    providers={
        # IP-2：M07 獎金傳票草稿與科目檢查
        ("voucher.draft", "accounting"): voucher_providers._provide_voucher_draft,
        # IP-105：附件目錄（attachments.catalog，2026-09-30 P2）
        ("attachments.catalog", "accounting"): attachments_catalog._AccountingCatalog,
        ("voucher.account_check", "accounting"): accounting_export.validate_account_code,
        # IP-3：M07 撥付銀行選項
        ("accounting.settings", "accounting"): accounting_export._provide_accounting_settings,
        # IP-4：M07 作廢草稿、查傳票狀態
        ("voucher.void_draft", "accounting"): voucher_providers._provide_voucher_void_draft,
        ("voucher.status", "accounting"): voucher_providers._provide_voucher_status,
        ("voucher.by_no", "accounting"): voucher_providers._provide_voucher_by_no,
        # IP-22（暫定號）：M01 案件整包的傳票段
        ("voucher.by_case", "accounting"): vouchers.vouchers_by_case,
        # M01-PLAN §3-7（C）：待我簽核的傳票項目、轉簽的簽核鏈讀寫（M01 佇列只彙整）
        ("approval.queue_items", "voucher"): voucher_providers._queue_items,
        ("approval.reassign", "voucher"): voucher_providers._VoucherReassign,
    },
)
