"""Per-user email notification opt-out list.

users.notification_muted stores a JSON array of event keys the user has
turned OFF — an *opt-out* list, not opt-in. Empty / NULL (the default for
every existing and newly created user) means "receives everything", so
adding a brand-new event key here later never silently mutes anyone; it
only takes effect once a user explicitly unchecks it in 使用者管理.

Each key below corresponds 1:1 to a notify_* function in email_notify.py
(key = function name with the notify_ prefix stripped).
"""
import json

# (group label, [(event_key, Chinese description), ...]) — drives the
# 使用者管理 → 通知偏好 checkbox UI (frontend/pages/users.html) and is the
# single source of truth for which keys exist.
EVENT_GROUPS = [
    ("簽核流程", [
        ("approval_request",  "報價單待審核通知（當層簽核人）"),
        ("next_tier",         "報價單進入下一層審核"),
        ("approved",          "報價單審核完成"),
        ("returned",          "報價單退回修改"),
        ("resubmit_requester","修改版報價單重新送審確認"),
        ("shipping_submitted","出貨單待審核通知（當層簽核人）"),
        ("shipping_next_tier","出貨單進入下一層審核"),
        ("shipping_approved", "出貨單審核完成"),
        ("shipping_returned", "出貨單退回修改"),
        ("contractor_voucher_submitted","承攬商匯款申請待審核通知（當層簽核人）"),
        ("contractor_voucher_next_tier","承攬商匯款申請進入下一層審核"),
        ("contractor_voucher_approved", "承攬商匯款申請審核完成"),
        ("contractor_voucher_returned", "承攬商匯款申請退回修改"),
        ("invoice_voucher_submitted","開票申請憑據待審核通知（當層簽核人）"),
        ("invoice_voucher_next_tier","開票申請憑據進入下一層審核"),
        ("invoice_voucher_approved", "開票申請憑據審核完成"),
        ("invoice_voucher_returned", "開票申請憑據退回修改"),
        ("payment_request_submitted","請款單待審核通知（當層簽核人）"),
        ("payment_request_next_tier","請款單進入下一層審核"),
        ("payment_request_approved", "請款單審核完成"),
        ("payment_request_returned", "請款單退回修改"),
        ("approval_reminder", "簽核逾期催辦提醒（工作日 1/3/5 天分級升級，含報價單／匯款申請／開票申請憑據／請款單）"),
    ]),
    ("工作事項", [
        ("daily_task_assigned",  "工作事項指派通知"),
        ("daily_task_completed", "工作事項完成回報"),
        ("daily_task_overdue",   "工作事項逾期未完成"),
        ("daily_task_overdue_manager", "工作事項逾期未完成（我是部門主管，通知我部門成員的逾期事項）"),
        ("daily_task_edited",    "工作事項內容已編輯"),
        ("range_task_deadline",  "區間工作事項即將到期"),
    ]),
    ("案件與到期提醒", [
        ("case_stage_deadline", "案件執行進度即將到期"),
        ("case_stage_deadline_manager", "案件執行進度即將到期（我是部門主管，通知我部門成員的案件進度）"),
        # 2026-09-10 補登：f8198e9 新增「案件專案期間超期」通知時，
        # email_notify.py::notify_case_project_overdue() 直接呼叫
        # _admin_emails("case_project_overdue")，但這個 key 沒有一起加進來——
        # is_enabled() 是精確字串比對，key 不在這裡不會報錯，只是使用者
        # 在「使用者管理 → 通知偏好」永遠看不到這個選項，也就永遠關不掉，
        # 症狀跟 2026-08-28 那次 case_change_request(ed) 打錯字一模一樣。
        # 同一輪已把 test_notification_prefs_coverage.py 從「只驗一個 key」
        # 改成掃描 email_notify.py 全部呼叫端，之後再漏就會被測試擋下。
        ("case_project_overdue", "案件專案期間已超期（每日檢查，超期當天寄一次、之後每 7 天一次）"),
        ("warranty_expiry",     "設備保固即將到期"),
        ("dev_case_stale",      "業務開發案件逾期未跟進"),
    ]),
    ("業務開發審核", [
        ("dev_case_delete_request", "業務開發案件刪除申請"),
        ("dev_case_relink_request", "業務開發案件連結異動申請"),
    ]),
    ("系統與報表", [
        ("settlement_finalized", "成本精算完結通知"),
        ("case_closing_report", "案件結案報表 PDF（僅最高管理員）"),
        ("monthly_report",       "每月營運報表"),
        ("module_activity",      "各模組新增／異動通知（建立帳號、案件等一般活動）"),
        ("cert_expiry",          "HTTPS 憑證即將到期（每日檢查，依憑證種類自動調整提前天數）"),
        ("backup_stale",         "備份已停止運作（每日檢查，超過 36 小時沒有成功備份）"),
        ("disk_space_low",       "磁碟空間不足（每日檢查，低於 10% 且低於 20 GB）"),
    ]),
    # 標案雷達（2026-09-21，細線 6 第 5 步）。
    # ⚠️ 三個 key 刻意分開，不共用一個。「抓不到」與「疑似改版」的**處置相反**
    # （掛掉只要等它好、改版要改解析器），共用一個 key 的話使用者關掉其中一個
    # 就同時關掉另一個——而他關掉的多半是吵的那個，留下的是他其實想要的那個。
    ("標案雷達", [
        ("tender_found",         "標案雷達命中新標案（每日一封彙總，不是每筆一封）"),
        ("tender_fetch_failed",  "標案雷達抓不到對方網站（連不上／逾時／被擋；只在「進入異常」時寄一次）"),
        ("tender_source_changed","標案雷達疑似對方改版（解析大量失敗；只在「進入異常」時寄一次）"),
    ]),
    ("已結案案件解鎖", [
        ("case_close_blocked",   "完結案被防呆機制擋下（未達成前置條件）"),
        ("case_change_requested","已結案案件半解鎖期間的變更/上傳待審核（僅最高管理員）"),
    ]),
]

EVENT_KEYS = [key for _, items in EVENT_GROUPS for key, _ in items]


def is_enabled(muted_json, event_key: str) -> bool:
    """True unless event_key is present in the user's muted list.
    muted_json may be None / '' / '[]' / a JSON array string, or already-parsed."""
    if not event_key or not muted_json:
        return True
    try:
        muted = json.loads(muted_json) if isinstance(muted_json, str) else muted_json
    except Exception:
        return True
    return event_key not in (muted or [])
