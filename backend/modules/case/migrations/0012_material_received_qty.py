# -*- coding: utf-8 -*-
"""case v12（2026-11-14，一條龍 P2b／D7＝A）：`case_material_approvals` 加 `received_qty`（已到數量，分批累計）。

- received_qty：REAL，可為 NULL。**NULL＝沒有分批記錄（舊資料與舊的「確認到貨」一律是 NULL＝視為全數到貨）**，既有列不用補值；
  `material.shippable` 本來就讀這一欄（沒填＝全數），所以加欄位本身不改任何現有行為。
- 只新增欄位、冪等；表不在 ⇒ 回原因字串＝未完成（下次啟動再補）；不自己 commit、不 import 會演進的程式碼。
- 到貨欄位不屬簽核的實質內容（`SUBSTANTIVE_KEYS` 不含），寫入它不觸發重新簽核。
- 回退：只進不退；舊程式不認得這一欄、整列讀取照常、INSERT 不帶它也是 NULL ⇒ 回滾程式碼不需動資料。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_material_approvals)").fetchall()}
    if not cols:
        return "case_material_approvals 表不存在，已到數量欄位這次不補、下次啟動再試"
    if "received_qty" not in cols:
        conn.execute("ALTER TABLE case_material_approvals ADD COLUMN received_qty REAL")
    return None
