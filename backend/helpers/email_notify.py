"""External email notifications via SMTP (Gmail App Password)."""
import html as _html
import logging
import os
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


def _is_production_install() -> bool:
    """正式機身分守門，比照 apply_update.ps1／setup_autostart_task.ps1 既有的
    「只認 C:\\Users\\Motrix\\Desktop\\V9.0 這個安裝路徑」慣例——這支檔案自己的
    絕對路徑若不在 \\V9.0\\ 底下，就一律視為開發/測試環境。"""
    here = os.path.abspath(__file__).replace("/", "\\")
    return "\\V9.0\\" in here


_PRODUCTION_INSTALL = _is_production_install()


def _smtp_send_blocked(subject: str) -> bool:
    """2026-08-27 新增的硬性防呆：開發機啟動 dev server 時，既有的「簽核逾期催辦」
    啟動排程曾經意外對真實同仁寄出真實催辦信（見 _apply_dev_subject_prefix 的
    dev_mode 機制——那套是 2026-08-26 針對同類事故加的軟性提醒，只會在 subject
    加註文字，需要手動開啟且不會真的擋下寄送，這次同一種事故又發生了一次，代表
    「預設關閉、需要手動開啟」的軟性方案不夠）。這裡改成預設硬擋：只要目前執行的
    程式碼不是安裝在正式機路徑（_is_production_install()），無論 email_notify 設定
    的 enabled／dev_mode 開關怎麼設，一律不會真的呼叫 SMTP 寄信，只會記錄
    log 供除錯查看內容。要在開發機真的測試寄信，請直接用真實的正式機環境測試，
    不要在本機開發環境啟動會觸發背景排程的完整 dev server。"""
    if _PRODUCTION_INSTALL:
        return False
    logger.warning("email BLOCKED — not running from production install path (dev/test environment); subject: %r", subject)
    return True

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
        f'<div class="foot">本郵件由 MOTRIX 專案管理系統自動發送，請勿直接回覆。'
        f'如有疑問，請聯絡系統管理員。</div>'
        f'</div></body></html>'
    )


def _cfg() -> dict:
    return _get_setting("email_notify", {}) or {}


def _base_url() -> str:
    # 2026-08-27：預設值改 https（見 backend/tools/https_setup.ps1）——但這只影響
    # 「從未存過設定值」的情況，正式機若已經存過 http 版本，這裡的預設值改變不會
    # 回溯更新既有設定，套用 HTTPS 後需要 superadmin 手動去通知設定頁更新一次。
    return (_cfg().get("base_url") or "https://172.16.10.177:666").rstrip("/")


_DEV_SUBJECT_PREFIX = "【開發機測試】"


def _apply_dev_subject_prefix(cfg: dict, subject: str) -> str:
    """開發機測試模式（system_settings.email_notify.dev_mode，2026-08-26 新增）：
    這是存在各機器自己 SQLite DB 裡的設定值，不隨 git 部署流程移動，正式機的
    DB 不會被這個設定影響，只要開發機自己開啟即可，避免開發機測試觸發的通知信
    被收件人誤認為正式環境的真實通知（見一次啟動開發伺服器後不慎寄出正式逾期
    提醒信給真實同仁的事故）。"""
    if not cfg.get("dev_mode"):
        return subject
    if subject.startswith(_DEV_SUBJECT_PREFIX):
        return subject
    return f"{_DEV_SUBJECT_PREFIX}{subject}"


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
    subject = _apply_dev_subject_prefix(cfg, subject)
    if _smtp_send_blocked(subject):
        return
    if not to_addrs:
        logger.warning("email skipped — recipient list empty; subject: %r", subject)
        return
    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user", "")
    pw   = cfg.get("smtp_password", "")
    from_name = cfg.get("from_name", "MOTRIX專案管理系統")
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
    subject = _apply_dev_subject_prefix(cfg, subject)
    if _smtp_send_blocked(subject):
        raise RuntimeError("非正式機環境，已擋下寄送（見 _smtp_send_blocked 說明）")
    if not to_addrs:
        raise RuntimeError("收件人清單為空")
    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user", "")
    pw   = cfg.get("smtp_password", "")
    from_name = cfg.get("from_name", "MOTRIX專案管理系統")
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


def notify_payment_request_submitted(request_no: str, customer: str, approver_usernames: list) -> None:
    """請款單送審 → 通知當層簽核人"""
    to = _lookup_emails(approver_usernames, "payment_request_submitted")
    if not to:
        logger.warning("notify_payment_request_submitted: 簽核人 %s 皆無設定 email（request_no=%r）",
                       approver_usernames, request_no)
        return
    page = f"{_base_url()}/pages/case-management.html"
    html = _build_html(
        "請款單簽核申請", "待您審核", "#2F6FD6",
        [("請款單號", request_no), ("客戶名稱", customer)],
        "", page,
        intro="您好，以下請款單已進入簽核流程，敬請於系統中完成審核作業。",
        button_text="前往審核",
    )
    _async_send(to, f"【MOTRIX】請款單待審核 — {request_no}（{customer}）", html)


