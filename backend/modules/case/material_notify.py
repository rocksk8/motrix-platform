# -*- coding: utf-8 -*-
"""叫料審核（31-C）的通知信：送審／下一層／核准／退回（2026-10-02）。

比照 `expense_notify.py`：信件類型由模組載入時登記（`_mt.register(..., owner="case")`；自動併入個人通知偏好）；寄送一律走
L1 通用入口 `email_notify.send_registered`（字面 key，守門 test_mail_registry 核對）。**信內不放金額**（只放單號、案件、品名）。
寄信是**附帶動作**：任何例外只記 log，不可以讓簽核動作失敗——對外入口（`fire`）自己包 try。
"""
import logging

from helpers import email_notify as _en
from helpers import mail_types as _mt

logger = logging.getLogger(__name__)

_APPROVE = "請登入系統，於簽核佇列開啟該材料申請確認內容後核准或退回。"
_RESULT = "請登入系統查看目前狀態；如有疑問請洽簽核人。"
_RETURN = "請登入系統依退回原因修改材料申請內容後重新送審。"

_mt.register("material_order_submitted", "材料申請待審核", "approval", "none", "當層簽核人",
             "材料申請在您簽核之前不會成為已核准的材料申請（不能標記已申購）。", _APPROVE, owner="case")
_mt.register("material_order_next_tier", "材料申請輪到您審核", "approval", "none", "當層簽核人",
             "前一層已完成，材料申請在本層簽核之前不會繼續。", _APPROVE, owner="case")
_mt.register("material_order_approved", "材料申請已核准", "approval", "none", "申請人",
             "材料申請已核准，可以標記已申購。", _RESULT, owner="case")
_mt.register("material_order_returned", "材料申請被退回", "approval", "none", "申請人",
             "材料申請已退回，修改並重新送審之前流程暫停。", _RETURN, owner="case")

# 叫料匯款申請（31-C 匯款切片）：同一組四種事件，類型名 material_payment_*；信內不放金額與帳戶
_mt.register("material_payment_submitted", "材料申請匯款申請待審核", "approval", "none", "當層簽核人",
             "匯款申請在您簽核之前不會交給出納付款。", _APPROVE, owner="case")
_mt.register("material_payment_next_tier", "材料申請匯款申請輪到您審核", "approval", "none", "當層簽核人",
             "前一層已完成，匯款申請在本層簽核之前不會繼續。", _APPROVE, owner="case")
_mt.register("material_payment_approved", "材料申請匯款申請已核准", "approval", "none", "申請人",
             "匯款申請已核准，已交給出納付款。", _RESULT, owner="case")
_mt.register("material_payment_returned", "材料申請匯款申請被退回", "approval", "none", "申請人",
             "匯款申請已退回，修改並重新送審之前流程暫停。", "請登入系統依退回原因修改匯款申請後重新送審。", owner="case")

# 材料申請變更申請（33-M2b）：同一組四種事件，類型名 material_change_*；信內不放金額
_mt.register("material_change_submitted", "材料申請變更待審核", "approval", "none", "當層簽核人",
             "變更申請在您簽核之前不會生效，原已核准的材料申請照常有效。", _APPROVE, owner="case")
_mt.register("material_change_next_tier", "材料申請變更輪到您審核", "approval", "none", "當層簽核人",
             "前一層已完成，變更申請在本層簽核之前不會生效。", _APPROVE, owner="case")
_mt.register("material_change_approved", "材料申請變更已核准", "approval", "none", "申請人",
             "變更申請已核准並套用，材料申請已切換為變更後的內容。", _RESULT, owner="case")
_mt.register("material_change_returned", "材料申請變更被退回", "approval", "none", "申請人",
             "變更申請已退回，原已核准的材料申請不受影響；修改並重新送審之前變更不會生效。", "請登入系統依退回原因修改變更申請後重新送審。", owner="case")

EVENTS = ("submitted", "next_tier", "approved", "returned")


def _page(quote_no, name="approval-queue.html"):
    return "%s/pages/%s" % (_en._base_url(), name)


def _rows(info, extra=None):
    rows = [("材料申請", info.get("docCode") or "—"), ("案件", info.get("quoteNo") or "—"), ("品名", info.get("itemName") or "—")]
    return rows + list(extra or [])


