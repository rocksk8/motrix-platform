# -*- coding: utf-8 -*-
"""M01 案件（case）：報價單、案件管理（階段、執行、動態、額外支出、叫料、完工單）、簽核佇列與簽核歷史、業務訂單。
只 import core／helpers／db（L1），其他模組的資料一律經串接點（INTEGRATION-POINTS）。

提供者一律在下方 ModuleSpec 宣告（M01-PLAN §3-8 ③ CA-O3）：模組停用、未授權或載入失敗 ⇒ 載入器不登記，
`case.access`（「M01 在不在」的唯一訊號）隨之消失；不再有 import 時的 `registry.provide()`。"""
import importlib

from core.registry import ModuleSpec

from modules.case import attachments, case_deadlines, gl_events, payables, quotations
# ⚠️ router 一律用別名：`from modules.case.api import quotations` 會把套件屬性 `modules.case.quotations`
#    （報價單 helper）蓋成 api 那一支，`from modules.case import quotations` 就拿錯檔
from modules.case.api import (case_action_items as _api_action_items, case_extra_expenses as _api_extra_expenses,
                              completion_notes as _api_completion_notes, material_orders as _api_material_orders,
                              quotations as _api_quotations)

#: 模組自己的 migration（檔名以版號開頭，不是合法的 import 名稱 ⇒ importlib）
_m0001 = importlib.import_module("modules.case.migrations.0001_extra_expense_invoice_no")
_m0002 = importlib.import_module("modules.case.migrations.0002_extra_expense_remit_fee")

MODULE = ModuleSpec(
    key="case",
    # v1：case_extra_expenses.invoice_no（請款流程，2026-09-27）；v2：匯款實付／手續費／差額審核欄位（W1，2026-09-30）
    migrations=[(1, _m0001.up), (2, _m0002.up)],
    # 與搬遷前 main.py 的掛載順序相同（路由比對順序不變）
    routers=[_api_quotations.router, _api_material_orders.router, _api_extra_expenses.router,
             _api_completion_notes.router, _api_action_items.router],
    providers={
        # IP-12：逐案權限與摘要（也是「M01 在不在」的唯一訊號，helpers.case_access.CASE_PRESENT）
        ("case.access", "case"): quotations._CaseAccess,
        # IP-96／IP-97：案件摘要、交貨地點
        ("case.summary", "case"): quotations.case_summary,
        ("case.locations", "case"): quotations._CaseLocations,
        # IP-95：收入認列、支出歸月、待補登、成案月份（M08）
        ("case.recognition", "case"): quotations._CaseRecognition,
        # IP-91／IP-92：報價預設條款（L1 system）、PDF 版本紀錄（L1 pdf_gen）
        ("case.default_terms", "case"): quotations._default_terms,
        ("case.doc_version", "case"): quotations._record_doc_version,
        # IP-11：每日到期檢查
        ("daily.check", "case_deadlines"): case_deadlines.run_daily_checks,
        # IP-10：「待我簽核」佇列上 M01 的五種單據（彙整在 L1 routers/approval_queue.py，2026-09-27）
        ("approval.queue_items", "case"): _api_quotations.approval_queue_items,
        # IP-93：佇列詳情的內容（M01 自己的四種單據；每案權限、抬頭、遮蔽在 L1）
        ("approval.detail", "quotation"): _api_quotations.detail_quotation,
        ("approval.detail", "completion_note"): _api_quotations.detail_completion_note,
        ("approval.detail", "extra_expense"): _api_quotations.detail_extra_expense,
        ("approval.detail", "case_change"): _api_quotations.detail_case_change,
        # IP-94：轉簽時的簽核鏈讀寫（M01 自己的兩種單據）
        ("approval.reassign", "quotation"): _api_quotations._QuotationReassign,
        ("approval.reassign", "completion_note"): _api_quotations.COMPLETION_NOTE_REASSIGN,
        # IP-6：行事曆事件 id 回寫
        ("calendar.writeback", "quotation"): _api_quotations._calendar_writeback_quotation,
        ("calendar.writeback", "case_stage"): _api_quotations._calendar_writeback_case_stage,
        # IP-17：派工品項匯入報價單（M04）
        ("quotation.append_items", "quotations"): _api_quotations._append_items_to_quotation,
        # IP-21：案件上的附件（M06 傳票帶入；ATT）
        ("attachments.for_document", "case"): attachments._CaseAttachments,
        # IP-104：上傳檔的讀取權限（/api/photo-token、/api/uploads；2026-09-30 P0）
        ("uploads.path_access", "case"): attachments._CasePathAccess,
        # IP-105：附件目錄（attachments.catalog，2026-09-30 P2）
        ("attachments.catalog", "case"): attachments._CaseCatalog,
        # IP-100：請款待付款（已核准、未登錄付款日的額外支出 ⇒ M05 出納；登錄付款寫回付款日）
        ("payables.pending", "case"): payables._Payables,
        # IP-GL1（W4 總帳 C4b）：額外支出 E11／E11b、叫料 E12／E12b；唯讀
        ("gl.events", "case"): gl_events.gl_events,
        # IP-102（W1）：匯款差額審核；IP-9：額外支出的匯款手續費列營運報表支出
        ("remit.reviews", "case"): payables._RemitReviews,
        ("expense.entries", "remit_fee_case"): payables._expense_entries,
    },
)