def notify_payment_request_next_tier(request_no: str, customer: str, tier_no: int,
                                     total_tiers: int, approver_usernames: list) -> None:
    """前層通過，請款單下一層簽核通知"""
    to = _lookup_emails(approver_usernames, "payment_request_next_tier")
    if not to:
        logger.warning("notify_payment_request_next_tier: 第 %d 層簽核人 %s 皆無設定 email（request_no=%r）",
                       tier_no, approver_usernames, request_no)
        return
    page = f"{_base_url()}/pages/case-management.html"
    html = _build_html(
        "請款單簽核流程通知", "輪到您審核", "#2F6FD6",
        [("請款單號", request_no), ("客戶名稱", customer),
         ("目前進度", f"第 {tier_no} 層審核（共 {total_tiers} 層）")],
        "", page,
        intro=f"您好，前層審核已完成，請款單現已進入第 {tier_no} 層審核階段，敬請登入系統完成審核。",
        button_text="前往審核",
    )
    _async_send(to, f"【MOTRIX】請款單審核通知（第 {tier_no}/{total_tiers} 層）— {request_no}（{customer}）", html)


def notify_payment_request_approved(request_no: str, customer: str, approved_by: str,
                                    requester_username: str) -> None:
    """請款單全員簽核完成 → 通知申請人"""
    to = _lookup_emails([requester_username], "payment_request_approved")
    if not to:
        logger.warning("notify_payment_request_approved: 申請人 %r 無設定 email（request_no=%r）",
                       requester_username, request_no)
        return
    page = f"{_base_url()}/pages/case-management.html"
    html = _build_html(
        "請款單審核完成", "已核准", "#16A34A",
        [("請款單號", request_no), ("客戶名稱", customer), ("核准人", approved_by)],
        "", page,
        intro="您好，以下請款單已完成審核並核准。",
        button_text="前往查看",
    )
    _async_send(to, f"【MOTRIX】請款單已核准 — {request_no}（{customer}）", html)


def notify_payment_request_returned(request_no: str, customer: str, note: str,
                                    requester_username: str) -> None:
    """請款單退回 → 通知申請人"""
    to = _lookup_emails([requester_username], "payment_request_returned")
    if not to:
        logger.warning("notify_payment_request_returned: 申請人 %r 無設定 email（request_no=%r）",
                       requester_username, request_no)
        return
    page = f"{_base_url()}/pages/case-management.html"
    html = _build_html(
        "請款單退回通知", "請修改後重新送審", "#DC2626",
        [("請款單號", request_no), ("客戶名稱", customer)],
        "", page,
        intro="您好，您送出的請款單經審核後，因需要調整已退回，請參閱下方備註後完成修改並重新送審。",
        note=note,
        button_text="前往修改",
    )
    _async_send(to, f"【MOTRIX】請款單已退回 — {request_no}（{customer}）", html)


def notify_approval_reminder(doc_type_label: str, doc_no: str, desc: str, days_elapsed: int,
                             approver_usernames: list, also_superadmin: bool = False) -> None:
    """簽核逾期催辦（2026-08-21，2026-08-24 補上出貨單，2026-08-25 收斂收件人）：
    報價單／承攬商匯款申請／開票申請憑據／出貨單共用同一支——卡在簽核柱列超過
    工作日 1/3/5 天時由 routers/daily_tasks.py 的每日排程呼叫。days_elapsed 決定
    badge 文字/顏色的嚴重度分級；also_superadmin 為真時額外加上最高管理員收件人
    （3 天門檻起）——只通知 superadmin，不是全部 admin，避免一般 admin 被灌爆。
    統一連到簽核佇列頁（四種文件現在都在同一頁），不用像其他通知一樣依文件類型
    分開連結。"""
    to = list(set(_lookup_emails(approver_usernames, "approval_reminder")
                  + (_superadmin_emails("approval_reminder") if also_superadmin else [])))
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
            f'<div class="foot">本郵件由 MOTRIX 專案管理系統自動發送，請勿直接回覆。如有疑問，請聯絡系統管理員。</div>'
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
        f'<div class="foot">本郵件由 MOTRIX 專案管理系統自動發送，請勿直接回覆。'
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


