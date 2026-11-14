# -*- coding: utf-8 -*-
"""crm v5（2026-11-14，T86 業務開發 UX #17；PM 裁示 B：固定兩欄）：
`dev_cases.expected_amount`（預估金額，整數、可為 NULL）／`expected_close_date`（預計成交日，ISO 日期文字、可為 NULL）。

- 只新增兩欄：凍結的 V9 schema 不動；回退到舊程式碼時舊程式碼不讀它，照常運作。既有列兩欄都是 NULL＝「沒填」（不是 0）。
- 冪等：欄位已在就不加。表不在（不該發生：V9 建）⇒ 回原因字串＝未完成（版號不前進、下次啟動再補）。
- 不自己 commit；SQL 寫在這裡，不 import 任何會演進的程式碼（守門 tests/platform/test_module_migrations.py）。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dev_cases)").fetchall()}
    if not cols:
        return "dev_cases 表不存在（應由 V9 建立），這次不補、下次啟動再試"
    if "expected_amount" not in cols:
        conn.execute("ALTER TABLE dev_cases ADD COLUMN expected_amount INTEGER")
    if "expected_close_date" not in cols:
        conn.execute("ALTER TABLE dev_cases ADD COLUMN expected_close_date TEXT")
    return None
