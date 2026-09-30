# -*- coding: utf-8 -*-
"""crm v1（2026-09-30，使用者：業務開發新增案件要有「介紹人」）：`dev_cases.referrer`。

- 只新增一欄（TEXT NOT NULL DEFAULT ''）：凍結的 V9 schema 不動；回退到舊程式碼時舊程式碼不讀它、照常運作。
- 冪等：欄位已在就不加。表不在（不該發生：V9 建）⇒ 回原因字串＝未完成（版號不前進、下次啟動再補）。
- 不自己 commit；SQL 寫在這裡，不 import 任何會演進的程式碼（守門 tests/platform/test_module_migrations.py）。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dev_cases)").fetchall()}
    if not cols:
        return "dev_cases 表不存在（應由 V9 建立），這次不補、下次啟動再試"
    if "referrer" not in cols:
        conn.execute("ALTER TABLE dev_cases ADD COLUMN referrer TEXT NOT NULL DEFAULT ''")
    return None
