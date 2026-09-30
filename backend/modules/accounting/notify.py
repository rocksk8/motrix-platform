# -*- coding: utf-8 -*-
"""會計模組的通知信：傳票簽核（送審／下一層／核准／退回）與總帳申請（`ledger_action`：送審／核准／退回）。

比照 `modules/tender_radar/notify.py`：信件類型由模組載入時登記（`_mt.register`，模組不在 ⇒ 類型不存在）；
L1 寄信原語（收件人、版面、寄送）一律經 `_en.<name>` 取用（晚綁定）。
寄信是**附帶動作**：任何例外只記 log，不可以讓簽核動作失敗（呼叫端另外包 try）。
涵蓋：手開傳票、引擎草稿、折舊傳票、稅額結轉傳票（同一條簽核路徑）；總帳申請（結帳／重開期間／年度結帳／期初批次）。
"""
import logging

from helpers import email_notify as _en
from helpers import mail_types as _mt

logger = logging.getLogger(__name__)

_APPROVE = "請登入系統，於簽核佇列開啟該項目確認內容後核准或退回。"
_RESULT = "請登入系統查看目前狀態；如有疑問請洽簽核人。"
_RETURN = "請登入系統依退回說明修改內容後重新送審。"

_mt.register("voucher_submitted", "會計傳票待審核", "approval", "none", "當層簽核人",
             "傳票在您簽核之前不會進入下一個流程，也無法過帳入帳。", _APPROVE, owner="accounting")
_mt.register("voucher_next_tier", "會計傳票進入下一層審核", "approval", "none", "該層簽核人",
             "前一層已完成，傳票在本層簽核之前不會繼續（最後一層固定是最高管理者）。", _APPROVE, owner="accounting")
_mt.register("voucher_approved", "會計傳票審核完成", "approval", "none", "送審人",
             "傳票已核准，可以過帳。", _RESULT, owner="accounting")
_mt.register("voucher_returned", "會計傳票退回修改", "approval", "none", "送審人",
             "傳票已退回為草稿，修改並重新送審之前流程暫停。", _RETURN, owner="accounting")
_mt.register("ledger_action_submitted", "總帳申請待審核", "approval", "none", "最高管理者",
             "結帳、重開期間、年度結帳、期初批次在最高管理者核准之前不會執行。", _APPROVE, owner="accounting")
_mt.register("ledger_action_approved", "總帳申請已核准並執行", "approval", "none", "申請人",
             "申請的總帳動作已經核准並執行。", _RESULT, owner="accounting")
_mt.register("ledger_action_returned", "總帳申請被退回", "approval", "none", "申請人",
             "申請已退回，動作沒有執行；修改後可重新申請。", _RETURN, owner="accounting")


_INTRO = {
    'voucher_submitted': "您好，以下會計傳票已進入簽核流程，敬請於系統中完成審核。",
    'voucher_next_tier': "您好，前層審核已完成，傳票現已進入第 %d 層審核階段。",
    'voucher_approved': "您好，以下會計傳票已完成審核並核准，可以過帳。",
    'voucher_returned': "您好，您送審的會計傳票經審核後退回，請參閱下方說明修改後重新送審。",
    'ledger_action_submitted': "您好，以下總帳動作需要最高管理者核准後才會執行。",
    'ledger_action_approved': "您好，您申請的總帳動作已核准並執行。",
    'ledger_action_returned': "您好，您申請的總帳動作經審核後退回，沒有執行。",
}


def _page(name):
    return "%s/pages/%s" % (_en._base_url(), name)


def notify_voucher_submitted(voucher_no, summary, approver_usernames):
    to = _en._lookup_emails([u for u in approver_usernames if u], "voucher_submitted")
    if not to:
        logger.warning("voucher_submitted：收件人皆無設定 email")
        return
    html = _en._build_html("voucher_submitted", "會計傳票簽核申請", "待您審核", "#2F6FD6",
                           [("傳票號碼", voucher_no), ("摘要", summary or "—")],
                           "", _page("approval-queue.html"), intro=_INTRO["voucher_submitted"], button_text="前往審核")
    _en._async_send(to, _mt.subject("voucher_submitted", "會計傳票待審核：%s" % voucher_no), html)


