# -*- coding: utf-8 -*-
"""accounting v3（2026-10-01）：底層預留——分錄維度與費用類別（之後新增維度／費用類別＝設定資料，不再開 migration）。

- `voucher_lines.dim_json`：分錄維度 `{維度代碼: 值}`（例：部門、專案）；預設 `{}`，舊資料與舊程式不受影響。
- `gl_dimensions`：維度設定（代碼、顯示名稱、是否啟用）。
- `expense_categories`：費用類別（代碼發布後不可改，改名只改 name）；單據的費用類別只存代碼，科目由 `gl_category_map` 對應。
只新增、冪等；回退程式碼時舊程式不讀新東西。
"""
_TABLES = (
    """CREATE TABLE IF NOT EXISTS gl_dimensions (
        code TEXT PRIMARY KEY, label TEXT NOT NULL DEFAULT '', is_active INTEGER NOT NULL DEFAULT 1, sort INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS expense_categories (
        code TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', default_tax TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1, sort INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '')""",
)


def up(conn):
    for ddl in _TABLES:
        conn.execute(ddl)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(voucher_lines)")}
    if cols and "dim_json" not in cols:
        conn.execute("ALTER TABLE voucher_lines ADD COLUMN dim_json TEXT NOT NULL DEFAULT '{}'")
