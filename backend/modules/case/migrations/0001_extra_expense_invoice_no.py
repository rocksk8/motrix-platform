# -*- coding: utf-8 -*-
"""case v1（2026-09-27，請款流程）：`case_extra_expenses.invoice_no`——發票號碼（選填，''＝未填）。

- 只新增欄位：回退到舊程式碼時，舊程式碼不讀它、照常運作（「只回程式」的回滾相容）。
- 冪等：欄位已在就不加。
- 表不在（不該發生：V9 v75 建）⇒ **回原因字串＝未完成**（core.migrations 回傳值慣例，CORE 1.58）：版號不前進、記 ERROR、
  服務照常起來，下次啟動再補（2026-09-28 使用者裁示「該補就補」；原本什麼都不做卻照樣記 v1 ⇒ 永遠不會補）。不建表、不猜。
- 不自己 commit（稽核 D PM1）：core.migrations.run_all 逐支包 SAVEPOINT，成功才由它 commit；自己 commit 會讓 savepoint 失效、丟例外時撤不回。
- 凍住的歷史：SQL 寫在這裡，不 import 任何會演進的程式碼（守門 tests/platform/test_module_migrations.py）。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_extra_expenses)").fetchall()}
    if not cols:
        return "case_extra_expenses 表不存在（應由 V9 v75 建立），invoice_no 這次不補、下次啟動再試"
    if "invoice_no" not in cols:
        conn.execute("ALTER TABLE case_extra_expenses ADD COLUMN invoice_no TEXT NOT NULL DEFAULT ''")
    return None
