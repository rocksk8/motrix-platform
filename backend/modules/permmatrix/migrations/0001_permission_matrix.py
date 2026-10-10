# -*- coding: utf-8 -*-
"""permmatrix v1（權限矩陣框架 P0 里程碑 2）：矩陣、個人覆寫、版本、待生效、代理五張表。

- perm_role_caps（T1）：矩陣的**覆寫列**——沒有列＝用種子（由各能力的 legacy 推導，永遠跟著模組宣告走）；有列＝管理者明確勾（granted=1）或明確取消種子給的（granted=0）。
  所以新模組加進來的能力不必回填矩陣。
- perm_user_overrides（T1）：個人允許／禁止（禁止優先）。
- perm_versions（T1）：每次即時生效的矩陣變更後的完整快照（回溯用；回溯＝以差異走一般寫入路徑，高風險授予仍要 24 小時待生效）。
- perm_pending（T1）：高風險授予的 24 小時待生效（使用者裁示）。`state`：pending → active｜cancelled｜superseded；生效由讀取時的 `activate_due` 轉態，不靠排程。
- perm_delegations（T1）：代理。`scope_kind` ＝ caps｜doc_types｜approval_slot（approval_slot 為既有「簽核代理人」語意，之後把 approval_delegates 併進來）。
- 冪等（IF NOT EXISTS）；不自己 commit；SQL 寫在這裡（凍住的歷史），不 import 會演進的程式碼。
"""


def up(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS perm_role_caps ("
        " role TEXT NOT NULL, cap TEXT NOT NULL, granted INTEGER NOT NULL,"
        " set_by TEXT NOT NULL DEFAULT '', set_at TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',"
        " PRIMARY KEY (role, cap))")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS perm_user_overrides ("
        " user_id INTEGER NOT NULL, cap TEXT NOT NULL, effect TEXT NOT NULL CHECK (effect IN ('allow','deny')),"
        " set_by TEXT NOT NULL DEFAULT '', set_at TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',"
        " PRIMARY KEY (user_id, cap))")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS perm_versions ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, created_by TEXT NOT NULL DEFAULT '',"
        " action TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '', snapshot_json TEXT NOT NULL DEFAULT '{}')")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS perm_pending ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',"
        " risk_caps_json TEXT NOT NULL DEFAULT '[]', reason TEXT NOT NULL DEFAULT '',"
        " requested_by TEXT NOT NULL DEFAULT '', requested_at TEXT NOT NULL, effective_at TEXT NOT NULL,"
        " state TEXT NOT NULL DEFAULT 'pending', resolved_by TEXT NOT NULL DEFAULT '', resolved_at TEXT NOT NULL DEFAULT '',"
        " resolve_note TEXT NOT NULL DEFAULT '')")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_pending_due ON perm_pending(state, effective_at)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS perm_delegations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, delegator TEXT NOT NULL, delegate TEXT NOT NULL,"
        " scope_kind TEXT NOT NULL, scope_json TEXT NOT NULL DEFAULT '{}',"
        " valid_from TEXT NOT NULL DEFAULT '', valid_to TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',"
        " state TEXT NOT NULL DEFAULT 'active', requested_by TEXT NOT NULL DEFAULT '', requested_at TEXT NOT NULL DEFAULT '',"
        " effective_at TEXT NOT NULL DEFAULT '', revoked_by TEXT NOT NULL DEFAULT '', revoked_at TEXT NOT NULL DEFAULT '',"
        " revoke_reason TEXT NOT NULL DEFAULT '', legacy_id INTEGER)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_deleg_delegate ON perm_delegations(delegate, state)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_deleg_delegator ON perm_delegations(delegator)")
    return None
