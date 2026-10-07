# -*- coding: utf-8 -*-
"""subcontract v6（2026-10-07，第 45 班預定付款日）：`contractor_payment_vouchers` 加 `planned_pay_date`（出納預計哪天匯款）。

- planned_pay_date：YYYY-MM-DD；''＝沒填。可編輯（出納端點、建立匯款單時選填）；**不是**派發上的「應付款日期」（`snapshot_json.payableDate`，建立當下凍結、語意是合約應付日），兩者並存、不自動複製（使用者 2026-10-07 Q1）。
  付款後保留當歷史；舊列全部 ''（不回填）。
- ⚠ 0005 曾整表重建（`remit_kinds_voucher_rebuild`）：新欄加在 0006（0005 之後）即可；**之後任何重建這張表的遷移都必須帶這一欄**（`test_module_migrations` 有欄位存在斷言）。
- 只新增欄位、冪等；表不在 ⇒ 回原因字串＝未完成（下次啟動再補）；不自己 commit、不 import 會演進的程式碼。
- 回退：只進不退；舊程式不認得這一欄、SELECT * 照常、INSERT 不帶它也有預設值 ⇒ 回滾程式碼不需動資料。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(contractor_payment_vouchers)").fetchall()}
    if not cols:
        return "contractor_payment_vouchers 表不存在，承攬商匯款預定付款日欄位這次不補、下次啟動再試"
    if "planned_pay_date" not in cols:
        conn.execute("ALTER TABLE contractor_payment_vouchers ADD COLUMN planned_pay_date TEXT NOT NULL DEFAULT ''")
    return None
