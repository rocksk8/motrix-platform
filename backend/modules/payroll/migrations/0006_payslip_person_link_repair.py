# -*- coding: utf-8 -*-
"""payroll v6（2026-10-09，第 48 班勞報單人員連動——修復用；設計 docs/platform/plans/PAYSLIP-PERSON-LINK-T48.md §2、§8）。

為什麼有這一支：migration 5 在開發過程中換過定義。早期版本（只在開發／演練庫跑過，**沒上過正式機**）把姓名推測直接寫進 `contractor_id`
並加 `contractor_match` 欄位；定案版改成只寫獨立的 `contractor_guess_id`。已經以早期版本跑到 schema 5 的庫不會重跑 migration 5，所以這裡補：
1. 確保 `contractor_guess_id` 欄位存在（定案版 migration 5 已加則略過）。
2. **修復早期版本的汙染**：`contractor_match='unconfirmed'` 的列，其 `contractor_id` 是推測 ⇒ 搬到 `contractor_guess_id`，`contractor_id` 還原成 NULL，
   `contractor_match` 清空。只動 `contractor_match='unconfirmed'` 且 `contractor_id IS NOT NULL` 的列；人工確認過（match=''）的 `contractor_id` 不動。
3. 冪等：全新庫（沒有 `contractor_match` 欄位）只確認欄位存在、什麼都不改；重跑沒有東西可修。
不自己 commit、不 import 會演進的程式碼。回滾：欄位留著無害。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(payslips)").fetchall()}
    if not cols:
        return "payslips 表不存在，勞報單人員連動修復這次不做、下次啟動再試"
    if "contractor_guess_id" not in cols:
        conn.execute("ALTER TABLE payslips ADD COLUMN contractor_guess_id INTEGER")
    if "contractor_match" in cols:
        conn.execute("UPDATE payslips SET contractor_guess_id=contractor_id, contractor_id=NULL, contractor_match=''"
                     " WHERE contractor_match='unconfirmed' AND contractor_id IS NOT NULL")
        conn.execute("UPDATE payslips SET contractor_match='' WHERE contractor_match='unconfirmed'")
    return None
