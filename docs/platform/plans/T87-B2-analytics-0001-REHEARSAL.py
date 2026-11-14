# -*- coding: utf-8 -*-
"""T87 B2：analytics 模組 migration 0001（custom_reports）在『備份副本』上的預演腳本。

用法（只對副本；不要指向正式 DB）：
    python -B T87-B2-analytics-0001-REHEARSAL.py <副本.db> <0001_custom_reports.py 路徑> check      # 唯讀：預演前後各跑一次
    python -B T87-B2-analytics-0001-REHEARSAL.py <副本.db> <0001_custom_reports.py 路徑> apply      # 在副本上執行（含寫版號）
    python -B T87-B2-analytics-0001-REHEARSAL.py <副本.db> <0001_custom_reports.py 路徑> rollback   # 回滾演練（DROP 兩表＋版號回 0）

`apply` 做的事和 core/migrations.py 的 run_all 一樣：SAVEPOINT → up(conn) → RELEASE → 寫 module_schema_versions(analytics,1)。
`check` 以 mode=ro 開啟，不寫任何東西。
"""
import importlib.util
import sqlite3
import sys
import time
from datetime import datetime

NEW_TABLES = ("custom_reports", "custom_report_shares")


def _ro(db):
    return sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)


def check(db):
    c = _ro(db)
    try:
        print("integrity_check =", c.execute("PRAGMA integrity_check").fetchone()[0])
        print("user_version    =", c.execute("PRAGMA user_version").fetchone()[0])
        print("（核心 schema_version 以 T 步驟檔 #12 的既有指令讀取為準，前後須相同）")
        print("module_schema_versions =", c.execute("SELECT module, version, applied_at FROM module_schema_versions ORDER BY module").fetchall())
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index') ORDER BY name")]
        print("sqlite_master 物件數 =", len(names))
        for t in NEW_TABLES:
            ex = t in names
            n = c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] if ex else None
            cols = [r[1] for r in c.execute("PRAGMA table_info(%s)" % t)] if ex else []
            print("%-22s 存在=%s 列數=%s 欄=%s" % (t, ex, n, cols))
        want = ("custom_reports", "custom_report_shares", "idx_custom_reports_username", "idx_custom_report_shares_user",
                "sqlite_autoindex_custom_reports_1", "sqlite_autoindex_custom_report_shares_1")
        print("本遷移的 6 個物件（表2＋明列索引2＋UNIQUE 自動索引2）：", [n for n in want if n in names])
        print("sqlite_sequence 存在 =", "sqlite_sequence" in names, "（不存在時，第一次建 AUTOINCREMENT 表會連它一起建 ⇒ 物件數多 1）")
        print("既有表（不含新表）數 =", len([r for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'") if r[0] not in NEW_TABLES]))
    finally:
        c.close()


def _load(path):
    spec = importlib.util.spec_from_file_location("analytics_0001", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def apply(db, path):
    m = _load(path)
    c = sqlite3.connect(db)
    try:
        t0 = time.perf_counter()
        c.execute("SAVEPOINT motrix_module_migration")
        res = m.up(c)
        if res is not None:
            c.execute("ROLLBACK TO motrix_module_migration")
            c.execute("RELEASE motrix_module_migration")
            print("未完成：", res)
            return 1
        c.execute("RELEASE motrix_module_migration")
        c.execute("INSERT INTO module_schema_versions (module, version, applied_at) VALUES (?,?,?) "
                  "ON CONFLICT(module) DO UPDATE SET version=excluded.version, applied_at=excluded.applied_at",
                  ("analytics", 1, datetime.now().isoformat()))
        c.commit()
        print("apply 完成，耗時 %.1f ms" % ((time.perf_counter() - t0) * 1000))
        return 0
    finally:
        c.close()


def rollback(db):
    c = sqlite3.connect(db)
    try:
        c.execute("DROP TABLE IF EXISTS custom_report_shares")
        c.execute("DROP TABLE IF EXISTS custom_reports")
        c.execute("UPDATE module_schema_versions SET version=0 WHERE module='analytics'")
        c.commit()
        print("rollback 完成（兩表已 DROP、analytics 版號＝0）")
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    db, mig, cmd = sys.argv[1], sys.argv[2], sys.argv[3]
    if cmd == "check":
        check(db)
    elif cmd == "apply":
        sys.exit(apply(db, mig))
    elif cmd == "rollback":
        sys.exit(rollback(db))
    else:
        print(__doc__)
        sys.exit(2)
