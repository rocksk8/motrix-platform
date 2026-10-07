# -*- coding: utf-8 -*-
"""case v8（2026-10-07，第 45 班預定付款日）：`case_material_payments`（叫料匯款申請）加 `planned_pay_date`。

- planned_pay_date：YYYY-MM-DD；''＝沒填。**每張匯款申請一個日期**（一張申請可分次付款；日期＝「下一次付款預定日」）；不是實際付款日（付款明細在 `case_material_payment_lines`）。
  申請人在草稿／已退回期間可填、可改；核准後只有出納端點（財務角色／superadmin）能改。舊列全部 ''（不回填）。
- 只新增欄位、冪等；表不在 ⇒ 回原因字串＝未完成（下次啟動再補）；不自己 commit、不 import 會演進的程式碼。
- 回退：只進不退；舊程式不認得這一欄、SELECT * 照常、INSERT 不帶它也有預設值 ⇒ 回滾程式碼不需動資料。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_material_payments)").fetchall()}
    if not cols:
        return "case_material_payments 表不存在，材料申請匯款預定付款日欄位這次不補、下次啟動再試"
    if "planned_pay_date" not in cols:
        conn.execute("ALTER TABLE case_material_payments ADD COLUMN planned_pay_date TEXT NOT NULL DEFAULT ''")
    return None
