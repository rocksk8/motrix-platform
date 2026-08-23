"""External email notifications via SMTP (Gmail App Password)."""
import html as _html
import logging
import smtplib
import threading
from email.encoders import encode_base64 as _encode_b64
from email.mime.base import MIMEBase as _MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote as _pct_quote

from .settings import _get_setting
from .notification_prefs import is_enabled as _pref_enabled

logger = logging.getLogger(__name__)

_STYLE = """
body{font-family:Arial,sans-serif;background:#F5F5F0;margin:0;padding:24px}
.card{background:#fff;border-radius:10px;padding:28px 32px;max-width:560px;
      margin:0 auto;box-shadow:0 2px 8px rgba(0,0,0,.08)}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;
       font-weight:600;color:#fff}
.intro{font-size:14px;color:#444;line-height:1.7;margin-bottom:18px}
.lbl{font-size:12px;color:#888;margin-top:14px;margin-bottom:3px}
.val{font-size:14px;color:#1a1a1a;font-weight:500}
.btn{display:inline-block;margin-top:22px;padding:10px 22px;background:#1D4ED8;
     color:#ffffff !important;border-radius:7px;text-decoration:none;font-size:14px;font-weight:600}
.note{margin-top:14px;padding:10px 12px;background:#FFF8E1;border-radius:6px;
      font-size:13px;color:#7A5A00}
.foot{font-size:11px;color:#aaa;margin-top:24px;border-top:1px solid #eee;padding-top:14px}
"""


def _build_html(title: str, badge_text: str, badge_color: str,
                rows: list, quote_no: str, base_url: str,
                note: str = "", intro: str = "",
                button_text: str = "前往系統查看") -> str:
    row_html = "".join(
        f'<div class="lbl">{k}</div><div class="val">{v}</div>'
        for k, v in rows
    )
    intro_html = f'<div class="intro">{intro}</div>' if intro else ""
    note_html  = f'<div class="note">{note}</div>' if note else ""
    link = f"{base_url}/pages/quotation-form.html?no={quote_no}" if quote_no else base_url
    return (
        f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="UTF-8">'
        f'<style>{_STYLE}</style></head><body><div class="card">'
        f'<div style="font-size:18px;font-weight:700;color:#1a1a1a;margin-bottom:16px;">'
        f'{title} <span class="badge" style="background:{badge_color}">{badge_text}</span></div>'
        f'{intro_html}{row_html}{note_html}'
        f'<a href="{link}" class="btn" style="display:inline-block;margin-top:22px;padding:10px 22px;background:#1D4ED8;color:#ffffff !important;border-radius:7px;text-decoration:none;font-size:14px;font-weight:600">{button_text}</a>'
        f'<div class="foot">本郵件由 MOTRIX 營運管理系統自動發送，請勿直接回覆。'
        f'如有疑問，請聯絡系統管理員。</div>'
        f'</div></body></html>'
    )


def _cfg() -> dict:
    return _get_setting("email_notify", {}) or {}


def _base_url() -> str:
    return (_cfg().get("base_url") or "http://172.16.10.177:666").rstrip("/")


def _admin_emails(event_key: str = None) -> list:
    """Return emails of active admin/superadmin users who have email configured
    and have not muted event_key (see helpers/notification_prefs.py)."""
    try:
        from db import get_db
        conn = get_db()
        rows = conn.execute(
            "SELECT email, notification_muted FROM users "
            "WHERE active=1 AND role IN ('admin','superadmin') "
            "AND email IS NOT NULL AND email != ''",
        ).fetchall()
        conn.close()
        return [r["email"] for r in rows if _pref_enabled(r["notification_muted"], event_key)]
    except Exception as exc:
        logger.warning("_admin_emails failed: %s", exc)
        return []


def _lookup_emails(usernames: list, event_key: str = None) -> list:
    if not usernames:
        return []
    try:
        from db import get_db
        conn = get_db()
        ph = ",".join("?" * len(usernames))
        rows = conn.execute(
            f"SELECT email, notification_muted FROM users "
            f"WHERE username IN ({ph}) AND active=1 AND email!=''",
            usernames,
        ).fetchall()
        conn.close()
        return [r["email"] for r in rows if r["email"] and _pref_enabled(r["notification_muted"], event_key)]
    except Exception as exc:
        logger.warning("_lookup_emails failed: %s", exc)
        return []


def _send(to_addrs: list, subject: str, html: str) -> None:
    cfg = _cfg()
    if not cfg.get("enabled"):
        return
    if not to_addrs:
        logger.warning("email skipped — recipient list empty; subject: %r", subject)
        return
    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user", "")
    pw   = cfg.get("smtp_password", "")
    from_name = cfg.get("from_name", "MOTRIX營運系統")
    if not user or not pw:
        logger.warning("email skipped — SMTP credentials not configured; subject: %r", subject)
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{from_name} <{user}>"
    msg["To"]      = ", ".join(to_addrs)
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(user, pw)
            s.sendmail(user, to_addrs, msg.as_string())
        logger.info("email sent to %s — %r", to_addrs, subject)
    except Exception as exc:
        logger.warning("email send failed: %s", exc)


def _async_send(to_addrs: list, subject: str, html: str) -> None:
    threading.Thread(target=_send, args=(to_addrs, subject, html), daemon=True).start()


def _send_raising(to_addrs: list, subject: str, html: str) -> None:
    """同 _send，但 SMTP 失敗時直接拋出例外（供測試端點用）。"""
    cfg = _cfg()
    if not cfg.get("enabled"):
        raise RuntimeError("Email 通知功能未啟用")
    if not to_addrs:
        raise RuntimeError("收件人清單為空")
    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user", "")
    pw   = cfg.get("smtp_password", "")
    from_name = cfg.get("from_name", "MOTRIX營運系統")
    if not user or not pw:
        raise RuntimeError("SMTP 帳號或應用程式密碼未設定")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{from_name} <{user}>"
    msg["To"]      = ", ".join(to_addrs)
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP(host, port, timeout=15) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(user, pw)
        s.sendmail(user, to_addrs, msg.as_string())


# ── Public event functions ────────────────────────────────────────────────────

def notify_approval_request(quote_no: str, customer: str, approver_usernames: list) -> None:
    """新報價/改版送審 → 通知當層簽核人"""
    to = _lookup_emails(approver_usernames, "approval_request")
    if not to:
        logger.warning("notify_approval_request: 簽核人 %s 皆無設定 email（quote_no=%r）", approver_usernames, quote_no)
        return
    html = _build_html(
        "報價單簽核申請", "待您審核", "#2F6FD6",
        [("報價單號", quote_no), ("客戶名稱", customer)],
        quote_no, _base_url(),
        intro="您好，以下報價單已進入簽核流程，敬請於系統中完成審核作業。",
        button_text="前往審核報價單",
    )
    _async_send(to, f"【MOTRIX】報價單待審核 — {quote_no}（{customer}）", html)


