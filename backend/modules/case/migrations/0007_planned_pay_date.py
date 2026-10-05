# -*- coding: utf-8 -*-
"""case v7（2026-10-05，預定付款日）：`case_extra_expenses` 加 `planned_pay_date`（請款人／出納預計哪天付款；選填）。

- planned_pay_date：YYYY-MM-DD；''＝沒填（舊列全部維持 ''，不補值）。**不是**實際付款日（`paid_date`／`remit_date` 是出納付款時才填）：
  付款後保留當歷史，不清除；提醒信與行事曆「付款待辦」只對「已核准、未付款、未作廢」的列、依這個日期發。
- 只新增欄位、冪等；表不在 ⇒ 回原因字串＝未完成（下次啟動再補）；不自己 commit、不 import 會演進的程式碼。
- 回退（down）：本專案 migration 只進不退；舊程式不認得這一欄、SELECT * 照常、INSERT 不帶它也有預設值 ⇒ 回滾程式碼不需動資料。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_extra_expenses)").fetchall()}
    if not cols:
        return "case_extra_expenses 表不存在，預定付款日欄位這次不補、下次啟動再試"
    if "planned_pay_date" not in cols:
        conn.execute("ALTER TABLE case_extra_expenses ADD COLUMN planned_pay_date TEXT NOT NULL DEFAULT ''")
    return None
