# -*- coding: utf-8 -*-
"""勞報單送審流程的通知（第 46 班；設計 PAYSLIP-APPROVAL-T45.md §5）：信件＋站內通知。

比照 `bonus_notify.py`：信件類型由模組載入時登記（`owner="payroll"`，自動併入個人通知偏好）；寄送走 L1 `email_notify.send_registered`
（字面 key，守門 test_mail_registry 核對）。**用語（t44 統一規範）：主旨寫結果**——「勞報單 PS-… 待審核／輪到您審核／已核准／已退回／已付款／待付款」。
🔴 **信與站內通知都不放金額、受領人姓名、身分資料**（只放單號、開單日期）。寄信是附帶動作：任何例外只記 log，不可以讓簽核或付款失敗。
自核規則：收件人就是操作的那一位 ⇒ 不寄給自己。
"""
import logging
from urllib.parse import quote

from helpers import email_notify as _en
from helpers import mail_types as _mt

logger = logging.getLogger(__name__)

_mt.register("payslip_submitted", "勞報單待審核（簽核人）", "approval", "none", "簽核人",
             "勞報單已送審，輪到您審核（含代理人）。", "請登入系統，於「待我簽核」或勞報單頁審核。（信中不含金額與受領人資料）", owner="payroll")
_mt.register("payslip_next_tier", "勞報單輪到下一層（簽核人）", "approval", "none", "簽核人",
             "勞報單上一層已核准，輪到您審核（含代理人）。", "請登入系統，於「待我簽核」或勞報單頁審核。（信中不含金額與受領人資料）", owner="payroll")
_mt.register("payslip_approved", "勞報單核准（送審人）", "approval", "none", "送審人",
             "勞報單已核准，可以匯出，並由出納付款。", "請登入系統，於勞報單頁查看。（信中不含金額與受領人資料）", owner="payroll")
_mt.register("payslip_returned", "勞報單退回（送審人）", "approval", "none", "送審人",
             "勞報單被退回（回到草稿），需要修改後重新送審。", "請登入系統，於勞報單頁查看退回原因並修改後重新送審。（信中不含金額與受領人資料）", owner="payroll")
_mt.register("payslip_payable", "勞報單已核准待付款（出納）", "business", "finance", "財務",
             "勞報單已核准，等待出納付款。", "請登入系統，於出納的「待付款申請」登錄付款。（信中不含金額與受領人資料）", owner="payroll")
_mt.register("payslip_paid", "勞報單已付款（送審人）", "approval", "none", "送審人",
             "勞報單已由出納登錄付款。", "請登入系統，於勞報單頁查看。（信中不含金額與受領人資料）", owner="payroll")


def ident(slip_no) -> str:
    return "勞報單 %s" % (slip_no or "")


def page_link(slip_no) -> str:
    """站內通知用的相對頁面連結（單號先 URL 編碼；L1 `_LINK_RE` 只收 `[A-Za-z0-9_.=&%:+-]`）。"""
    return "payslips.html?q=%s" % quote(slip_no or "", safe="")


def _mail_link(slip_no) -> str:
    return "%s/pages/%s" % (_en._base_url(), page_link(slip_no))


def _inapp(user, type_, slip_no, message, link=None) -> None:
    from helpers.audit import _notify
    _notify(user, type_, slip_no, slip_no, message, link=link or page_link(slip_no))


def fire_submitted(slip_no, slip_date, recipients, *, next_tier=False, actor="") -> bool:
    """送審（或上一層核准）⇒ 輪到的簽核人（含代理人）。`next_tier`＝下一層。操作的人本人不寄。回 True＝有寄信。"""
    who = [u for u in dict.fromkeys(recipients or []) if u and u != (actor or "").strip()]
    if not who:
        return False
    msg = "%s %s" % (ident(slip_no), "輪到您審核" if next_tier else "待審核")
    for u in who:
        try:
            _inapp(u, "payslip_submitted", "%s:%s" % (slip_no, "n" if next_tier else "s"), msg)
        except Exception:                                            # noqa: BLE001 — 附帶動作
            logger.exception("勞報單站內通知失敗（%s）", slip_no)
    rows = [("單號", slip_no or "—"), ("開單日期", slip_date or "—")]
    try:
        if next_tier:
            return _en.send_registered("payslip_next_tier", title="勞報單輪到您審核", reason=msg, usernames=who, rows=rows,
                                       badge_text="待審核", badge_color="#D97706", link=_mail_link(slip_no), button_text="前往審核",
                                       note="您好，%s 上一層已核准，輪到您審核。" % ident(slip_no))
        return _en.send_registered("payslip_submitted", title="勞報單待審核", reason=msg, usernames=who, rows=rows,
                                   badge_text="待審核", badge_color="#D97706", link=_mail_link(slip_no), button_text="前往審核",
                                   note="您好，%s 已送審，請審核。" % ident(slip_no))
    except Exception:                                                # noqa: BLE001
        logger.exception("勞報單送審通知失敗（%s）", slip_no)
        return False