def notify_next_tier(quote_no: str, customer: str, tier_no: int,
                     total_tiers: int, approver_usernames: list) -> None:
    """前層通過，下一層簽核通知"""
    to = _lookup_emails(approver_usernames, "next_tier")
    if not to:
        logger.warning("notify_next_tier: 第 %d 層簽核人 %s 皆無設定 email（quote_no=%r）", tier_no, approver_usernames, quote_no)
        return
    html = _build_html(
        "報價單簽核流程通知", "輪到您審核", "#2F6FD6",
        [("報價單號", quote_no), ("客戶名稱", customer),
         ("目前進度", f"第 {tier_no} 層審核（共 {total_tiers} 層）")],
        quote_no, _base_url(),
        intro=f"您好，前層審核已完成，報價單現已進入第 {tier_no} 層審核階段，敬請登入系統完成審核。",
        button_text="前往審核報價單",
    )
    _async_send(to, f"【MOTRIX】報價單審核通知（第 {tier_no}/{total_tiers} 層）— {quote_no}（{customer}）", html)


def notify_approved(quote_no: str, customer: str,
                    approved_by: str, requester_username: str) -> None:
    """全員簽核完成 → 通知申請人 + admin_emails"""
    to = list(set(_lookup_emails([requester_username], "approved") + _admin_emails("approved")))
    if not to:
        logger.warning("notify_approved: 申請人 %r 及所有管理員皆無設定 email（quote_no=%r）", requester_username, quote_no)
        return
    html = _build_html(
        "報價單審核完成", "全數通過", "#16A34A",
        [("報價單號", quote_no), ("客戶名稱", customer), ("最終審核人", approved_by)],
        quote_no, _base_url(),
        intro="您好，以下報價單已完成全部層級審核，正式生效。感謝各位審核人員配合。",
        button_text="前往查看報價單",
    )
    _async_send(to, f"【MOTRIX】報價單審核完成 — {quote_no}（{customer}）", html)


def notify_returned(quote_no: str, new_quote_no: str, customer: str,
                    note: str, requester_username: str) -> None:
    """退回修改 → 通知申請人"""
    to = _lookup_emails([requester_username], "returned")
    if not to:
        logger.warning("notify_returned: 申請人 %r 無設定 email（quote_no=%r）", requester_username, quote_no)
        return
    html = _build_html(
        "報價單退回修改通知", "請修改後重新送審", "#DC2626",
        [("原單號", quote_no), ("修改版單號", new_quote_no), ("客戶名稱", customer)],
        new_quote_no, _base_url(),
        intro="您好，您提交的報價單經審核後，因需要調整已退回，請參閱下方備註後完成修改，並重新送審。",
        note=note,
        button_text="前往修改報價單",
    )
    _async_send(to, f"【MOTRIX】報價單退回修改 — {quote_no}（{customer}）", html)


def notify_shipping_submitted(note_no: str, customer: str, approver_usernames: list) -> None:
    """出貨單送審 → 通知當層簽核人"""
    to = _lookup_emails(approver_usernames, "shipping_submitted")
    if not to:
        logger.warning("notify_shipping_submitted: 簽核人 %s 皆無設定 email（note_no=%r）", approver_usernames, note_no)
        return
    page = f"{_base_url()}/pages/shipping-notes.html?no={note_no}"
    html = _build_html(
        "出貨單簽核申請", "待您審核", "#2F6FD6",
        [("出貨單號", note_no), ("客戶名稱", customer)],
        "", page,
        intro="您好，以下出貨單已進入簽核流程，敬請於系統中完成審核作業。",
        button_text="前往審核出貨單",
    )
    _async_send(to, f"【MOTRIX】出貨單待審核 — {note_no}（{customer}）", html)


def notify_shipping_next_tier(note_no: str, customer: str, tier_no: int,
                              total_tiers: int, approver_usernames: list) -> None:
    """前層通過，出貨單下一層簽核通知"""
    to = _lookup_emails(approver_usernames, "shipping_next_tier")
    if not to:
        logger.warning("notify_shipping_next_tier: 第 %d 層簽核人 %s 皆無設定 email（note_no=%r）",
                       tier_no, approver_usernames, note_no)
        return
    page = f"{_base_url()}/pages/shipping-notes.html?no={note_no}"
    html = _build_html(
        "出貨單簽核流程通知", "輪到您審核", "#2F6FD6",
        [("出貨單號", note_no), ("客戶名稱", customer),
         ("目前進度", f"第 {tier_no} 層審核（共 {total_tiers} 層）")],
        "", page,
        intro=f"您好，前層審核已完成，出貨單現已進入第 {tier_no} 層審核階段，敬請登入系統完成審核。",
        button_text="前往審核出貨單",
    )
    _async_send(to, f"【MOTRIX】出貨單審核通知（第 {tier_no}/{total_tiers} 層）— {note_no}（{customer}）", html)


def notify_shipping_approved(note_no: str, customer: str, approved_by: str, requester_username: str) -> None:
    """出貨單全員簽核完成 → 通知申請人"""
    to = _lookup_emails([requester_username], "shipping_approved")
    if not to:
        logger.warning("notify_shipping_approved: 申請人 %r 無設定 email（note_no=%r）", requester_username, note_no)
        return
    page = f"{_base_url()}/pages/shipping-notes.html?no={note_no}"
    html = _build_html(
        "出貨單審核完成", "已核准", "#16A34A",
        [("出貨單號", note_no), ("客戶名稱", customer), ("核准人", approved_by)],
        "", page,
        intro="您好，以下出貨單已完成審核並核准。",
        button_text="前往查看出貨單",
    )
    _async_send(to, f"【MOTRIX】出貨單已核准 — {note_no}（{customer}）", html)


def notify_shipping_returned(note_no: str, customer: str, note: str, requester_username: str) -> None:
    """出貨單退回 → 通知申請人"""
    to = _lookup_emails([requester_username], "shipping_returned")
    if not to:
        logger.warning("notify_shipping_returned: 申請人 %r 無設定 email（note_no=%r）", requester_username, note_no)
        return
    page = f"{_base_url()}/pages/shipping-notes.html?no={note_no}"
    html = _build_html(
        "出貨單退回通知", "請修改後重新送審", "#DC2626",
        [("出貨單號", note_no), ("客戶名稱", customer)],
        "", page,
        intro="您好，您送出的出貨單經審核後，因需要調整已退回，請參閱下方備註後完成修改並重新送審。",
        note=note,
        button_text="前往修改出貨單",
    )
    _async_send(to, f"【MOTRIX】出貨單已退回 — {note_no}（{customer}）", html)


def notify_contractor_voucher_submitted(voucher_no: str, vendor_name: str, approver_usernames: list) -> None:
    """承攬商匯款申請送審 → 通知當層簽核人"""
    to = _lookup_emails(approver_usernames, "contractor_voucher_submitted")
    if not to:
        logger.warning("notify_contractor_voucher_submitted: 簽核人 %s 皆無設定 email（voucher_no=%r）",
                       approver_usernames, voucher_no)
        return
    page = f"{_base_url()}/pages/case-management.html"
    html = _build_html(
        "承攬商匯款申請簽核申請", "待您審核", "#2F6FD6",
        [("申請單號", voucher_no), ("承攬商", vendor_name)],
        "", page,
        intro="您好，以下承攬商匯款申請已進入簽核流程，敬請於系統中完成審核作業。",
        button_text="前往審核",
    )
    _async_send(to, f"【MOTRIX】承攬商匯款申請待審核 — {voucher_no}（{vendor_name}）", html)


