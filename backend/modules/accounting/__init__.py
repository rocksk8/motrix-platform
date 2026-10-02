# -*- coding: utf-8 -*-
"""M06 會計（accounting）：傳票（建立、簽核、過帳、作廢重開、PDF、附件帶入）、會計科目、T100 傳票匯出。
只 import core／helpers／db（L1），不 import 其他 L2 模組：案件、派工、開票、進貨的資料都經串接點取得
（IP-1 dispatch.row、IP-14 contractor_voucher.*、IP-20 inventory.paid_batches、IP-21 attachments.for_document、
receivables.tax_invoices）；暫時直讀別組表的例外列在 tests/platform/test_accounting_foreign_reads.py（到期守門）。"""
import importlib

from core.registry import ModuleSpec

from modules.accounting import attachments_catalog
from modules.accounting.ledger import auto_run as _auto_run
from modules.accounting.ledger import custom_events as _custom_events
from modules.accounting.ledger import fixed_assets as _fixed_assets
from modules.accounting.ledger import month_totals as _month_totals
from modules.accounting.ledger import source_status as _source_status
from modules.accounting.api import account_items, accounting_export, ledger_annotations, ledger_assets, ledger_category_map, ledger_closing, ledger_engine, ledger_periods, ledger_reports, ledger_requests, ledger_settings, ledger_statements, ledger_tax, voucher_providers, vouchers

_m0001 = importlib.import_module("modules.accounting.migrations.0001_ledger_base")
_m0002 = importlib.import_module("modules.accounting.migrations.0002_ledger_action_requests")
_m0003 = importlib.import_module("modules.accounting.migrations.0003_dims_and_categories")

MODULE = ModuleSpec(
    key="accounting",
    routers=[accounting_export.router, ledger_annotations.router, ledger_category_map.router, ledger_category_map.list_router, account_items.router, vouchers.router, ledger_periods.router, ledger_reports.router, ledger_engine.router, ledger_settings.router, ledger_assets.router, ledger_tax.router, ledger_statements.router, ledger_closing.router, ledger_requests.router],
    migrations=[(1, _m0001.up), (2, _m0002.up), (3, _m0003.up)],
    schedulers=[lambda: _auto_run.schedule()],          # L1：分錄引擎每小時自動產生草稿（旗標 engine_drafts 開著才跑）
    providers={
        # IP-2：M07 獎金傳票草稿與科目檢查
        ("voucher.draft", "accounting"): voucher_providers._provide_voucher_draft,
        # IP `expense.categories`：啟用中的費用類別（費用單據的下拉選項取用；代碼發布後不可改）
        ("expense.categories", "accounting"): ledger_category_map.provide_categories,
        # IP `gl.category_account`：費用類別 → 科目代號（唯讀，顯示用快照）
        ("gl.category_account", "accounting"): ledger_category_map.provide_category_account,
        # IP-GL1：自訂模組單據入帳（C7；來源＝L1 建構器 helpers/custom_finance.gl_lines，鍵 custom_modules）
        ("gl.events", "custom_modules"): _custom_events.gl_events,
        # IP-105：附件目錄（attachments.catalog，2026-09-30 P2）
        ("attachments.catalog", "accounting"): attachments_catalog._AccountingCatalog,
        ("voucher.account_check", "accounting"): accounting_export.validate_account_code,
        # IP-106（暫定號）：來源是否已入帳（各來源寫入端點的非阻擋提示；MONEY-FLOWS §9 L3）
        ("gl.source_status", "accounting"): _source_status.source_status,
        # IP-107（暫定號）：總帳逐月彙總（營運分析『與總帳差異』頁；MONEY-FLOWS §9 L4）
        ("ledger.month_totals", "accounting"): _month_totals.month_totals,
        # IP-3：M07 撥付銀行選項
        ("accounting.settings", "accounting"): accounting_export._provide_accounting_settings,
        # IP-4：M07 作廢草稿、查傳票狀態
        ("voucher.void_draft", "accounting"): voucher_providers._provide_voucher_void_draft,
        ("voucher.status", "accounting"): voucher_providers._provide_voucher_status,
        ("voucher.by_no", "accounting"): voucher_providers._provide_voucher_by_no,
        # IP-GL1（W4 總帳 C6）：固定資產取得 E13a、每月折舊 E13b（來源 fixed_assets，由總帳自己提供）；唯讀
        ("gl.events", "fixed_assets"): _fixed_assets.gl_events,
        # IP-22（暫定號）：M01 案件整包的傳票段
        ("voucher.by_case", "accounting"): vouchers.vouchers_by_case,
        # M01-PLAN §3-7（C）：待我簽核的傳票項目、轉簽的簽核鏈讀寫（M01 佇列只彙整）
        ("approval.queue_items", "voucher"): voucher_providers._queue_items,
        ("approval.queue_items", "ledger_action"): ledger_requests.queue_items,
        ("approval.reassign", "voucher"): voucher_providers._VoucherReassign,
    },
)
