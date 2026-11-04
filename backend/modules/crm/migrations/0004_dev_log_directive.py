# -*- coding: utf-8 -*-
"""crm v4（2026-11-04，開發記錄「批示」，見 docs/platform/plans/DEV-LOG-DIRECTIVE-PLAN.md）：

1. 新表 `dev_log_directive(id, log_id, case_id, author_id, owner_unit_id, content, parent_id, created_at)`：
   批示與回覆同表（`parent_id` 為空＝批示、非空＝回覆，只一層）；只增不改不刪。`log_id` 不加 FK（開發記錄由 V9 建、可被硬刪，
   由端點自己驗存在並擋刪）。`owner_unit_id INTEGER NOT NULL DEFAULT 1`（單位守門 test_unit_scope_guard_t6，同 dev_case_progress）。
2. 新表 `dev_log_directive_target(id, directive_id, user_id, must_reply, replied_at, owner_unit_id)`：批示的通知／待回覆對象，
   `UNIQUE(directive_id, user_id)`；`must_reply=0` 是只知會，`replied_at` 是該對象首次回覆的時間。

- 沒有既有資料要搬；冪等：表／索引已在就不重建，重跑什麼都不改。
- 這是 L2 遷移，失敗會讓 crm 整模組下線 ⇒ 前置表不在（不該發生：V9 建）回原因字串＝未完成（版號不前進、下次啟動再補）。
- 不自己 commit；SQL 寫在這裡，不 import 任何會演進的程式碼（守門 tests/platform/test_module_migrations.py）。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dev_logs)").fetchall()}
    if not cols:
        return "dev_logs 表不存在（應由 V9 建立），這次不補、下次啟動再試"
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dev_log_directive ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " log_id INTEGER NOT NULL,"
        " case_id INTEGER NOT NULL,"
        " author_id INTEGER NOT NULL,"
        " owner_unit_id INTEGER NOT NULL DEFAULT 1,"
        " content TEXT NOT NULL,"
        " parent_id INTEGER,"
        " created_at TEXT NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dev_log_directive_case ON dev_log_directive(case_id, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dev_log_directive_log ON dev_log_directive(log_id)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dev_log_directive_target ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " directive_id INTEGER NOT NULL,"
        " user_id INTEGER NOT NULL,"
        " must_reply INTEGER NOT NULL DEFAULT 1,"
        " replied_at TEXT,"
        " owner_unit_id INTEGER NOT NULL DEFAULT 1,"
        " UNIQUE(directive_id, user_id))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dev_log_directive_target_user ON dev_log_directive_target(user_id)")
    return None