def notify_contractor_voucher_next_tier(voucher_no: str, vendor_name: str, tier_no: int,
                                        total_tiers: int, approver_usernames: list) -> None:
    """前層通過，承攬商匯款申請下一層簽核通知"""
    to = _lookup_emails(approver_usernames, "contractor_voucher_next_tier")
    if not to:
        logger.warning("notify_contractor_voucher_next_tier: 第 %d 層簽核人 %s 皆無設定 email（voucher_no=%r）",
                       tier_no, approver_usernames, voucher_no)
        return
    page = f"{_base_url()}/pages/case-management.html"
    html = _build_html(
        "承攬商匯款申請簽核流程通知", "輪到您審核", "#2F6FD6",
        [("申請單號", voucher_no), ("承攬商", vendor_name),
         ("目前進度", f"第 {tier_no} 層審核（共 {total_tiers} 層）")],
        "", page,
        intro=f"您好，前層審核已完成，承攬商匯款申請現已進入第 {tier_no} 層審核階段，敬請登入系統完成審核。",
        button_text="前往審核",
    )
    _async_send(to, f"【MOTRIX】承攬商匯款申請審核通知（第 {tier_no}/{total_tiers} 層）— {voucher_no}（{vendor_name}）", html)


def notify_contractor_voucher_approved(voucher_no: str, vendor_name: str, approved_by: str,
                                       requester_username: str) -> None:
    """承攬商匯款申請全員簽核完成 → 通知申請人"""
    to = _lookup_emails([requester_username], "contractor_voucher_approved")
    if not to:
        logger.warning("notify_contractor_voucher_approved: 申請人 %r 無設定 email（voucher_no=%r）",
                       requester_username, voucher_no)
        return
    page = f"{_base_url()}/pages/case-management.html"
    html = _build_html(
        "承攬商匯款申請審核完成", "已核准", "#16A34A",
        [("申請單號", voucher_no), ("承攬商", vendor_name), ("核准人", approved_by)],
        "", page,
        intro="您好，以下承攬商匯款申請已完成審核並核准，可提供財務單位辦理匯款。",
        button_text="前往查看",
    )
    _async_send(to, f"【MOTRIX】承攬商匯款申請已核准 — {voucher_no}（{vendor_name}）", html)


def notify_contractor_voucher_returned(voucher_no: str, vendor_name: str, note: str,
                                       requester_username: str) -> None:
    """承攬商匯款申請退回 → 通知申請人"""
    to = _lookup_emails([requester_username], "contractor_voucher_returned")
    if not to:
        logger.warning("notify_contractor_voucher_returned: 申請人 %r 無設定 email（voucher_no=%r）",
                       requester_username, voucher_no)
        return
    page = f"{_base_url()}/pages/case-management.html"
    html = _build_html(
        "承攬商匯款申請退回通知", "請修改後重新送審", "#DC2626",
        [("申請單號", voucher_no), ("承攬商", vendor_name)],
        "", page,
        intro="您好，您送出的承攬商匯款申請經審核後，因需要調整已退回，請參閱下方備註後完成修改並重新送審。",
        note=note,
        button_text="前往修改",
    )
    _async_send(to, f"【MOTRIX】承攬商匯款申請已退回 — {voucher_no}（{vendor_name}）", html)


def notify_invoice_voucher_submitted(voucher_no: str, customer: str, approver_usernames: list) -> None:
    """開票申請憑據送審 → 通知當層簽核人"""
    to = _lookup_emails(approver_usernames, "invoice_voucher_submitted")
    if not to:
        logger.warning("notify_invoice_voucher_submitted: 簽核人 %s 皆無設定 email（voucher_no=%r）",
                       approver_usernames, voucher_no)
        return
    page = f"{_base_url()}/pages/case-management.html"
    html = _build_html(
        "開票申請憑據簽核申請", "待您審核", "#2F6FD6",
        [("憑據單號", voucher_no), ("客戶名稱", customer)],
        "", page,
        intro="您好，以下開票申請憑據已進入簽核流程，敬請於系統中完成審核作業。",
        button_text="前往審核",
    )
    _async_send(to, f"【MOTRIX】開票申請憑據待審核 — {voucher_no}（{customer}）", html)


def notify_invoice_voucher_next_tier(voucher_no: str, customer: str, tier_no: int,
                                     total_tiers: int, approver_usernames: list) -> None:
    """前層通過，開票申請憑據下一層簽核通知"""
    to = _lookup_emails(approver_usernames, "invoice_voucher_next_tier")
    if not to:
        logger.warning("notify_invoice_voucher_next_tier: 第 %d 層簽核人 %s 皆無設定 email（voucher_no=%r）",
                       tier_no, approver_usernames, voucher_no)
        return
    page = f"{_base_url()}/pages/case-management.html"
    html = _build_html(
        "開票申請憑據簽核流程通知", "輪到您審核", "#2F6FD6",
        [("憑據單號", voucher_no), ("客戶名稱", customer),
         ("目前進度", f"第 {tier_no} 層審核（共 {total_tiers} 層）")],
        "", page,
        intro=f"您好，前層審核已完成，開票申請憑據現已進入第 {tier_no} 層審核階段，敬請登入系統完成審核。",
        button_text="前往審核",
    )
    _async_send(to, f"【MOTRIX】開票申請憑據審核通知（第 {tier_no}/{total_tiers} 層）— {voucher_no}（{customer}）", html)


def notify_invoice_voucher_approved(voucher_no: str, customer: str, approved_by: str,
                                    requester_username: str) -> None:
    """開票申請憑據全員簽核完成 → 通知申請人"""
    to = _lookup_emails([requester_username], "invoice_voucher_approved")
    if not to:
        logger.warning("notify_invoice_voucher_approved: 申請人 %r 無設定 email（voucher_no=%r）",
                       requester_username, voucher_no)
        return
    page = f"{_base_url()}/pages/case-management.html"
    html = _build_html(
        "開票申請憑據審核完成", "已核准", "#16A34A",
        [("憑據單號", voucher_no), ("客戶名稱", customer), ("核准人", approved_by)],
        "", page,
        intro="您好，以下開票申請憑據已完成審核並核准，可提供財務單位辦理開立發票。",
        button_text="前往查看",
    )
    _async_send(to, f"【MOTRIX】開票申請憑據已核准 — {voucher_no}（{customer}）", html)


def notify_invoice_voucher_returned(voucher_no: str, customer: str, note: str,
                                    requester_username: str) -> None:
    """開票申請憑據退回 → 通知申請人"""
    to = _lookup_emails([requester_username], "invoice_voucher_returned")
    if not to:
        logger.warning("notify_invoice_voucher_returned: 申請人 %r 無設定 email（voucher_no=%r）",
                       requester_username, voucher_no)
        return
    page = f"{_base_url()}/pages/case-management.html"
    html = _build_html(
        "開票申請憑據退回通知", "請修改後重新送審", "#DC2626",
        [("憑據單號", voucher_no), ("客戶名稱", customer)],
        "", page,
        intro="您好，您送出的開票申請憑據經審核後，因需要調整已退回，請參閱下方備註後完成修改並重新送審。",
        note=note,
        button_text="前往修改",
    )
    _async_send(to, f"【MOTRIX】開票申請憑據已退回 — {voucher_no}（{customer}）", html)


