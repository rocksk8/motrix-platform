# -*- coding: utf-8 -*-
"""費用單據（kind<>''）的通知信：送審／下一層／核准／退回／待撥款／已撥款（A2-7，2026-10-01）。

比照 `modules/accounting/notify.py`：信件類型由模組載入時登記（`_mt.register(..., owner="case")`，模組不在 ⇒ 類型不存在；
自動併入個人通知偏好）；寄送一律走 L1 通用入口 `email_notify.send_registered`（字面 key，守門 test_mail_registry 核對）。
**信內不放金額**（使用者裁示：金額可見性＝簽核人＋申請人＋財務／出納；信件走外部郵件系統）。
寄信是**附帶動作**：任何例外只記 log，不可以讓簽核／付款動作失敗——對外入口（`fire`）自己包 try。
`kind=''` 的舊額外支出完全不經過這裡（呼叫端先檢查 kind）。
"""
import json
import logging

from helpers import email_notify as _en
from helpers import mail_types as _mt

logger = logging.getLogger(__name__)

_APPROVE = "請登入系統，於簽核佇列開啟該單據確認內容後核准或退回。"
_RESULT = "請登入系統查看目前狀態；如有疑問請洽簽核人。"
_RETURN = "請登入系統依退回原因修改內容後重新送審。"
_PAY = "請登入系統，於出納的「待付款申請」確認收款資料後登錄付款。"

_mt.register("expense_form_submitted", "費用單據待審核", "approval", "none", "當層簽核人",
             "單據在您簽核之前不會進入下一個流程，也不會撥款。", _APPROVE, owner="case")
_mt.register("expense_form_next_tier", "費用單據輪到您審核", "approval", "none", "當層簽核人",
             "前一層已完成，單據在本層簽核之前不會繼續。", _APPROVE, owner="case")
_mt.register("expense_form_approved", "費用單據已核准", "approval", "none", "申請人",
             "單據已核准，後續由出納處理（需付款者）。", _RESULT, owner="case")
_mt.register("expense_form_returned", "費用單據被退回", "approval", "none", "申請人",
             "單據已退回，修改並重新送審之前流程暫停。", _RETURN, owner="case")
_mt.register("expense_form_payout_pending", "費用單據待撥款", "business", "none", "出納",
             "單據已核准，等待出納登錄付款。", _PAY, owner="case")
_mt.register("expense_form_paid", "費用單據已付款", "business", "none", "申請人",
             "出納已登錄付款。", _RESULT, owner="case")

EVENTS = ("submitted", "next_tier", "approved", "returned", "payout_pending", "paid")


def _page(name):
    return "%s/pages/%s" % (_en._base_url(), name)


def _kind_name(conn, kind):
    try:
        from helpers import expense_types as ET
        t = ET.get_type(conn, kind)
        return (t or {}).get("body", {}).get("name") or kind
    except Exception:                                            # noqa: BLE001 — 名稱只是顯示
        return kind


def _cashiers(conn):
    from helpers.auth import finance_usernames          # 第42班：出納通知 ⇒ 在職財務角色＋superadmin（不再掃 cashier 勾選）
    return finance_usernames(conn)


def _rows(conn, row, extra=None):
    kind = row["kind"]
    rows = [("單據", _kind_name(conn, kind)), ("單號", row["doc_code"] or "—")]
    return rows + list(extra or [])


def _mail(event, conn, row, *, usernames, extra=None, reason="", page="approval-queue.html", button="前往查看"):
    """event 只用字面字串呼叫 `send_registered`（守門逐一核對）——所以每個事件各寫一個分支。"""
    users = [u for u in dict.fromkeys(usernames or []) if u]
    if not users:
        return False
    kn = _kind_name(conn, row["kind"])
    rows = _rows(conn, row, extra)
    link = _page(page)
    ident = "%s %s" % (kn, row["doc_code"] or "")        # 主旨與內文開頭用：不放金額
    if event == "submitted":
        return _en.send_registered("expense_form_submitted", title="%s簽核申請" % kn, rows=rows, usernames=users,
                                   badge_text="待您審核", link=link, button_text="前往審核",
                                   reason=ident, note="您好，以下%s已進入簽核流程，敬請於系統中完成審核。" % kn)
    if event == "next_tier":
        return _en.send_registered("expense_form_next_tier", title="%s簽核流程通知" % kn, rows=rows, usernames=users,
                                   badge_text="輪到您審核", link=link, button_text="前往審核",
                                   reason=ident, note="您好，前層審核已完成，%s現已輪到您審核。" % kn)
    if event == "approved":
        return _en.send_registered("expense_form_approved", title="%s已核准" % kn, rows=rows, usernames=users,
                                   badge_text="已核准", badge_color="#2E8B57", link=link, button_text=button,
                                   reason=ident, note="您好，您送審的%s已完成審核並核准。" % kn)
    if event == "returned":
        return _en.send_registered("expense_form_returned", title="%s被退回" % kn, rows=rows, usernames=users,
                                   badge_text="已退回", badge_color="#C0392B", link=link, button_text=button,
                                   reason=ident, note="您好，您送審的%s經審核後退回，請參閱退回原因修改後重新送審。" % kn)
    if event == "payout_pending":
        return _en.send_registered("expense_form_payout_pending", title="%s待撥款" % kn, rows=rows, usernames=users,
                                   badge_text="待付款", link=link, button_text="前往付款",
                                   reason=ident, note="您好，以下%s已核准，等待您登錄付款。" % kn)
    if event == "paid":
        return _en.send_registered("expense_form_paid", title="%s已付款" % kn, rows=rows, usernames=users,
                                   badge_text="已付款", badge_color="#2E8B57", link=link, button_text=button,
                                   reason=ident, note="您好，您申請的%s已由出納登錄付款。" % kn)
    raise ValueError("未知的費用單據通知事件：%r" % (event,))


def fire(event, conn, row, *, approvers=None, requester="", reason="", tier_no=0, total_tiers=0, payable=None):
    """對外入口（呼叫端不必包 try）。`row`＝case_extra_expenses 的列；`kind=''` ⇒ 什麼都不做。回 True＝有寄。"""
    try:
        if not (row["kind"] or ""):
            return False
        if event == "submitted":
            return _mail("submitted", conn, row, usernames=approvers)
        if event == "next_tier":
            return _mail("next_tier", conn, row, usernames=approvers,
                         extra=[("目前進度", "第 %d 層審核（共 %d 層）" % (tier_no, total_tiers))] if tier_no else None)
        if event == "approved":
            sent = _mail("approved", conn, row, usernames=[requester], page="payment-request.html?tab=mine")
            if payable:
                sent = _mail("payout_pending", conn, row, usernames=_cashiers(conn), page="cashier.html") or sent
            return sent
        if event == "returned":
            return _mail("returned", conn, row, usernames=[requester], page="payment-request.html?tab=mine",
                         extra=[("退回原因", reason or "—")] if reason else None)
        if event == "paid":
            return _mail("paid", conn, row, usernames=[requester], page="payment-request.html?tab=mine")
        raise ValueError(event)
    except Exception:                                            # noqa: BLE001 — 附帶動作：不可以讓簽核／付款失敗
        logger.exception("費用單據通知失敗（%s）", event)
        return False
