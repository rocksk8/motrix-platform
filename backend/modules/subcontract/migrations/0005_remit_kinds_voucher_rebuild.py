# -*- coding: utf-8 -*-
"""subcontract v5（2026-10-02，31-B S1：匯款款別／分期）：重建 `contractor_payment_vouchers`——拿掉 `dispatch_id UNIQUE`、加款別與分期欄位。

為什麼要重建：`dispatch_id INTEGER UNIQUE NOT NULL` 是**欄位內嵌**的 UNIQUE（`db.py _m045`），SQLite 沒有 `DROP CONSTRAINT`，只能建新表→搬資料→換名。
- 新欄（全部有預設值，舊列＝舊式整筆申請）：`kind`（款別代碼；`''`＝舊式整筆）、`kind_name`（建立當下的名稱快照）、`kinds_version`（建立當下生效的款別版本）、
  `seq`（同款別第幾期；`0`＝舊式）、`ratio`（比例申請時的比例，定額為 NULL）、`pretax_amount`（本期稅前，整數元；舊列 NULL ⇒ 讀快照）、
  `inv_no`／`inv_date`／`inv_files_json`（本期發票）、`void_reason`／`voided_at`／`voided_by`（作廢；作廢的不佔額度與唯一性）。
- 唯一性改成部分唯一索引：`kind=''` 且未作廢的申請，同一派發最多一張（與舊行為一致）；`kind<>''` 且未作廢的，同派發同款別同期不重複。
- 搬資料前後逐列比對舊欄位（筆數＋全部欄位值）；不一致 ⇒ 丟例外（loader 的 SAVEPOINT 撤回整支，舊表原封不動，該模組下線、版號不前進）。
- 欄位定義取自**現有表**（PRAGMA table_info），所以正式機表被手工加過的欄也會保留；`voucher_no UNIQUE`、兩個外鍵（派發、廠商）與
  兩個索引（`idx_cpv_quote_no`、`idx_cpv_status`）照舊重建。`sqlite_sequence` 取舊值與最大 id 的較大者，不回頭重用 id。
- 冪等：已經沒有 `dispatch_id` 單欄 UNIQUE 且有 `kind` 欄 ⇒ 只補索引；表不在 ⇒ 回原因字串＝未完成（下次啟動再試）。
- 不自己 commit、不用 PRAGMA foreign_keys（交易內不能改；正式機實測沒有其他表參照這張表，DROP 安全）。設計：docs/platform/plans/REMIT-KINDS-31B-DESIGN.md §3。"""

TABLE = "contractor_payment_vouchers"
_NEW_COLS = (
    ("kind", "TEXT NOT NULL DEFAULT ''"),
    ("kind_name", "TEXT NOT NULL DEFAULT ''"),
    ("kinds_version", "INTEGER NOT NULL DEFAULT 0"),
    ("seq", "INTEGER NOT NULL DEFAULT 0"),
    ("ratio", "REAL"),
    ("pretax_amount", "INTEGER"),
    ("inv_no", "TEXT NOT NULL DEFAULT ''"),
    ("inv_date", "TEXT NOT NULL DEFAULT ''"),
    ("inv_files_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("void_reason", "TEXT NOT NULL DEFAULT ''"),
    ("voided_at", "TEXT NOT NULL DEFAULT ''"),
    ("voided_by", "TEXT NOT NULL DEFAULT ''"),
)
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_cpv_quote_no ON contractor_payment_vouchers(quote_no)",
    "CREATE INDEX IF NOT EXISTS idx_cpv_status ON contractor_payment_vouchers(status)",
    "CREATE INDEX IF NOT EXISTS idx_cpv_dispatch ON contractor_payment_vouchers(dispatch_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_cpv_dispatch_legacy ON contractor_payment_vouchers(dispatch_id) WHERE kind = '' AND voided_at = ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_cpv_dispatch_kind_seq ON contractor_payment_vouchers(dispatch_id, kind, seq) WHERE kind <> '' AND voided_at = ''",
)


def _cols(conn, table):
    """⇒ [(name, type, notnull, dflt, pk)]；一律用位置取值（不依賴連線的 row_factory）。"""
    return [(r[1], r[2], r[3], r[4], r[5]) for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()]


def _has_dispatch_unique(conn):
    """有沒有『只含 dispatch_id、非部分』的唯一約束（內嵌 UNIQUE 的 autoindex 或獨立唯一索引）。"""
    for r in conn.execute("PRAGMA index_list(%s)" % TABLE).fetchall():
        name, unique, partial = r[1], r[2], (r[4] if len(r) > 4 else 0)
        if not unique or partial:
            continue
        cols = [x[2] for x in conn.execute("PRAGMA index_info(%s)" % name).fetchall()]
        if cols == ["dispatch_id"]:
            return True
    return False


def _ddl(cols):
    parts = []
    for name, typ, notnull, dflt, pk in cols:
        if name == "id":
            parts.append("id INTEGER PRIMARY KEY AUTOINCREMENT")
            continue
        p = "%s %s" % (name, typ or "TEXT")
        if name == "voucher_no":
            p += " UNIQUE"
        if notnull:
            p += " NOT NULL"
        if dflt is not None:
            p += " DEFAULT %s" % dflt
        if name == "dispatch_id":
            p += " REFERENCES contractor_dispatches(id)"
        elif name == "vendor_id":
            p += " REFERENCES vendor_contractors(id)"
        parts.append(p)
    have = {c[0] for c in cols}
    for name, decl in _NEW_COLS:
        if name not in have:
            parts.append("%s %s" % (name, decl))
    return "CREATE TABLE contractor_payment_vouchers_new (\n  " + ",\n  ".join(parts) + "\n)"


def up(conn):
    cols = _cols(conn, TABLE)
    if not cols:
        return "contractor_payment_vouchers 表不存在，匯款款別欄位這次不補、下次啟動再試"
    names = [c[0] for c in cols]
    if "kind" in names and not _has_dispatch_unique(conn):
        for ddl in _INDEXES:                                       # 已經重建過：只確保索引都在
            conn.execute(ddl)
        return None
    old_cols = ", ".join(names)
    before = conn.execute("SELECT %s FROM %s ORDER BY id" % (old_cols, TABLE)).fetchall()
    seq_row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (TABLE,)).fetchone()
    old_seq = int(seq_row[0]) if seq_row and seq_row[0] is not None else 0
    conn.execute("DROP TABLE IF EXISTS contractor_payment_vouchers_new")
    conn.execute(_ddl(cols))
    conn.execute("INSERT INTO contractor_payment_vouchers_new (%s) SELECT %s FROM %s ORDER BY id" % (old_cols, old_cols, TABLE))
    after = conn.execute("SELECT %s FROM contractor_payment_vouchers_new ORDER BY id" % old_cols).fetchall()
    if len(before) != len(after) or [tuple(r) for r in before] != [tuple(r) for r in after]:
        raise RuntimeError("重建 %s 時搬資料前後不一致（舊 %d 列、新 %d 列）；已撤回，舊表不動" % (TABLE, len(before), len(after)))
    conn.execute("DROP TABLE %s" % TABLE)
    conn.execute("ALTER TABLE contractor_payment_vouchers_new RENAME TO %s" % TABLE)
    max_id = max([int(r[names.index("id")]) for r in before] or [0])
    conn.execute("DELETE FROM sqlite_sequence WHERE name=?", (TABLE,))
    conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (TABLE, max(old_seq, max_id)))
    for ddl in _INDEXES:
        conn.execute(ddl)
    return None