def notify_approval_reminder(doc_type_label: str, doc_no: str, desc: str, days_elapsed: int,
                             approver_usernames: list, also_superadmin: bool = False) -> None:
    """簽核逾期催辦（2026-08-21）：報價單／承攬商匯款申請／開票申請憑據共用同一支——
    卡在簽核柱列超過工作日 1/3/5 天時由 routers/daily_tasks.py 的每日排程呼叫。
    days_elapsed 決定 badge 文字/顏色的嚴重度分級；also_superadmin 為真時額外加上
    全部 admin/superadmin 收件人（3 天門檻起）。統一連到簽核佇列頁（三種文件現在
    都在同一頁），不用像其他通知一樣依文件類型分開連結。"""
    to = list(set(_lookup_emails(approver_usernames, "approval_reminder")
                  + (_admin_emails("approval_reminder") if also_superadmin else [])))
    if not to:
        logger.warning("notify_approval_reminder: %s %r 的簽核人 %s 及管理員皆無設定 email（also_superadmin=%s）",
                       doc_type_label, doc_no, approver_usernames, also_superadmin)
        return
    if days_elapsed >= 5:
        badge, color = f"已逾期 {days_elapsed} 個工作日，急件", "#DC2626"
    elif days_elapsed >= 3:
        badge, color = f"已逾期 {days_elapsed} 個工作日，已通知管理員", "#EA580C"
    else:
        badge, color = f"已逾期 {days_elapsed} 個工作日", "#D97706"
    page = f"{_base_url()}/pages/approval-queue.html"
    html = _build_html(
        f"{doc_type_label}簽核逾期提醒", badge, color,
        [("單號", doc_no), ("內容", desc), ("已等待", f"{days_elapsed} 個工作日")],
        "", page,
        intro=f"您好，以下{doc_type_label}已送出審核，但等待您簽核已超過 {days_elapsed} 個工作日，敬請儘速於系統中完成審核作業。"
              + ("目前已同步通知系統管理員協助處理。" if also_superadmin else ""),
        button_text="前往簽核佇列",
    )
    _async_send(to, f"【MOTRIX】{doc_type_label}簽核逾期提醒（{days_elapsed} 個工作日）— {doc_no}", html)


def notify_resubmit_requester(new_quote_no: str, original_quote_no: str,
                              customer: str, requester_username: str,
                              approver_names: list) -> None:
    """退回改版重新送審 → 確認信給申請人"""
    to = _lookup_emails([requester_username], "resubmit_requester")
    if not to:
        logger.warning("notify_resubmit_requester: 申請人 %r 無設定 email（quote_no=%r）",
                       requester_username, new_quote_no)
        return
    approver_str = "、".join(approver_names) if approver_names else "相關簽核人員"
    html = _build_html(
        "修改版報價單已送審", "重新送審確認", "#2F6FD6",
        [("修改版單號", new_quote_no), ("原始單號", original_quote_no),
         ("客戶名稱", customer), ("待審核人員", approver_str)],
        new_quote_no, _base_url(),
        intro="您好，您的修改版報價單已成功送出，目前正等待簽核人員審核，請耐心等候通知。",
        button_text="前往查看報價單",
    )
    _async_send(to, f"【MOTRIX】修改版報價單已送審 — {new_quote_no}（{customer}）", html)


def notify_daily_task_assigned(task_id: int, title: str, task_date: str,
                               assignee_usernames: list,
                               description: str = '') -> None:
    """工作事項指派 → 通知被指派人"""
    to = _lookup_emails(assignee_usernames, "daily_task_assigned")
    if not to:
        logger.warning("notify_daily_task_assigned: 指派對象 %s 皆無設定 email（task_id=%d）",
                       assignee_usernames, task_id)
        return
    task_page = f"{_base_url()}/pages/daily-tasks.html"
    rows = [("執行日期", task_date), ("工作事項", title)]
    if description and description.strip():
        rows.append(("工作說明", description.strip()))
    html = _build_html(
        "工作事項指派通知", "請於期限內完成", "#2F6FD6",
        rows, "", task_page,
        intro="您好，系統已為您安排以下工作事項，請於指定日期完成並回報執行狀況。",
        button_text="前往工作事項",
    )
    _async_send(to, f"【MOTRIX】工作事項指派通知 — {title}（{task_date}）", html)


def notify_dev_case_delete_request(case_id: int, case_name: str,
                                   requester_display: str, reason: str = '') -> None:
    """業務開發案件刪除申請 → 通知所有最高管理者審核"""
    to = _superadmin_emails("dev_case_delete_request")
    if not to:
        logger.warning("notify_dev_case_delete_request: 無最高管理者 email（case_id=%d）", case_id)
        return
    crm_page = f"{_base_url()}/pages/dev-crm.html"
    rows = [("案件名稱", case_name), ("申請人", requester_display)]
    if reason and reason.strip():
        rows.append(("刪除原因", reason.strip()))
    html = _build_html(
        "業務開發案件刪除申請", "請盡速審核", "#DC2626",
        rows, "", crm_page,
        intro=f"{requester_display} 申請刪除業務開發案件，請最高管理者登入系統審核。",
        button_text="前往審核",
    )
    _async_send(to, f"【MOTRIX】業務開發案件刪除申請 — {case_name}", html)


def notify_dev_case_relink_request(case_id: int, case_name: str, requester_display: str,
                                   target_quote_no: str = '', reason: str = '') -> None:
    """業務開發案件報價單連結異動申請（改連結或清空連結）→ 通知所有最高管理者審核"""
    to = _superadmin_emails("dev_case_relink_request")
    if not to:
        logger.warning("notify_dev_case_relink_request: 無最高管理者 email（case_id=%d）", case_id)
        return
    crm_page = f"{_base_url()}/pages/dev-crm.html"
    action_desc = f"改為連結至 {target_quote_no}" if target_quote_no else "解除連結（清空報價單號）"
    rows = [("案件名稱", case_name), ("申請人", requester_display), ("異動內容", action_desc)]
    if reason and reason.strip():
        rows.append(("申請原因", reason.strip()))
    html = _build_html(
        "業務開發案件報價單連結異動申請", "請盡速審核", "#DC2626",
        rows, "", crm_page,
        intro=f"{requester_display} 申請異動業務開發案件的報價單連結，請最高管理者登入系統審核。",
        button_text="前往審核",
    )
    _async_send(to, f"【MOTRIX】業務開發案件連結異動申請 — {case_name}", html)


