# -*- coding: utf-8 -*-
"""case v1（2026-09-27，請款流程）：`case_extra_expenses.invoice_no`——發票號碼（選填，''＝未填）。

- 只新增欄位：回退到舊程式碼時，舊程式碼不讀它、照常運作（「只回程式」的回滾相容）。
- 冪等：欄位已在就不加。表不在（不該發生：V9 v75 建）⇒ 什麼都不做，不建表、不猜。
- 凍住的歷史：SQL 寫在這裡，不 import 任何會演進的程式碼（守門 tests/platform/test_module_migrations.py）。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_extra_expenses)").fetchall()}
    if cols and "invoice_no" not in cols:
        conn.execute("ALTER TABLE case_extra_expenses ADD COLUMN invoice_no TEXT NOT NULL DEFAULT ''")
    conn.commit()
