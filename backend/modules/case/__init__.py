# -*- coding: utf-8 -*-
"""M01 案件（case）：報價單、案件管理（階段、執行、動態、額外支出、叫料、完工單）、簽核佇列與簽核歷史、業務訂單。
只 import core／helpers／db（L1），其他模組的資料一律經串接點（INTEGRATION-POINTS）。

提供者一律在下方 ModuleSpec 宣告（M01-PLAN §3-8 ③ CA-O3）：模組停用、未授權或載入失敗 ⇒ 載入器不登記，
`case.access`（「M01 在不在」的唯一訊號）隨之消失；不再有 import 時的 `registry.provide()`。"""
from core.registry import ModuleSpec

from modules.case import attachments, case_deadlines, quotations
# ⚠️ router 一律用別名：`from modules.case.api import quotations` 會把套件屬性 `modules.case.quotations`
#    （報價單 helper）蓋成 api 那一支，`from modules.case import quotations` 就拿錯檔
from modules.case.api import (case_action_items as _api_action_items, case_extra_expenses as _api_extra_expenses,
                              completion_notes as _api_completion_notes, material_orders as _api_material_orders,
                              quotations as _api_quotations)

MODULE = ModuleSpec(
    key="case",
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
    },
)
