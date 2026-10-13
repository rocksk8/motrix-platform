# -*- coding: utf-8 -*-
"""U0a 演練用：把合成資料播進一個已建好 schema 的資料庫（開發端自建庫；**不是正式機資料**，報告要註明）。

用法：python tools/platform/u0a_seed_synthetic.py <db> [--rows 3]
每張一般資料表播 N 列：INTEGER 主鍵交給 SQLite；NOT NULL 且無預設的欄位依型別填值（TEXT 帶表名欄名列號，滿足 UNIQUE）；
遇到 CHECK／FK／觸發器擋下的表就略過並列出（不強求每張都有資料）。目的：讓列數、內容雜湊、序列等價檢查有東西可比，不是還原真實資料。
"""
import sqlite3
import sys

SKIP = {"schema_version", "module_schema_versions", "sqlite_sequence"}


def seed(path, rows=3):
    conn = sqlite3.connect(str(path))
    done, skipped = [], []
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for t in tables:
            if t in SKIP:
                continue
            info = conn.execute('PRAGMA table_info("%s")' % t).fetchall()      # cid,name,type,notnull,dflt,pk
            if conn.execute('SELECT 1 FROM "%s" LIMIT 1' % t).fetchone():
                continue                                                         # 已有資料（例如種子設定）不動
            ok = 0
            for i in range(1, rows + 1):
                cols, vals = [], []
                for _, name, typ, notnull, dflt, pk in info:
                    typ = (typ or "").upper()
                    if pk and "INT" in typ:
                        continue
                    if dflt is not None and not pk:
                        continue
                    if not notnull and not pk:
                        continue
                    cols.append('"%s"' % name)
                    vals.append(i if ("INT" in typ or "BOOL" in typ) else (1.5 + i if ("REAL" in typ or "FLOA" in typ or "NUM" in typ) else "seed-%s-%s-%d" % (t, name, i)))
                conn.execute("SAVEPOINT s")
                try:
                    if cols:
                        conn.execute('INSERT INTO "%s" (%s) VALUES (%s)' % (t, ",".join(cols), ",".join("?" * len(cols))), vals)
                    else:
                        conn.execute('INSERT INTO "%s" DEFAULT VALUES' % t)
                    conn.execute("RELEASE s")
                    ok += 1
                except sqlite3.Error:
                    conn.execute("ROLLBACK TO s")
                    conn.execute("RELEASE s")
            (done if ok else skipped).append(t)
        conn.commit()
    finally:
        conn.close()
    return done, skipped


if __name__ == "__main__":
    n = 3
    if "--rows" in sys.argv:
        n = int(sys.argv[sys.argv.index("--rows") + 1])
    d, s = seed(sys.argv[1], n)
    print("播入 %d 張表；略過 %d 張：%s" % (len(d), len(s), ", ".join(s)))
