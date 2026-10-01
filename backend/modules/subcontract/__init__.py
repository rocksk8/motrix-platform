# -*- coding: utf-8 -*-
"""M04 外包工班（subcontract）：承攬人員、協力廠商與派工、承攬商匯款申請。只 import core／helpers／db（L1），不 import 其他 L2 模組。"""
import importlib

from core.registry import ModuleSpec

from modules.subcontract import attachments, gl_events, remit
from modules.subcontract.api import contractor_vouchers, contractors, dispatch_approval, vendor_contractors

#: 模組自己的 migration（檔名以版號開頭，不是合法的 import 名稱 ⇒ importlib）
_m0001 = importlib.import_module("modules.subcontract.migrations.0001_remit_fee")
_m0002 = importlib.import_module("modules.subcontract.migrations.0002_dispatch_file_delete_requests")
_m0003 = importlib.import_module("modules.subcontract.migrations.0003_dispatch_approval")

MODULE = ModuleSpec(
    key="subcontract",
    # v1：contractor_payment_vouchers 匯款實付／手續費／差額審核欄位（W1）；v2：dispatch_file_delete_requests（N1，報價單附件刪除申請）；v3：contractor_dispatches 兩段審核欄位（31-A，派發審核）
    migrations=[(1, _m0001.up), (2, _m0002.up), (3, _m0003.up)],
    routers=[contractors.router, vendor_contractors.router, dispatch_approval.router, contractor_vouchers.router],
    providers={
        # IP-1：派工單列序列化（M01 應計派工成本、M06 傳票摘要來源）
        ("dispatch.row", "subcontract"): vendor_contractors._dispatch_row,
        # IP-15：M01 案件整包的承攬派工段
        ("dispatch.list_for_case", "subcontract"): vendor_contractors.list_dispatches_for_case,
        # IP-15 追加：成本檢視（M06 傳票；只回金額、日期、案件、廠商、品項描述、外包人數，不回姓名）
        ("dispatch.cost_for_case", "subcontract"): vendor_contractors.dispatch_cost_for_case,
        # IP-14：M05 出納與 M06 會計匯出讀付款憑據的形狀
        ("contractor_voucher.public", "subcontract"): contractor_vouchers._voucher_public,
        # IP-10／approval.reassign（M01-PLAN §3-7）：M01「待我簽核」佇列與轉簽的承攬商匯款申請
        ("approval.queue_items", "subcontract"): contractor_vouchers.queue_items,
        ("approval.reassign", "contractor_voucher"): contractor_vouchers.REASSIGN,
        ("approval.detail", "contractor_voucher"): contractor_vouchers.queue_detail,
        # IP-14（同一串接點的第二個能力）：區間內已付款的憑據（M06 T100 付款傳票；不再自己讀本模組的表）
        ("contractor_voucher.paid_between", "subcontract"): contractor_vouchers._paid_between,
        # IP-102（W1）：出納頁的匯款差額審核；IP-9：匯款手續費列營運報表支出
        ("remit.reviews", "contractor_voucher"): remit._RemitReviews,
        ("expense.entries", "remit_fee_contractor"): remit._expense_entries,
        # IP-10（N1）：承攬商報價單附件的刪除申請進簽核佇列（type＝dispatch_file_delete），核可／退回打派工的 delete-approve／delete-reject
        ("approval.queue_items", "subcontract_dispatch_file"): vendor_contractors.delete_queue_items,
        ("approval.detail", "dispatch_file_delete"): vendor_contractors.delete_queue_detail,
        # IP-GL1（W4 總帳 C2）：承攬商發票（E04）與匯款（E05／E05b）事件，供 M06 總帳引擎產生傳票草稿；唯讀
        ("gl.events", "subcontract"): gl_events.gl_events,
        # IP-21（暫定號）：M06 傳票帶入附件的來源（派工單、承攬商發票）
        ("attachments.for_document", "subcontract"): attachments._SubcontractAttachments,
        # IP-104：上傳檔的讀取權限（派工單附件、承攬商發票；2026-09-30 P0）
        ("uploads.path_access", "subcontract"): attachments._SubcontractPathAccess,
        # IP-105：附件目錄（attachments.catalog，2026-09-30 P2）
        ("attachments.catalog", "subcontract"): attachments._SubcontractCatalog,
    },
)