def _mail(event, info, *, usernames, extra=None, page="approval-queue.html"):
    """event 只用字面字串呼叫 `send_registered`（守門逐一核對）——所以每個事件各寫一個分支。"""
    users = [u for u in dict.fromkeys(usernames or []) if u]
    if not users:
        return False
    rows = _rows(info, extra)
    link = _page(info.get("quoteNo"), page)
    ident = "材料申請 %s" % (info.get("docCode") or "")
    if event == "submitted":
        return _en.send_registered("material_order_submitted", title="材料申請簽核申請", rows=rows, usernames=users,
                                   badge_text="待您審核", link=link, button_text="前往審核", reason=ident + " 待審核",
                                   note="您好，以下材料申請已進入簽核流程，敬請於系統中完成審核。")
    if event == "next_tier":
        return _en.send_registered("material_order_next_tier", title="材料申請簽核流程通知", rows=rows, usernames=users,
                                   badge_text="輪到您審核", link=link, button_text="前往審核", reason=ident + " 輪到您審核",
                                   note="您好，前層審核已完成，材料申請現已輪到您審核。")
    if event == "approved":
        return _en.send_registered("material_order_approved", title="材料申請已核准", rows=rows, usernames=users,
                                   badge_text="已核准", badge_color="#2E8B57", link=link, button_text="前往查看", reason=ident + " 已核准",
                                   note="您好，您送審的材料申請已完成審核並核准。")
    if event == "returned":
        return _en.send_registered("material_order_returned", title="材料申請被退回", rows=rows, usernames=users,
                                   badge_text="已退回", badge_color="#C0392B", link=link, button_text="前往查看", reason=ident + " 已退回",
                                   note="您好，您送審的材料申請經審核後退回，請參閱退回原因修改後重新送審。")
    raise ValueError("未知的材料申請通知事件：%r" % (event,))


def fire(event, info, *, approvers=None, requester="", reason="", tier_no=0, total_tiers=0):
    """對外入口（呼叫端不必包 try）。`info`＝{docCode, quoteNo, itemName}。回 True＝有寄。"""
    try:
        if event == "submitted":
            return _mail("submitted", info, usernames=approvers)
        if event == "next_tier":
            return _mail("next_tier", info, usernames=approvers,
                         extra=[("目前進度", "第 %d 層審核（共 %d 層）" % (tier_no, total_tiers))] if tier_no else None)
        if event == "approved":
            return _mail("approved", info, usernames=[requester], page="case-management.html")
        if event == "returned":
            return _mail("returned", info, usernames=[requester], page="case-management.html",
                         extra=[("退回原因", reason or "—")] if reason else None)
        raise ValueError(event)
    except Exception:                                            # noqa: BLE001 — 附帶動作：不可以讓簽核失敗
        logger.exception("材料申請通知失敗（%s）", event)
        return False


def _pay_rows(info, extra=None):
    rows = [("匯款申請", info.get("docCode") or "—"), ("案件", info.get("quoteNo") or "—"), ("品名", info.get("itemName") or "—")]
    return rows + list(extra or [])


def _pay_mail(event, info, *, usernames, extra=None, page="approval-queue.html"):
    """叫料匯款申請的信（字面 key 各一個分支；不放金額與收款帳戶）。"""
    users = [u for u in dict.fromkeys(usernames or []) if u]
    if not users:
        return False
    rows = _pay_rows(info, extra)
    link = _page(info.get("quoteNo"), page)
    ident = "匯款申請 %s" % (info.get("docCode") or "")
    if event == "submitted":
        return _en.send_registered("material_payment_submitted", title="材料申請匯款申請簽核", rows=rows, usernames=users,
                                   badge_text="待您審核", link=link, button_text="前往審核", reason=ident + " 待審核",
                                   note="您好，以下材料申請匯款申請已進入簽核流程，敬請於系統中完成審核。")
    if event == "next_tier":
        return _en.send_registered("material_payment_next_tier", title="材料申請匯款申請簽核流程通知", rows=rows, usernames=users,
                                   badge_text="輪到您審核", link=link, button_text="前往審核", reason=ident + " 輪到您審核",
                                   note="您好，前層審核已完成，匯款申請現已輪到您審核。")
    if event == "approved":
        return _en.send_registered("material_payment_approved", title="材料申請匯款申請已核准", rows=rows, usernames=users,
                                   badge_text="已核准", badge_color="#2E8B57", link=link, button_text="前往查看", reason=ident + " 已核准",
                                   note="您好，您送審的匯款申請已完成審核並核准，已交給出納付款。")
    if event == "returned":
        return _en.send_registered("material_payment_returned", title="材料申請匯款申請被退回", rows=rows, usernames=users,
                                   badge_text="已退回", badge_color="#C0392B", link=link, button_text="前往查看", reason=ident + " 已退回",
                                   note="您好，您送審的匯款申請經審核後退回，請參閱退回原因修改後重新送審。")
    raise ValueError("未知的材料申請匯款通知事件：%r" % (event,))