def notify_case_closing_report(quote_no: str, customer: str, project: str, pdf_bytes: bytes) -> None:
    """案件標記已結案 → 自動寄送內部結案報表 PDF 給最高管理員（2026-08-25）。
    報表含成本/毛利等內部機密資訊，只寄 superadmin（不比照 notify_settlement_finalized
    發給全部 admin），由 pdf_gen.py::_generate_case_closing_pdf() 產生 PDF 成功後呼叫。"""
    to = _superadmin_emails("case_closing_report")
    if not to:
        logger.warning("notify_case_closing_report: 無 superadmin email 收件人（quote_no=%r）", quote_no)
        return
    if not pdf_bytes:
        logger.warning("notify_case_closing_report: PDF 內容為空，略過寄送（quote_no=%r）", quote_no)
        return
    case_page = f"{_base_url()}/pages/case-management.html?q={quote_no}"
    label = f"{customer}{'／' + project if project else ''}" or quote_no
    html = _build_html(
        "案件結案報表", "已產生", "#7C3AED",
        [("報價單號", quote_no), ("客戶名稱", customer), ("專案名稱", project or "（未填寫）")],
        "", case_page,
        intro=f"案件「{label}」已標記結案，系統已自動產生內部結案報表 PDF（含收入/成本/損益分析等內部財務資訊），詳見附件，僅供內部留存查核使用。",
        button_text="前往查看案件",
    )
    attachments = [(f"{quote_no}_結案報表.pdf", pdf_bytes, "application/pdf")]
    threading.Thread(
        target=_send_with_attachments,
        args=(to, f"【MOTRIX】案件結案報表 — {quote_no}（{customer}）", html, attachments),
        daemon=True,
    ).start()


def notify_case_close_blocked(quote_no: str, customer: str, project: str,
                              reasons: list, pending_usernames: list) -> None:
    """完結案防呆擋下（2026-08-26）：三項前置條件（執行進度100%／款項全收齊／
    相關單據簽核完成）任一未達成時，完結案動作被擋下，通知尚未完成該項的
    簽核人（pending_usernames，可能為空——例如款項未收齊沒有對應的「簽核人」
    概念）＋最高管理員（不論如何都通知，即使 pending_usernames 已涵蓋所有
    superadmin，重複的 email 由呼叫端 set() 去重）。"""
    to = list(set(_lookup_emails(pending_usernames, "case_close_blocked")
                  + _superadmin_emails("case_close_blocked")))
    if not to:
        logger.warning("notify_case_close_blocked: 無收件人（quote_no=%r）", quote_no)
        return
    case_page = f"{_base_url()}/pages/case-management.html?q={quote_no}"
    label = f"{customer}{'／' + project if project else ''}" or quote_no
    html = _build_html(
        "完結案被擋下", "尚未達成前置條件", "#DC2626",
        [("報價單號", quote_no), ("客戶名稱", customer), ("專案名稱", project or "（未填寫）"),
         ("未達成項目", "、".join(reasons))],
        "", case_page,
        intro=f"案件「{label}」嘗試完結案時被系統擋下，因為尚有前置條件未達成，請盡速處理相關項目後再次嘗試完結案。",
        button_text="前往查看案件",
    )
    _async_send(to, f"【MOTRIX】完結案被擋下 — {quote_no}（{customer}）", html)


def notify_case_change_requested(quote_no: str, customer: str, project: str,
                                 summary: str, requester_display: str) -> None:
    """已結案案件半解鎖期間的變更/上傳請求（2026-08-26）→ 通知最高管理員審核
    （routers/quotations.py 新增的 8 個「暫存待審」端點共用這支）。只寄
    superadmin，跟 notify_case_closing_report 一樣的收件範圍取捨——已結案
    案件的異動審核屬於高權限操作，不比照一般附件上傳（任何人可傳）發給全部
    admin。"""
    to = _superadmin_emails("case_change_requested")
    if not to:
        logger.warning("notify_case_change_requested: 無 superadmin email 收件人（quote_no=%r）", quote_no)
        return
    queue_page = f"{_base_url()}/pages/approval-queue.html"
    label = f"{customer}{'／' + project if project else ''}" or quote_no
    html = _build_html(
        "已結案案件變更待審核", "待審核", "#7C3AED",
        [("報價單號", quote_no), ("客戶名稱", customer), ("申請人", requester_display),
         ("變更內容", summary)],
        "", queue_page,
        intro=f"已結案案件「{label}」目前處於半解鎖狀態，{requester_display} 提出以下變更，需最高管理員於簽核佇列審核後才會套用。",
        button_text="前往簽核佇列",
    )
    _async_send(to, f"【MOTRIX】已結案案件變更待審核 — {quote_no}（{customer}）", html)


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


