# -*- coding: utf-8 -*-
"""U0a 演練用：把合成資料播進一個已建好 schema 的資料庫（開發端自建庫；**不是正式機資料**，報告要註明）。

用法：python tools/platform/u0a_seed_synthetic.py <db> [--rows 3] [--bulk audit_log=100000,quotations=100000,notifications=100000]
  --bulk：把指定的表放大到 N 列（以該表第一列為樣板，唯一鍵欄位加序號後綴；用來證明 ADD COLUMN 與遷移時間不隨列數成長）
每張一般資料表播 N 列：INTEGER 主鍵交給 SQLite；NOT NULL 且無預設的欄位依型別填值（TEXT 帶表名欄名列號，滿足 UNIQUE）；
遇到 CHECK／FK／觸發器擋下的表就略過並列出（不強求每張都有資料）。目的：讓列數、內容雜湊、序列等價檢查有東西可比，不是還原真實資料。
"""
import sqlite3
import sys

SKIP = {"schema_version", "module_schema_versions", "sqlite_sequence"}


def build_row(info, table, i):
    """依 PRAGMA table_info 組一列『舊程式式』的值（只填 NOT NULL 且無預設的欄位）⇒ (欄位清單, 值清單)。"""
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
        vals.append(i if ("INT" in typ or "BOOL" in typ) else (1.5 + i if ("REAL" in typ or "FLOA" in typ or "NUM" in typ) else "seed-%s-%s-%d" % (table, name, i)))
    return cols, vals


def bulk(path, table, n):
    """把 table 放大到至少 n 列（樣板＝第一列；INTEGER 主鍵交給 SQLite；唯一索引內的欄位加序號）。回實際列數。"""
    conn = sqlite3.connect(str(path))
    try:
        info = conn.execute('PRAGMA table_info("%s")' % table).fetchall()
        names = [r[1] for r in info]
        uniq = set()
        for idx in conn.execute('PRAGMA index_list("%s")' % table).fetchall():
            if idx[2]:
                uniq |= {r[2] for r in conn.execute('PRAGMA index_info("%s")' % idx[1]).fetchall()}
        tmpl = conn.execute('SELECT * FROM "%s" LIMIT 1' % table).fetchone()
        if tmpl is None:
            return 0
        pk_int = {r[1] for r in info if r[5] and "INT" in (r[2] or "").upper()}
        use = [c for c in names if c not in pk_int]
        have = conn.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0]
        base = dict(zip(names, tmpl))
        batch = []
        for i in range(have + 1, n + 1):
            row = []
            for c in use:
                v = base[c]
                if c in uniq and v is not None:
                    v = (v + 1000000 + i) if isinstance(v, (int, float)) else "%s-%d" % (v, i)
                row.append(v)
            batch.append(row)
            if len(batch) >= 5000:
                conn.executemany('INSERT INTO "%s" (%s) VALUES (%s)' % (table, ",".join('"%s"' % c for c in use), ",".join("?" * len(use))), batch)
                batch = []
        if batch:
            conn.executemany('INSERT INTO "%s" (%s) VALUES (%s)' % (table, ",".join('"%s"' % c for c in use), ",".join("?" * len(use))), batch)
        conn.commit()
        return conn.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0]
    finally:
        conn.close()


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
                cols, vals = build_row(info, t, i)
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
    if "--bulk" in sys.argv:
        for part in sys.argv[sys.argv.index("--bulk") + 1].split(","):
            t, _, k = part.partition("=")
            print("放大 %s → %d 列" % (t, bulk(sys.argv[1], t, int(k))))
