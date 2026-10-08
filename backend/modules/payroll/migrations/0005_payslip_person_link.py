# -*- coding: utf-8 -*-
"""payroll v5（2026-10-09，第 48 班勞報單人員 ⇄ 派工連動；設計 docs/platform/plans/PAYSLIP-PERSON-LINK-T48.md §2）。

- `payslips` 加一欄 `contractor_match TEXT NOT NULL DEFAULT ''`：`''`＝已確認（新單、人工確認過）；`'unconfirmed'`＝舊單靠名字推測的對應。
- 回填（冪等、保守）：`contractor_id` 為空 且 `contractor_name` 去空白後恰好對到**一位**外包名冊人員（`contractors.name` 去空白後相同）
  ⇒ 寫 `contractor_id` ＋ `contractor_match='unconfirmed'`。對不到、或同名多位 ⇒ 不動。已有 `contractor_id` 的列完全不碰。
  **不建任何派發連結**（舊單永遠不被靜默連到派發）。重跑不改任何已有值。
- 名冊表 `contractors` 不在（外包模組沒裝）⇒ 只加欄位、回原因字串＝回填未完成（下次啟動再補）。
- 回滾：欄位留著無害（舊程式不認得、INSERT 不帶有預設值）；要還原回填：
  `UPDATE payslips SET contractor_id=NULL, contractor_match='' WHERE contractor_match='unconfirmed'`。
- 不自己 commit、不 import 會演進的程式碼。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(payslips)").fetchall()}
    if not cols:
        return "payslips 表不存在，勞報單人員連動欄位這次不補、下次啟動再試"
    if "contractor_match" not in cols:
        conn.execute("ALTER TABLE payslips ADD COLUMN contractor_match TEXT NOT NULL DEFAULT ''")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='contractors'").fetchone() is None:
        return "contractors 表不存在，舊勞報單的名稱對應這次不回填、下次啟動再試"
    by_name = {}
    for r in conn.execute("SELECT id, name FROM contractors").fetchall():
        key = (r[1] or "").strip()
        if key:
            by_name.setdefault(key, []).append(r[0])
    for r in conn.execute("SELECT id, contractor_name FROM payslips WHERE contractor_id IS NULL AND TRIM(COALESCE(contractor_name,'')) != ''").fetchall():
        ids = by_name.get((r[1] or "").strip(), [])
        if len(ids) == 1:
            conn.execute("UPDATE payslips SET contractor_id=?, contractor_match='unconfirmed' WHERE id=? AND contractor_id IS NULL", (ids[0], r[0]))
    return None
