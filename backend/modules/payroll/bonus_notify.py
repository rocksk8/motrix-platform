# -*- coding: utf-8 -*-
"""獎金分潤核准 → 通知申請人（送審人）的信（t44-bonus-mail，2026-10-06）。

之前只有「待審核 ⇒ 輪到的簽核人」與「待發放 ⇒ 出納」兩種信，**送審人從來收不到結果**。這裡補上第三種：簽核完成、進入待發放時，
寄給送審人（`approval_json.requestedBy`）。

比照 `modules/case/material_notify.py`：信件類型由模組載入時登記（`owner="payroll"`；自動併入個人通知偏好）；寄送走 L1 通用入口
`email_notify.send_registered`（字面 key，守門 test_mail_registry 核對）。
用語（t44 申請人通知統一規範）：識別＝「獎金分潤 {單號}」＋結果字「已核准」；主旨與信件事由是同一句「獎金分潤 {單號} 已核准」。
🔴 **信內不放金額**（只放單號與客戶名稱，與既有獎金信一致）。寄信是附帶動作：任何例外只記 log，不可以讓簽核失敗——對外入口自己包 try。
"""
import logging
from urllib.parse import quote

from helpers import email_notify as _en
from helpers import mail_types as _mt

logger = logging.getLogger(__name__)

_mt.register("bonus_approved", "獎金分潤核准（送審人）", "approval", "none", "送審人",
             "獎金分潤已核准、進入待發放，等待出納發放。", "請登入系統，於獎金分潤頁查看；發放由出納處理。（信中不含金額）", owner="payroll")
_mt.register("bonus_returned", "獎金分潤退回（送審人）", "approval", "none", "送審人",
             "獎金分潤被駁回或退回（回到草稿），需要修改後重新送審。", "請登入系統，於獎金分潤頁查看退回原因並修改後重新送審。（信中不含金額）", owner="payroll")


_mt.register("bonus_approver_bypass", "獎金分潤層外核准（通知其他最高管理者）", "approval", "none", "其他最高管理者",
             "有最高管理者不在簽核層內、代替唯一的簽核人核准了一張獎金分潤。", "請登入系統，於獎金分潤頁與稽核紀錄查看核准人、原簽核人與原因。（信中不含金額）", owner="payroll")


def ident(quote_no) -> str:
    return "獎金分潤 %s" % (quote_no or "")


def _page_link(quote_no) -> str:
    """站內通知用的相對頁面連結（單號先 URL 編碼；L1 `_LINK_RE` 只收 `[A-Za-z0-9_.=&%:+-]`）。"""
    return "bonus.html?q=%s" % quote(quote_no or "", safe="")


def _mail_link(quote_no) -> str:
    return "%s/pages/%s" % (_en._base_url(), _page_link(quote_no))      # 與 `case/material_notify._page` 同一個組法


def _notice_in_app(quote_no, requester, *, type_="bonus_approved", message=None) -> None:
    """站內通知（含單號＋連結）。`type` 以 `_approved` 結尾 ⇒ L1 `_notify` 同一 (type, ref_id, 收件人) 只留一列；金額不放。
    `link` 參數由 t44-inapp-bell 提供（同一班整合）。"""
    from helpers.audit import _notify
    msg = message or "%s 已核准，等待出納發放" % ident(quote_no)
    _notify(requester, type_, quote_no, quote_no, msg, link=_page_link(quote_no))


