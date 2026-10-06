# -*- coding: utf-8 -*-
"""通知矩陣（信件 × 行事曆）的對照登記（L1；MAIL-CAL 階段 1，設計 docs/platform/plans/MAIL-CAL-MERGE-DESIGN.md）。

[單位] plat:notify_matrix    [層] L1    [穩定度] 實作（階段 1：同頁對照＋兩欄可勾，寫回既有儲存，零遷移）
[公開介面] EVENT_LINKS, MAIL_OFF_LOCKED, mail_off_lock_reason, mail_off_needs_confirm, is_mail_off,
           calendar_link_of_mail, calendar_disabled_reason, calendar_only_codes
[不變式] 本檔只放「對照」與「規則」，不讀寫任何設定、不 import 業務模組（email_notify 反過來 import 本檔，不可循環）；
         矩陣的資料來源仍是兩份登記（信件＝mail_types，行事曆＝google_calendar.EVENT_TYPES），沒登記就沒有列。

使用者裁示（2026-10-05，經 node-06）：每個事件有兩個互相獨立的公司層勾選「信件」「行事曆」；
  - 全部類型都允許「只進行事曆（信件關）」；關簽核類／系統類信件時要有確認警告；
  - 資安／營運攸關的信件鎖住不准關（`MAIL_OFF_LOCKED`）；
  - 個人退訂仍只在 users.html；行事曆只有公司層；
  - 沒有日期或沒有信件範本的格子停用；預設行為不變。
信件「關」存在既有的 `system_settings.mail_recipient_overrides[key]["off"] = True`（與收件模式並存，重新打開時原收件設定還在）；
缺項＝沒關。行事曆格就是 `system_settings.google_calendar.events[code]`。
"""
from . import mail_types as _mt

#: 行事曆代碼 ⇒ 對應的信件。`mail`＝矩陣上承載該行事曆格的主列；`also`＝同一個事件的其他信件（行事曆格顯示「同上」）；
#: `note`＝日期說明（顯示在行事曆格旁）。配對在這裡寫死，不靠名稱猜（設計 §1.5）。
EVENT_LINKS = {
    "invoice_voucher": {"mail": "invoice_voucher_approved", "also": (), "note": "核准當天"},
    "payment_request": {"mail": "payment_request_approved", "also": (), "note": "核准當天"},
    "shipping_note":   {"mail": "shipping_approved", "also": (), "note": "出貨日期"},
    "stage_due":       {"mail": "case_stage_deadline", "also": ("case_stage_deadline_manager",), "note": "階段到期日"},
    "dev_case_stale":  {"mail": "dev_case_stale", "also": (), "note": "停滯起算日"},
    "expense_payout":  {"mail": "expense_form_paid", "also": (), "note": "付款日（行事曆含所有請款類型，信件只有費用單據）"},
}

#: 資安／營運攸關的信件：信件格鎖住、不可關閉 ⇒ {key: 原因}。後端驗證（PUT 400）、寄信端也忽略這類的 off（雙保險）。
MAIL_OFF_LOCKED = {
    "backup_error": "備份失敗沒有通知時，發生故障可能遺失資料",
    "backup_stale": "備份停擺沒有通知時，發生故障可能遺失資料",
    "disk_space_low": "磁碟空間不足沒有通知時，備份與上傳會失敗",
    "cert_expiry": "憑證到期沒有通知時，使用者開啟系統會出現瀏覽器安全性警告",
    "company_setup_alert": "本公司資料未確認沒有通知時，對外文件可能使用未經確認的公司資料",
    "system_test_mail": "測試信用來確認寄信設定，關閉後無法驗證",
}

#: 關閉這些分類的信件要先經確認警告（流程會卡住／看不到告警）。
MAIL_OFF_CONFIRM_CATEGORIES = ("approval", "system")

#: 沒有行事曆格的原因：特例（有日期、但政策上或尚未提供）。其餘依分類給預設原因。
_NOT_YET = "尚未提供這類行事曆事件"
_EVENT_DAY = "事件日型（只有核准或完成當天），價值低，不放公司行事曆"
CALENDAR_DISABLED_SPECIAL = {
    "warranty_expiry": _NOT_YET, "range_task_deadline": _NOT_YET, "case_project_overdue": _NOT_YET,
    "tender_found": "標案截止日是逐筆事件，尚未提供行事曆事件",
    "daily_task_assigned": "個人事項，不放公司行事曆", "daily_task_edited": "個人事項，不放公司行事曆",
    "daily_task_overdue": "日期已過的逾期提醒，不建事件", "daily_task_overdue_manager": "日期已過的逾期提醒，不建事件",
    "cert_expiry": "受眾是技術人員，不放公司行事曆",
    **{k: _EVENT_DAY for k in (
        "approved", "bonus_correction_approved", "contractor_voucher_approved", "custom_def_approved", "custom_record_approved",
        "ledger_action_approved", "material_change_approved", "material_order_approved", "material_payment_approved",
        "voucher_approved", "dispatch_approved", "dispatch_completion_approved", "expense_form_approved",
        "case_closing_report", "settlement_finalized")},
}
_DEFAULT_REASON = {"approval": "簽核流程通知，沒有日期", "system": "系統告警，沒有日期", "business": "沒有可當日曆日期的欄位"}


def mail_off_lock_reason(key: str) -> str:
    """鎖住的原因；空字串＝可以關。"""
    return MAIL_OFF_LOCKED.get(key, "")


def mail_off_needs_confirm(key: str) -> bool:
    t = _mt.get(key)
    return bool(t and t.category in MAIL_OFF_CONFIRM_CATEGORIES)


def is_mail_off(key, overrides: dict) -> bool:
    """信件類型目前是不是被公司關閉。鎖住的類型一律回 False（即使設定檔裡有 off）；未登記的 key 回 False（fail closed 另有規則）。"""
    if not key or key in MAIL_OFF_LOCKED or _mt.get(key) is None:
        return False
    o = (overrides or {}).get(key)
    return bool(isinstance(o, dict) and o.get("off") is True)


def _mail_to_cal() -> dict:
    out = {}
    for code, link in EVENT_LINKS.items():
        out[link["mail"]] = {"code": code, "primary": True, "note": link["note"]}
        for k in link["also"]:
            out[k] = {"code": code, "primary": False, "note": link["note"]}
    return out


def calendar_link_of_mail(key: str):
    """⇒ {"code", "primary", "note"} 或 None（沒有對應的行事曆事件）。"""
    return _mail_to_cal().get(key)


def calendar_disabled_reason(key: str) -> str:
    """這個信件類型的行事曆格為什麼停用（有對應行事曆事件的回空字串）。永遠有文字——新登記的類型也有預設原因（守門：test_notify_matrix）。"""
    if calendar_link_of_mail(key):
        return ""
    t = _mt.get(key)
    return CALENDAR_DISABLED_SPECIAL.get(key) or _DEFAULT_REASON[t.category if t else "business"]


def calendar_only_codes(all_codes) -> list:
    """沒有對應信件的行事曆代碼（信件格停用：沒有信件範本），保持 `all_codes` 的順序。"""
    return [c for c in all_codes if c not in EVENT_LINKS]
