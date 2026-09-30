# -*- coding: utf-8 -*-
"""accounting v2（2026-09-30，W4 總帳 B1）：報表列定義表 gl_fs_lines、科目的現金流量分類 cashflow_class。

- gl_fs_lines：財務報表的列（資產負債表／綜合損益表／權益變動表／現金流量表），會計師可調整名稱、排序、停用；列代碼固定。
  種子資料由 `ledger/fs_lines.py::ensure_fs_lines` 於使用時補（不寫在 migration：migration 不 import 會演進的程式碼）。
- gl_account_meta.cashflow_class：科目的現金流量分類（cash／operating／investing／financing；空字串＝尚未分類，守門會紅）。
只新增（加表、加欄位），冪等；回退程式碼時舊程式不讀新東西。不自己 commit。
"""


def up(conn):
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "gl_account_meta" not in have:
        return "gl_account_meta 表不存在（應由 accounting v1 建立），這次不補、下次啟動再試"
    conn.execute(
        """CREATE TABLE IF NOT EXISTS gl_fs_lines (
            code TEXT PRIMARY KEY, statement TEXT NOT NULL, label TEXT NOT NULL,
            sort INTEGER NOT NULL DEFAULT 0, side TEXT NOT NULL DEFAULT 'D',
            kind TEXT NOT NULL DEFAULT 'line', is_active INTEGER NOT NULL DEFAULT 1,
            note TEXT NOT NULL DEFAULT '')""")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(gl_account_meta)")}
    if "cashflow_class" not in cols:
        conn.execute("ALTER TABLE gl_account_meta ADD COLUMN cashflow_class TEXT NOT NULL DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_gl_fs_lines_stmt ON gl_fs_lines(statement, sort)")
    return None
