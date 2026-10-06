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

from helpers import email_notify as _en
from helpers import mail_types as _mt

logger = logging.getLogger(__name__)

_mt.register("bonus_approved", "獎金分潤核准（送審人）", "approval", "none", "送審人",
             "獎金分潤已核准、進入待發放，等待出納發放。", "請登入系統，於獎金分潤頁查看；發放由出納處理。（信中不含金額）", owner="payroll")


def ident(quote_no) -> str:
    return "獎金分潤 %s" % (quote_no or "")


def fire_approved(quote_no, customer, requester, *, approver="") -> bool:
    """核准（進入待發放）⇒ 通知送審人。送審人就是簽核的那一位（唯一的最高管理者自簽）⇒ 不寄給自己。回 True＝有寄。"""
    try:
        req = (requester or "").strip()
        if not req or req == (approver or "").strip():
            return False
        text = "%s 已核准" % ident(quote_no)
        return _en.send_registered(
            "bonus_approved", title="獎金分潤已核准", reason=text, usernames=[req],
            rows=[("單號", quote_no or "—"), ("客戶", customer or "—")],
            badge_text="已核准", badge_color="#2E8B57",
            link="%s/pages/bonus.html?q=%s" % (_en._base_url(), quote_no), button_text="前往查看",
            note="您好，您送審的%s已完成審核並核准。" % ident(quote_no))
    except Exception:                                            # noqa: BLE001 — 附帶動作：不可以讓簽核失敗
        logger.exception("獎金分潤核准通知失敗（%s）", quote_no)
        return False