def _monthly_report_recipient_emails() -> list:
    """每月營運報表收件人（2026-08-27 起可設定，取代原本寫死只寄 superadmin）。
    settings key 從未寫入過（superadmin 還沒按過一次「儲存」）時，沿用舊行為寄給
    superadmin，避免上線當下設定值是空的、突然沒人收到信；一旦 superadmin 存過
    一次（即使存的是空清單），就完全照設定值決定收件人，不再 fallback。"""
    raw = _get_setting("monthly_report_recipients")
    if raw is None:
        return _superadmin_emails("monthly_report")
    user_ids = raw.get("userIds") or []
    if not user_ids:
        return []
    try:
        from db import get_db
        conn = get_db()
        placeholders = ",".join("?" * len(user_ids))
        rows = conn.execute(
            f"SELECT email, notification_muted FROM users "
            f"WHERE active=1 AND id IN ({placeholders}) "
            f"AND email IS NOT NULL AND email != ''",
            user_ids,
        ).fetchall()
        conn.close()
        return [r["email"] for r in rows if _pref_enabled(r["notification_muted"], "monthly_report")]
    except Exception as exc:
        logger.warning("_monthly_report_recipient_emails failed: %s", exc)
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
    subject = _apply_dev_subject_prefix(cfg, subject)
    if _smtp_send_blocked(subject):
        return
    if not to_addrs:
        logger.warning("email skipped — recipient list empty; subject: %r", subject)
        return
    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user", "")
    pw   = cfg.get("smtp_password", "")
    from_name = cfg.get("from_name", "MOTRIX專案管理系統")
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
    """每月營運報表 → 寄送 Excel + PDF 附件給設定的收件人（見 _monthly_report_recipient_emails）"""
    to = _monthly_report_recipient_emails()
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
        f'<div class="foot">本郵件由 MOTRIX 專案管理系統每月自動寄送，請勿直接回覆。'
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
        f'<div class="foot">本郵件由 MOTRIX 專案管理系統自動發送，請勿直接回覆。</div>'
        f'</div></body></html>'
    )
    _async_send(to, f"[MOTRIX] {module_label} — {action_label}", html)


def notify_case_project_overdue(
    quote_no: str,
    customer_name: str,
    project_name: str,
    end_date: str,
    days_overdue: int,
) -> None:
    """案件專案期間已超期 → 所有 admin/superadmin"""
    to = _admin_emails("case_project_overdue")
    if not to:
        return
    case_page = f"{_base_url()}/pages/case-management.html?quote={quote_no}"
    if days_overdue == 0:
        badge_text, badge_color = "今日超期", "#DC2626"
        intro = f"案件「{project_name}」（客戶：{customer_name}）預計於 {end_date} 完成，今日已超期。"
    else:
        badge_text, badge_color = f"已超期 {days_overdue} 天", "#DC2626"
        intro = f"案件「{project_name}」（客戶：{customer_name}）預計於 {end_date} 完成，已超期 {days_overdue} 天。"
    html = _build_html(
        "案件專案期間已超期", badge_text, badge_color,
        [("案件號", quote_no), ("客戶", customer_name), ("專案名稱", project_name or "（未填）"), ("預計結束日期", end_date)],
        "", case_page,
        intro=intro,
        button_text="前往案件管理",
    )
    _async_send(to, f"【MOTRIX】案件專案期間已超期 — {project_name or quote_no}（已超期 {days_overdue} 天）", html)


