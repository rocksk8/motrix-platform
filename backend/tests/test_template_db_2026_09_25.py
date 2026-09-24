"""範本庫（`_template_db`）複製出來的庫，必須與每題新鮮 `init_db` 的庫等價。

📌 2026-09-25（PLAN-TEST-PERF §5.1）：`client` 改成從 session 範本複製，不再每題跑 116 個 migration。
☠️ 省下來的前提是「複製的 ＝ 新建的」。這一題守那個前提：
   - 全部 DDL（`sqlite_master` 的 sql，含索引、觸發器、檢視）
   - `schema_version`（跑到第幾個 migration）
   - 每張表的每一列（時間戳遮罩後比較：範本在 session 開始時建，新鮮庫在這一題建）
   - 開啟方式：以產品的 `db._connect` 開啟後仍是 WAL
🔑 不相等的時候要能說出**哪一張表、哪一列**，不是只說「不一樣」。
"""
import re
import sqlite3

import db

_TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?")
_RANDOM_COLS = {"password_hash"}


def _snapshot(path, readonly=False):
    # readonly：唯讀且不建 -wal／-shm（immutable），讀範本時不可以動到它（其他題正在從它複製）
    if readonly:
        from pathlib import Path
        conn = sqlite3.connect(Path(path).as_uri() + "?immutable=1", uri=True)
    else:
        conn = sqlite3.connect(path)
    try:
        ddl = sorted((r[0], r[1], r[2] or "") for r in conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        rows = {}
        for t in tables:
            cur = conn.execute('SELECT * FROM "%s"' % t)
            cols = [d[0] for d in cur.description]
            data = cur.fetchall()
            # 設計上就隨機的欄位（demo 閘門帳號的臨時密碼 secrets.token_urlsafe）不比
            rows[t] = sorted(tuple("<RANDOM>" if c in _RANDOM_COLS
                                   else _TS.sub("<TS>", v) if isinstance(v, str) else v
                                   for c, v in zip(cols, r)) for r in data)
        return {"ddl": ddl, "rows": rows}
    finally:
        conn.close()


def diff(a, b):
    """兩份快照的差異（空＝等價），以人讀得懂的一行一項列出。純函式。"""
    out = []
    da, dbb = set(a["ddl"]), set(b["ddl"])
    out += ["只在範本：%s %s" % x[:2] for x in sorted(da - dbb)]
    out += ["只在新建：%s %s" % x[:2] for x in sorted(dbb - da)]
    for t in sorted(set(a["rows"]) | set(b["rows"])):
        ra, rb = a["rows"].get(t), b["rows"].get(t)
        if ra != rb:
            out.append("表 %s 的資料不同（範本 %s 列、新建 %s 列）" % (t, len(ra or []), len(rb or [])))
    return out


def test_the_template_equals_a_fresh_init_db(_template_db, tmp_path):
    """範本檔本身 ＝ 新鮮 init_db。

    📌 更正（2026-09-25，建包 -n 6 下紅過一次：audit_log「範本 1 筆、新鮮 0 筆」）：
       第一版比的是 client 的**活庫**，而活庫會被前一題還在跑的背景執行緒寫入（已知的隔離漏洞，
       另案處理）——那一筆 audit_log 不是範本多出來的，是別人寫進這一題的庫。
       這一題的主張是「範本＝新建」，比對對象應該是**範本檔本身**（每題從它 copyfile，它自己不會被寫）。
       這不是放寬：範本少一張表、少一列、少跑一個 migration，照樣紅（見正對照題與突變紀錄）。
    """
    fresh = str(tmp_path / "fresh.db")
    db.init_db(fresh)
    problems = diff(_snapshot(_template_db, readonly=True), _snapshot(fresh))
    assert problems == [], "範本與新鮮 init_db 不等價：\n  " + "\n  ".join(problems)


def test_a_client_db_is_its_own_file_opened_as_wal(client, _template_db):
    assert db.DB_PATH != _template_db and db.DEMO_DB_PATH != _template_db
    conn = db._connect(db.DB_PATH)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        # 寫進這一題的庫，不可以寫到範本（每題隔離）
        conn.execute("CREATE TABLE zz_probe (x)")
        conn.commit()
    finally:
        conn.close()
    t = sqlite3.connect(_template_db)
    try:
        assert not t.execute("SELECT 1 FROM sqlite_master WHERE name='zz_probe'").fetchone()
    finally:
        t.close()


def test_the_comparison_catches_schema_version_rows_and_ddl(tmp_path):
    """正對照：差一個 migration、差一列種子資料、差一張表，都要被說出來；時間戳不同不算差。"""
    base = str(tmp_path / "a.db")
    db.init_db(base)
    snap = _snapshot(base)
    assert diff(snap, _snapshot(base)) == []

    def mutated(sql):
        p = str(tmp_path / ("m%d.db" % abs(hash(sql))))
        import shutil
        shutil.copyfile(base, p)
        c = sqlite3.connect(p)
        c.execute(sql)
        c.commit()
        c.close()
        return _snapshot(p)

    assert any("schema_version" in x for x in diff(snap, mutated("UPDATE schema_version SET version = version - 1")))
    assert any("system_settings" in x for x in diff(snap, mutated("DELETE FROM system_settings WHERE rowid = (SELECT MIN(rowid) FROM system_settings)")))
    assert any("zz_extra" in x for x in diff(snap, mutated("CREATE TABLE zz_extra (x)")))
    assert diff(snap, mutated("UPDATE system_settings SET updated_at = '1999-01-01T00:00:00'")) == []
