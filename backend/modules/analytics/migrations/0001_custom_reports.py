# -*- coding: utf-8 -*-
"""analytics v1（2026-11-14，T87 B2 自訂報表「我的報表」）：兩張新表。

1. `custom_reports(id, username, name, source_id, definition_json, created_at, updated_at, last_exported_at, owner_unit_id)`：
   使用者存的報表**設定**（欄位、條件、分組…的 JSON，≤ 8 KB 由應用層把關），不存結果、不存任何授權。
   鍵＝擁有者登入帳號；`UNIQUE(username, name)`（同一人不可重名）。`owner_unit_id INTEGER NOT NULL DEFAULT 1`（單位守門）。
2. `custom_report_shares(id, report_id, shared_with, created_at, owner_unit_id)`：擁有者把報表分享給指定同事（設定 `custom_reports.sharing` 開啟時才有作用；
   關閉時資料保留、不顯示）。`UNIQUE(report_id, shared_with)`。被分享者只能檢視與複製，執行時用自己的權限。

- 只新增、不改任何既有表；冪等：表／索引已在就不重建，重跑什麼都不改；沒有前置表要求。
- 回退到舊程式碼：舊程式不讀這兩張表，照常運作（旗標 `custom_reports.enabled` 預設關）。

## 回滾說明（人工，僅在確定要拆除功能時）
    DROP TABLE IF EXISTS custom_report_shares;
    DROP TABLE IF EXISTS custom_reports;
  並把 `module_schema_versions` 裡 analytics 的版本由 1 改回 0。⚠ 會丟掉使用者存的所有報表設定：先備份資料庫。
  不拆表也可以：把設定 `custom_reports.enabled` 關閉即可（資料保留，重新開啟後恢復）。

- 不自己 commit；守門 tests/platform/test_module_migrations.py。
"""


def up(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS custom_reports ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " username TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " source_id TEXT NOT NULL,"
        " definition_json TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " last_exported_at TEXT,"
        " owner_unit_id INTEGER NOT NULL DEFAULT 1,"
        " UNIQUE(username, name))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_custom_reports_username ON custom_reports(username)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS custom_report_shares ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " report_id INTEGER NOT NULL,"
        " shared_with TEXT NOT NULL,"
        " created_at TEXT NOT NULL,"
        " owner_unit_id INTEGER NOT NULL DEFAULT 1,"
        " UNIQUE(report_id, shared_with))"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_custom_report_shares_user ON custom_report_shares(shared_with)")
    return None