def notify_cert_expiry(
    days_left: int,
    not_after: str,
    issuer_cn: str,
    cert_path: str,
    is_acme: bool,
) -> None:
    """HTTPS 憑證即將到期／已過期 → 所有 admin/superadmin（2026-09-11）

    刻意把「該怎麼修」直接寫進信裡，而且依簽發者分兩種寫法：這封信會在
    好幾百天後才第一次寄出，那時候沒有人會記得 mkcert 或 Posh-ACME 是什麼、
    更不會記得要去翻哪份文件。信裡查得到做法，才不用等到出事當天現學。
    """
    to = _admin_emails("cert_expiry")
    if not to:
        return

    if days_left < 0:
        badge_text, badge_color = f"已過期 {-days_left} 天", "#DC2626"
        intro = (
            f"正式機的 HTTPS 憑證已於 {not_after} 過期（{-days_left} 天前）。"
            "Passkey 現在應該已經完全無法使用。"
        )
    elif days_left == 0:
        badge_text, badge_color = "今日到期", "#DC2626"
        intro = f"正式機的 HTTPS 憑證於今日（{not_after}）到期。"
    else:
        badge_text, badge_color = f"剩 {days_left} 天", "#D97706" if days_left > 7 else "#DC2626"
        intro = f"正式機的 HTTPS 憑證將於 {not_after} 到期，剩下 {days_left} 天。"

    # 影響範圍講清楚，避免收信的人以為「憑證過期＝系統掛了」而驚動所有人
    impact = (
        "<b>影響範圍</b>：<br>"
        "• Passkey／指紋登入 → <b>完全不能用</b>（瀏覽器不再視為安全內容）<br>"
        "• 密碼登入、TOTP、手機掃 QR → <b>仍可使用</b>，但瀏覽器會跳憑證警告，"
        "需要點「進階 → 繼續前往」<br>"
        "• 系統本身與資料 → 不受影響"
    )

    if is_acme:
        howto = (
            "<b>這張是自動續期的憑證（Let's Encrypt）</b>，正常情況下它應該早就自己換好了——"
            "收到這封信代表<b>自動續期已經失敗</b>。請在正式機檢查："
            "<br>1. 排程工作「MOTRIX ERP Cert Renew」是否還在、最近一次執行結果為何"
            "<br>2. <code>backend\\logs\\letsencrypt_renew.log</code> 的錯誤訊息"
            "<br>3. Cloudflare API Token 是否已失效或被撤銷"
            "<br>手動補救：以系統管理員執行 "
            "<code>backend\\tools\\letsencrypt_renew.ps1 -Force</code>"
        )
    else:
        howto = (
            "<b>這張是自簽憑證（mkcert）</b>，不會自己更新，必須手動重產。"
            "在正式機以系統管理員執行："
            "<br><code>backend\\tools\\https_setup.ps1 -ExtraNames motrix.internal -Force</code>"
            "<br>然後執行 <code>backend\\restart.bat</code> 重啟服務。"
            "<br>根 CA 本身有效期到 2036-09-07，<b>同事電腦上裝的 CA 不用動</b>；"
            "重產後 Passkey 也不會失效（RP ID 沒有改變）。"
        )

    html = _build_html(
        "HTTPS 憑證即將到期", badge_text, badge_color,
        [
            ("到期日", not_after),
            ("剩餘天數", f"{days_left} 天" if days_left >= 0 else f"已過期 {-days_left} 天"),
            ("簽發者", issuer_cn or "（不明）"),
            ("憑證檔", cert_path),
        ],
        "", _base_url(),
        note=f"{impact}<br><br>{howto}",
        intro=intro,
        button_text="前往系統",
    )
    subject_state = "已過期" if days_left < 0 else f"剩 {days_left} 天"
    _async_send(to, f"【MOTRIX】HTTPS 憑證{subject_state} — {not_after}", html)


def notify_backup_stale(stale: list, threshold_hours: int) -> None:
    """備份太久沒跑 → 所有 admin/superadmin（2026-09-14）

    `stale` 是 [(標籤, 最後一次成功的 datetime 或 None)]。

    這封信的收件人不見得懂「SQLite 快照」跟「雲端每日 JSON」差在哪，所以信裡
    直接把「這代表什麼、現在有多少風險、該去看哪裡」講完——比照
    notify_cert_expiry() 的作法。備份斷掉跟憑證到期一樣，都是那種**隔很久才
    第一次寄出、寄出時沒有人記得當初怎麼設計的**的告警。
    """
    to = _admin_emails("backup_stale")
    if not to:
        return

    rows, never = [], False
    for label, ts in stale:
        if ts is None:
            rows.append((label, "⚠️ 查無任何成功紀錄"))
            never = True
        else:
            hours = int((datetime.now() - ts).total_seconds() / 3600)
            rows.append((label, f"{ts.strftime('%Y-%m-%d %H:%M')}（{hours} 小時前）"))

    intro = (
        f"系統已超過 {threshold_hours} 小時沒有完成備份。"
        "這封信不是備份執行失敗的通知（那種會另外寄）——"
        "而是<b>備份根本沒有被執行</b>，或執行了但沒有留下成功紀錄。"
    )
    note = (
        "<b>現在的風險</b>：從最後一次成功備份到現在的所有異動，"
        "目前<b>沒有任何一份副本</b>。這段期間若資料庫損毀或誤刪，這些資料救不回來。"
        "<br><br><b>請依序檢查（正式機）</b>："
        "<br>1. 排程工作「MOTRIX ERP Daily Backup」是否還在、最近一次執行結果為何"
        "<br>2. <code>backup_alerts\\BACKUP_ALERT.txt</code> 有沒有內容"
        "<br>3. 雲端碟是否掛得起來（任一磁碟機代號下要找得到 "
        "<code>我的雲端硬碟\\系統存檔</code>）"
        "<br>4. <code>backend\\logs\\server.log</code> 搜尋 <code>_daily_backup</code>"
        "<br>5. <b>是否有第二台機器掛著同一個雲端資料夾</b>——"
        "先跑的那台會寫下當日 <code>.done</code>，正式機看到就直接略過、"
        "而且不會留下任何錯誤紀錄"
        "<br><br><b>立即補救</b>：在正式機執行 "
        "<code>python backend\\backup_job.py</code> 手動觸發一次。"
    )
    if never:
        note = ("<b>其中一項查無任何成功紀錄</b>——若這是新安裝或剛還原的環境，"
                "代表該層備份從未成功執行過，請優先確認排程與雲端碟設定。<br><br>") + note

    html = _build_html(
        "備份已停止運作", "需要立即處理", "#DC2626",
        rows, "", _base_url(),
        note=note, intro=intro, button_text="前往系統",
    )
    _async_send(to, "【MOTRIX】⚠️ 備份已超過 %d 小時沒有成功執行" % threshold_hours, html)


