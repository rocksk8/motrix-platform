"""helpers package — re-exports the full public API for backward compatibility.

Submodules:
  auth        password hashing, session validation, weak-password policy
  settings    system_settings CRUD
  audit       audit log + in-app notifications
  quotations  hot-path field sync for the quotations table
  dates       date arithmetic (_add_months, _warranty_expiry, _workdays_elapsed)
  tiered_approval  shared tiers 依序簽核純邏輯（2026-08-22，四個 router 共用）
  google_calendar  Google 行事曆 push 整合（2026-08-21）
  case_stage_tasks 案件執行進度勾選完成 → 每日工作事項月曆（2026-09-11）
  startup     server startup checks, Edge path resolution
"""

from .auth import (
    _SUPERADMIN_MODULES,
    _hash,
    _hash_pw,
    _verify_pw,
    _LEGACY_WEAK_PASSWORDS,
    _CREDENTIALS_FILE,
    MIN_PASSWORD_LEN,
    DEMO_TOKEN_PREFIX,
    PASSKEY_ENABLED,
    is_weak_password,
    _write_initial_credentials,
    _require_user,
    _tok,
    user_has_module, can_see_financial, require_any_module,
)
from .settings import _get_setting, _set_setting
from .audit import (_notify, _audit, _filter_live_notifications, _purge_notifications,
                    notify_org_chain_notice)
from .quotations import (
    SQL_DEAL_TAG, SQL_SETTLE_STATUS, quote_hot_fields, save_quotation_json, _steps_to_tiers,
    payment_item_amounts, summarize_payment_items, case_extra_expenses,
    quote_won_month_map, norm_at, validate_invoice_no, validate_invoice_amounts, validate_quote_tax,
)
from .case_access import guard_case_access, is_document_approver  # L1（2026-09-26 自 quotations 下沉）
from .dates import _add_months, _warranty_expiry, _workdays_elapsed
from .tiered_approval import (
    active_tiers, current_tier_idx, setting_to_active_tiers,
    first_pending_approver, check_approve_permission, check_reject_permission,
    check_no_tier_self_approval, resolve_department_manager, resolve_division_manager,
    resolve_submitter_org_chain, submitter_manager_tiers, org_chain_notice_usernames,
    plan_self_cascade, cascade_self_tiers,
    resolve_tier_approvers, UnresolvedManagerError,
    approval_flow_setting_key, resolve_active_flow_setting, active_delegators_for,
    APPROVAL_DOC_TYPES, DEFAULT_UNIFIED_DOC_TYPES, APPROVAL_DOC_TYPE_LABELS,
)
from .email_notify import (
    notify_approval_request,
    notify_next_tier,
    notify_approved,
    notify_returned,
    notify_resubmit_requester,
    notify_settlement_finalized,
    notify_case_closing_report,
    notify_daily_task_assigned,
    notify_daily_task_completed,
    notify_daily_task_overdue,
    notify_daily_task_overdue_manager,
    notify_daily_task_edited,
    notify_warranty_expiry,
    notify_monthly_report,
    notify_range_task_deadline,
    notify_module_activity,
    notify_dev_case_delete_request,
    notify_dev_case_relink_request,
    notify_case_stage_deadline,
    notify_case_stage_deadline_manager,
    notify_case_project_overdue,
    notify_cert_expiry, notify_backup_stale, notify_disk_space_low,
    notify_dev_case_stale,
    notify_shipping_submitted,
    notify_shipping_next_tier,
    notify_shipping_approved,
    notify_shipping_returned,
    notify_contractor_voucher_submitted,
    notify_contractor_voucher_next_tier,
    notify_contractor_voucher_approved,
    notify_contractor_voucher_returned,
    notify_invoice_voucher_submitted,
    notify_invoice_voucher_next_tier,
    notify_invoice_voucher_approved,
    notify_invoice_voucher_returned,
    notify_payment_request_submitted,
    notify_payment_request_next_tier,
    notify_payment_request_approved,
    notify_payment_request_returned,
    notify_approval_reminder,
    notify_case_close_blocked,
    notify_case_change_requested,
)
from .google_calendar import (
    push_event_for_invoice_voucher,
    push_event_for_payment_request,
    push_event_for_shipping_note,
    push_event_for_quotation_won,
    push_event_for_dev_case_converted,
    push_event_for_dev_case_stale,
    push_event_for_important_comment,
    push_event_for_case_stage_due,
    push_event_for_case_stage_done,
    push_event_delete_for_case_stage,
    create_test_event as create_calendar_test_event,
)
from .case_stage_tasks import (
    sync_daily_task_for_case_stage, daily_task_notice,
    delete_daily_task_for_case_stage,
)
from .uploads import (
    save_document_files,
    delete_document_file,
)
from .startup import (
    _EDGE_CANDIDATES,
    _get_edge_path,
    EDGE_PDF_SEMAPHORE,
    EDGE_PDF_TIMEOUT_SECONDS,
    run_edge_pdf,
    init_default_admin,
    init_demo_account,
    flag_weak_passwords,
    init_unlock_passwords,
    _cleanup_sessions,
    _sync_module_versions,
)

