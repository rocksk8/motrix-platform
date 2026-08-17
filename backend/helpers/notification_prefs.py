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
    ]),
    ("工作事項", [
        ("daily_task_assigned",  "工作事項指派通知"),
        ("daily_task_completed", "工作事項完成回報"),
        ("daily_task_overdue",   "工作事項逾期未完成"),
        ("daily_task_edited",    "工作事項內容已編輯"),
        ("range_task_deadline",  "區間工作事項即將到期"),
    ]),
    ("案件與到期提醒", [
        ("case_stage_deadline", "案件執行進度即將到期"),
        ("project_deadline",    "專案預計完工日即將到期"),
        ("warranty_expiry",     "設備保固即將到期"),
        ("dev_case_stale",      "業務開發案件逾期未跟進"),
    ]),
    ("業務開發審核", [
        ("dev_case_delete_request", "業務開發案件刪除申請"),
        ("dev_case_relink_request", "業務開發案件連結異動申請"),
    ]),
    ("系統與報表", [
        ("settlement_finalized", "成本精算完結通知"),
        ("monthly_report",       "每月營運報表"),
        ("module_activity",      "各模組新增／異動通知（建立帳號、案件等一般活動）"),
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
