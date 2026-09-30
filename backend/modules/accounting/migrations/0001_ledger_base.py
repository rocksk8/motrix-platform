# -*- coding: utf-8 -*-
"""accounting v1（2026-09-30，W4 總帳「底層一次到位」）：B～C 全部批次會用到的表／欄位／觸發器集中在這一版。

使用者裁示（2026-09-30）：全域的部分先上，之後 B3～C9 各批只改 accounting 模組程式、不再新增 migration。未出貨，故把先前的 v1／v2 併成同一版；
全部只新增（加表、加欄位、加觸發器）、冪等，回退程式碼時舊程式不讀新東西。不自己 commit；SQL 全寫在這裡，不 import 任何會演進的程式碼。

分組（設計稿 proposal-gl 的章節）：
- 期間與科目（03、01）：gl_settings／gl_account_meta（含 cashflow_class）／gl_account_roles／gl_fiscal_years／gl_periods／gl_period_log／
  gl_opening_*／gl_balance_snapshot／gl_statement_snapshots／gl_fs_lines。
- 分錄引擎（02）：gl_source_events／gl_engine_runs／gl_confirm_batches／gl_cursors／gl_category_map／gl_custom_field_map／
  gl_source_annotations（會計補登來源憑證資料，取代要求各來源模組加欄位）／gl_backfill_runs。
- 營業稅與扣繳（05）：gl_tax401_map／gl_tax_settlements／gl_invoice_adjustments／gl_withholding_items。
- 存貨成本（07）：gl_inv_moves（只增不改）／gl_inv_parts。
- 固定資產（06）：fa_categories／fa_assets／fa_revisions（只增不改）／fa_depr_runs／fa_depr_lines。
- 新欄位：voucher_lines（case_no／party_key／tax_code／doc_no）、vouchers_all（kind／reverses_no／is_backfill／origin／gl_event_id）。
- 觸發器（縱深防禦）：非 open 期間不可過帳、不可作廢已過帳傳票；已過帳傳票日期與分錄不可改；稽核／異動／凍結類表只增不改不刪。
  沒有任何期間資料（gl_periods 空）＝全部視為開放 ⇒ 舊資料與未啟用總帳的部署行為不變。
"""
_TABLES = (
    """CREATE TABLE IF NOT EXISTS gl_settings (
        key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS gl_account_meta (
        code TEXT PRIMARY KEY REFERENCES account_items(code),
        acct_type TEXT NOT NULL, normal_side TEXT NOT NULL,
        postable INTEGER NOT NULL DEFAULT 1, is_contra INTEGER NOT NULL DEFAULT 0,
        fs_line TEXT NOT NULL DEFAULT '', cashflow_class TEXT NOT NULL DEFAULT '', tax_role TEXT NOT NULL DEFAULT '',
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
    # ── 報表列、結帳快照 ──
    """CREATE TABLE IF NOT EXISTS gl_fs_lines (
        code TEXT PRIMARY KEY, statement TEXT NOT NULL, label TEXT NOT NULL,
        sort INTEGER NOT NULL DEFAULT 0, side TEXT NOT NULL DEFAULT 'D',
        kind TEXT NOT NULL DEFAULT 'line', is_active INTEGER NOT NULL DEFAULT 1,
        note TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS gl_balance_snapshot (
        period_id INTEGER NOT NULL, account_code TEXT NOT NULL,
        debit INTEGER NOT NULL DEFAULT 0, credit INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (period_id, account_code))""",
    """CREATE TABLE IF NOT EXISTS gl_statement_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, fy INTEGER NOT NULL DEFAULT 0,
        period_end TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL DEFAULT '{}',
        frozen INTEGER NOT NULL DEFAULT 1, created_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '')""",
    # ── 分錄引擎 ──
    """CREATE TABLE IF NOT EXISTS gl_source_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, source_module TEXT NOT NULL DEFAULT '', source_type TEXT NOT NULL,
        source_key TEXT NOT NULL, event_code TEXT NOT NULL, rev INTEGER NOT NULL DEFAULT 1,
        event_date TEXT NOT NULL, content_hash TEXT NOT NULL DEFAULT '', amount INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending', voucher_id INTEGER, reversal_voucher_id INTEGER, supersedes_id INTEGER,
        note TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL DEFAULT '{}',
        first_seen TEXT NOT NULL DEFAULT '', last_seen TEXT NOT NULL DEFAULT '',
        UNIQUE (source_type, source_key, event_code, rev))""",
    """CREATE TABLE IF NOT EXISTS gl_engine_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL DEFAULT '', finished_at TEXT NOT NULL DEFAULT '',
        started_by TEXT NOT NULL DEFAULT '', range_start TEXT NOT NULL DEFAULT '', range_end TEXT NOT NULL DEFAULT '',
        scanned INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL DEFAULT 0, drift INTEGER NOT NULL DEFAULT 0,
        blocked INTEGER NOT NULL DEFAULT 0, notices_json TEXT NOT NULL DEFAULT '[]')""",
    """CREATE TABLE IF NOT EXISTS gl_confirm_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '', total INTEGER NOT NULL DEFAULT 0, ok_count INTEGER NOT NULL DEFAULT 0,
        detail_json TEXT NOT NULL DEFAULT '[]')""",
    """CREATE TABLE IF NOT EXISTS gl_cursors (name TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS gl_category_map (
        source TEXT NOT NULL, category TEXT NOT NULL, role TEXT NOT NULL DEFAULT '', account_code TEXT NOT NULL DEFAULT '',
        nondeductible INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', PRIMARY KEY (source, category))""",
    """CREATE TABLE IF NOT EXISTS gl_custom_field_map (
        module_key TEXT NOT NULL, field_key TEXT NOT NULL, debit_account TEXT NOT NULL DEFAULT '',
        credit_account TEXT NOT NULL DEFAULT '', tax_code TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (module_key, field_key))""",
    """CREATE TABLE IF NOT EXISTS gl_source_annotations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, source_type TEXT NOT NULL, source_key TEXT NOT NULL,
        field TEXT NOT NULL, value TEXT NOT NULL DEFAULT '', updated_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT '', UNIQUE (source_type, source_key, field))""",
    """CREATE TABLE IF NOT EXISTS gl_backfill_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, range_start TEXT NOT NULL DEFAULT '', range_end TEXT NOT NULL DEFAULT '',
        sources_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'running',
        counts_json TEXT NOT NULL DEFAULT '{}', created_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '',
        finished_at TEXT NOT NULL DEFAULT '')""",
    # ── 營業稅與扣繳 ──
    """CREATE TABLE IF NOT EXISTS gl_tax401_map (
        tax_code TEXT NOT NULL, invoice_kind TEXT NOT NULL DEFAULT '', side TEXT NOT NULL DEFAULT 'OUT',
        field_amt TEXT NOT NULL DEFAULT '', field_tax TEXT NOT NULL DEFAULT '', field_zero TEXT NOT NULL DEFAULT '',
        note TEXT NOT NULL DEFAULT '', PRIMARY KEY (tax_code, invoice_kind))""",
    """CREATE TABLE IF NOT EXISTS gl_tax_settlements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
        output_tax INTEGER NOT NULL DEFAULT 0, input_tax INTEGER NOT NULL DEFAULT 0, carry_prev INTEGER NOT NULL DEFAULT 0,
        payable INTEGER NOT NULL DEFAULT 0, carry_new INTEGER NOT NULL DEFAULT 0, refund_amount INTEGER NOT NULL DEFAULT 0,
        voucher_id INTEGER, status TEXT NOT NULL DEFAULT 'draft', created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '', UNIQUE (period_start, period_end))""",
    """CREATE TABLE IF NOT EXISTS gl_invoice_adjustments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, invoice_no TEXT NOT NULL, quote_no TEXT NOT NULL DEFAULT '',
        party_key TEXT NOT NULL DEFAULT '', adj_type TEXT NOT NULL, adj_date TEXT NOT NULL,
        pretax INTEGER NOT NULL DEFAULT 0, tax INTEGER NOT NULL DEFAULT 0, cert_no TEXT NOT NULL DEFAULT '',
        reason TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft', voucher_id INTEGER,
        approval_json TEXT NOT NULL DEFAULT '{}', created_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS gl_withholding_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, source_type TEXT NOT NULL DEFAULT '',
        source_key TEXT NOT NULL DEFAULT '', party_key TEXT NOT NULL DEFAULT '', income_type TEXT NOT NULL DEFAULT '',
        gross INTEGER NOT NULL DEFAULT 0, amount INTEGER NOT NULL DEFAULT 0, period_ym TEXT NOT NULL DEFAULT '',
        remitted_at TEXT NOT NULL DEFAULT '', remit_voucher_id INTEGER, created_at TEXT NOT NULL DEFAULT '',
        UNIQUE (kind, source_type, source_key))""",
    # ── 存貨成本（移動加權平均）──
    """CREATE TABLE IF NOT EXISTS gl_inv_moves (
        id INTEGER PRIMARY KEY AUTOINCREMENT, part_no TEXT NOT NULL, move_at TEXT NOT NULL, move_type TEXT NOT NULL,
        qty INTEGER NOT NULL, amount INTEGER NOT NULL, qty_after INTEGER NOT NULL, value_after INTEGER NOT NULL,
        ref_type TEXT NOT NULL DEFAULT '', ref_key TEXT NOT NULL DEFAULT '', case_no TEXT NOT NULL DEFAULT '',
        links_move_id INTEGER, created_at TEXT NOT NULL DEFAULT '', UNIQUE (ref_type, ref_key, part_no, move_type))""",
    """CREATE TABLE IF NOT EXISTS gl_inv_parts (
        part_no TEXT PRIMARY KEY, qty INTEGER NOT NULL DEFAULT 0, value INTEGER NOT NULL DEFAULT 0,
        last_move_id INTEGER, updated_at TEXT NOT NULL DEFAULT '')""",
    # ── 固定資產 ──
    """CREATE TABLE IF NOT EXISTS fa_categories (
        code TEXT PRIMARY KEY, name TEXT NOT NULL, cost_account TEXT NOT NULL DEFAULT '', accum_account TEXT NOT NULL DEFAULT '',
        expense_account TEXT NOT NULL DEFAULT '', default_life_years INTEGER NOT NULL DEFAULT 5,
        default_tax_life_years INTEGER NOT NULL DEFAULT 5, life_table_ref TEXT NOT NULL DEFAULT '', is_active INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS fa_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, asset_no TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT '', acquired_on TEXT NOT NULL, in_service_on TEXT NOT NULL,
        cost INTEGER NOT NULL DEFAULT 0, input_tax INTEGER NOT NULL DEFAULT 0,
        life_years INTEGER NOT NULL DEFAULT 5, salvage INTEGER NOT NULL DEFAULT 0,
        tax_life_years INTEGER NOT NULL DEFAULT 5, tax_salvage INTEGER NOT NULL DEFAULT 0,
        method TEXT NOT NULL DEFAULT 'straight_line', tax_capitalized INTEGER NOT NULL DEFAULT 1, refund_flag INTEGER NOT NULL DEFAULT 0,
        supplier_key TEXT NOT NULL DEFAULT '', invoice_no TEXT NOT NULL DEFAULT '', invoice_date TEXT NOT NULL DEFAULT '',
        source_doc TEXT NOT NULL DEFAULT '', case_no TEXT NOT NULL DEFAULT '', dept_code TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft', disposed_on TEXT NOT NULL DEFAULT '', disposal_amount INTEGER NOT NULL DEFAULT 0,
        note TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS fa_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id INTEGER NOT NULL, effective_month TEXT NOT NULL,
        life_years INTEGER NOT NULL, salvage INTEGER NOT NULL, reason TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS fa_depr_runs (
        ym TEXT PRIMARY KEY, voucher_id INTEGER, total INTEGER NOT NULL DEFAULT 0, tax_total INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS fa_depr_lines (
        ym TEXT NOT NULL, asset_id INTEGER NOT NULL, amount INTEGER NOT NULL DEFAULT 0, tax_amount INTEGER NOT NULL DEFAULT 0,
        accum_after INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (ym, asset_id))""",
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
    ("vouchers_all", "gl_event_id", "INTEGER NOT NULL DEFAULT 0"),
    ("gl_account_meta", "cashflow_class", "TEXT NOT NULL DEFAULT ''"),        # 較早的開發庫（先有 gl_account_meta 沒有此欄）補欄
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_vlines_case ON voucher_lines(case_no)",
    "CREATE INDEX IF NOT EXISTS idx_vlines_party ON voucher_lines(party_key, account_code)",
    "CREATE INDEX IF NOT EXISTS idx_vouchers_kind ON vouchers_all(kind, voucher_date)",
    "CREATE INDEX IF NOT EXISTS idx_gl_periods_range ON gl_periods(start_date, end_date)",
    "CREATE INDEX IF NOT EXISTS idx_gl_fs_lines_stmt ON gl_fs_lines(statement, sort)",
    "CREATE INDEX IF NOT EXISTS idx_gse_status ON gl_source_events(status, event_date)",
    "CREATE INDEX IF NOT EXISTS idx_gse_voucher ON gl_source_events(voucher_id)",
    "CREATE INDEX IF NOT EXISTS idx_vouchers_gl_event ON vouchers_all(gl_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_gl_inv_moves_part ON gl_inv_moves(part_no, id)",
    "CREATE INDEX IF NOT EXISTS idx_gl_inv_moves_case ON gl_inv_moves(case_no)",
    "CREATE INDEX IF NOT EXISTS idx_fa_assets_status ON fa_assets(status, in_service_on)",
    "CREATE INDEX IF NOT EXISTS idx_gl_withholding_period ON gl_withholding_items(kind, period_ym)",
    "CREATE INDEX IF NOT EXISTS idx_gl_adjust_invoice ON gl_invoice_adjustments(invoice_no)",
    "CREATE INDEX IF NOT EXISTS idx_gl_annot_source ON gl_source_annotations(source_type, source_key)",
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
    ("gl_events_no_delete",
     "CREATE TRIGGER gl_events_no_delete BEFORE DELETE ON gl_source_events "
     "BEGIN SELECT RAISE(ABORT, '來源事件只改狀態、不可刪除（稽核軌跡）'); END"),
    ("gl_inv_moves_no_update",
     "CREATE TRIGGER gl_inv_moves_no_update BEFORE UPDATE ON gl_inv_moves "
     "BEGIN SELECT RAISE(ABORT, '存貨異動明細只增不改（更正請寫反向異動）'); END"),
    ("gl_inv_moves_no_delete",
     "CREATE TRIGGER gl_inv_moves_no_delete BEFORE DELETE ON gl_inv_moves "
     "BEGIN SELECT RAISE(ABORT, '存貨異動明細只增不刪'); END"),
    ("gl_fa_revisions_no_update",
     "CREATE TRIGGER gl_fa_revisions_no_update BEFORE UPDATE ON fa_revisions "
     "BEGIN SELECT RAISE(ABORT, '固定資產估計變動只增不改'); END"),
    ("gl_fa_revisions_no_delete",
     "CREATE TRIGGER gl_fa_revisions_no_delete BEFORE DELETE ON fa_revisions "
     "BEGIN SELECT RAISE(ABORT, '固定資產估計變動只增不刪'); END"),
    ("gl_stmt_snapshots_no_update",
     "CREATE TRIGGER gl_stmt_snapshots_no_update BEFORE UPDATE ON gl_statement_snapshots WHEN OLD.frozen = 1 "
     "BEGIN SELECT RAISE(ABORT, '已凍結的決算報表快照不可修改'); END"),
    ("gl_stmt_snapshots_no_delete",
     "CREATE TRIGGER gl_stmt_snapshots_no_delete BEFORE DELETE ON gl_statement_snapshots WHEN OLD.frozen = 1 "
     "BEGIN SELECT RAISE(ABORT, '已凍結的決算報表快照不可刪除'); END"),
)

TRIGGER_NAMES = tuple(n for n, _ in _TRIGGERS)


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
