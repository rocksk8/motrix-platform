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
    is_weak_password,
    _write_initial_credentials,
    _require_user,
    _tok,
)
from .settings import _get_setting, _set_setting
from .audit import _notify, _audit
from .quotations import SQL_DEAL_TAG, SQL_SETTLE_STATUS, quote_hot_fields, save_quotation_json
from .dates import _add_months, _warranty_expiry
from .startup import (
    _EDGE_CANDIDATES,
    _get_edge_path,
    init_default_admin,
    flag_weak_passwords,
    init_unlock_passwords,
    _cleanup_sessions,
)

__all__ = [
    # auth
    "_SUPERADMIN_MODULES", "_hash", "_hash_pw", "_verify_pw",
    "_LEGACY_WEAK_PASSWORDS", "_CREDENTIALS_FILE", "MIN_PASSWORD_LEN",
    "is_weak_password", "_write_initial_credentials", "_require_user", "_tok",
    # settings
    "_get_setting", "_set_setting",
    # audit
    "_notify", "_audit",
    # quotations
    "SQL_DEAL_TAG", "SQL_SETTLE_STATUS", "quote_hot_fields", "save_quotation_json",
    # dates
    "_add_months", "_warranty_expiry",
    # startup
    "_EDGE_CANDIDATES", "_get_edge_path",
    "init_default_admin", "flag_weak_passwords", "init_unlock_passwords", "_cleanup_sessions",
]