__all__ = [
    # auth
    "_SUPERADMIN_MODULES", "_hash", "_hash_pw", "_verify_pw", "can_see_financial", "require_any_module",
    "_LEGACY_WEAK_PASSWORDS", "_CREDENTIALS_FILE", "MIN_PASSWORD_LEN", "DEMO_TOKEN_PREFIX",
    "is_weak_password", "_write_initial_credentials", "_require_user", "_tok",
    # settings
    "_get_setting", "_set_setting",
    # audit
    "_notify", "_audit", "_filter_live_notifications", "_purge_notifications",
    # quotations
    "SQL_DEAL_TAG", "SQL_SETTLE_STATUS", "quote_hot_fields", "save_quotation_json",
    "payment_item_amounts", "summarize_payment_items", "case_extra_expenses",
    "quote_won_month_map", "norm_at", "validate_invoice_no", "validate_invoice_amounts", "validate_quote_tax", "guard_case_access", "is_document_approver",
    # dates
    "_add_months", "_warranty_expiry", "_workdays_elapsed",
    "active_tiers", "current_tier_idx", "setting_to_active_tiers",
    "first_pending_approver", "check_approve_permission", "check_reject_permission",
    "check_no_tier_self_approval", "active_delegators_for",
    "resolve_submitter_org_chain", "submitter_manager_tiers", "org_chain_notice_usernames",
    "plan_self_cascade", "cascade_self_tiers", "notify_org_chain_notice",
    "approval_flow_setting_key", "resolve_active_flow_setting",
    "APPROVAL_DOC_TYPES", "DEFAULT_UNIFIED_DOC_TYPES", "APPROVAL_DOC_TYPE_LABELS",
    # email_notify
    "notify_approval_request", "notify_next_tier", "notify_approved",
    "notify_returned", "notify_resubmit_requester", "notify_settlement_finalized",
    "notify_case_closing_report",
    "notify_daily_task_assigned", "notify_daily_task_completed", "notify_daily_task_overdue",
    "notify_daily_task_edited", "notify_warranty_expiry", "notify_monthly_report",
    "notify_range_task_deadline", "notify_dev_case_delete_request", "notify_dev_case_relink_request",
    "notify_case_stage_deadline", "notify_case_stage_deadline_manager",
    "notify_case_project_overdue", "notify_cert_expiry",
    "notify_backup_stale", "notify_disk_space_low",
    "notify_dev_case_stale",
    "notify_shipping_submitted", "notify_shipping_next_tier",
    "notify_shipping_approved", "notify_shipping_returned",
    "notify_contractor_voucher_submitted", "notify_contractor_voucher_next_tier",
    "notify_contractor_voucher_approved", "notify_contractor_voucher_returned",
    "notify_invoice_voucher_submitted", "notify_invoice_voucher_next_tier",
    "notify_invoice_voucher_approved", "notify_invoice_voucher_returned",
    "notify_payment_request_submitted", "notify_payment_request_next_tier",
    "notify_payment_request_approved", "notify_payment_request_returned",
    "notify_approval_reminder",
    "notify_case_close_blocked", "notify_case_change_requested",
    # google_calendar
    "push_event_for_invoice_voucher", "push_event_for_payment_request", "push_event_for_shipping_note",
    "push_event_for_quotation_won", "create_calendar_test_event",
    "push_event_for_case_stage_due", "push_event_for_case_stage_done",
    "push_event_delete_for_case_stage",
    # case_stage_tasks（執行進度 → 每日工作事項月曆）
    "sync_daily_task_for_case_stage", "delete_daily_task_for_case_stage", "daily_task_notice",
    # uploads
    "save_document_files", "delete_document_file",
    # startup
    "_EDGE_CANDIDATES", "_get_edge_path", "EDGE_PDF_SEMAPHORE",
    "EDGE_PDF_TIMEOUT_SECONDS", "run_edge_pdf",
    "init_default_admin", "init_demo_account", "flag_weak_passwords", "init_unlock_passwords",
    "_cleanup_sessions", "_sync_module_versions",
]