def fire_approved(slip_no, slip_date, requester, finance_users, *, approver="") -> bool:
    """最後一層核准 ⇒ ① 送審人（結果；自核不寄給自己）② 財務收件人（站內＋群組信：已核准，待付款）。回 True＝有寄信給送審人。"""
    req = (requester or "").strip()
    sent = False
    rows = [("單號", slip_no or "—"), ("開單日期", slip_date or "—")]
    if req and req != (approver or "").strip():
        try:
            _inapp(req, "payslip_approved", slip_no, "%s 已核准" % ident(slip_no))
        except Exception:                                            # noqa: BLE001
            logger.exception("勞報單核准站內通知失敗（%s）", slip_no)
        try:
            sent = _en.send_registered("payslip_approved", title="勞報單已核准", reason="%s 已核准" % ident(slip_no), usernames=[req], rows=rows,
                                       badge_text="已核准", badge_color="#2E8B57", link=_mail_link(slip_no), button_text="前往查看",
                                       note="您好，您送審的%s已完成審核並核准，可以匯出，並由出納付款。" % ident(slip_no))
        except Exception:                                            # noqa: BLE001
            logger.exception("勞報單核准通知失敗（%s）", slip_no)
    for u in dict.fromkeys(finance_users or []):
        try:
            _inapp(u, "payslip_payable", slip_no, "%s 已核准，待付款" % ident(slip_no), link="cashier.html?tab=payreq")
        except Exception:                                            # noqa: BLE001
            logger.exception("勞報單待付款站內通知失敗（%s）", slip_no)
    try:
        _en.send_registered("payslip_payable", title="勞報單已核准待付款", reason="%s 已核准，待付款" % ident(slip_no), to_group=True, rows=rows,
                            badge_text="待付款", badge_color="#2F6FD6", link="%s/pages/cashier.html" % _en._base_url(), button_text="前往出納",
                            note="您好，%s 已核准，請於出納的「待付款申請」登錄付款。" % ident(slip_no))
    except Exception:                                                # noqa: BLE001
        logger.exception("勞報單待付款通知失敗（%s）", slip_no)
    return sent


def fire_returned(slip_no, slip_date, requester, *, approver="", reason="") -> bool:
    """駁回（待審核）⇒ 回草稿：通知送審人，主旨寫「已退回」、信內附原因。送審人就是操作的那一位 ⇒ 不寄給自己。"""
    req = (requester or "").strip()
    if not req or req == (approver or "").strip():
        return False
    reason = (reason or "").strip()
    try:
        _inapp(req, "payslip_returned", slip_no, ("%s 已退回：%s" % (ident(slip_no), reason[:100])) if reason else "%s 已退回" % ident(slip_no))
    except Exception:                                                # noqa: BLE001
        logger.exception("勞報單退回站內通知失敗（%s）", slip_no)
    try:
        return _en.send_registered("payslip_returned", title="勞報單已退回", reason="%s 已退回" % ident(slip_no), usernames=[req],
                                   rows=[("單號", slip_no or "—"), ("開單日期", slip_date or "—"), ("退回原因", (reason[:100] + ("…" if len(reason) > 100 else "")) or "—")],   # 第47班稽核：信內與站內同樣截斷（自由文字不整段進信箱）
                                   badge_text="已退回", badge_color="#C0392B", link=_mail_link(slip_no), button_text="前往查看",
                                   note="您好，您送審的%s已被退回（回到草稿），請依原因修改後重新送審。" % ident(slip_no))
    except Exception:                                                # noqa: BLE001
        logger.exception("勞報單退回通知失敗（%s）", slip_no)
        return False


def fire_paid(slip_no, slip_date, requester, *, payer="") -> bool:
    """出納登錄付款 ⇒ 通知送審人「已付款」（付款人就是送審人時不寄給自己）。"""
    req = (requester or "").strip()
    if not req or req == (payer or "").strip():
        return False
    try:
        _inapp(req, "payslip_paid", slip_no, "%s 已付款" % ident(slip_no))
    except Exception:                                                # noqa: BLE001
        logger.exception("勞報單已付款站內通知失敗（%s）", slip_no)
    try:
        return _en.send_registered("payslip_paid", title="勞報單已付款", reason="%s 已付款" % ident(slip_no), usernames=[req],
                                   rows=[("單號", slip_no or "—"), ("開單日期", slip_date or "—")],
                                   badge_text="已付款", badge_color="#2E8B57", link=_mail_link(slip_no), button_text="前往查看",
                                   note="您好，%s 已由出納登錄付款。" % ident(slip_no))
    except Exception:                                                # noqa: BLE001
        logger.exception("勞報單已付款通知失敗（%s）", slip_no)
        return False