def notify_daily_task_completed(task_id: int, title: str, task_date: str,
                                completed_by_username: str, completed_by_display: str,
                                report: str,
                                supervisor_usernames: list = None,
                                is_edit: bool = False,
                                old_report: str = "") -> None:
    """工作事項完成回報 → 通知指定主管；未指定則通知所有 admin/superadmin。
    is_edit=True 時使用「已修改」格式並顯示修改前後對照。"""
    if supervisor_usernames:
        to = _lookup_emails(supervisor_usernames, "daily_task_completed")
        if not to:
            logger.warning(
                "notify_daily_task_completed: 指定主管均無設定 email，信件略過"
                "（task_id=%d, supervisors=%s）", task_id, supervisor_usernames,
            )
            return
    else:
        to = _admin_emails("daily_task_completed")
    if not to:
        logger.warning("notify_daily_task_completed: 無有效收件人（task_id=%d）", task_id)
        return
    task_page = f"{_base_url()}/pages/daily-tasks.html"
    name = completed_by_display or completed_by_username
    if is_edit:
        old_text = old_report or "（未填寫）"
        new_text = report or "（未填寫）"
        html = (
            f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="UTF-8">'
            f'<style>{_STYLE}</style></head><body><div class="card">'
            f'<div style="font-size:18px;font-weight:700;color:#1a1a1a;margin-bottom:16px;">'
            f'工作事項回報已修改 <span class="badge" style="background:#D97706">已修改</span></div>'
            f'<div class="intro"><strong>{name}</strong> 修改了以下工作事項的回報內容，請確認修改前後差異。</div>'
            f'<div class="lbl">執行日期</div><div class="val">{task_date}</div>'
            f'<div class="lbl">工作事項</div><div class="val">{title}</div>'
            f'<div class="lbl">修改人員</div><div class="val">{name}</div>'
            f'<div style="margin-top:14px;padding:10px 12px;background:#FEF3C7;border-radius:6px;'
            f'font-size:12px;color:#92400E;font-weight:600;margin-bottom:4px">修改前</div>'
            f'<div class="val" style="color:#9CA3AF;text-decoration:line-through;white-space:pre-wrap">{old_text}</div>'
            f'<div style="margin-top:8px;padding:10px 12px;background:#F0FDF4;border-radius:6px;'
            f'font-size:12px;color:#15803D;font-weight:600;margin-bottom:4px">修改後</div>'
            f'<div class="val"><strong style="white-space:pre-wrap">{new_text}</strong></div>'
            f'<a href="{task_page}" class="btn" style="display:inline-block;margin-top:22px;padding:10px 22px;background:#1D4ED8;color:#ffffff !important;border-radius:7px;text-decoration:none;font-size:14px;font-weight:600">前往查看回報</a>'
            f'<div class="foot">本郵件由 MOTRIX 營運管理系統自動發送，請勿直接回覆。如有疑問，請聯絡系統管理員。</div>'
            f'</div></body></html>'
        )
        _async_send(to, f"【MOTRIX】工作事項回報已修改 — {name} · {title}（{task_date}）", html)
    else:
        html = _build_html(
            "工作事項完成回報", "已完成", "#16A34A",
            [
                ("執行日期", task_date),
                ("工作事項", title),
                ("回報人員", name),
                ("執行回報", report or "（人員未填寫回報內容）"),
            ],
            "", task_page,
            intro=f"以下工作事項已由 {name} 完成回報，請登入系統查看詳細內容。",
            button_text="前往查看回報",
        )
        _async_send(to, f"【MOTRIX】工作事項完成回報 — {name} · {title}（{task_date}）", html)


def notify_daily_task_overdue(task_id: int, title: str, task_date: str,
                              assignee_username: str, assignee_display: str,
                              supervisor_usernames: list = None) -> None:
    """逾期未完成工作事項 → 通知被指派人 + 指定主管（若有），否則通知所有 admin/superadmin"""
    assignee_to = _lookup_emails([assignee_username], "daily_task_overdue")
    if supervisor_usernames:
        mgr_to = _lookup_emails(supervisor_usernames, "daily_task_overdue")
        if not mgr_to:
            logger.warning(
                "notify_daily_task_overdue: 指定主管均無設定 email（task_id=%d, supervisors=%s）",
                task_id, supervisor_usernames,
            )
    else:
        mgr_to = _admin_emails("daily_task_overdue")
    to = list({*assignee_to, *mgr_to})
    if not to:
        logger.warning(
            "notify_daily_task_overdue: 無法寄信（task_id=%d, username=%s）", task_id, assignee_username
        )
        return
    task_page = f"{_base_url()}/pages/daily-tasks.html"
    name = assignee_display or assignee_username
    html = _build_html(
        "工作事項逾期未完成", "請立即處理", "#DC2626",
        [
            ("執行日期",   task_date),
            ("工作事項",   title),
            ("負責人員",   name),
        ],
        "", task_page,
        intro=f"{name} 負責的以下工作事項於 {task_date} 截止日前尚未完成回報，請盡速確認處理狀況。",
        button_text="前往查看工作事項",
    )
    _async_send(to, f"【MOTRIX】工作事項逾期未完成 — {name} · {title}（{task_date}）", html)


def notify_daily_task_overdue_manager(task_id: int, title: str, task_date: str,
                                       assignee_username: str, assignee_display: str,
                                       department_id: int) -> None:
    """逾期未完成工作事項 → 額外通知負責人所屬部門的主管（2026-08-22g）。
    獨立事件 key（daily_task_overdue_manager），跟指派人自己收到的
    daily_task_overdue 分開訂閱/取消訂閱，且跟任務本身的 supervisors
    欄位（既有的、逐任務手動指定的主管清單）是兩條互不相關的路徑——
    這裡走的是組織架構（departments.manager_user_id），department_id
    是空值或部門沒有主管時直接安靜跳過，不當錯誤處理（純通知性質，
    不像簽核路由那樣需要擋下流程）。"""
    to = _department_manager_emails(department_id, "daily_task_overdue_manager")
    if not to:
        return
    task_page = f"{_base_url()}/pages/daily-tasks.html"
    name = assignee_display or assignee_username
    html = _build_html(
        "部門成員工作事項逾期未完成", "請關注處理", "#DC2626",
        [
            ("執行日期",   task_date),
            ("工作事項",   title),
            ("負責人員",   name),
        ],
        "", task_page,
        intro=f"您部門的 {name} 負責的以下工作事項於 {task_date} 截止日前尚未完成回報，請關注處理狀況。",
        button_text="前往查看工作事項",
    )
    _async_send(to, f"【MOTRIX】部門成員工作事項逾期未完成 — {name} · {title}（{task_date}）", html)


def notify_range_task_deadline(
    task_id: int,
    title: str,
    end_date: str,
    days_left: int,
    assignee_username: str,
    assignee_display: str,
    supervisor_usernames: list = None,
) -> None:
    """區間工作事項即將到期 → 指派人 + 主管"""
    assignee_to = _lookup_emails([assignee_username], "range_task_deadline")
    if supervisor_usernames:
        mgr_to = _lookup_emails(supervisor_usernames, "range_task_deadline")
        if not mgr_to:
            mgr_to = _admin_emails("range_task_deadline")
    else:
        mgr_to = _admin_emails("range_task_deadline")
    to = list({*assignee_to, *mgr_to})
    if not to:
        return
    task_page = f"{_base_url()}/pages/daily-tasks.html"
    name = assignee_display or assignee_username
    if days_left == 0:
        badge_text, badge_color = "今日截止", "#DC2626"
        intro = (f"{name} 負責的區間工作事項「{title}」"
                 f"今日（{end_date}）為最後截止日，請盡速完成並回報。")
    else:
        badge_text, badge_color = f"剩餘 {days_left} 天", "#D97706"
        intro = (f"{name} 負責的區間工作事項「{title}」"
                 f"將於 {end_date} 截止，尚餘 {days_left} 天，請儘早完成並回報。")
    html = _build_html(
        "區間工作事項即將到期", badge_text, badge_color,
        [("工作事項", title), ("截止日期", end_date), ("負責人員", name)],
        "", task_page,
        intro=intro,
        button_text="前往工作事項",
    )
    _async_send(to, f"【MOTRIX】區間工作事項即將到期 — {name} · {title}（{end_date}）", html)


