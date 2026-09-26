# -*- coding: utf-8 -*-
"""M04 外包工班（subcontract）：承攬人員、協力廠商與派工、承攬商匯款申請。只 import core／helpers／db（L1），不 import 其他 L2 模組。"""
from core.registry import ModuleSpec

from modules.subcontract import attachments
from modules.subcontract.api import contractor_vouchers, contractors, vendor_contractors

MODULE = ModuleSpec(
    key="subcontract",
    routers=[contractors.router, vendor_contractors.router, contractor_vouchers.router],
    providers={
        # IP-1：派工單列序列化（M01 應計派工成本、M06 傳票摘要來源）
        ("dispatch.row", "subcontract"): vendor_contractors._dispatch_row,
        # IP-15：M01 案件整包的承攬派工段
        ("dispatch.list_for_case", "subcontract"): vendor_contractors.list_dispatches_for_case,
        # IP-14：M05 出納與 M06 會計匯出讀付款憑據的形狀
        ("contractor_voucher.public", "subcontract"): contractor_vouchers._voucher_public,
        # IP-10／approval.reassign（M01-PLAN §3-7）：M01「待我簽核」佇列與轉簽的承攬商匯款申請
        ("approval.queue_items", "subcontract"): contractor_vouchers.queue_items,
        ("approval.reassign", "contractor_voucher"): contractor_vouchers.REASSIGN,
        ("approval.detail", "contractor_voucher"): contractor_vouchers.queue_detail,
        # IP-14（同一串接點的第二個能力）：區間內已付款的憑據（M06 T100 付款傳票；不再自己讀本模組的表）
        ("contractor_voucher.paid_between", "subcontract"): contractor_vouchers._paid_between,
        # IP-21（暫定號）：M06 傳票帶入附件的來源（派工單、承攬商發票）
        ("attachments.for_document", "subcontract"): attachments._SubcontractAttachments,
    },
)
