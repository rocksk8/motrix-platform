# -*- coding: utf-8 -*-
"""accounting v1（2026-09-30，W4 總帳 P1）：會計期間、科目屬性與角色、期初餘額、期間鎖定觸發器。

設計：docs/platform（proposal-general-ledger）03-periods-close.md、01-accounts.md。
- 新表：gl_settings／gl_account_meta／gl_account_roles／gl_fiscal_years／gl_periods／gl_period_log（只增不改不刪）／
  gl_opening_batches／gl_opening_balances／gl_opening_items。
- 新欄位（加法，預設值使舊資料與舊程式照常）：voucher_lines（case_no／party_key／tax_code／doc_no）、
  vouchers_all（kind／reverses_no／is_backfill／origin）。VIEW `vouchers` 是 `SELECT *`，讀取時展開，新欄位自動可見。
- 觸發器（縱深防禦，API 與引擎之外的第三層）：非 open 期間不可過帳、不可作廢已過帳傳票；已過帳傳票的日期與分錄不可改。
  沒有任何期間資料（gl_periods 空）＝全部視為開放 ⇒ 舊資料與未啟用總帳的部署行為不變。
- 不自己 commit；SQL 全寫在這裡，不 import 任何會演進的程式碼（守門 tests/platform/test_module_migrations.py）。
"""

_TABLES = (
    """CREATE TABLE IF NOT EXISTS gl_settings (
        key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS gl_account_meta (
        code TEXT PRIMARY KEY REFERENCES account_items(code),
        acct_type TEXT NOT NULL, normal_side TEXT NOT NULL,
        postable INTEGER NOT NULL DEFAULT 1, is_contra INTEGER NOT NULL DEFAULT 0,
        fs_line TEXT NOT NULL DEFAULT '', tax_role TEXT NOT NULL DEFAULT '',
        display_name TEXT NOT NULL DEFAULT '', is_active INTEGER NOT NULL DEFAULT 1,
        note TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS gl_account_roles (
        role TEXT NOT NULL, scope_type TEXT NOT NULL DEFAULT '', scope_key TEXT NOT NULL DEFAULT '',
        account_code TEXT NOT NULL REFERENCES account_items(code),
        effective_from TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (role, scope_type, scope_key, effective_from))""",
    """CREATE TABLE IF NOT EXISTS gl_fiscal_years (
        year INTEGER PRIMARY KEY, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        opening_mode TEXT NOT NULL DEFAULT 'carry', opening_date TEXT NOT NULL DEFAULT '',
        opening_batch_id INTEGER, created_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS gl_periods (
        id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER NOT NULL REFERENCES gl_fiscal_years(year),
        period_no INTEGER NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open', stale INTEGER NOT NULL DEFAULT 0,
        closed_by TEXT NOT NULL DEFAULT '', closed_at TEXT NOT NULL DEFAULT '',
        tb_hash TEXT NOT NULL DEFAULT '', UNIQUE(year, period_no))""",
    """CREATE TABLE IF NOT EXISTS gl_period_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, period_id INTEGER, year INTEGER,
        action TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', actor TEXT NOT NULL, at TEXT NOT NULL,
        tb_hash_before TEXT NOT NULL DEFAULT '', tb_hash_after TEXT NOT NULL DEFAULT '',
        detail_json TEXT NOT NULL DEFAULT '{}')""",
    """CREATE TABLE IF NOT EXISTS gl_opening_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER NOT NULL, opening_date TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'import', filename TEXT NOT NULL DEFAULT '',
        voucher_id INTEGER, created_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '',
        undone_at TEXT NOT NULL DEFAULT '', undone_by TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS gl_opening_balances (
        batch_id INTEGER NOT NULL REFERENCES gl_opening_batches(id), account_code TEXT NOT NULL,
        debit INTEGER NOT NULL DEFAULT 0, credit INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (batch_id, account_code))""",
    """CREATE TABLE IF NOT EXISTS gl_opening_items (
        batch_id INTEGER NOT NULL, account_code TEXT NOT NULL, party_key TEXT NOT NULL,
        doc_no TEXT NOT NULL, doc_date TEXT NOT NULL DEFAULT '', amount INTEGER NOT NULL,
        PRIMARY KEY (batch_id, account_code, party_key, doc_no))""",
)