def notify_voucher_next_tier(voucher_no, summary, tier_no, total_tiers, approver_usernames):
    to = _en._lookup_emails([u for u in approver_usernames if u], "voucher_next_tier")
    if not to:
        logger.warning("voucher_next_tier：收件人皆無設定 email")
        return
    html = _en._build_html("voucher_next_tier", "會計傳票簽核流程通知", "輪到您審核", "#2F6FD6",
                           [("傳票號碼", voucher_no), ("摘要", summary or "—"), ("目前進度", "第 %d 層審核（共 %d 層）" % (tier_no, total_tiers))],
                           "", _page("approval-queue.html"), intro=_INTRO["voucher_next_tier"] % tier_no, button_text="前往審核")
    _en._async_send(to, _mt.subject("voucher_next_tier", "會計傳票審核通知（第 %d/%d 層）：%s" % (tier_no, total_tiers, voucher_no)), html)


def notify_voucher_approved(voucher_no, summary, approved_by, requester_username):
    to = _en._lookup_emails([u for u in [requester_username] if u], "voucher_approved")
    if not to:
        logger.warning("voucher_approved：收件人皆無設定 email")
        return
    html = _en._build_html("voucher_approved", "會計傳票審核完成", "已核准", "#16A34A",
                           [("傳票號碼", voucher_no), ("摘要", summary or "—"), ("最後核准人", approved_by)],
                           "", _page("voucher.html"), intro=_INTRO["voucher_approved"], button_text="前往查看")
    _en._async_send(to, _mt.subject("voucher_approved", "會計傳票已核准：%s" % voucher_no), html)


def notify_voucher_returned(voucher_no, summary, note, requester_username):
    to = _en._lookup_emails([u for u in [requester_username] if u], "voucher_returned")
    if not to:
        logger.warning("voucher_returned：收件人皆無設定 email")
        return
    html = _en._build_html("voucher_returned", "會計傳票退回通知", "請修改後重新送審", "#DC2626",
                           [("傳票號碼", voucher_no), ("摘要", summary or "—")],
                           "", _page("voucher.html"), intro=_INTRO["voucher_returned"], note=note or "", button_text="前往修改")
    _en._async_send(to, _mt.subject("voucher_returned", "會計傳票已退回：%s" % voucher_no), html)


def notify_ledger_action_submitted(request_no, action_label, requester, approver_usernames):
    to = _en._lookup_emails([u for u in approver_usernames if u], "ledger_action_submitted")
    if not to:
        logger.warning("ledger_action_submitted：收件人皆無設定 email")
        return
    html = _en._build_html("ledger_action_submitted", "總帳申請簽核", "待您審核", "#2F6FD6",
                           [("申請號", request_no), ("申請內容", action_label), ("申請人", requester)],
                           "", _page("approval-queue.html"), intro=_INTRO["ledger_action_submitted"], button_text="前往審核")
    _en._async_send(to, _mt.subject("ledger_action_submitted", "總帳申請待審核：%s（%s）" % (request_no, action_label)), html)


def notify_ledger_action_approved(request_no, action_label, approved_by, requester_username):
    to = _en._lookup_emails([u for u in [requester_username] if u], "ledger_action_approved")
    if not to:
        logger.warning("ledger_action_approved：收件人皆無設定 email")
        return
    html = _en._build_html("ledger_action_approved", "總帳申請已核准", "已核准並執行", "#16A34A",
                           [("申請號", request_no), ("申請內容", action_label), ("核准人", approved_by)],
                           "", _page("ledger-hub.html"), intro=_INTRO["ledger_action_approved"], button_text="前往查看")
    _en._async_send(to, _mt.subject("ledger_action_approved", "總帳申請已核准並執行：%s（%s）" % (request_no, action_label)), html)


def notify_ledger_action_returned(request_no, action_label, note, requester_username):
    to = _en._lookup_emails([u for u in [requester_username] if u], "ledger_action_returned")
    if not to:
        logger.warning("ledger_action_returned：收件人皆無設定 email")
        return
    html = _en._build_html("ledger_action_returned", "總帳申請退回通知", "動作未執行", "#DC2626",
                           [("申請號", request_no), ("申請內容", action_label)],
                           "", _page("ledger-hub.html"), intro=_INTRO["ledger_action_returned"], note=note or "", button_text="前往查看")
    _en._async_send(to, _mt.subject("ledger_action_returned", "總帳申請已退回：%s（%s）" % (request_no, action_label)), html)