def fire_payment(event, info, *, approvers=None, requester="", reason="", tier_no=0, total_tiers=0):
    """叫料匯款申請的對外入口（附帶動作，自己包 try）。`info`＝{docCode, quoteNo, itemName}。"""
    try:
        if event == "submitted":
            return _pay_mail("submitted", info, usernames=approvers)
        if event == "next_tier":
            return _pay_mail("next_tier", info, usernames=approvers,
                             extra=[("目前進度", "第 %d 層審核（共 %d 層）" % (tier_no, total_tiers))] if tier_no else None)
        if event == "approved":
            return _pay_mail("approved", info, usernames=[requester], page="case-management.html")
        if event == "returned":
            return _pay_mail("returned", info, usernames=[requester], page="case-management.html",
                             extra=[("退回原因", reason or "—")] if reason else None)
        raise ValueError(event)
    except Exception:                                            # noqa: BLE001
        logger.exception("材料申請匯款通知失敗（%s）", event)
        return False


def _chg_mail(event, info, *, usernames, extra=None, page="approval-queue.html"):
    """材料申請變更申請的信（字面 key 各一個分支；不放金額）。"""
    users = [u for u in dict.fromkeys(usernames or []) if u]
    if not users:
        return False
    rows = [("變更申請", info.get("docCode") or "—"), ("案件", info.get("quoteNo") or "—"), ("品名", info.get("itemName") or "—")] + list(extra or [])
    link = _page(info.get("quoteNo"), page)
    ident = "材料申請變更 %s" % (info.get("docCode") or "")
    if event == "submitted":
        return _en.send_registered("material_change_submitted", title="材料申請變更簽核申請", rows=rows, usernames=users,
                                   badge_text="待您審核", link=link, button_text="前往審核", reason=ident + " 待審核",
                                   note="您好，以下材料申請變更已進入簽核流程，敬請於系統中完成審核；核准前原材料申請內容照常有效。")
    if event == "next_tier":
        return _en.send_registered("material_change_next_tier", title="材料申請變更簽核流程通知", rows=rows, usernames=users,
                                   badge_text="輪到您審核", link=link, button_text="前往審核", reason=ident + " 輪到您審核",
                                   note="您好，前層審核已完成，材料申請變更現已輪到您審核。")
    if event == "approved":
        return _en.send_registered("material_change_approved", title="材料申請變更已核准", rows=rows, usernames=users,
                                   badge_text="已核准", badge_color="#2E8B57", link=link, button_text="前往查看", reason=ident + " 已核准",
                                   note="您好，您送審的材料申請變更已完成審核並套用。")
    if event == "returned":
        return _en.send_registered("material_change_returned", title="材料申請變更被退回", rows=rows, usernames=users,
                                   badge_text="已退回", badge_color="#C0392B", link=link, button_text="前往查看", reason=ident + " 已退回",
                                   note="您好，您送審的材料申請變更經審核後退回，原材料申請不受影響；請參閱退回原因修改後重新送審。")
    raise ValueError("未知的材料申請變更通知事件：%r" % (event,))


def fire_change(event, info, *, approvers=None, requester="", reason="", tier_no=0, total_tiers=0):
    """材料申請變更申請的對外入口（附帶動作，自己包 try）。`info`＝{docCode, quoteNo, itemName}。"""
    try:
        if event == "submitted":
            return _chg_mail("submitted", info, usernames=approvers)
        if event == "next_tier":
            return _chg_mail("next_tier", info, usernames=approvers,
                             extra=[("目前進度", "第 %d 層審核（共 %d 層）" % (tier_no, total_tiers))] if tier_no else None)
        if event == "approved":
            return _chg_mail("approved", info, usernames=[requester], page="case-management.html")
        if event == "returned":
            return _chg_mail("returned", info, usernames=[requester], page="case-management.html",
                             extra=[("退回原因", reason or "—")] if reason else None)
        raise ValueError(event)
    except Exception:                                            # noqa: BLE001
        logger.exception("材料申請變更通知失敗（%s）", event)
        return False