def notify_case_stage_deadline(
    quote_no: str,
    stage_label: str,
    due_date: str,
    days_left: int,
    assignee_username: str,
    assignee_display: str,
    customer_name: str = "",
    project_name: str = "",
    supervisor_usernames: list = None,
) -> None:
    """案件執行進度階段即將到期／已逾期 → 負責人 + 主管（無則 admin）"""
    assignee_to = _lookup_emails([assignee_username], "case_stage_deadline")
    if supervisor_usernames:
        mgr_to = _lookup_emails(supervisor_usernames, "case_stage_deadline")
        if not mgr_to:
            mgr_to = _admin_emails("case_stage_deadline")
    else:
        mgr_to = _admin_emails("case_stage_deadline")
    to = list({*assignee_to, *mgr_to})
    if not to:
        return
    case_page = f"{_base_url()}/pages/case-management.html?q={quote_no}"
    name  = assignee_display or assignee_username
    label = f"{customer_name}{'／' if customer_name and project_name else ''}{project_name}" or quote_no
    if days_left <= 0:
        badge_text, badge_color = "已逾期", "#DC2626"
        intro = (f"{name} 負責的案件「{label}」執行進度階段「{stage_label}」"
                 f"已於 {due_date} 到期尚未完成，請盡速確認處理狀況。")
    else:
        badge_text, badge_color = f"剩餘 {days_left} 天", "#D97706"
        intro = (f"{name} 負責的案件「{label}」執行進度階段「{stage_label}」"
                 f"將於 {due_date} 到期，尚餘 {days_left} 天，請儘早確認進度。")
    html = _build_html(
        "案件執行進度即將到期", badge_text, badge_color,
        [("案件單號", quote_no), ("階段", stage_label), ("到期日期", due_date), ("負責人員", name)],
        "", case_page,
        intro=intro,
        button_text="前往案件管理",
    )
    _async_send(to, f"【MOTRIX】案件執行進度到期提醒 — {name} · {label} · {stage_label}", html)


def notify_case_stage_deadline_manager(
    quote_no: str,
    stage_label: str,
    due_date: str,
    days_left: int,
    assignee_username: str,
    assignee_display: str,
    department_id: int,
    customer_name: str = "",
    project_name: str = "",
) -> None:
    """案件執行進度階段即將到期／已逾期 → 額外通知負責人所屬部門的主管（案件/專案管理延伸，2026-08-22）。
    比照 notify_daily_task_overdue_manager 的既有原則：獨立事件 key，跟負責人自己收到的
    case_stage_deadline 分開訂閱/取消訂閱；department_id 是空值或部門沒有主管時安靜跳過，
    純通知性質，不擋流程。"""
    to = _department_manager_emails(department_id, "case_stage_deadline_manager")
    if not to:
        return
    case_page = f"{_base_url()}/pages/case-management.html?q={quote_no}"
    name  = assignee_display or assignee_username
    label = f"{customer_name}{'／' if customer_name and project_name else ''}{project_name}" or quote_no
    if days_left <= 0:
        badge_text, badge_color = "已逾期", "#DC2626"
        intro = (f"您部門的 {name} 負責的案件「{label}」執行進度階段「{stage_label}」"
                 f"已於 {due_date} 到期尚未完成，請關注處理狀況。")
    else:
        badge_text, badge_color = f"剩餘 {days_left} 天", "#D97706"
        intro = (f"您部門的 {name} 負責的案件「{label}」執行進度階段「{stage_label}」"
                 f"將於 {due_date} 到期，尚餘 {days_left} 天，請儘早關注。")
    html = _build_html(
        "部門成員案件執行進度即將到期", badge_text, badge_color,
        [("案件單號", quote_no), ("階段", stage_label), ("到期日期", due_date), ("負責人員", name)],
        "", case_page,
        intro=intro,
        button_text="前往案件管理",
    )
    _async_send(to, f"【MOTRIX】部門成員案件進度到期提醒 — {name} · {label} · {stage_label}", html)


def notify_project_deadline(
    project_id: int,
    project_code: str,
    project_name: str,
    end_date: str,
    days_left: int,
    assignee_username: str,
    assignee_display: str,
) -> None:
    """專案「預計完工」日期即將到期／已逾期 → 通知被分配的成員（無分配則 admin）"""
    assignee_to = _lookup_emails([assignee_username], "project_deadline") if assignee_username else []
    to = list({*assignee_to, *(_admin_emails("project_deadline") if not assignee_to else [])})
    if not to:
        return
    project_page = f"{_base_url()}/pages/projects.html?id={project_id}"
    name = assignee_display or assignee_username or "（未指派成員）"
    if days_left <= 0:
        badge_text, badge_color = "已逾期", "#DC2626"
        intro = f"專案「{project_name}」（{project_code}）預計完工日 {end_date} 已到期，請盡速確認進度。"
    else:
        badge_text, badge_color = f"剩餘 {days_left} 天", "#D97706"
        intro = f"專案「{project_name}」（{project_code}）預計於 {end_date} 完工，尚餘 {days_left} 天，請儘早確認進度。"
    html = _build_html(
        "專案預計完工日即將到期", badge_text, badge_color,
        [("專案代號", project_code), ("專案名稱", project_name), ("預計完工", end_date)],
        "", project_page,
        intro=intro,
        button_text="前往專案管理",
    )
    _async_send(to, f"【MOTRIX】專案到期提醒 — {project_name}（{project_code}）", html)


def notify_project_deadline_manager(
    project_id: int,
    project_code: str,
    project_name: str,
    end_date: str,
    days_left: int,
    department_id: int,
) -> None:
    """專案「預計完工」日期即將到期／已逾期 → 額外通知專案所屬部門的主管（案件/專案管理延伸，2026-08-22）。
    跟 notify_project_deadline（通知被分配成員）是兩條獨立路徑；department_id 是空值或
    部門沒有主管時安靜跳過，純通知性質，不擋流程。"""
    to = _department_manager_emails(department_id, "project_deadline_manager")
    if not to:
        return
    project_page = f"{_base_url()}/pages/projects.html?id={project_id}"
    if days_left <= 0:
        badge_text, badge_color = "已逾期", "#DC2626"
        intro = f"您部門的專案「{project_name}」（{project_code}）預計完工日 {end_date} 已到期，請關注進度。"
    else:
        badge_text, badge_color = f"剩餘 {days_left} 天", "#D97706"
        intro = f"您部門的專案「{project_name}」（{project_code}）預計於 {end_date} 完工，尚餘 {days_left} 天，請儘早關注。"
    html = _build_html(
        "部門專案預計完工日即將到期", badge_text, badge_color,
        [("專案代號", project_code), ("專案名稱", project_name), ("預計完工", end_date)],
        "", project_page,
        intro=intro,
        button_text="前往專案管理",
    )
    _async_send(to, f"【MOTRIX】部門專案到期提醒 — {project_name}（{project_code}）", html)


