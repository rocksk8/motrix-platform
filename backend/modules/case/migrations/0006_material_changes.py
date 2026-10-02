# -*- coding: utf-8 -*-
"""case v6（2026-10-03，第 33 班 33-M2a：材料申請變更申請）：新增覆核表 `case_material_changes`。

已核准的材料申請要改內容（追加採購單行、改數量）不回草稿，改開一張「變更申請」（MC-YYYYMMDD-NNNN）走簽核；
原已核准版本在變更核准前**完全不動**（成本、到貨、可出貨量照舊有效），核准後才原子切換（設計 docs/platform/plans/MATERIAL-CHANGE-REQUEST-DESIGN.md）。
- status：草稿／待審核／簽核中／已核准／已退回／已撤回；base_version＝提案時原審核列的 version（套用時必須仍相同，防競態）。
- proposal_json＝變更後內容、base_json＝提案當下原內容、diff_json＝差異（送審時由伺服器重算）。
- 部分唯一索引：一筆材料申請同時最多一個進行中的變更（草稿／待審核／簽核中）。
只新增、冪等（IF NOT EXISTS）、不回填、不動任何既有表；不自己 commit。沒有變更列＝沒有變更（現狀）。
"""
_DDL = (
    """CREATE TABLE IF NOT EXISTS case_material_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quote_no TEXT NOT NULL,
        item_id TEXT NOT NULL,
        doc_code TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT '草稿',
        base_version INTEGER NOT NULL DEFAULT 1,
        proposal_json TEXT NOT NULL DEFAULT '{}',
        base_json TEXT NOT NULL DEFAULT '{}',
        diff_json TEXT NOT NULL DEFAULT '[]',
        approval_json TEXT NOT NULL DEFAULT '{}',
        reason TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '',
        submitted_by TEXT NOT NULL DEFAULT '',
        submitted_at TEXT NOT NULL DEFAULT '',
        approved_at TEXT NOT NULL DEFAULT '',
        applied_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '')""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_cmc_doc_code ON case_material_changes(doc_code)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_cmc_one_live ON case_material_changes(quote_no, item_id) WHERE status IN ('草稿','待審核','簽核中')",
    "CREATE INDEX IF NOT EXISTS idx_cmc_item ON case_material_changes(quote_no, item_id)",
    "CREATE INDEX IF NOT EXISTS idx_cmc_status ON case_material_changes(status)",
)


def up(conn):
    for ddl in _DDL:
        conn.execute(ddl)
