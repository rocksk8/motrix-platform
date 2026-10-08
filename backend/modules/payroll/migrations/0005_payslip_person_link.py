# -*- coding: utf-8 -*-
"""payroll v5（2026-10-09，第 48 班勞報單人員 ⇄ 派工連動；設計 docs/platform/plans/PAYSLIP-PERSON-LINK-T48.md §2）。

- `payslips` 加一欄 `contractor_guess_id INTEGER`（NULL＝沒有推測）：舊單「靠姓名推測」的外包名冊對應，**與權威的 `contractor_id` 分開存**。
  🔴 金流／總帳（`gl_events` 的對象鍵 `C<id>`、`remit_link.candidates`、匯款單受款人檢查）只看 `contractor_id`；推測值永遠不會流進去，
  直到最高管理者在勞報單頁「確認」才升格成 `contractor_id`（同一個條件式 UPDATE；已簽回／已付款／已作廢的單不給確認，因為會改變已入帳分錄的對象鍵）。
- 回填（冪等、保守）：`contractor_id` 為空、`contractor_guess_id` 為空、狀態不是「已作廢」，且 `contractor_name` 去空白後恰好對到**一位**外包名冊人員
  ⇒ 只寫 `contractor_guess_id`。對不到、同名多位 ⇒ 不動。**不碰 `contractor_id`、不建任何派發連結。** 重跑不改任何已有值。
- 名冊表 `contractors` 不在 ⇒ 只加欄位、回 None（沒有可回填的東西，不讓模組下線）。
- 回滾（備份先做）：欄位留著無害（舊程式不認得、INSERT 不帶 ⇒ NULL）；要還原回填：`UPDATE payslips SET contractor_guess_id=NULL`
  （確認過的 `contractor_id` 是人工決定，不在此還原）。
- 不自己 commit、不 import 會演進的程式碼。
"""


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(payslips)").fetchall()}
    if not cols:
        return "payslips 表不存在，勞報單人員連動欄位這次不補、下次啟動再試"
    if "contractor_guess_id" not in cols:
        conn.execute("ALTER TABLE payslips ADD COLUMN contractor_guess_id INTEGER")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='contractors'").fetchone() is None:
        return None
    by_name = {}
    for r in conn.execute("SELECT id, name FROM contractors").fetchall():
        key = (r[1] or "").strip()
        if key:
            by_name.setdefault(key, []).append(r[0])
    for r in conn.execute("SELECT id, contractor_name FROM payslips WHERE contractor_id IS NULL AND contractor_guess_id IS NULL AND status != '已作廢'"
                          " AND TRIM(COALESCE(contractor_name,'')) != ''").fetchall():
        ids = by_name.get((r[1] or "").strip(), [])
        if len(ids) == 1:
            conn.execute("UPDATE payslips SET contractor_guess_id=? WHERE id=? AND contractor_id IS NULL AND contractor_guess_id IS NULL", (ids[0], r[0]))
    return None