def notify_disk_space_low(problems: list, temp_bloat: list = None,
                          temp_total_gb: float = 0) -> None:
    """磁碟空間不足／測試暫存累積 → 所有 admin/superadmin（2026-09-14）

    `problems` 是 [{label, path, free_gb, total_gb, free_pct}]；
    `temp_bloat` 是 [{name, path, gb}]（2026-09-15 新增）。

    值得單獨寄一封的理由：磁碟滿掉的第一個症狀通常不是「磁碟滿了」，而是
    備份寫不進去、測試跑不起來、PDF 產不出來——很難第一時間聯想到空間。

    **兩種觸發共用一封信與同一個通知偏好 key**（`disk_space_low`）：對收信的人來說
    這是同一件事（空間被吃掉了，要去清），分成兩個開關只會讓人多關一個。
    """
    to = _admin_emails("disk_space_low")
    if not to:
        return

    rows = [(p["label"],
             f"剩餘 {p['free_gb']} GB / 共 {p['total_gb']} GB（{p['free_pct']}%）— {p['path']}")
            for p in problems]

    # 只有測試暫存過大、磁碟還很寬裕時，標題不能寫「空間不足」——那是假訊息，
    # 收信的人會照著去清正式資料。
    if not problems and temp_bloat:
        rows = [(d["name"], f"{d['gb']} GB — {d['path']}") for d in temp_bloat[:12]]
        if len(temp_bloat) > 12:
            rows.append(("…", f"另有 {len(temp_bloat) - 12} 個目錄"))
        html = _build_html(
            "測試暫存佔用過大", f"共 {temp_total_gb} GB 可清除", "#D97706",
            rows, "", _base_url(),
            intro=("測試與打包留下的暫存目錄累積到需要處理的程度了。"
                   "磁碟剩餘空間本身還正常——這封信是在它變成問題之前先講。"),
            note=("<b>這些目錄清掉一律安全</b>：它們是 pytest 每次執行的暫存"
                  "（`--basetemp`），名字帶時間戳或標籤，所以每跑一次就多一份、"
                  "不會被覆蓋也沒有任何機制會清。"
                  "<br><br>清除方式：<code>rd /s /q \"%TEMP%\\motrix-pytest-*\"</code>"
                  "（或直接刪上面列出的資料夾）。"
                  "<br><br><b>為什麼會這麼大</b>：測試期間「PDF 存檔鏡像」是真的在產生"
                  "PDF，一次完整測試會寫出上萬個單據 PDF（約 3.5 GB）。"),
            button_text="前往系統",
        )
        _async_send(to, f"【MOTRIX】測試暫存佔用 {temp_total_gb} GB（可安全清除）", html)
        return

    worst = min(p["free_gb"] for p in problems)
    if temp_bloat:
        rows.append(("測試暫存（可清除）",
                     f"共 {temp_total_gb} GB，{len(temp_bloat)} 個目錄 — %TEMP%\\motrix-pytest-*"))

    html = _build_html(
        "磁碟空間不足", f"最低剩餘 {worst} GB", "#D97706" if worst > 5 else "#DC2626",
        rows, "", _base_url(),
        intro="正式機的磁碟剩餘空間已低於安全水位。",
        note=(
            "<b>為什麼要現在處理</b>：磁碟滿掉時最先壞的通常是<b>備份</b>"
            "（寫不進去、而且可能只留下一行 log），其次是 PDF 產生與檔案上傳。"
            "等到症狀出現時，往往已經漏掉好幾天的備份。"
            "<br><br><b>可以安全清掉的東西</b>："
            "<br>• <code>%TEMP%\\motrix-pytest-*</code> — 測試暫存，每跑一次 3～4 GB，"
            "名字每次都不同所以不會被覆蓋、也沒有任何機制會清（2026-09-15 實測一次清出 136 GB）"
            "<br>• <code>backend\\db_backups\\pre_update_*</code> — 部署前快照，"
            "系統每天會自動只留最新 5 份（2026-09-14 起），手動刪更舊的也安全"
            "<br>• <code>backend\\rollback_snapshots\\</code> — 只保留最新 5 份，更舊的可刪"
            "<br>• <code>deploy_packages\\</code>（開發機）— 已套用過的舊部署包"
            "<br><br><b>不要刪</b>：<code>uploads\\</code>、各類 PDF 存檔目錄、"
            "<code>backend\\db_backups\\YYYY-MM-DD\\</code> —— 那些是原始憑據與還原來源。"
        ),
        button_text="前往系統",
    )
    _async_send(to, f"【MOTRIX】磁碟空間不足 — 最低剩餘 {worst} GB", html)