def fire_approved(quote_no, customer, requester, *, approver="") -> bool:
    """核准（進入待發放）⇒ 通知送審人（信＋站內）。送審人就是簽核的那一位（唯一的最高管理者自簽）⇒ 都不寄給自己。回 True＝有寄信。
    站內通知與信互不依賴（公司關閉這種信，站內通知照寫）。"""
    req = (requester or "").strip()
    if not req or req == (approver or "").strip():
        return False
    try:
        _notice_in_app(quote_no, req)
    except Exception:                                            # noqa: BLE001 — 附帶動作
        logger.exception("獎金分潤核准站內通知失敗（%s）", quote_no)
    try:
        text = "%s 已核准" % ident(quote_no)
        return _en.send_registered(
            "bonus_approved", title="獎金分潤已核准", reason=text, usernames=[req],
            rows=[("單號", quote_no or "—"), ("客戶", customer or "—")],
            badge_text="已核准", badge_color="#2E8B57",
            link=_mail_link(quote_no), button_text="前往查看",
            note="您好，您送審的%s已完成審核並核准。" % ident(quote_no))
    except Exception:                                            # noqa: BLE001 — 附帶動作：不可以讓簽核失敗
        logger.exception("獎金分潤核准通知失敗（%s）", quote_no)
        return False


def fire_returned(quote_no, customer, requester, *, approver="", reason="") -> bool:
    """駁回（待審核）或退回（待發放等）⇒ 回草稿：通知送審人（信＋站內），主旨寫結果「已退回」、信內附原因。
    送審人就是操作的那一位 ⇒ 不寄給自己。回 True＝有寄信。"""
    req = (requester or "").strip()
    if not req or req == (approver or "").strip():
        return False
    reason = (reason or "").strip()
    try:
        _notice_in_app(quote_no, req, type_="bonus_returned",
                       message="%s 已退回：%s" % (ident(quote_no), reason[:100]) if reason else "%s 已退回" % ident(quote_no))
    except Exception:                                            # noqa: BLE001 — 附帶動作
        logger.exception("獎金分潤退回站內通知失敗（%s）", quote_no)
    try:
        return _en.send_registered(
            "bonus_returned", title="獎金分潤已退回", reason="%s 已退回" % ident(quote_no), usernames=[req],
            rows=[("單號", quote_no or "—"), ("客戶", customer or "—"), ("退回原因", reason or "—")],
            badge_text="已退回", badge_color="#C0392B",
            link=_mail_link(quote_no), button_text="前往查看",
            note="您好，您送審的%s已被退回（回到草稿），請依原因修改後重新送審。" % ident(quote_no))
    except Exception:                                            # noqa: BLE001 — 附帶動作：不可以讓退回失敗
        logger.exception("獎金分潤退回通知失敗（%s）", quote_no)
        return False


def fire_bypass(quote_no, customer, actor, sole_approver, reason, recipients) -> bool:
    """層外最高管理者代核（簽核層只有一位簽核人）⇒ 通知**其他**在職最高管理者（信＋站內；含原簽核人，不含操作者本人）。
    附帶動作：任何例外只記 log，不可以讓已完成的核准失敗；稽核紀錄已在核准的同一個交易裡寫好（強制），這裡只是知會。"""
    who = [r for r in dict.fromkeys(x for x in (recipients or []) if x) if r != (actor or "")]
    if not who:
        return False
    text = "%s 由 %s 代 %s 核准（不在簽核層內）：%s" % (ident(quote_no), actor, sole_approver or "—", (reason or "")[:120])
    for r in who:
        try:
            _notice_in_app(quote_no, r, type_="bonus_approver_bypass", message=text)
        except Exception:                                        # noqa: BLE001 — 附帶動作
            logger.exception("獎金分潤層外核准站內通知失敗（%s → %s）", quote_no, r)
    try:
        return _en.send_registered(
            "bonus_approver_bypass", title="獎金分潤層外核准", reason="%s 層外核准" % ident(quote_no), usernames=who,
            rows=[("單號", quote_no or "—"), ("客戶", customer or "—"), ("核准人", actor or "—"), ("原簽核人", sole_approver or "—"), ("原因", reason or "—")],
            badge_text="層外核准", badge_color="#B45309",
            link=_mail_link(quote_no), button_text="前往查看",
            note="您好，%s 的簽核層只有一位簽核人，由 %s 以最高管理者身分代為核准；原因與時間已寫入稽核紀錄。" % (ident(quote_no), actor))
    except Exception:                                            # noqa: BLE001 — 附帶動作
        logger.exception("獎金分潤層外核准通知失敗（%s）", quote_no)
        return False
