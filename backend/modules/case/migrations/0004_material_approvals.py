# -*- coding: utf-8 -*-
"""case v4（2026-10-02，第 31 班 31-C：叫料審核）：新增疊加審核表 `case_material_approvals`。

叫料（`quotations.data_json` → `caseRecord.materialOrders[]`）沒有資料表；審核狀態不塞進每一列（整包覆蓋會蓋掉、
佇列要掃全部案件的 JSON、沒有單號可引用），改用一張薄表以 (quote_no, item_id) 疊加：
- **沒有疊加列＝舊單**（不回填、不標記遷移；舊單行為與今天相同，見 `modules/case/material_approval.py`）。
- status：草稿／待審核／簽核中／已核准／已退回／已取消；approval_json＝既有分層簽核的 tiers 與歷程格式。
- content_hash：核准當時的實質欄位雜湊（品名、數量、單位、單價、小計、supplierId）；之後實質欄位不符 ⇒ 回草稿重送審。
- received_on／received_by／received_at：到貨確認（不簽核，只記日期與確認人）。
只新增、冪等（IF NOT EXISTS）；不動任何既有表；不自己 commit。
設計：docs/platform/plans/MATERIAL-ORDER-APPROVAL-DESIGN.md §3.1。
"""
_DDL = (
    """CREATE TABLE IF NOT EXISTS case_material_approvals (
        quote_no TEXT NOT NULL,
        item_id TEXT NOT NULL,
        doc_code TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT '草稿',
        approval_json TEXT NOT NULL DEFAULT '{}',
        submitted_by TEXT NOT NULL DEFAULT '',
        submitted_at TEXT NOT NULL DEFAULT '',
        approved_at TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL DEFAULT '',
        received_on TEXT NOT NULL DEFAULT '',
        received_by TEXT NOT NULL DEFAULT '',
        received_at TEXT NOT NULL DEFAULT '',
        cancel_reason TEXT NOT NULL DEFAULT '',
        cancelled_by TEXT NOT NULL DEFAULT '',
        cancelled_at TEXT NOT NULL DEFAULT '',
        version INTEGER NOT NULL DEFAULT 1,
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (quote_no, item_id))""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_cma_doc_code ON case_material_approvals(doc_code) WHERE doc_code <> ''",
    "CREATE INDEX IF NOT EXISTS idx_cma_status ON case_material_approvals(status)",
)


def up(conn):
    for ddl in _DDL:
        conn.execute(ddl)
