# -*- coding: utf-8 -*-
"""case v5（2026-10-02，第 31 班 31-C：叫料匯款申請）：新增 `case_material_payments`（匯款申請）與 `case_material_payment_lines`（付款明細）。

每張叫料單可開多張匯款申請（`UNIQUE(quote_no, item_id, seq)`），每張各自走分層簽核→出納；出納可對每張申請分次登錄付款，
每次一列付款明細。叫料單的 `paidStatus／paidAmount／paidDate` 是明細合計的**投影**（寫回只經 `material_payment.sync_order_paid`）。
- 申請的 `snapshot_json` 凍結叫料單內容與收款帳戶（銀行代碼、戶名、帳號；帳戶屬個資 F2：一般備份拿掉）。
- `amount_approved`：申請金額（鎖額度：未作廢申請的合計 ≤ 叫料單小計）。
只新增、冪等（IF NOT EXISTS）；不動任何既有表；不自己 commit。設計：docs/platform/plans/MATERIAL-ORDER-APPROVAL-DESIGN.md §3.4。
"""
_DDL = (
    """CREATE TABLE IF NOT EXISTS case_material_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_code TEXT NOT NULL DEFAULT '',
        quote_no TEXT NOT NULL,
        item_id TEXT NOT NULL,
        seq INTEGER NOT NULL DEFAULT 1,
        supplier_id INTEGER,
        amount_approved REAL NOT NULL DEFAULT 0,
        over_cap_reason TEXT NOT NULL DEFAULT '',
        snapshot_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT '草稿',
        approval_json TEXT NOT NULL DEFAULT '{}',
        submitted_by TEXT NOT NULL DEFAULT '',
        submitted_at TEXT NOT NULL DEFAULT '',
        approved_at TEXT NOT NULL DEFAULT '',
        void_reason TEXT NOT NULL DEFAULT '',
        voided_by TEXT NOT NULL DEFAULT '',
        voided_at TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '',
        UNIQUE (quote_no, item_id, seq))""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_cmp_doc_code ON case_material_payments(doc_code) WHERE doc_code <> ''",
    "CREATE INDEX IF NOT EXISTS idx_cmp_status ON case_material_payments(status)",
    """CREATE TABLE IF NOT EXISTS case_material_payment_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payment_id INTEGER NOT NULL,
        paid_at TEXT NOT NULL DEFAULT '',
        amount REAL NOT NULL DEFAULT 0,
        fee REAL NOT NULL DEFAULT 0,
        remit_review TEXT NOT NULL DEFAULT '',
        remit_review_by TEXT NOT NULL DEFAULT '',
        remit_review_at TEXT NOT NULL DEFAULT '',
        remit_review_note TEXT NOT NULL DEFAULT '',
        pay_method TEXT NOT NULL DEFAULT '',
        pay_account_code TEXT NOT NULL DEFAULT '',
        paid_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '')""",
    "CREATE INDEX IF NOT EXISTS idx_cmpl_payment ON case_material_payment_lines(payment_id)",
)


def up(conn):
    for ddl in _DDL:
        conn.execute(ddl)