# ── 標案雷達（2026-09-21，細線 6 第 5 步）────────────────────────────────────
#
# ⚠️ **三支獨立函式，event key 寫在函式內部，不是一支帶參數的。**
# 既有 44 支 `notify_*` 零支把 key 當參數，而這不只是慣例問題：
# `tests/test_notification_prefs_coverage.py` 是**掃本檔的 `_admin_emails(...)`
# 呼叫端**來比對 `EVENT_GROUPS`——一支函式帶參數的話，守門掃不出那三個 key，
# **漏登記不會紅**。慣例跟守門是綁在一起的。
#
# ⚠️ 三個 key 也刻意分開：「抓不到」與「疑似改版」的**處置相反**
# （掛掉等它好、改版要改解析器）。共用一個 key 的話，使用者關掉吵的那個，
# 就同時關掉了他其實想留的那個。
#
# ⚠️⚠️ **三支都走 `_send_raising` 而不是 `_async_send`。**
# `_async_send` 是**射後不理**（只開一條執行緒），而 `_send` 裡有**五個安靜的 return**
# （功能未啟用／非正式機被擋／收件人空／SMTP 未設定／SMTP 例外），**一個都傳不回來**。
# 後果分兩種，而第二種更嚴重：
#   `notify_tender_found`        → 標案被標記「已通知」而信沒出去 ⇒ **永遠不會再寄**
#   `notify_tender_fetch_failed` → 邊緣被消耗掉而信沒出去 ⇒ **雷達從此瞎著且沒人會知道**
# 🔑 前者是漏掉幾筆標案，**後者是漏掉「雷達壞了」這件事本身**。
# ⚠️ 最可能的觸發是「SMTP 還沒設定」——**使用者第一次啟用的那一天**。
# 📌 它們跑在排程的 Timer 執行緒裡，同步阻塞 15 秒無害。

_TENDER_SOURCE_NOTE = (
    "資料來源：政府電子採購網（依其著作權聲明重製，已註明出處）。"
    "本信由標案雷達每日彙總自動寄出，可在「通知設定」關閉。"
)


