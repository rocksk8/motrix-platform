# -*- coding: utf-8 -*-
"""subcontract v2（2026-09-30，N1）：`dispatch_file_delete_requests`——承攬商報價單附件的「申請刪除」（要審核）。

一列＝一次刪除申請：`status`＝待審核／已核可／已退回；`approval_json`＝簽核鏈（申請人、tiers、currentTier，
形狀同各單據的 approval，簽核佇列與 `helpers.approval_queue.tier_fields` 直接吃）。核可前檔案本身（contractor_dispatches.files_json）
不動；核可走完全部簽核層才刪檔。
- 只新增表、冪等；不自己 commit、不 import 會演進的程式碼；SQL 寫在這裡。
"""


def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dispatch_file_delete_requests (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            dispatch_id   INTEGER NOT NULL,
            file_id       TEXT    NOT NULL,
            quote_no      TEXT    NOT NULL DEFAULT '',
            filename      TEXT    NOT NULL DEFAULT '',
            reason        TEXT    NOT NULL DEFAULT '',
            status        TEXT    NOT NULL DEFAULT '待審核',
            approval_json TEXT    NOT NULL DEFAULT '{}',
            requested_by  TEXT    NOT NULL DEFAULT '',
            requested_at  TEXT    NOT NULL DEFAULT '',
            decided_by    TEXT    NOT NULL DEFAULT '',
            decided_at    TEXT    NOT NULL DEFAULT '',
            decision_note TEXT    NOT NULL DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dfdr_dispatch ON dispatch_file_delete_requests(dispatch_id, file_id, status)")
    return None
