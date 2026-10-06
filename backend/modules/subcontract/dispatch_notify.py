# -*- coding: utf-8 -*-
"""派發審核的通知信（31-A S5）：兩段（派發審核／完工審核）各四種——送審／下一層／核准／退回。

比照 `modules/case/expense_notify.py`：類型由模組載入時登記（`owner="subcontract"`，自動併入個人通知偏好）；
寄送一律走 L1 `email_notify.send_registered`（字面 key）；**信內不放金額**；寄信是附帶動作，例外只記 log、不可讓簽核失敗。"""
import logging

from helpers import email_notify as _en
from helpers import mail_types as _mt

logger = logging.getLogger(__name__)

_APPROVE = "請登入系統，於簽核佇列開啟該單據確認內容後核准或退回。"
_RESULT = "請登入系統查看目前狀態；如有疑問請洽簽核人。"
_RETURN = "請登入系統依退回原因修改內容後重新送審。"

_mt.register("dispatch_submitted", "承攬商派發待審核", "approval", "none", "當層簽核人",
             "派發在您簽核之前不會進入下一個流程（不能送出、驗收或請款）。", _APPROVE, owner="subcontract")
_mt.register("dispatch_next_tier", "承攬商派發輪到您審核", "approval", "none", "當層簽核人",
             "前一層已完成，派發在本層簽核之前不會繼續。", _APPROVE, owner="subcontract")
_mt.register("dispatch_approved", "承攬商派發已核准", "approval", "none", "申請人",
             "派發已核准，可依序送出、驗收。", _RESULT, owner="subcontract")
_mt.register("dispatch_returned", "承攬商派發被退回", "approval", "none", "申請人",
             "派發已退回，修改並重新送審之前流程暫停。", _RETURN, owner="subcontract")
_mt.register("dispatch_completion_submitted", "承攬商派發完工待審核", "approval", "none", "當層簽核人",
             "完工審核通過之前，派發不會完結。", _APPROVE, owner="subcontract")
_mt.register("dispatch_completion_next_tier", "承攬商派發完工輪到您審核", "approval", "none", "當層簽核人",
             "前一層已完成，完工審核在本層簽核之前不會繼續。", _APPROVE, owner="subcontract")
_mt.register("dispatch_completion_approved", "承攬商派發完工已核准", "approval", "none", "申請人",
             "完工審核通過，派發已完結。", _RESULT, owner="subcontract")
_mt.register("dispatch_completion_returned", "承攬商派發完工被退回", "approval", "none", "申請人",
             "完工申請已退回，修正並重新申請之前派發維持已驗收。", _RETURN, owner="subcontract")


def _link():
    return "%s/pages/approval-queue.html" % _en._base_url()


def _mail(stage, event, row, subject, usernames, extra):
    """stage／event 只用字面字串呼叫 `send_registered`（守門逐一核對）——所以每個事件各寫一個分支。"""
    users = [u for u in dict.fromkeys(usernames or []) if u]
    if not users:
        return False
    code = row["doc_code"] or ("#%s" % row["id"])
    rows = [("單號", code), ("案件", row["quote_no"] or "—"), ("承攬商", subject)] + list(extra or [])
    ident = "派發 %s" % code                         # 主旨與內文開頭用：不放金額
    link = _link()
    if stage == "dispatch":
        if event == "submitted":
            return _en.send_registered("dispatch_submitted", title="承攬商派發簽核申請", rows=rows, usernames=users,
                                       badge_text="待您審核", link=link, button_text="前往審核", reason=ident + " 待審核",
                                       note="您好，以下承攬商派發已進入簽核流程，敬請於系統中完成審核。")
        if event == "next_tier":
            return _en.send_registered("dispatch_next_tier", title="承攬商派發簽核流程通知", rows=rows, usernames=users,
                                       badge_text="輪到您審核", link=link, button_text="前往審核", reason=ident + " 輪到您審核",
                                       note="您好，前層審核已完成，派發現已輪到您審核。")
        if event == "approved":
            return _en.send_registered("dispatch_approved", title="承攬商派發已核准", rows=rows, usernames=users,
                                       badge_text="已核准", badge_color="#2E8B57", link=link, button_text="前往查看",
                                       reason=ident + " 已核准", note="您好，您送審的承攬商派發已完成審核並核准。")
        if event == "returned":
            return _en.send_registered("dispatch_returned", title="承攬商派發被退回", rows=rows, usernames=users,
                                       badge_text="已退回", badge_color="#C0392B", link=link, button_text="前往查看",
                                       reason=ident + " 已退回", note="您好，您送審的承攬商派發經審核後退回，請參閱退回原因修改後重新送審。")
    elif stage == "completion":
        if event == "submitted":
            return _en.send_registered("dispatch_completion_submitted", title="承攬商派發完工簽核申請", rows=rows,
                                       usernames=users, badge_text="待您審核", link=link, button_text="前往審核",
                                       reason=ident + " 待審核", note="您好，以下承攬商派發的完工申請已進入簽核流程，敬請於系統中完成審核。")
        if event == "next_tier":
            return _en.send_registered("dispatch_completion_next_tier", title="承攬商派發完工簽核流程通知", rows=rows,
                                       usernames=users, badge_text="輪到您審核", link=link, button_text="前往審核",
                                       reason=ident + " 輪到您審核", note="您好，前層審核已完成，派發完工現已輪到您審核。")
        if event == "approved":
            return _en.send_registered("dispatch_completion_approved", title="承攬商派發完工已核准", rows=rows,
                                       usernames=users, badge_text="已完工", badge_color="#2E8B57", link=link,
                                       button_text="前往查看", reason=ident + " 已核准", note="您好，您申請的承攬商派發完工已完成審核並核准。")
        if event == "returned":
            return _en.send_registered("dispatch_completion_returned", title="承攬商派發完工被退回", rows=rows,
                                       usernames=users, badge_text="已退回", badge_color="#C0392B", link=link,
                                       button_text="前往查看", reason=ident + " 已退回",
                                       note="您好，您申請的承攬商派發完工經審核後退回，請參閱退回原因修正後重新申請。")
    raise ValueError("未知的派發通知事件：%r／%r" % (stage, event))


def fire(stage, event, row, subject, *, approvers=None, requester="", reason="", tier_no=0, total_tiers=0):
    """對外入口（呼叫端不必包 try）。`stage`＝'dispatch'｜'completion'；回 True＝有寄。"""
    try:
        if event in ("submitted", "next_tier"):
            extra = [("目前進度", "第 %d 層審核（共 %d 層）" % (tier_no, total_tiers))] if (event == "next_tier" and tier_no) else None
            return _mail(stage, event, row, subject, approvers, extra)
        if event == "approved":
            return _mail(stage, event, row, subject, [requester], None)
        if event == "returned":
            return _mail(stage, event, row, subject, [requester], [("退回原因", reason or "—")] if reason else None)
        raise ValueError(event)
    except Exception:                                            # noqa: BLE001 — 附帶動作：不可以讓簽核失敗
        logger.exception("派發審核通知失敗（%s／%s）", stage, event)
        return False
