# -*- coding: utf-8 -*-
"""費用單據（kind<>''）的通知信：送審／下一層／核准／退回／待撥款／已撥款（A2-7，2026-10-01）。

比照 `modules/accounting/notify.py`：信件類型由模組載入時登記（`_mt.register(..., owner="case")`，模組不在 ⇒ 類型不存在；
自動併入個人通知偏好）；寄送一律走 L1 通用入口 `email_notify.send_registered`（字面 key，守門 test_mail_registry 核對）。
**信內不放金額**（使用者裁示：金額可見性＝簽核人＋申請人＋財務／出納；信件走外部郵件系統）。
寄信是**附帶動作**：任何例外只記 log，不可以讓簽核／付款動作失敗——對外入口（`fire`）自己包 try。
`kind=''` 的舊額外支出（第44班起）只寄「已核准／被退回」給申請人（單號用 `#id`，沒有送審／下一層／待撥款信，行為其餘不變）。
第44班（使用者裁示）：主旨與內文標題一律寫出**結果**（「請購單 PR-… 已核准／已退回／待審核／輪到您審核／待付款／已付款」）；
站內通知、管理員活動信與這裡共用 `doc_ident()` 的同一個「類型＋單號」寫法。
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

# 第44班：額外支出「變更申請」的申請人通知（核准生效／駁回）——原本只有站內通知與管理員活動信
_mt.register("expense_change_approved", "支出申請變更已核准", "approval", "none", "申請人",
             "變更已核准並生效，單據已改為變更後的內容。", _RESULT, owner="case")
_mt.register("expense_change_returned", "支出申請變更被駁回", "approval", "none", "申請人",
             "變更申請已駁回，單據維持原內容；修改後可重新申請變更。", _RETURN, owner="case")

EVENTS = ("submitted", "next_tier", "approved", "returned", "payout_pending", "paid")
#: kind='' 的舊額外支出只寄這兩種（申請人看得到結果；送審／下一層／待撥款維持不寄）
_LEGACY_EVENTS = ("approved", "returned")


def _page(name):
    return "%s/pages/%s" % (_en._base_url(), name)


def _kind_name(conn, kind):
    try:
        from helpers import expense_types as ET
        t = ET.get_type(conn, kind)
        return (t or {}).get("body", {}).get("name") or kind
    except Exception:                                            # noqa: BLE001 — 名稱只是顯示
        return kind


def doc_ident(conn, row) -> str:
    """「類型名＋單號」：站內通知、管理員活動信、信件主旨共用的寫法（第44班）。typed 單據＝`請購單 PR-20261006-0001`；舊式簡單額外支出沒有單號＝`支出申請 #16`。"""
    kind = (row["kind"] or "") if "kind" in row.keys() else ""
    code = (row["doc_code"] or "") if "doc_code" in row.keys() else ""
    if kind:
        return ("%s %s" % (_kind_name(conn, kind), code)).strip()
    return "支出申請 #%s" % row["id"]


def _cashiers(conn):
    from helpers.auth import finance_usernames          # 第42班：出納通知 ⇒ 在職財務角色＋superadmin（不再掃 cashier 勾選）
    return finance_usernames(conn)


def _rows(conn, row, extra=None):
    kind = row["kind"]
    rows = [("單據", _kind_name(conn, kind) if kind else "支出申請"), ("單號", row["doc_code"] or ("#%s" % row["id"]))]
    return rows + list(extra or [])


def _mail(event, conn, row, *, usernames, extra=None, reason="", page="approval-queue.html", button="前往查看"):
    """event 只用字面字串呼叫 `send_registered`（守門逐一核對）——所以每個事件各寫一個分支。"""
    users = [u for u in dict.fromkeys(usernames or []) if u]
    if not users:
        return False
    kn = _kind_name(conn, row["kind"]) if row["kind"] else "支出申請"
    rows = _rows(conn, row, extra)
    link = _page(page)
    ident = doc_ident(conn, row)                          # 主旨與內文開頭用：不放金額
    if event == "submitted":
        return _en.send_registered("expense_form_submitted", title="%s簽核申請" % kn, rows=rows, usernames=users,
                                   badge_text="待您審核", link=link, button_text="前往審核",
                                   reason=ident + " 待審核", note="您好，以下%s已進入簽核流程，敬請於系統中完成審核。" % kn)
    if event == "next_tier":
        return _en.send_registered("expense_form_next_tier", title="%s簽核流程通知" % kn, rows=rows, usernames=users,
                                   badge_text="輪到您審核", link=link, button_text="前往審核",
                                   reason=ident + " 輪到您審核", note="您好，前層審核已完成，%s現已輪到您審核。" % kn)
    if event == "approved":
        return _en.send_registered("expense_form_approved", title="%s已核准" % kn, rows=rows, usernames=users,
                                   badge_text="已核准", badge_color="#2E8B57", link=link, button_text=button,
                                   reason=ident + " 已核准", note="您好，您送審的%s已完成審核並核准。" % kn)
    if event == "returned":
        return _en.send_registered("expense_form_returned", title="%s被退回" % kn, rows=rows, usernames=users,
                                   badge_text="已退回", badge_color="#C0392B", link=link, button_text=button,
                                   reason=ident + " 已退回", note="您好，您送審的%s經審核後退回，請參閱退回原因修改後重新送審。" % kn)
    if event == "payout_pending":
        return _en.send_registered("expense_form_payout_pending", title="%s待撥款" % kn, rows=rows, usernames=users,
                                   badge_text="待付款", link=link, button_text="前往付款",
                                   reason=ident + " 待付款", note="您好，以下%s已核准，等待您登錄付款。" % kn)
    if event == "paid":
        return _en.send_registered("expense_form_paid", title="%s已付款" % kn, rows=rows, usernames=users,
                                   badge_text="已付款", badge_color="#2E8B57", link=link, button_text=button,
                                   reason=ident + " 已付款", note="您好，您申請的%s已由出納登錄付款。" % kn)
    raise ValueError("未知的費用單據通知事件：%r" % (event,))


def fire(event, conn, row, *, approvers=None, requester="", reason="", tier_no=0, total_tiers=0, payable=None):
    """對外入口（呼叫端不必包 try）。`row`＝case_extra_expenses 的列；`kind=''` ⇒ 什麼都不做。回 True＝有寄。"""
    try:
        if not (row["kind"] or "") and event not in _LEGACY_EVENTS:
            return False
        if event == "submitted":
            return _mail("submitted", conn, row, usernames=approvers)
        if event == "next_tier":
            return _mail("next_tier", conn, row, usernames=approvers,
                         extra=[("目前進度", "第 %d 層審核（共 %d 層）" % (tier_no, total_tiers))] if tier_no else None)
        if event == "approved":
            sent = _mail("approved", conn, row, usernames=[requester], page="payment-request.html?tab=mine")
            if payable and (row["kind"] or ""):
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


def fire_change(event, conn, row, *, requester="", reason=""):
    """額外支出「變更申請」通知申請人（第44班）：`approved`＝核准並生效、`returned`＝駁回。`row`＝case_extra_expenses 的列（kind 為空也寄）。
    event 只用字面字串呼叫 `send_registered`（守門逐一核對）。信內不放金額。任何例外只記 log。"""
    try:
        users = [u for u in dict.fromkeys([requester]) if u]
        if not users:
            return False
        ident = doc_ident(conn, row)
        rows = _rows(conn, row, [("申請內容", "變更申請")])
        link = _page("payment-request.html?tab=mine")
        if event == "approved":
            return _en.send_registered("expense_change_approved", title="支出申請變更已核准", rows=rows, usernames=users,
                                       badge_text="變更已核准", badge_color="#2E8B57", link=link, button_text="前往查看",
                                       reason=ident + " 變更已核准", note="您好，您申請的%s變更已完成審核並生效。" % ident)
        if event == "returned":
            return _en.send_registered("expense_change_returned", title="支出申請變更被駁回", rows=rows + ([("駁回原因", reason)] if reason else []),
                                       usernames=users, badge_text="變更已駁回", badge_color="#C0392B", link=link, button_text="前往查看",
                                       reason=ident + " 變更已駁回", note="您好，您申請的%s變更經審核後駁回，單據維持原內容。" % ident)
        raise ValueError(event)
    except Exception:                                            # noqa: BLE001 — 附帶動作：不可以讓簽核失敗
        logger.exception("費用單據變更通知失敗（%s）", event)
        return False


# ── 完工單核准 ⇒ 申請人（第44班；原本只有站內通知與管理員活動信）──────────────────────────────
_mt.register("completion_note_approved", "完工單已核准", "approval", "none", "申請人",
             "完工單已核准，案件可依完工單繼續後續流程。", _RESULT, owner="case")


def fire_completion_approved(note_no, quote_no, customer, requester):
    """完工單最終核准 ⇒ 寄給申請人（單號＝完工單號；信內不放金額）。任何例外只記 log。"""
    try:
        users = [u for u in dict.fromkeys([requester]) if u]
        if not users:
            return False
        ident = "完工單 %s" % note_no
        rows = [("完工單", note_no), ("案件", quote_no or "—"), ("客戶", customer or "—")]
        link = _page("case-management.html?q=%s" % quote_no if quote_no else "case-management.html")
        return _en.send_registered("completion_note_approved", title="完工單已核准", rows=rows, usernames=users,
                                   badge_text="已核准", badge_color="#2E8B57", link=link, button_text="前往查看",
                                   reason=ident + " 已核准", note="您好，您送審的%s已完成審核並核准。" % ident)
    except Exception:                                            # noqa: BLE001
        logger.exception("完工單核准通知失敗")
        return False
