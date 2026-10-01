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

_APPROVE = "請登入系統，於簽核佇列開啟該叫料單確認內容後核准或退回。"
_RESULT = "請登入系統查看目前狀態；如有疑問請洽簽核人。"
_RETURN = "請登入系統依退回原因修改叫料內容後重新送審。"

_mt.register("material_order_submitted", "叫料單待審核", "approval", "none", "當層簽核人",
             "叫料單在您簽核之前不會成為已核准的叫料（不能標記已叫料）。", _APPROVE, owner="case")
_mt.register("material_order_next_tier", "叫料單輪到您審核", "approval", "none", "當層簽核人",
             "前一層已完成，叫料單在本層簽核之前不會繼續。", _APPROVE, owner="case")
_mt.register("material_order_approved", "叫料單已核准", "approval", "none", "申請人",
             "叫料單已核准，可以標記已叫料。", _RESULT, owner="case")
_mt.register("material_order_returned", "叫料單被退回", "approval", "none", "申請人",
             "叫料單已退回，修改並重新送審之前流程暫停。", _RETURN, owner="case")

EVENTS = ("submitted", "next_tier", "approved", "returned")


def _page(quote_no, name="approval-queue.html"):
    return "%s/pages/%s" % (_en._base_url(), name)


def _rows(info, extra=None):
    rows = [("叫料單", info.get("docCode") or "—"), ("案件", info.get("quoteNo") or "—"), ("品名", info.get("itemName") or "—")]
    return rows + list(extra or [])


def _mail(event, info, *, usernames, extra=None, page="approval-queue.html"):
    """event 只用字面字串呼叫 `send_registered`（守門逐一核對）——所以每個事件各寫一個分支。"""
    users = [u for u in dict.fromkeys(usernames or []) if u]
    if not users:
        return False
    rows = _rows(info, extra)
    link = _page(info.get("quoteNo"), page)
    ident = "叫料單 %s" % (info.get("docCode") or "")
    if event == "submitted":
        return _en.send_registered("material_order_submitted", title="叫料單簽核申請", rows=rows, usernames=users,
                                   badge_text="待您審核", link=link, button_text="前往審核", reason=ident,
                                   note="您好，以下叫料單已進入簽核流程，敬請於系統中完成審核。")
    if event == "next_tier":
        return _en.send_registered("material_order_next_tier", title="叫料單簽核流程通知", rows=rows, usernames=users,
                                   badge_text="輪到您審核", link=link, button_text="前往審核", reason=ident,
                                   note="您好，前層審核已完成，叫料單現已輪到您審核。")
    if event == "approved":
        return _en.send_registered("material_order_approved", title="叫料單已核准", rows=rows, usernames=users,
                                   badge_text="已核准", badge_color="#2E8B57", link=link, button_text="前往查看", reason=ident,
                                   note="您好，您送審的叫料單已完成審核並核准。")
    if event == "returned":
        return _en.send_registered("material_order_returned", title="叫料單被退回", rows=rows, usernames=users,
                                   badge_text="已退回", badge_color="#C0392B", link=link, button_text="前往查看", reason=ident,
                                   note="您好，您送審的叫料單經審核後退回，請參閱退回原因修改後重新送審。")
    raise ValueError("未知的叫料通知事件：%r" % (event,))


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
        logger.exception("叫料單通知失敗（%s）", event)
        return False
