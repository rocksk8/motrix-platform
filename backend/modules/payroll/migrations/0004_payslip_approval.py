# -*- coding: utf-8 -*-
"""payroll v4（2026-10-07，第 46 班勞報單送審＋出納整合＋派發連結；設計 docs/platform/plans/PAYSLIP-APPROVAL-T45.md §8）。

- `payslips` 加四欄（全部有預設值；舊列＝沒有簽核紀錄，不補假紀錄）：
  `approval_json`（簽核鏈與歷史；''＝舊單／草稿）、`planned_pay_date`（預定付款日 YYYY-MM-DD，''＝沒填；與 paydate 設計共用欄名）、
  `approved_at`／`approved_by`（最後一層核准的時間與人；舊列 ''）。
- 新表 `payslip_dispatch_links`（勞報單 ↔ 承攬派發的連結；一派發對多勞報單、一勞報單對多派發；唯一鍵 `(slip_no, dispatch_id)`）。
  不放 `payslips.data_json`／`contractor_dispatches`：跨模組以提供者互取，不互讀表。
- 只新增欄位／表、冪等；`payslips` 不在 ⇒ 回原因字串＝未完成（下次啟動再補）；不自己 commit、不 import 會演進的程式碼。
- 回退：只進不退；舊程式不認得新欄位／新表、`SELECT *` 照常、INSERT 不帶新欄有預設值。⚠ 回滾缺口：舊碼不認得 `待審核／已核准` 兩個狀態
  （`_LOCKED_STATUSES` 不含它們 ⇒ 舊碼下可被編輯／刪除）；回滾前先處理這兩種狀態的勞報單（使用者 Q11 裁示：接受，回滾 SOP 加一句）。
"""

_COLS = (
    ("approval_json", "TEXT NOT NULL DEFAULT ''"),
    ("planned_pay_date", "TEXT NOT NULL DEFAULT ''"),
    ("approved_at", "TEXT NOT NULL DEFAULT ''"),
    ("approved_by", "TEXT NOT NULL DEFAULT ''"),
)

_LINKS = (
    """CREATE TABLE IF NOT EXISTS payslip_dispatch_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slip_no TEXT NOT NULL,
        dispatch_id INTEGER NOT NULL,
        voucher_no TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '',
        UNIQUE (slip_no, dispatch_id))""",
    "CREATE INDEX IF NOT EXISTS idx_pdl_dispatch ON payslip_dispatch_links(dispatch_id)",
    "CREATE INDEX IF NOT EXISTS idx_pdl_slip ON payslip_dispatch_links(slip_no)",
)


def up(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(payslips)").fetchall()}
    if not cols:
        return "payslips 表不存在，勞報單簽核欄位這次不補、下次啟動再試"
    for name, ddl in _COLS:
        if name not in cols:
            conn.execute("ALTER TABLE payslips ADD COLUMN %s %s" % (name, ddl))
    for stmt in _LINKS:
        conn.execute(stmt)
    return None
