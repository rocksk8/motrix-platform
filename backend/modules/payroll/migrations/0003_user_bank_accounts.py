# -*- coding: utf-8 -*-
"""payroll v3（2026-10-01，A2 收款人：員工收款帳號）：新增 `user_bank_accounts`。

- 每位使用者**一個目前有效的帳戶**（部分唯一索引 `active=1`）；改帳號＝舊列標 `active=0`（留歷史、誰何時改的），新列 `active=1`。
- 不放在 `users`（L0 認證表）：銀行資料敏感、需要歷史與稽核；放在本模組表，之後勞報／獎金／請款都可讀它（經 `payee.bank_profile` 提供者）。
- `account_number` 存全數字（去空白、連字號）；對外回傳一律經 `modules/payroll/bank_account.py` 的遮蔽函式。
- 只新增表：回退到舊程式碼時舊程式碼不讀它、照常運作（「只回程式」的回滾相容）。冪等：`IF NOT EXISTS`。
- 不自己 commit；SQL 寫在這裡，不 import 任何會演進的程式碼（守門 tests/platform/test_module_migrations.py）。
"""


def up(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS user_bank_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        username TEXT NOT NULL,
        bank_code TEXT NOT NULL DEFAULT '',
        bank_name TEXT NOT NULL DEFAULT '',
        bank_branch TEXT NOT NULL DEFAULT '',
        account_name TEXT NOT NULL DEFAULT '',
        account_number TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1,
        verified_by TEXT NOT NULL DEFAULT '',
        verified_at TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '',
        updated_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '',
        replaced_at TEXT NOT NULL DEFAULT '')""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_uba_one_active ON user_bank_accounts(user_id) WHERE active = 1")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uba_username ON user_bank_accounts(username, active)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uba_user ON user_bank_accounts(user_id, id)")
    return None
