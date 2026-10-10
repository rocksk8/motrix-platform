# -*- coding: utf-8 -*-
"""recyclebin v1（第 53 班 P0）：刪除暫存區的一張表。

- recycle_bin（T1）：每一張被刪的單據一列。`snapshot_json`（單據列＋子表列的原文，還原用）與 `files_manifest_json`（隔離檔清單）**整欄是 F2**
  （含個資原文；一般每日 JSON 備份排除、完整列只進個資資料夾，見 archive._F2_FIELDS）。清除後保留一列精簡墓碑（snapshot 清空、狀態 purged），供稽核。
- token：uuid hex（隔離目錄名）；group_token：連帶刪除的一組單據共用；purge_after：刪除日 + 30 天（固定，D4）。
- 冪等（IF NOT EXISTS）；不自己 commit（run_all 包 SAVEPOINT）；凍住的歷史：SQL 寫在這裡，不 import 會演進的程式碼。
"""


def up(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS recycle_bin ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " token TEXT NOT NULL UNIQUE,"
        " group_token TEXT NOT NULL DEFAULT '',"
        " entity_type TEXT NOT NULL,"
        " entity_id TEXT NOT NULL,"
        " entity_label TEXT NOT NULL DEFAULT '',"
        " parent_type TEXT NOT NULL DEFAULT '',"
        " parent_id TEXT NOT NULL DEFAULT '',"
        " deleted_by TEXT NOT NULL DEFAULT '',"
        " deleted_by_display TEXT NOT NULL DEFAULT '',"
        " deleted_at TEXT NOT NULL,"
        " purge_after TEXT NOT NULL,"
        " reason TEXT NOT NULL DEFAULT '',"
        " via TEXT NOT NULL DEFAULT 'normal',"
        " impact_json TEXT NOT NULL DEFAULT '[]',"
        " snapshot_json TEXT NOT NULL DEFAULT '{}',"
        " files_manifest_json TEXT NOT NULL DEFAULT '[]',"
        " bytes INTEGER NOT NULL DEFAULT 0,"
        " file_count INTEGER NOT NULL DEFAULT 0,"
        " restore_status TEXT NOT NULL DEFAULT 'in_bin',"
        " restored_by TEXT NOT NULL DEFAULT '',"
        " restored_at TEXT NOT NULL DEFAULT '',"
        " restore_note TEXT NOT NULL DEFAULT '',"
        " purged_at TEXT NOT NULL DEFAULT '',"
        " purged_by TEXT NOT NULL DEFAULT '',"
        " schema_ver INTEGER NOT NULL DEFAULT 1)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recycle_bin_status_due ON recycle_bin(restore_status, purge_after)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recycle_bin_entity ON recycle_bin(entity_type, entity_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recycle_bin_group ON recycle_bin(group_token)")