def notify_dev_case_stale(case_id: int, case_name: str, customer_name: str,
                           days_since_update: int, usernames: list) -> None:
    """業務開發案件洽談中超過 30 天未更新 → 通知業務開發/專案規劃人員 + admin/superadmin"""
    to = _lookup_emails(usernames, "dev_case_stale")
    if not to:
        logger.warning("notify_dev_case_stale: 無有效收件人（case_id=%d）", case_id)
        return
    crm_page = f"{_base_url()}/pages/dev-crm.html"
    html = _build_html(
        "業務開發案件逾期未跟進", f"{days_since_update} 天未更新", "#DC2626",
        [("案件名稱", case_name), ("客戶", customer_name or "（未指定）"),
         ("狀態", "洽談中"), ("未更新天數", f"{days_since_update} 天")],
        "", crm_page,
        intro=f"案件「{case_name}」仍在洽談中，已 {days_since_update} 天未新增開發記錄或更新狀態，請確認後續跟進進度。",
        button_text="前往業務開發",
    )
    _async_send(to, f"【MOTRIX】業務開發案件逾期提醒 — {case_name}", html)


def notify_daily_task_edited(
    task_id: int,
    title: str,
    task_date: str,
    editor_username: str,
    editor_display: str,
    changes: list,
    supervisor_usernames: list = None,
) -> None:
    """工作事項編輯 → 通知指定主管；未指定則通知所有 admin/superadmin"""
    if supervisor_usernames:
        to = _lookup_emails(supervisor_usernames, "daily_task_edited")
        if not to:
            logger.warning(
                "notify_daily_task_edited: 指定主管均無設定 email，信件略過"
                "（task_id=%d, supervisors=%s）", task_id, supervisor_usernames,
            )
            return
    else:
        to = _admin_emails("daily_task_edited")
    if not to:
        logger.warning("notify_daily_task_edited: 無有效收件人（task_id=%d）", task_id)
        return
    task_page = f"{_base_url()}/pages/daily-tasks.html"
    name = editor_display or editor_username
    change_lines = "".join(
        f'<div class="lbl">{c["label"]}</div>'
        f'<div class="val"><span style="text-decoration:line-through;color:#999">{c["old"]}</span>'
        f' → <strong>{c["new"]}</strong></div>'
        for c in (changes or [])
    )
    if not change_lines:
        change_lines = '<div class="val">（無欄位變更）</div>'
    html = (
        f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="UTF-8">'
        f'<style>{_STYLE}</style></head><body><div class="card">'
        f'<div style="font-size:18px;font-weight:700;color:#1a1a1a;margin-bottom:16px;">'
        f'工作事項已編輯 <span class="badge" style="background:#7C3AED">已修改</span></div>'
        f'<div class="intro">以下工作事項由 <strong>{name}</strong> 進行了修改，請確認變更內容。</div>'
        f'<div class="lbl">執行日期</div><div class="val">{task_date}</div>'
        f'<div class="lbl">工作事項</div><div class="val">{title}</div>'
        f'<div class="lbl">編輯人員</div><div class="val">{name}</div>'
        f'<div style="margin-top:14px;padding:10px 12px;background:#F5F3FF;border-radius:6px;'
        f'font-size:12px;color:#5B21B6;font-weight:600">異動欄位</div>'
        f'{change_lines}'
        f'<a href="{task_page}" class="btn" style="display:inline-block;margin-top:22px;padding:10px 22px;background:#1D4ED8;color:#ffffff !important;border-radius:7px;text-decoration:none;font-size:14px;font-weight:600">前往查看工作事項</a>'
        f'<div class="foot">本郵件由 MOTRIX 營運管理系統自動發送，請勿直接回覆。'
        f'如有疑問，請聯絡系統管理員。</div>'
        f'</div></body></html>'
    )
    _async_send(to, f"【MOTRIX】工作事項已編輯 — {name} · {title}（{task_date}）", html)


def notify_warranty_expiry(
    device_name: str,
    customer: str,
    quote_no: str,
    days_left: int,
    expiry_date: str,
    sales_person: str,
) -> None:
    """保固即將到期 → 業務員 + 管理員"""
    to = list(dict.fromkeys(_lookup_emails([sales_person], "warranty_expiry") + _admin_emails("warranty_expiry")))
    if not to:
        logger.warning("notify_warranty_expiry: 無有效收件人（quote_no=%r）", quote_no)
        return
    color  = "#DC2626" if days_left <= 7 else "#D97706"
    label  = "緊急預警：7天內到期" if days_left <= 7 else "30天到期預警"
    html = _build_html(
        "設備保固即將到期", label, color,
        [
            ("設備名稱", device_name),
            ("客戶",     customer),
            ("到期日",   expiry_date),
            ("剩餘天數", f"{days_left} 天"),
            ("案件編號", quote_no),
        ],
        quote_no, _base_url(),
        intro=f"您負責的案件中有設備保固即將到期，請儘早與客戶確認是否需要延展保固或安排後續服務。",
        button_text="前往查看案件",
    )
    _async_send(
        to,
        f"【MOTRIX】保固到期預警 — {device_name}（{customer}）剩 {days_left} 天",
        html,
    )


def notify_settlement_finalized(quote_no: str, customer: str, finalized_by: str) -> None:
    """精算完結 → 通知 admin_emails"""
    to = _admin_emails("settlement_finalized")
    if not to:
        logger.warning("notify_settlement_finalized: 所有管理員皆無設定 email（quote_no=%r）", quote_no)
        return
    html = _build_html(
        "成本精算完結通知", "精算完結", "#7C3AED",
        [("報價單號", quote_no), ("客戶名稱", customer), ("完結人員", finalized_by)],
        quote_no, _base_url(),
        intro=f"以下報價單之成本精算已由 {finalized_by} 完結確認，請登入系統查閱最終結算資料。",
        button_text="前往查看精算結果",
    )
    _async_send(to, f"【MOTRIX】成本精算完結 — {quote_no}（{customer}）", html)


# ── Monthly report ────────────────────────────────────────────────────────────

def _superadmin_emails(event_key: str = None) -> list:
    """Return emails of active superadmin users; fallback to all admin/superadmin."""
    try:
        from db import get_db
        conn = get_db()
        rows = conn.execute(
            "SELECT email, notification_muted FROM users "
            "WHERE active=1 AND role='superadmin' "
            "AND email IS NOT NULL AND email != ''",
        ).fetchall()
        conn.close()
        emails = [r["email"] for r in rows if _pref_enabled(r["notification_muted"], event_key)]
        return emails if emails else _admin_emails(event_key)
    except Exception as exc:
        logger.warning("_superadmin_emails failed: %s", exc)
        return []