def notify_tender_found(tenders: list, watch_names: list = None,
                        announce_quiet_period: bool = False,
                        no_watches: bool = False) -> None:
    """標案雷達命中新標案 → 所有 admin/superadmin。

    ⚠️ **每日一封彙總，不是每筆一封**：命中 40 筆就是信裡 40 列。
    40 封信會讓收件人把整個事件 key 關掉，**而他關掉之後就再也收不到真正重要的那一筆**。

    `announce_quiet_period`：這一封寄完之後就要進入 7 天純記錄期時才給 True。
    ⚠️ **寄一封然後安靜一週，從收件人的角度跟「壞掉了」完全一樣**，
    而這條線的全部價值就是「不會漏掉標案」——讓收件人懷疑它壞了等於毀掉它。
    ⚠️ 但這句話**只能出現在那一封**：每封都寫的話，第 8 天恢復後的信也會這樣說，
    收件人會第二次以為它壞了。判斷在呼叫端（`_quiet_period_starts_after_this_mail`）。
    """
    to = _admin_emails("tender_found")
    if not to:
        return
    rows = []
    for t in (tenders or [])[:50]:
        deadline = t.get("deadline") or "未公告"
        budget = t.get("budget")
        budget_s = "未公告" if budget is None else f"{budget:,}"
        rows.append((f"{t.get('org', '')}｜{t.get('case_no', '')}",
                     f"{t.get('name', '')}<br>截止 {deadline}｜預算 {budget_s}"))
    more = len(tenders or []) - len(rows)
    if no_watches:
        # N17b：一條搜尋條件都沒有時，這封信的意義不是「幫你篩到了什麼」，
        # 而是「雷達開始跑了，但它還不知道你要找什麼」。
        # ⚠️ 講成「找到 N 筆符合條件」是**騙人的**——那是未經篩選的全部。
        intro = (
            f"標案雷達開始運作了，今天抓到 <b>{len(tenders or [])}</b> 筆標案。"
            "<b>⚠️ 你還沒設定任何搜尋條件，所以這是未經篩選的清單。</b>"
            "請到標案雷達頁面新增關鍵字與<b>排除詞</b>——"
            "沒有排除詞的話，這個功能會在第三天就吵到被你關掉。"
        )
    else:
        intro = f"標案雷達今天找到 <b>{len(tenders or [])}</b> 筆符合條件的新標案。"
    if more > 0:
        intro += f"（信中只列前 {len(rows)} 筆，其餘 {more} 筆請進系統查看）"
    if watch_names:
        intro += "　命中條件：" + "、".join(sorted(set(watch_names)))
    note = _TENDER_SOURCE_NOTE
    if announce_quiet_period:
        note = (
            "📌 這是標案雷達的第一封信。<b>接下來 7 天是純記錄模式，不會再寄信</b>——"
            "系統照常每天抓取並記錄，只是不打擾你。"
            "請在這段期間到畫面上確認關鍵字抓得準不準、需不需要加排除詞，"
            "第 8 天起才會恢復每日彙總。<br>" + note
        )
    html = _build_html(
        "標案雷達：新標案", f"{len(tenders or [])} 筆", "#1D4ED8",
        rows, "", _base_url(), note=note, intro=intro,
        button_text="前往標案雷達",
    )
    _send_raising(to, f"【MOTRIX】標案雷達：{len(tenders or [])} 筆新標案", html)


def notify_tender_fetch_failed(error: str, since: str = "") -> None:
    """標案雷達**抓不到對方網站** → 所有 admin/superadmin。

    ⚠️ **只在「進入異常」那一次寄**（邊緣觸發，不是準位觸發）。
    站台掛一週寄七封信的話，第八天真的壞掉時沒有人會看——
    **狼來了的告警等於沒有告警。**

    ⚠️ 跟 `notify_tender_source_changed` 是**不同的事件 key**：
    抓不到只要等它好，改版要改解析器。
    """
    to = _admin_emails("tender_fetch_failed")
    if not to:
        return
    rows = [("失敗原因", error or "（未記錄）")]
    if since:
        rows.append(("上次成功", since))
    intro = (
        "標案雷達連不上政府電子採購網，今天沒有抓到任何標案。"
        "<b>這通常不需要處理</b>——對方站台維護或網路暫時不通，下次排程會自動再試。"
        "這封信只在「從正常變成異常」的那一次寄出，連續失敗不會每天寄。"
    )
    note = (
        "如果連續多天都沒有收到標案彙總信，請到系統的標案雷達頁面看「雷達健康狀態」。"
        + _TENDER_SOURCE_NOTE
    )
    html = _build_html("標案雷達：抓不到來源網站", "連線失敗", "#B91C1C",
                       rows, "", _base_url(), note=note, intro=intro,
                       button_text="前往標案雷達")
    _send_raising(to, "【MOTRIX】⚠️ 標案雷達抓不到政府電子採購網", html)


def notify_tender_source_changed(parsed: int, dropped: int) -> None:
    """標案雷達**疑似對方改版** → 所有 admin/superadmin。

    解析大量失敗（丟掉的比解出來的多）代表對方頁面結構變了，**解析器要改**。
    ⚠️ 這跟「抓不到」是兩件事：那邊等它好就行，**這邊不動手就永遠抓不到東西**，
    而且畫面上看起來一切正常（雷達還在跑、只是每天都 0 筆）。
    """
    to = _admin_emails("tender_source_changed")
    if not to:
        return
    total = parsed + dropped
    rows = [("成功解析", f"{parsed} 筆"), ("解析失敗", f"{dropped} 筆"),
            ("本次總筆數", f"{total} 筆")]
    intro = (
        "標案雷達連得上政府電子採購網，但<b>大部分資料解析不出來</b>，"
        "多半是對方改了頁面結構。"
        "<b>這件事不會自己好</b>——在解析器跟著調整之前，雷達每天都會是 0 筆，"
        "而畫面上看起來一切正常。"
    )
    html = _build_html("標案雷達：疑似對方改版", f"丟棄 {dropped} 筆", "#92400E",
                       rows, "", _base_url(), note=_TENDER_SOURCE_NOTE, intro=intro,
                       button_text="前往標案雷達")
    _send_raising(to, "【MOTRIX】⚠️ 標案雷達疑似對方網站改版", html)