_COLUMNS = (
    ("voucher_lines", "case_no", "TEXT NOT NULL DEFAULT ''"),
    ("voucher_lines", "party_key", "TEXT NOT NULL DEFAULT ''"),
    ("voucher_lines", "tax_code", "TEXT NOT NULL DEFAULT ''"),
    ("voucher_lines", "doc_no", "TEXT NOT NULL DEFAULT ''"),
    ("vouchers_all", "kind", "TEXT NOT NULL DEFAULT 'manual'"),
    ("vouchers_all", "reverses_no", "TEXT NOT NULL DEFAULT ''"),
    ("vouchers_all", "is_backfill", "INTEGER NOT NULL DEFAULT 0"),
    ("vouchers_all", "origin", "TEXT NOT NULL DEFAULT ''"),
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_vlines_case ON voucher_lines(case_no)",
    "CREATE INDEX IF NOT EXISTS idx_vlines_party ON voucher_lines(party_key, account_code)",
    "CREATE INDEX IF NOT EXISTS idx_vouchers_kind ON vouchers_all(kind, voucher_date)",
    "CREATE INDEX IF NOT EXISTS idx_gl_periods_range ON gl_periods(start_date, end_date)",
)

# 「日期落在非開放期間」的判斷。voucher_date 一律 YYYY-MM-DD（取前 10 碼防帶時間的舊資料）。
_CLOSED = ("EXISTS (SELECT 1 FROM gl_periods p WHERE p.status <> 'open'"
           " AND substr(%s, 1, 10) BETWEEN p.start_date AND p.end_date)")

_TRIGGERS = (
    ("gl_period_no_post",
     "CREATE TRIGGER gl_period_no_post BEFORE UPDATE OF status ON vouchers_all "
     "WHEN NEW.status = '已過帳' AND OLD.status <> '已過帳' AND " + _CLOSED % "NEW.voucher_date" +
     " BEGIN SELECT RAISE(ABORT, '會計期間已結帳，不可過帳到此期間（請先重開期間，或改用開放期間的沖轉傳票）'); END"),
    ("gl_period_no_void",
     "CREATE TRIGGER gl_period_no_void BEFORE UPDATE OF voided_at ON vouchers_all "
     "WHEN OLD.voided_at = '' AND NEW.voided_at <> '' AND OLD.status = '已過帳' AND " + _CLOSED % "OLD.voucher_date" +
     " BEGIN SELECT RAISE(ABORT, '會計期間已結帳，已過帳傳票不可作廢（請開沖轉傳票，或先重開期間）'); END"),
    ("gl_posted_no_redate",
     "CREATE TRIGGER gl_posted_no_redate BEFORE UPDATE OF voucher_date ON vouchers_all "
     "WHEN OLD.status = '已過帳' AND NEW.voucher_date <> OLD.voucher_date "
     "BEGIN SELECT RAISE(ABORT, '已過帳傳票的日期不可修改'); END"),
    ("gl_posted_lines_no_insert",
     "CREATE TRIGGER gl_posted_lines_no_insert BEFORE INSERT ON voucher_lines "
     "WHEN (SELECT status FROM vouchers_all WHERE id = NEW.voucher_id) = '已過帳' "
     "BEGIN SELECT RAISE(ABORT, '已過帳傳票的分錄不可新增'); END"),
    ("gl_posted_lines_no_delete",
     "CREATE TRIGGER gl_posted_lines_no_delete BEFORE DELETE ON voucher_lines "
     "WHEN (SELECT status FROM vouchers_all WHERE id = OLD.voucher_id) = '已過帳' "
     "BEGIN SELECT RAISE(ABORT, '已過帳傳票的分錄不可刪除'); END"),
    ("gl_posted_lines_no_update",
     "CREATE TRIGGER gl_posted_lines_no_update BEFORE UPDATE OF account_code, debit, credit, voucher_id "
     "ON voucher_lines WHEN (SELECT status FROM vouchers_all WHERE id = OLD.voucher_id) = '已過帳' "
     "BEGIN SELECT RAISE(ABORT, '已過帳傳票的分錄不可修改'); END"),
    ("gl_period_log_no_update",
     "CREATE TRIGGER gl_period_log_no_update BEFORE UPDATE ON gl_period_log "
     "BEGIN SELECT RAISE(ABORT, '期間稽核軌跡只增不改'); END"),
    ("gl_period_log_no_delete",
     "CREATE TRIGGER gl_period_log_no_delete BEFORE DELETE ON gl_period_log "
     "BEGIN SELECT RAISE(ABORT, '期間稽核軌跡只增不刪'); END"),
)


def up(conn):
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    for need in ("vouchers_all", "voucher_lines", "account_items"):
        if need not in have:
            return "%s 表不存在（應由 V9 建立），這次不補、下次啟動再試" % need
    for ddl in _TABLES:
        conn.execute(ddl)
    for table, col, ddl in _COLUMNS:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
        if col not in cols:
            conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, ddl))
    for ddl in _INDEXES:
        conn.execute(ddl)
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    for name, ddl in _TRIGGERS:
        if name not in existing:
            conn.execute(ddl)
    return None