def _department_manager_emails(department_id: int, event_key: str = None) -> list:
    """Return the email of a department's current manager (empty list if the
    department has no manager set, the manager account has no email, or the
    manager has muted event_key). 2026-08-22g：處/部門組織架構的通知路由，
    比照 _superadmin_emails() 的寫法，只是收件人改成查 departments.manager_user_id。"""
    if not department_id:
        return []
    try:
        from db import get_db
        conn = get_db()
        row = conn.execute("""
            SELECT u.email, u.notification_muted FROM departments d
            JOIN users u ON u.id = d.manager_user_id
            WHERE d.id=? AND u.active=1 AND u.email IS NOT NULL AND u.email != ''
        """, (department_id,)).fetchone()
        conn.close()
        if not row or not _pref_enabled(row["notification_muted"], event_key):
            return []
        return [row["email"]]
    except Exception as exc:
        logger.warning("_department_manager_emails failed: %s", exc)
        return []


def _send_with_attachments(to_addrs: list, subject: str, html: str, attachments: list) -> None:
    """Send HTML email with binary file attachments.
    attachments: list of (filename_str, bytes, mime_type_str) e.g. ("report.xlsx", b"...", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    """
    cfg = _cfg()
    if not cfg.get("enabled"):
        return
    if not to_addrs:
        logger.warning("email skipped — recipient list empty; subject: %r", subject)
        return
    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user", "")
    pw   = cfg.get("smtp_password", "")
    from_name = cfg.get("from_name", "MOTRIX營運系統")
    if not user or not pw:
        logger.warning("email skipped — SMTP credentials not configured; subject: %r", subject)
        return

    outer = MIMEMultipart("mixed")
    outer["Subject"] = subject
    outer["From"]    = f"{from_name} <{user}>"
    outer["To"]      = ", ".join(to_addrs)

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html, "html", "utf-8"))
    outer.attach(alt)

    for fname, fbytes, ftype in attachments:
        main_type, sub_type = (ftype + "/octet-stream").split("/", 1)[:2]
        if "/" in ftype:
            main_type, sub_type = ftype.split("/", 1)
        part = _MIMEBase(main_type, sub_type)
        part.set_payload(fbytes)
        _encode_b64(part)
        # RFC 5987 filename encoding for non-ASCII characters
        part.add_header(
            "Content-Disposition",
            f"attachment; filename*=UTF-8''{_pct_quote(fname)}",
        )
        outer.attach(part)

    try:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            s.login(user, pw)
            s.sendmail(user, to_addrs, outer.as_string())
        logger.info("email+attachments sent to %s — %r", to_addrs, subject)
    except Exception as exc:
        logger.warning("email+attachments send failed: %s", exc)


def notify_monthly_report(period_label: str, period_str: str,
                          excel_bytes: bytes, pdf_bytes: bytes) -> None:
    """每月營運報表 → 寄送 Excel + PDF 附件給 superadmin 使用者"""
    to = _superadmin_emails("monthly_report")
    if not to:
        logger.warning("notify_monthly_report: 無 superadmin email 收件人（period=%r）", period_str)
        return

    base = _base_url()
    html = (
        f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="UTF-8">'
        f'<style>{_STYLE}</style></head><body><div class="card">'
        f'<div style="font-size:18px;font-weight:700;color:#1a1a1a;margin-bottom:16px;">'
        f'每月營運報表 <span class="badge" style="background:#2563EB">{period_label}</span></div>'
        f'<div class="intro">您好，以下為 {period_label} 的完整營運報表，請查收附件中的 Excel 及 PDF 格式。'
        f'如需查閱即時資料，請至線上報表系統。</div>'
        f'<div class="lbl">報表期間</div><div class="val">{period_label}</div>'
        f'<div class="lbl">附件格式</div><div class="val">Excel（.xlsx）+ PDF</div>'
        f'<a href="{base}/pages/reports.html" class="btn" style="display:inline-block;margin-top:22px;padding:10px 22px;background:#1D4ED8;color:#ffffff !important;border-radius:7px;text-decoration:none;font-size:14px;font-weight:600">前往線上報表系統</a>'
        f'<div class="foot">本郵件由 MOTRIX 營運管理系統每月自動寄送，請勿直接回覆。'
        f'如有疑問，請聯絡系統管理員。</div>'
        f'</div></body></html>'
    )

    safe = period_label.replace(" ", "").replace("年", "Y").replace("月", "M")
    attachments = []
    if excel_bytes:
        attachments.append((
            f"MOTRIX_營運報表_{safe}.xlsx",
            excel_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ))
    if pdf_bytes:
        attachments.append((
            f"MOTRIX_營運報表_{safe}.pdf",
            pdf_bytes,
            "application/pdf",
        ))
    if not attachments:
        logger.warning("notify_monthly_report: 無可寄附件（period=%r）", period_str)
        return

    threading.Thread(
        target=_send_with_attachments,
        args=(to, f"【MOTRIX】{period_label}營運報表", html, attachments),
        daemon=True,
    ).start()


def notify_module_activity(module_label: str, action_label: str,
                           actor: str, item_label: str,
                           page_path: str = "", detail: str = "") -> None:
    """Non-blocking email to all admin/superadmin when a new item is created in any module.

    detail: optional full free-text body (comment / log content / note ...). Always rendered
    in full, never truncated — the point is recipients can read the whole thing in the email
    itself without having to log into the system. Pass the real content here instead of
    folding a truncated snippet into item_label."""
    to = _admin_emails("module_activity")
    if not to:
        return
    base = _base_url()
    link = f"{base}/pages/{page_path}" if page_path else base
    detail_html = ""
    if detail and detail.strip():
        detail_esc = _html.escape(detail.strip()).replace("\n", "<br>")
        detail_html = f'<div class="lbl">內容</div><div class="val" style="white-space:pre-wrap">{detail_esc}</div>'
    html = (
        f'<!DOCTYPE html><html lang="zh-Hant"><head><meta charset="UTF-8">'
        f'<style>{_STYLE}</style></head><body><div class="card">'
        f'<div style="font-size:18px;font-weight:700;color:#1a1a1a;margin-bottom:16px;">'
        f'MOTRIX系統通知 <span class="badge" style="background:#2563EB">{_html.escape(module_label)}</span></div>'
        f'<div class="intro"><b>{_html.escape(actor)}</b> 在 <b>{_html.escape(module_label)}</b> 執行了 <b>{_html.escape(action_label)}</b>。</div>'
        f'<div class="lbl">項目</div><div class="val">{_html.escape(item_label)}</div>'
        f'{detail_html}'
        f'<a href="{link}" class="btn" style="display:inline-block;margin-top:22px;'
        f'padding:10px 22px;background:#1D4ED8;color:#ffffff !important;border-radius:7px;'
        f'text-decoration:none;font-size:14px;font-weight:600">前往系統查看</a>'
        f'<div class="foot">本郵件由 MOTRIX 營運管理系統自動發送，請勿直接回覆。</div>'
        f'</div></body></html>'
    )
    _async_send(to, f"[MOTRIX] {module_label} — {action_label}", html)
