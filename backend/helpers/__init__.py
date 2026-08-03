"""helpers package — re-exports the full public API for backward compatibility.

Submodules:
  auth        password hashing, session validation, weak-password policy
  settings    system_settings CRUD
  audit       audit log + in-app notifications
  quotations  hot-path field sync for the quotations table
  dates       date arithmetic (_add_months, _warranty_expiry)
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
    is_weak_password,
    _write_initial_credentials,
    _require_user,
    _tok,
)
from .settings import _get_setting, _set_setting
from .audit import _notify, _audit, _filter_live_notifications, _purge_notifications
from .quotations import SQL_DEAL_TAG, SQL_SETTLE_STATUS, quote_hot_fields, save_quotation_json, _steps_to_tiers
from .dates import _add_months, _warranty_expiry
from .email_notify import (
    notify_approval_request,
    notify_next_tier,
    notify_approved,
    notify_returned,
    notify_resubmit_requester,
    notify_settlement_finalized,
    notify_daily_task_assigned,
    notify_daily_task_completed,
    notify_daily_task_overdue,
    notify_daily_task_edited,
    notify_warranty_expiry,
    notify_monthly_report,
    notify_range_task_deadline,
    notify_module_activity,
    notify_dev_case_delete_request,
    notify_case_stage_deadline,
    notify_project_deadline,
    notify_dev_case_stale,
    notify_shipping_submitted,
    notify_shipping_next_tier,
    notify_shipping_approved,
    notify_shipping_returned,
)
from .startup import (
    _EDGE_CANDIDATES,
    _get_edge_path,
    init_default_admin,
    init_demo_account,
    flag_weak_passwords,
    init_unlock_passwords,
    _cleanup_sessions,
    _sync_module_versions,
)

__all__ = [
    # auth
    "_SUPERADMIN_MODULES", "_hash", "_hash_pw", "_verify_pw",
    "_LEGACY_WEAK_PASSWORDS", "_CREDENTIALS_FILE", "MIN_PASSWORD_LEN", "DEMO_TOKEN_PREFIX",
    "is_weak_password", "_write_initial_credentials", "_require_user", "_tok",
    # settings
    "_get_setting", "_set_setting",
    # audit
    "_notify", "_audit", "_filter_live_notifications", "_purge_notifications",
    # quotations
    "SQL_DEAL_TAG", "SQL_SETTLE_STATUS", "quote_hot_fields", "save_quotation_json",
    # dates
    "_add_months", "_warranty_expiry",
    # email_notify
    "notify_approval_request", "notify_next_tier", "notify_approved",
    "notify_returned", "notify_resubmit_requester", "notify_settlement_finalized",
    "notify_daily_task_assigned", "notify_daily_task_completed", "notify_daily_task_overdue",
    "notify_daily_task_edited", "notify_warranty_expiry", "notify_monthly_report",
    "notify_range_task_deadline", "notify_dev_case_delete_request",
    "notify_case_stage_deadline", "notify_project_deadline", "notify_dev_case_stale",
    "notify_shipping_submitted", "notify_shipping_next_tier",
    "notify_shipping_approved", "notify_shipping_returned",
    # startup
    "_EDGE_CANDIDATES", "_get_edge_path",
    "init_default_admin", "init_demo_account", "flag_weak_passwords", "init_unlock_passwords",
    "_cleanup_sessions", "_sync_module_versions",
]
