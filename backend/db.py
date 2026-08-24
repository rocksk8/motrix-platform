"""DB connection factory, schema initialisation, and numbered migrations."""
import sqlite3
import os
import re
import json
import shutil
import time
import logging
import threading
import contextvars
from datetime import datetime, date

logger = logging.getLogger(__name__)

DB_PATH      = os.path.join(os.path.dirname(__file__), "motrix_erp.db")
DEMO_DB_PATH = os.path.join(os.path.dirname(__file__), "motrix_erp_demo.db")

# Anything that writes files to disk (not just SQL rows) must check
# is_demo_mode() and redirect into one of these instead of the real shared
# folders — reset_demo_db() wipes them on every demo login. Without this,
# demo-created files would leak permanently into real storage, and could even
# collide with real filenames (project photos keyed by project id, PDFs keyed
# by quote_no/slip_no — both restart from 1 in the freshly-reset demo DB).
DEMO_PROJECT_PHOTOS_DIR  = os.path.join(os.path.dirname(__file__), "..", "uploads", "_demo_projects")
DEMO_UPLOADS_DIR         = os.path.join(os.path.dirname(__file__), "..", "uploads", "_demo_uploads")
DEMO_PDF_ARCHIVE_DIR     = os.path.join(os.path.dirname(__file__), "_demo_pdf_archive")
DEMO_PAYSLIP_ARCHIVE_DIR = os.path.join(os.path.dirname(__file__), "_demo_payslip_archive")
DEMO_SHIPPING_PDF_ARCHIVE_DIR = os.path.join(os.path.dirname(__file__), "_demo_shipping_pdf_archive")
DEMO_CONTRACTOR_VOUCHER_PDF_ARCHIVE_DIR = os.path.join(
    os.path.dirname(__file__), "_demo_contractor_voucher_pdf_archive")
DEMO_INVOICE_VOUCHER_PDF_ARCHIVE_DIR = os.path.join(
    os.path.dirname(__file__), "_demo_invoice_voucher_pdf_archive")
DEMO_PAYMENT_REQUEST_PDF_ARCHIVE_DIR = os.path.join(
    os.path.dirname(__file__), "_demo_payment_request_pdf_archive")

# Increment this whenever a new _mNNN function is added to _MIGRATIONS.
# v32/v33 (switch_guide tables + specs_json column) were initially missing
# from this checkout — reconstructed 2026-08-01 by reverse-engineering the
# actual schema off a production DB backup (see _m032_switch_guide docstring).
# v45/v46 (contractor_payment_vouchers / invoice_vouchers) added 2026-08-20,
# written directly on production while the dev machine was unreachable — see
# MOTRIX-ERP-QUICK.md §12 2026-08-20 entry for the dev-machine backport plan.
# v47: invoice_vouchers.amount real column, added same day after a redesign
# (自訂金額/自訂品項+數量 replacing the old fixed-installment-only model).
# v48: divisions/departments org structure (處/部門), 2026-08-22.
# v49: divisions.manager_user_id (處級主管), 2026-08-22.
# v50: projects.department_id, 2026-08-22.
# v51: case_stages/case_stage_visits (caseRecord.stages 正規化第一階段：唯讀鏡像，
# 回填既有資料，尚未接進任何讀寫路徑), 2026-08-23.
# v53: payment_requests（請款單），2026-08-24——同一輪也把報價單／開票申請憑據／
# 出貨單三組獨立簽核設定統一成 system_settings key 'unified_approval_flow'
# （見 routers/system.py），不是 schema 變動、不需要獨立 migration。
# v54: 報價單回簽欄位（新概念，比照 shipping_notes）＋三種單據（報價單/出貨單/
# 開票申請憑據）補上附件上傳欄位，2026-08-24 同一輪。
CURRENT_VERSION = 54

# Set True (per-request, via ContextVar — safe across FastAPI's async/threadpool
# execution model) whenever the current request is authenticated as the 'demo'
# account, so get_db() transparently redirects ALL queries — including the
# session/user lookups in _require_user()/_audit() — to the isolated demo DB.
_demo_mode: contextvars.ContextVar = contextvars.ContextVar("motrix_demo_mode", default=False)

# Serialises the whole reset-demo-db-then-seed-session sequence in
# routers/auth.py's login handler. Without this, two demo logins arriving at
# nearly the same moment (double-click, two people demoing at once) both wipe
# and re-seed the SAME shared demo DB concurrently, colliding on the fresh
# 'demo' user INSERT (UNIQUE violation) or on VACUUM/DELETE (database locked).
demo_reset_lock = threading.Lock()


def set_demo_mode(flag: bool) -> None:
    _demo_mode.set(flag)


def is_demo_mode() -> bool:
    return _demo_mode.get()


def spawn_bg_thread(target, args=(), kwargs=None, daemon=True) -> threading.Thread:
    """threading.Thread(...).start() 的安全版本：一般 threading.Thread 起的新執行緒
    永遠拿到全新、空白的 contextvars context，導致裡面呼叫的 is_demo_mode()/get_db()
    誤判成正式環境（即使觸發的 request 其實是 demo session）。這裡用
    contextvars.copy_context() 把呼叫當下的 context（含 _demo_mode）原封不動帶進新執行緒。
    任何在路由 handler 內起的背景工作，只要目標函式最終會碰 get_db()/is_demo_mode()，
    一律要用這個取代直接呼叫 threading.Thread。"""
    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(target, *args), kwargs=kwargs or {}, daemon=daemon)
    t.start()
    return t


def _connect(path: str):
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        pass
    return conn


def get_db():
    return _connect(DEMO_DB_PATH if _demo_mode.get() else DB_PATH)


def get_demo_db():
    """Always connects to the demo DB regardless of the current context — used
    by the login/logout handlers to seed/clean up the demo session before the
    request-scoped demo-mode flag would otherwise apply."""
    return _connect(DEMO_DB_PATH)


def _wipe_dir(path: str) -> None:
    for attempt in range(3):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            break
        except Exception:
            if attempt == 2:
                logger.warning("reset_demo_db: failed to clear %s", path)
            else:
                time.sleep(0.2)
    os.makedirs(path, exist_ok=True)


def reset_demo_db() -> None:
    """Wipe every row from every table in the demo DB, then every demo-only
    file-storage directory, back to a fresh, empty state. Called on every
    'demo' account login so each client demo starts clean.

    Uses SQL DELETE (same connection, no filesystem deletion of the .db/-wal/
    -shm files) specifically to avoid Windows file-lock races — a fresh SQLite
    WAL file can be briefly held by antivirus/indexer scanning right after the
    server creates it, and os.remove() on a locked file raises PermissionError
    that isn't recoverable mid-login.
    """
    if os.path.exists(DEMO_DB_PATH):
        conn = _connect(DEMO_DB_PATH)
        try:
            tables = [r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()]
            conn.execute("PRAGMA foreign_keys=OFF")
            for t in tables:
                conn.execute(f"DELETE FROM {t}")
            conn.commit()
            conn.execute("VACUUM")
        finally:
            conn.close()
    init_db(DEMO_DB_PATH)
    for d in (DEMO_PROJECT_PHOTOS_DIR, DEMO_UPLOADS_DIR, DEMO_PDF_ARCHIVE_DIR, DEMO_PAYSLIP_ARCHIVE_DIR,
              DEMO_SHIPPING_PDF_ARCHIVE_DIR, DEMO_CONTRACTOR_VOUCHER_PDF_ARCHIVE_DIR,
              DEMO_INVOICE_VOUCHER_PDF_ARCHIVE_DIR, DEMO_PAYMENT_REQUEST_PDF_ARCHIVE_DIR):
        _wipe_dir(d)


# ── Schema init ───────────────────────────────────────────────────────────────

def init_db(path: str = None):
    conn = _connect(path or DB_PATH)
    # Base tables — new installs get all columns from the start.
    # Existing installs: CREATE TABLE IF NOT EXISTS is a no-op; missing columns
    # are added by _run_migrations() below.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_version (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            version    INTEGER NOT NULL DEFAULT 0,
            applied_at TEXT    NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS quotations (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_no          TEXT    UNIQUE NOT NULL,
            status            TEXT    NOT NULL DEFAULT '草稿',
            customer_name     TEXT,
            project_name      TEXT,
            total             REAL    DEFAULT 0,
            pretax            REAL    DEFAULT 0,
            direct_margin_pct REAL    DEFAULT 0,
            net_margin_pct    REAL    DEFAULT 0,
            sales_person      TEXT,
            quote_date        TEXT,
            valid_days        INTEGER DEFAULT 30,
            data_json         TEXT    NOT NULL DEFAULT '{}',
            created_at        TEXT,
            updated_at        TEXT,
            created_by        TEXT,
            export_count      INTEGER DEFAULT 0,
            export_log        TEXT    DEFAULT '[]',
            deal_tag          TEXT    DEFAULT '',
            settle_status     TEXT    DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS quote_seq (
            month TEXT PRIMARY KEY,
            seq   INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS users (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            username             TEXT    UNIQUE NOT NULL,
            password_hash        TEXT    NOT NULL,
            display_name         TEXT    NOT NULL DEFAULT '',
            role                 TEXT    NOT NULL DEFAULT 'viewer',
            email                TEXT    DEFAULT '',
            phone                TEXT    DEFAULT '',
            modules              TEXT    DEFAULT '[]',
            active               INTEGER NOT NULL DEFAULT 1,
            created_at           TEXT    NOT NULL,
            unlock_password_hash TEXT    DEFAULT '',
            must_change_password INTEGER NOT NULL DEFAULT 0,
            notification_muted   TEXT    DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT    PRIMARY KEY,
            user_id    INTEGER NOT NULL,
            username   TEXT    NOT NULL,
            created_at TEXT    NOT NULL,
            expires_at TEXT
        );

        CREATE TABLE IF NOT EXISTS customers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            tax_id     TEXT    DEFAULT '',
            phone      TEXT    DEFAULT '',
            data_json  TEXT    NOT NULL DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS suppliers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            tax_id     TEXT    DEFAULT '',
            phone      TEXT    DEFAULT '',
            data_json  TEXT    NOT NULL DEFAULT '{}',
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS parts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            part_no    TEXT    UNIQUE NOT NULL,
            name       TEXT    NOT NULL DEFAULT '',
            brand      TEXT    DEFAULT '',
            unit       TEXT    DEFAULT '台',
            cost       REAL    DEFAULT 0,
            list_price REAL    DEFAULT 0,
            category   TEXT    DEFAULT '',
            note       TEXT    DEFAULT '',
            active     INTEGER NOT NULL DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            at           TEXT    NOT NULL,
            user_id      INTEGER,
            username     TEXT    DEFAULT '',
            display_name TEXT    DEFAULT '',
            action       TEXT    NOT NULL,
            target_type  TEXT    DEFAULT '',
            target_id    TEXT    DEFAULT '',
            target_label TEXT    DEFAULT '',
            detail       TEXT    DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS system_settings (
            key        TEXT PRIMARY KEY,
            value_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT    NOT NULL,
            type       TEXT    NOT NULL DEFAULT 'info',
            ref_id     TEXT    DEFAULT '',
            ref_label  TEXT    DEFAULT '',
            message    TEXT    NOT NULL DEFAULT '',
            is_read    INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            code              TEXT    UNIQUE NOT NULL DEFAULT '',
            name              TEXT    NOT NULL,
            status            TEXT    NOT NULL DEFAULT '規劃中',
            description       TEXT    DEFAULT '',
            linked_cases      TEXT    DEFAULT '[]',
            created_at        TEXT    NOT NULL,
            created_by        TEXT    DEFAULT '',
            data_json         TEXT    NOT NULL DEFAULT '{}',
            assigned_user_ids TEXT    DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS project_logs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id     INTEGER NOT NULL,
            log_date       TEXT    NOT NULL,
            work_content   TEXT    DEFAULT '',
            attendees      TEXT    DEFAULT '[]',
            action_items   TEXT    DEFAULT '[]',
            materials_used TEXT    DEFAULT '[]',
            photos         TEXT    DEFAULT '[]',
            log_status     TEXT    NOT NULL DEFAULT 'draft',
            created_at     TEXT    NOT NULL,
            created_by     TEXT    DEFAULT '',
            updated_at     TEXT    DEFAULT '',
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS project_stages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL,
            label       TEXT    NOT NULL DEFAULT '',
            sort_order  INTEGER NOT NULL DEFAULT 0,
            done        INTEGER NOT NULL DEFAULT 0,
            done_at     TEXT    NOT NULL DEFAULT '',
            start_date  TEXT    NOT NULL DEFAULT '',
            due_date    TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );
        CREATE INDEX IF NOT EXISTS idx_project_stages_project_id ON project_stages(project_id);

        CREATE TABLE IF NOT EXISTS work_logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date   TEXT    NOT NULL,
            user_id    INTEGER NOT NULL,
            content    TEXT    NOT NULL DEFAULT '',
            hours      REAL    NOT NULL DEFAULT 8.0,
            created_at TEXT    NOT NULL,
            created_by INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS contractors (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT    NOT NULL,
            id_number           TEXT    DEFAULT '',
            nationality         TEXT    DEFAULT '本國籍',
            has_union_insurance INTEGER NOT NULL DEFAULT 0,
            phone               TEXT    DEFAULT '',
            email               TEXT    DEFAULT '',
            address             TEXT    DEFAULT '',
            line_id             TEXT    DEFAULT '',
            bank_code           TEXT    DEFAULT '',
            bank_name           TEXT    DEFAULT '',
            bank_branch         TEXT    DEFAULT '',
            bank_account_name   TEXT    DEFAULT '',
            bank_account_number TEXT    DEFAULT '',
            notes               TEXT    DEFAULT '',
            active              INTEGER NOT NULL DEFAULT 1,
            created_at          TEXT,
            updated_at          TEXT,
            id_card_image       TEXT    DEFAULT '',
            id_card_image_back  TEXT    DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS payslips (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            slip_no           TEXT    UNIQUE NOT NULL,
            contractor_id     INTEGER,
            contractor_name   TEXT    DEFAULT '',
            income_type       TEXT    NOT NULL DEFAULT '9A',
            gross_amount      REAL    NOT NULL DEFAULT 0,
            tax_withheld      REAL    NOT NULL DEFAULT 0,
            nhi_supplement    REAL    NOT NULL DEFAULT 0,
            net_amount        REAL    NOT NULL DEFAULT 0,
            payment_method    TEXT    DEFAULT '匯款',
            slip_date         TEXT    DEFAULT '',
            status            TEXT    NOT NULL DEFAULT '草稿',
            tax_rules_version TEXT    DEFAULT '2026',
            export_count      INTEGER DEFAULT 0,
            export_log        TEXT    DEFAULT '[]',
            data_json         TEXT    NOT NULL DEFAULT '{}',
            created_by        TEXT    DEFAULT '',
            created_at        TEXT,
            updated_at        TEXT,
            FOREIGN KEY (contractor_id) REFERENCES contractors(id)
        );

        CREATE TABLE IF NOT EXISTS payslip_seq (
            month TEXT PRIMARY KEY,
            seq   INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS vendor_contractors (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL,
            tax_id       TEXT    DEFAULT '',
            contact_name TEXT    DEFAULT '',
            phone        TEXT    DEFAULT '',
            email        TEXT    DEFAULT '',
            address      TEXT    DEFAULT '',
            data_json    TEXT    NOT NULL DEFAULT '{}',
            active       INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT,
            updated_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS contractor_dispatches (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_no      TEXT    NOT NULL,
            vendor_id     INTEGER,
            dispatch_date TEXT    DEFAULT '',
            scope         TEXT    DEFAULT '',
            items_json    TEXT    DEFAULT '[]',
            total_amount  REAL    DEFAULT 0,
            status        TEXT    DEFAULT 'draft',
            notes         TEXT    DEFAULT '',
            invoice_no    TEXT    DEFAULT '',
            created_by    TEXT    DEFAULT '',
            created_at    TEXT,
            updated_at    TEXT,
            FOREIGN KEY (vendor_id) REFERENCES vendor_contractors(id)
        );
        CREATE INDEX IF NOT EXISTS idx_dispatches_quote_no
            ON contractor_dispatches(quote_no);
        CREATE INDEX IF NOT EXISTS idx_dispatches_vendor
            ON contractor_dispatches(vendor_id);

        CREATE TABLE IF NOT EXISTS daily_tasks (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            task_date           TEXT    NOT NULL,
            title               TEXT    NOT NULL DEFAULT '',
            description         TEXT    DEFAULT '',
            category            TEXT    DEFAULT '',
            priority            TEXT    NOT NULL DEFAULT '一般',
            assigned_to         TEXT    NOT NULL DEFAULT '[]',
            created_by          TEXT    NOT NULL DEFAULT '',
            created_at          TEXT    NOT NULL DEFAULT '',
            updated_at          TEXT    NOT NULL DEFAULT '',
            is_deleted          INTEGER NOT NULL DEFAULT 0,
            recurrence_type     TEXT    NOT NULL DEFAULT 'once',
            recurrence_days     TEXT    NOT NULL DEFAULT '[]',
            recurrence_end_date TEXT    NOT NULL DEFAULT '',
            supervisors         TEXT    NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS daily_task_completions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id         INTEGER NOT NULL REFERENCES daily_tasks(id),
            username        TEXT    NOT NULL,
            occurrence_date TEXT    NOT NULL DEFAULT '',
            completed       INTEGER NOT NULL DEFAULT 0,
            report          TEXT    DEFAULT '',
            completed_at    TEXT    DEFAULT '',
            UNIQUE(task_id, occurrence_date, username)
        );

        CREATE TABLE IF NOT EXISTS module_versions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            module     TEXT    NOT NULL,
            version    TEXT    NOT NULL DEFAULT '',
            updated_at TEXT    NOT NULL,
            content    TEXT    NOT NULL DEFAULT '',
            updated_by TEXT    NOT NULL DEFAULT '',
            UNIQUE(module, version)
        );
        CREATE INDEX IF NOT EXISTS idx_mv_module
            ON module_versions(module, updated_at);
    """)
    _run_migrations(conn)
    _seed_setting(conn, "edge_path", "")
    _seed_setting(conn, "company_profile", {
        "name": "允碩整合集創股份有限公司",
        "tax_id": "60575481",
        "contact_info": "Tel: 04-3610-6566｜info@miactw.com"
    })
    _seed_setting(conn, "tax_rules", {
        "version": "2026",
        "resident": {
            "50": {"tax_rate": 0.05, "tax_threshold": 90501},
            "9A": {"tax_rate": 0.10, "tax_threshold": 20010},
            "9B": {"tax_rate": 0.10, "tax_threshold": 20010}
        },
        "non_resident": {
            "50": {"tax_rate": 0.18, "tax_threshold": 0, "low_salary_rate": 0.06},
            "9A": {"tax_rate": 0.20, "tax_threshold": 0},
            "9B": {"tax_rate": 0.20, "tax_threshold": 5001}
        },
        "nhi": {
            "rate": 0.0211,
            "max_single_payment": 10000000,
            "thresholds": {"50": 29500, "9A": 20000, "9B": 20000}
        },
        "minimum_wage": {"monthly": 29500}
    })
    conn.commit()
    conn.close()


# ── Migration engine ──────────────────────────────────────────────────────────

def _col_exists(conn, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == col for r in rows)


def _col_notnull(conn, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == col and r["notnull"] for r in rows)


def _get_version(conn) -> int:
    try:
        row = conn.execute("SELECT version FROM schema_version WHERE id=1").fetchone()
        return row["version"] if row else 0
    except Exception:
        return 0


def _set_version(conn, version: int) -> None:
    conn.execute(
        "INSERT INTO schema_version (id, version, applied_at) VALUES (1, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET version=excluded.version, applied_at=excluded.applied_at",
        (version, datetime.now().isoformat()),
    )
    conn.commit()


def _run_migrations(conn) -> None:
    current = _get_version(conn)
    if current >= CURRENT_VERSION:
        return
    for i, fn in enumerate(_MIGRATIONS, start=1):
        if i <= current:
            continue
        logger.info("DB migration %d/%d: %s", i, CURRENT_VERSION, fn.__name__)
        fn(conn)
        _set_version(conn, i)
    logger.info("DB schema up to date (version %d)", CURRENT_VERSION)


# ── Individual migrations ─────────────────────────────────────────────────────
# Each function must be idempotent: check before altering, use IF NOT EXISTS.

def _m001_export_columns(conn):
    if not _col_exists(conn, "quotations", "export_count"):
        conn.execute("ALTER TABLE quotations ADD COLUMN export_count INTEGER DEFAULT 0")
    if not _col_exists(conn, "quotations", "export_log"):
        conn.execute("ALTER TABLE quotations ADD COLUMN export_log TEXT DEFAULT '[]'")
    conn.commit()


def _m002_sessions_expires(conn):
    if not _col_exists(conn, "sessions", "expires_at"):
        conn.execute("ALTER TABLE sessions ADD COLUMN expires_at TEXT")
    conn.commit()


def _m003_contractor_images(conn):
    if not _col_exists(conn, "contractors", "id_card_image"):
        conn.execute("ALTER TABLE contractors ADD COLUMN id_card_image TEXT DEFAULT ''")
    if not _col_exists(conn, "contractors", "id_card_image_back"):
        conn.execute("ALTER TABLE contractors ADD COLUMN id_card_image_back TEXT DEFAULT ''")
    conn.commit()


def _m004_unlock_password(conn):
    if not _col_exists(conn, "users", "unlock_password_hash"):
        conn.execute("ALTER TABLE users ADD COLUMN unlock_password_hash TEXT DEFAULT ''")
    conn.commit()


def _m005_must_change_password(conn):
    if not _col_exists(conn, "users", "must_change_password"):
        conn.execute(
            "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
        )
    conn.commit()


def _m006_hot_columns(conn):
    if not _col_exists(conn, "quotations", "deal_tag"):
        conn.execute("ALTER TABLE quotations ADD COLUMN deal_tag TEXT DEFAULT ''")
    if not _col_exists(conn, "quotations", "settle_status"):
        conn.execute("ALTER TABLE quotations ADD COLUMN settle_status TEXT DEFAULT ''")
    # Backfill existing rows that were saved before hot columns existed.
    try:
        conn.execute("""
            UPDATE quotations SET
              deal_tag     = COALESCE(json_extract(data_json, '$.dealTag'), ''),
              settle_status = COALESCE(json_extract(data_json, '$.settlement.status'), '')
            WHERE deal_tag = '' AND settle_status = ''
        """)
    except Exception as e:
        logger.warning("m006 backfill failed: %s", e)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_quotations_deal_tag ON quotations(deal_tag)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_quotations_settle_status ON quotations(settle_status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_quotations_sales_person ON quotations(sales_person)"
    )
    conn.commit()


def _m007_fix_legacy_display_names(conn):
    """One-time: normalise display_name values that were set to username+role suffix."""
    role_labels = {
        "superadmin": "超級管理員",
        "admin": "管理員",
        "sales": "業務",
        "viewer": "檢視者",
    }
    rows = conn.execute("SELECT id, username, display_name, role FROM users").fetchall()
    changed = False
    for r in rows:
        legacy = r["username"] + role_labels.get(r["role"], "")
        if r["display_name"] in (legacy, r["username"], r["username"].lower()):
            conn.execute(
                "UPDATE users SET display_name=? WHERE id=?",
                (r["username"].capitalize(), r["id"]),
            )
            changed = True
    if changed:
        conn.commit()


def _m008_fix_legacy_owner_names(conn):
    """One-time: replace historical jeff display-name variants with correct name."""
    old_names = ("jeff", "Jeff", "Jeff 管理員", "jeff管理員", "jeff超級管理員", "Jeff超級管理員")
    correct = "黃玉龍"
    rows = conn.execute("SELECT id, data_json FROM customers").fetchall()
    for r in rows:
        try:
            d = json.loads(r["data_json"] or "{}")
            if d.get("ownerName") in old_names:
                d["ownerName"] = correct
                conn.execute(
                    "UPDATE customers SET data_json=? WHERE id=?",
                    (json.dumps(d, ensure_ascii=False), r["id"]),
                )
        except Exception:
            pass
    conn.execute(
        "UPDATE quotations SET sales_person=? WHERE sales_person IN ({})".format(
            ",".join("?" * len(old_names))
        ),
        [correct] + list(old_names),
    )
    # Also fix jeff display_name if it's still a legacy variant
    conn.execute(
        "UPDATE users SET display_name=? WHERE username='jeff' AND display_name IN ({})".format(
            ",".join("?" * len(old_names))
        ),
        [correct] + list(old_names),
    )
    conn.execute(
        "UPDATE users SET email='jeff@miactw.com' WHERE username='jeff' AND (email='' OR email IS NULL)"
    )
    conn.commit()


def _m009_migrate_legacy_visits(conn):
    """One-time: convert old customer visit format (visitDate/visitPeople) to new schema."""
    rows = conn.execute("SELECT id, data_json FROM customers").fetchall()
    for r in rows:
        try:
            data = json.loads(r["data_json"] or "{}")
        except Exception:
            continue
        visits = data.get("visits") or []
        new_visits = []
        changed = False
        for i, v in enumerate(visits):
            if v.get("attendees") is not None:
                new_visits.append(v)
                continue
            nv = dict(v)
            if "date" not in nv:
                nv["date"] = nv.pop("visitDate", "") or ""
            if "type" not in nv:
                nv["type"] = "現場拜訪"
            if "id" not in nv:
                nv["id"] = int(datetime.now().timestamp() * 1000) + i
            people_str = nv.pop("visitPeople", "") or ""
            nv["attendees"] = [
                p.strip() for p in re.split(r"[、,，]", people_str) if p.strip()
            ]
            new_visits.append(nv)
            changed = True
        if changed:
            data["visits"] = new_visits
            conn.execute(
                "UPDATE customers SET data_json=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False), r["id"]),
            )
    conn.commit()


def _m010_sales_person_id(conn):
    """Add sales_person_id FK column to quotations; best-effort backfill from display_name."""
    if not _col_exists(conn, "quotations", "sales_person_id"):
        conn.execute(
            "ALTER TABLE quotations ADD COLUMN sales_person_id INTEGER REFERENCES users(id)"
        )
    try:
        conn.execute("""
            UPDATE quotations SET sales_person_id = (
                SELECT id FROM users
                WHERE display_name = quotations.sales_person AND active = 1
                LIMIT 1
            )
            WHERE sales_person_id IS NULL AND sales_person != '' AND sales_person IS NOT NULL
        """)
    except Exception as e:
        logger.warning("m010 backfill failed: %s", e)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_quotations_sales_person_id ON quotations(sales_person_id)"
    )
    conn.commit()


def _m011_login_rate_limit(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_rate_limit (
            ip           TEXT PRIMARY KEY,
            locked_until TEXT NOT NULL
        )
    """)
    conn.commit()


def _m012_project_assigned_users(conn):
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN assigned_user_ids TEXT DEFAULT '[]'")
    except Exception:
        pass
    conn.commit()


def _m013_daily_tasks(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_tasks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            task_date    TEXT    NOT NULL,
            title        TEXT    NOT NULL DEFAULT '',
            description  TEXT    DEFAULT '',
            category     TEXT    DEFAULT '',
            priority     TEXT    NOT NULL DEFAULT '一般',
            assigned_to  TEXT    NOT NULL DEFAULT '[]',
            created_by   TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL DEFAULT '',
            updated_at   TEXT    NOT NULL DEFAULT '',
            is_deleted   INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_task_completions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id      INTEGER NOT NULL REFERENCES daily_tasks(id),
            username     TEXT    NOT NULL,
            completed    INTEGER NOT NULL DEFAULT 0,
            report       TEXT    DEFAULT '',
            completed_at TEXT    DEFAULT '',
            UNIQUE(task_id, username)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_daily_tasks_date ON daily_tasks(task_date)"
    )
    conn.commit()


def _m014_weekly_recurrence(conn):
    """Add recurrence columns to daily_tasks; rebuild daily_task_completions with occurrence_date."""
    for col_def in [
        "recurrence_type     TEXT NOT NULL DEFAULT 'once'",
        "recurrence_days     TEXT NOT NULL DEFAULT '[]'",
        "recurrence_end_date TEXT NOT NULL DEFAULT ''",
    ]:
        try:
            conn.execute(f"ALTER TABLE daily_tasks ADD COLUMN {col_def}")
        except Exception:
            pass
    # Rebuild daily_task_completions with new UNIQUE(task_id, occurrence_date, username)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS _dtc_v14 (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id         INTEGER NOT NULL REFERENCES daily_tasks(id),
            username        TEXT    NOT NULL,
            occurrence_date TEXT    NOT NULL DEFAULT '',
            completed       INTEGER NOT NULL DEFAULT 0,
            report          TEXT    DEFAULT '',
            completed_at    TEXT    DEFAULT '',
            UNIQUE(task_id, occurrence_date, username)
        );
        INSERT OR IGNORE INTO _dtc_v14
            (id, task_id, username, occurrence_date, completed, report, completed_at)
        SELECT c.id, c.task_id, c.username,
               COALESCE(t.task_date, ''),
               c.completed, c.report, c.completed_at
        FROM daily_task_completions c
        LEFT JOIN daily_tasks t ON t.id = c.task_id;
        DROP TABLE daily_task_completions;
        ALTER TABLE _dtc_v14 RENAME TO daily_task_completions;
        CREATE INDEX IF NOT EXISTS idx_daily_tasks_date
            ON daily_tasks(task_date);
    """)
    conn.commit()


def _m015_daily_task_password(conn):
    """Add daily_task_pw_hash to users for daily-task admin-view unlock."""
    try:
        conn.execute("ALTER TABLE users ADD COLUMN daily_task_pw_hash TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass
    conn.commit()


def _m016_daily_task_supervisors(conn):
    """Add supervisors column to daily_tasks for per-task notification targets."""
    try:
        conn.execute("ALTER TABLE daily_tasks ADD COLUMN supervisors TEXT NOT NULL DEFAULT '[]'")
    except Exception:
        pass
    conn.commit()


def _m017_session_last_active(conn):
    """Add last_active column to sessions for idle-timeout enforcement."""
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN last_active TEXT")
    except Exception:
        pass
    conn.commit()


def _m019_daily_task_case_no(conn):
    """Add case_no to daily_tasks — loose FK to quotations.quote_no."""
    try:
        conn.execute("ALTER TABLE daily_tasks ADD COLUMN case_no TEXT NOT NULL DEFAULT ''")
        conn.commit()
    except Exception:
        pass


def _m022_vendor_contractors(conn):
    """Create vendor_contractors and contractor_dispatches tables."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vendor_contractors (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL,
            tax_id       TEXT    DEFAULT '',
            contact_name TEXT    DEFAULT '',
            phone        TEXT    DEFAULT '',
            email        TEXT    DEFAULT '',
            address      TEXT    DEFAULT '',
            data_json    TEXT    NOT NULL DEFAULT '{}',
            active       INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT,
            updated_at   TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contractor_dispatches (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_no      TEXT    NOT NULL,
            vendor_id     INTEGER NOT NULL,
            dispatch_date TEXT    DEFAULT '',
            scope         TEXT    DEFAULT '',
            items_json    TEXT    DEFAULT '[]',
            total_amount  REAL    DEFAULT 0,
            status        TEXT    DEFAULT 'draft',
            notes         TEXT    DEFAULT '',
            created_by    TEXT    DEFAULT '',
            created_at    TEXT,
            updated_at    TEXT,
            FOREIGN KEY (vendor_id) REFERENCES vendor_contractors(id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dispatches_quote_no ON contractor_dispatches(quote_no)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dispatches_vendor ON contractor_dispatches(vendor_id)"
    )
    conn.commit()


def _m023_dispatch_tax_rate(conn):
    """Add tax_rate column to contractor_dispatches (default 5%)."""
    try:
        conn.execute(
            "ALTER TABLE contractor_dispatches ADD COLUMN tax_rate REAL DEFAULT 0.05"
        )
        conn.commit()
    except Exception:
        pass


def _m024_entity_codes(conn):
    """Add sequential code field (C/S/V-YYYYMM-NNN) to customers, suppliers, vendor_contractors."""
    for table in ('customers', 'suppliers', 'vendor_contractors'):
        if not _col_exists(conn, table, 'code'):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN code TEXT NOT NULL DEFAULT ''")

    for table, prefix in [('customers', 'C'), ('suppliers', 'S'), ('vendor_contractors', 'V')]:
        rows = conn.execute(
            f"SELECT id, created_at FROM {table} WHERE code='' ORDER BY created_at ASC, id ASC"
        ).fetchall()
        counters: dict = {}
        for row in rows:
            ca = row['created_at'] or ''
            if len(ca) >= 7 and ca[4] == '-':
                month = ca[:4] + ca[5:7]
            else:
                month = datetime.now().strftime('%Y%m')
            counters[month] = counters.get(month, 0) + 1
            code = f"{prefix}-{month}-{counters[month]:03d}"
            conn.execute(f"UPDATE {table} SET code=? WHERE id=?", (code, row['id']))

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_code "
        "ON customers(code) WHERE code != ''"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_code "
        "ON suppliers(code) WHERE code != ''"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_vendor_contractors_code "
        "ON vendor_contractors(code) WHERE code != ''"
    )
    conn.commit()


def _m021_completion_edit_count(conn):
    """Add report_edit_count to daily_task_completions — incremented on each report edit."""
    try:
        conn.execute(
            "ALTER TABLE daily_task_completions ADD COLUMN report_edit_count INTEGER NOT NULL DEFAULT 0"
        )
        conn.commit()
    except Exception:
        pass


def _m020_daily_task_edit_log(conn):
    """Create daily_task_edit_log for tracking field-level changes on task edits."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_task_edit_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id      INTEGER NOT NULL,
            changed_by   TEXT    NOT NULL,
            changed_at   TEXT    NOT NULL,
            changes_json TEXT    NOT NULL DEFAULT '[]'
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dtel_task ON daily_task_edit_log(task_id, changed_at)"
    )
    conn.commit()


def _m018_module_versions(conn):
    """Create module_versions table for per-module changelog tracking."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS module_versions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            module     TEXT    NOT NULL,
            version    TEXT    NOT NULL DEFAULT '',
            updated_at TEXT    NOT NULL,
            content    TEXT    NOT NULL DEFAULT '',
            updated_by TEXT    NOT NULL DEFAULT ''
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mv_module ON module_versions(module, updated_at)"
    )
    conn.commit()


def _m027_dev_crm(conn):
    """Create dev_cases and dev_logs tables for pre-quotation CRM module."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dev_cases (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            case_name          TEXT    NOT NULL DEFAULT '',
            customer_name      TEXT    NOT NULL DEFAULT '',
            customer_id        INTEGER REFERENCES customers(id) ON DELETE SET NULL,
            status             TEXT    NOT NULL DEFAULT '洽談中',
            sales_persons      TEXT    NOT NULL DEFAULT '[]',
            planners           TEXT    NOT NULL DEFAULT '[]',
            converted_quote_no TEXT    NOT NULL DEFAULT '',
            created_by         INTEGER REFERENCES users(id),
            created_at         TEXT    NOT NULL,
            updated_at         TEXT    NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dev_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id         INTEGER NOT NULL REFERENCES dev_cases(id) ON DELETE CASCADE,
            log_date        TEXT    NOT NULL,
            log_by          INTEGER NOT NULL REFERENCES users(id),
            channel         TEXT    NOT NULL DEFAULT '',
            content         TEXT    NOT NULL DEFAULT '',
            next_action     TEXT    NOT NULL DEFAULT '',
            status_snapshot TEXT    NOT NULL DEFAULT '',
            needs_approval  INTEGER NOT NULL DEFAULT 0,
            approved_by     INTEGER REFERENCES users(id),
            approved_at     TEXT    NOT NULL DEFAULT '',
            created_by      INTEGER REFERENCES users(id),
            created_at      TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dev_cases_status ON dev_cases(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dev_logs_case ON dev_logs(case_id, log_date)")
    conn.commit()


def _m026_case_updates_work_log_case(conn):
    """Add case_updates table for case activity feed; add case_no to work_logs."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_updates (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_no   TEXT    NOT NULL,
            author     TEXT    NOT NULL,
            content    TEXT    NOT NULL,
            type       TEXT    NOT NULL DEFAULT 'comment',
            created_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_case_updates_quote_no "
        "ON case_updates(quote_no, created_at)"
    )
    if not _col_exists(conn, "work_logs", "case_no"):
        conn.execute("ALTER TABLE work_logs ADD COLUMN case_no TEXT NOT NULL DEFAULT ''")
    conn.commit()


def _m025_dispatch_acceptance(conn):
    """Add accepted_at / accepted_by to contractor_dispatches for acceptance flow node."""
    for col, defn in [("accepted_at", "TEXT NOT NULL DEFAULT ''"),
                      ("accepted_by", "TEXT NOT NULL DEFAULT ''")]:
        if not _col_exists(conn, "contractor_dispatches", col):
            conn.execute(f"ALTER TABLE contractor_dispatches ADD COLUMN {col} {defn}")
    conn.commit()


def _m029_contractor_passbook(conn):
    """Add bank_passbook_image column to contractors."""
    if not _col_exists(conn, "contractors", "bank_passbook_image"):
        conn.execute("ALTER TABLE contractors ADD COLUMN bank_passbook_image TEXT DEFAULT ''")
    conn.commit()


def _m028_dev_cases_soft_delete(conn):
    """Add soft-delete + pending-delete columns to dev_cases."""
    for col, defn in [
        ("is_deleted",            "INTEGER NOT NULL DEFAULT 0"),
        ("deleted_at",            "TEXT    NOT NULL DEFAULT ''"),
        ("deleted_by",            "TEXT    NOT NULL DEFAULT ''"),
        ("deleted_snapshot",      "TEXT    NOT NULL DEFAULT ''"),
        ("pending_delete",        "INTEGER NOT NULL DEFAULT 0"),
        ("delete_requested_by",   "TEXT    NOT NULL DEFAULT ''"),
        ("delete_requested_at",   "TEXT    NOT NULL DEFAULT ''"),
        ("delete_reason",         "TEXT    NOT NULL DEFAULT ''"),
    ]:
        if not _col_exists(conn, "dev_cases", col):
            conn.execute(f"ALTER TABLE dev_cases ADD COLUMN {col} {defn}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dev_cases_is_deleted ON dev_cases(is_deleted)"
    )
    conn.commit()


def _m042_dev_cases_relink_review(conn):
    """Add pending-relink review columns to dev_cases — changing or clearing an
    already-established converted_quote_no now goes through admin+ request →
    superadmin approve, same shape as _m028_dev_cases_soft_delete's delete flow.
    An empty relink_target_quote_no is a valid, meaningful value (= unlink)."""
    for col, defn in [
        ("pending_relink",         "INTEGER NOT NULL DEFAULT 0"),
        ("relink_requested_by",    "TEXT    NOT NULL DEFAULT ''"),
        ("relink_requested_at",    "TEXT    NOT NULL DEFAULT ''"),
        ("relink_reason",          "TEXT    NOT NULL DEFAULT ''"),
        ("relink_target_quote_no", "TEXT    NOT NULL DEFAULT ''"),
    ]:
        if not _col_exists(conn, "dev_cases", col):
            conn.execute(f"ALTER TABLE dev_cases ADD COLUMN {col} {defn}")
    conn.commit()


def _m043_notification_prefs(conn):
    """Per-user email notification opt-out list (see helpers/notification_prefs.py).
    DEFAULT '[]' means "nothing muted" — SQLite backfills existing rows with the
    column default on ALTER TABLE ADD COLUMN, so no separate UPDATE is needed and
    no existing user's email behaviour changes until they explicitly mute something."""
    if not _col_exists(conn, "users", "notification_muted"):
        conn.execute("ALTER TABLE users ADD COLUMN notification_muted TEXT DEFAULT '[]'")
    conn.commit()


def _m044_dispatch_invoice_no(conn):
    """承攬商派發新增發票號碼欄位，比照報價單收款品項 invoiceNo 的自由文字慣例。"""
    if not _col_exists(conn, "contractor_dispatches", "invoice_no"):
        conn.execute("ALTER TABLE contractor_dispatches ADD COLUMN invoice_no TEXT DEFAULT ''")
    conn.commit()


def _m045_contractor_payment_vouchers(conn):
    """Create contractor_payment_vouchers（承攬商匯款申請）：一張申請對應一筆已完工的
    承攬商派發（dispatch_id UNIQUE，強制 1:1），供財務端核准匯款用。獨立簽核流程
    （system_settings key 'contractor_voucher_approval_flow'），機制比照出貨單但
    「已核准」之後額外多一個「已匯款」財務結案標記（is_paid，獨立於 status，比照
    出貨單「已核准」跟「已回簽」是兩個獨立狀態的做法）。見 routers/contractor_vouchers.py。

    承攬商/銀行帳戶/金額/品項於建立當下寫入 snapshot_json 凍結快照——日後若
    vendor_contractors 資料異動（改銀行帳戶、改名稱等）不會回頭改到已產生的申請，
    這點與出貨單品項快照、成本精算 finalized 快照是同一個「已定案文件不隨來源異動」
    的慣例（見 §5.5 settlement 文件）。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contractor_payment_vouchers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            voucher_no    TEXT    UNIQUE NOT NULL,
            dispatch_id   INTEGER UNIQUE NOT NULL REFERENCES contractor_dispatches(id),
            quote_no      TEXT    NOT NULL,
            vendor_id     INTEGER REFERENCES vendor_contractors(id),
            status        TEXT    NOT NULL DEFAULT '草稿',
            snapshot_json TEXT    NOT NULL DEFAULT '{}',
            data_json     TEXT    NOT NULL DEFAULT '{}',
            is_paid       INTEGER NOT NULL DEFAULT 0,
            paid_by       TEXT    DEFAULT '',
            paid_at       TEXT    DEFAULT '',
            paid_log      TEXT    NOT NULL DEFAULT '[]',
            export_count  INTEGER DEFAULT 0,
            export_log    TEXT    DEFAULT '[]',
            created_by    TEXT    DEFAULT '',
            created_at    TEXT,
            updated_at    TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cpv_quote_no ON contractor_payment_vouchers(quote_no)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cpv_status ON contractor_payment_vouchers(status)"
    )
    conn.commit()


def _m046_invoice_vouchers(conn):
    """Create invoice_vouchers（開票申請憑據）：案件款項明細（quotations.data_json.
    caseRecord.payment.items[]，本身不是獨立資料表，見 helpers/quotations.py
    payment_item_amounts()）匯出給財務單位申請開立發票用的獨立單據。scope='single'
    對應單一 payment_idx；scope='all' 彙整整份收款排程，payment_idx 為 NULL。

    不要求 received=true 才能建立（2026-08-20 起）——部分案件是先開發票才能收款，
    未收款項目也允許申請，snapshot 內保留 received 旗標供 PDF 標示實際收款狀況。
    獨立簽核流程（system_settings key 'invoice_voucher_approval_flow'），
    狀態機比照出貨單（草稿→待審核→簽核中→已核准），核准即定稿，不像承攬商匯款
    申請多一個「已匯款」財務結案節點——開票申請憑據本身就是最終文件。見
    routers/invoice_vouchers.py。

    客戶/案件/款項明細於建立當下寫入 snapshot_json 凍結快照，理由同
    contractor_payment_vouchers：已送出財務的憑據不應該因為之後有人編輯報價單
    款項明細而回頭改變內容。

    2026-08-20 起 scope 語意已改為 'amount'（自訂金額）/'items'（自訂品項+數量），
    取代原本的 'single'/'all'（見 _m047_invoice_vouchers_amount 與
    routers/invoice_vouchers.py），payment_idx 欄位對新資料不再使用但保留不刪，
    SQLite 不方便中途拿掉欄位，舊資料也還讀得到。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invoice_vouchers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            voucher_no    TEXT    UNIQUE NOT NULL,
            quote_no      TEXT    NOT NULL,
            scope         TEXT    NOT NULL DEFAULT 'single',
            payment_idx   INTEGER,
            status        TEXT    NOT NULL DEFAULT '草稿',
            snapshot_json TEXT    NOT NULL DEFAULT '{}',
            data_json     TEXT    NOT NULL DEFAULT '{}',
            export_count  INTEGER DEFAULT 0,
            export_log    TEXT    DEFAULT '[]',
            created_by    TEXT    DEFAULT '',
            created_at    TEXT,
            updated_at    TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_iv_quote_no ON invoice_vouchers(quote_no)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_iv_status ON invoice_vouchers(status)"
    )
    conn.commit()


def _m047_invoice_vouchers_amount(conn):
    """新增 invoice_vouchers.amount 真實欄位（2026-08-20，使用者實測後重新設計）。

    背景：原本開票申請只能挑一個既有款項期別（scope='single'/'all'），使用者
    反映很多案件是「先開發票才能收款」，需要能自訂任意金額或自訂品項+數量來
    申請，且已申請過的金額/品項數量要能從剩餘可開票額度扣除，避免重複請款。

    這個 amount 欄位是「這張申請這次要開多少錢」的唯一權威數字（不論
    scope='amount' 自訂金額、還是 scope='items' 自訂品項時等於選取品項金額
    加總），獨立成真實 SQL 欄位是為了能直接用 SUM() 計算「這張報價單目前
    已申請多少、還剩多少可申請」，不必每次都把所有筆 snapshot_json 解析一遍。

    舊資料（scope='single'/'all' 建立的既有草稿）用當時存的 snapshot_json.items
    金額加總回填，讓它們一樣正確算進「已申請額度」，不會產生資料落差。"""
    if not _col_exists(conn, "invoice_vouchers", "amount"):
        conn.execute("ALTER TABLE invoice_vouchers ADD COLUMN amount REAL NOT NULL DEFAULT 0")
        for row in conn.execute("SELECT id, snapshot_json FROM invoice_vouchers").fetchall():
            try:
                snap = json.loads(row["snapshot_json"] or "{}")
                total = sum(float(it.get("amount", 0) or 0) for it in (snap.get("items") or []))
            except Exception:
                total = 0
            conn.execute("UPDATE invoice_vouchers SET amount=? WHERE id=?", (total, row["id"]))
    conn.commit()


def _m048_org_structure(conn):
    """新增處/部門組織架構（2026-08-22）。純組織分類用途，department 上的
    manager_user_id 先預留給未來「部門主管自動列入簽核」使用，這輪不接
    tiered_approval.py。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS divisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            division_id INTEGER NOT NULL REFERENCES divisions(id),
            name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            manager_user_id INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE(division_id, name)
        )
    """)
    if not _col_exists(conn, "users", "department_id"):
        conn.execute("ALTER TABLE users ADD COLUMN department_id INTEGER REFERENCES departments(id)")
    conn.commit()


def _m049_division_manager(conn):
    """新增 divisions.manager_user_id（處級主管，2026-08-22）。使用者回饋現有
    組織架構只有部門能設主管、處級沒有對應欄位，這裡補齊對稱性，一樣先預留
    給未來簽核路由使用，這輪不接 tiered_approval.py。"""
    if not _col_exists(conn, "divisions", "manager_user_id"):
        conn.execute("ALTER TABLE divisions ADD COLUMN manager_user_id INTEGER REFERENCES users(id)")
    conn.commit()


def _m050_project_department(conn):
    """新增 projects.department_id（2026-08-22）。案件/專案管理延伸建議的一部分——
    專案原本指派只到個人（assigned_user_ids），完全沒接組織架構；補上部門欄位讓
    專案可依部門篩選、逾期通知可升級給部門主管（比照報價單既有的 sales_person_id
    → department_id 查表模式）。"""
    if not _col_exists(conn, "projects", "department_id"):
        conn.execute("ALTER TABLE projects ADD COLUMN department_id INTEGER REFERENCES departments(id)")
    conn.commit()


def _m051_case_stages_normalize(conn):
    """caseRecord.stages 正規化第一階段（2026-08-23）：新增 case_stages/case_stage_visits
    唯讀鏡像表，回填既有 quotations.data_json.caseRecord.stages 資料。這輪刻意不接進
    任何現有讀寫路徑——update_case_record()／case-management.js／quotation-form.html／
    dashboard.py／daily_tasks.py／stage_board() 全部維持原樣讀寫 JSON；新表只是回填出
    來的鏡像，供下一輪 CRUD 端點與前端切換使用。dependsOn 陣列裡的舊 JSON id（
    Date.now() 基底，前端 addStage() 產生）在回填時 remap 成新的關聯式 id。
    assigned_to/depends_on 刻意維持 JSON text 欄位，不再往下正規化成 join table——
    這兩個陣列通常只有 1~3 個元素、永遠整組讀寫，沒有跨階段查詢需求。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_stages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_no    TEXT    NOT NULL,
            label       TEXT    NOT NULL DEFAULT '',
            sort_order  INTEGER NOT NULL DEFAULT 0,
            done        INTEGER NOT NULL DEFAULT 0,
            done_at     TEXT    NOT NULL DEFAULT '',
            start_date  TEXT    NOT NULL DEFAULT '',
            due_date    TEXT    NOT NULL DEFAULT '',
            assigned_to TEXT    NOT NULL DEFAULT '[]',
            depends_on  TEXT    NOT NULL DEFAULT '[]',
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_case_stages_quote_no ON case_stages(quote_no)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_stage_visits (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_id     INTEGER NOT NULL REFERENCES case_stages(id) ON DELETE CASCADE,
            visit_date   TEXT    NOT NULL DEFAULT '',
            visit_people INTEGER NOT NULL DEFAULT 0,
            note         TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_case_stage_visits_stage_id ON case_stage_visits(stage_id)")
    conn.commit()

    now = datetime.now().isoformat()
    rows = conn.execute("""
        SELECT quote_no, data_json FROM quotations
        WHERE json_extract(data_json, '$.caseRecord.stages') IS NOT NULL
    """).fetchall()

    for row in rows:
        try:
            data = json.loads(row["data_json"] or "{}")
        except Exception:
            continue
        stages = ((data.get("caseRecord") or {}).get("stages")) or []
        if not stages:
            continue

        id_map = {}
        inserted = []
        for idx, st in enumerate(stages):
            cur = conn.execute("""
                INSERT INTO case_stages
                    (quote_no, label, sort_order, done, done_at, start_date, due_date,
                     assigned_to, depends_on, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                row["quote_no"],
                st.get("label") or "",
                idx,
                1 if st.get("done") else 0,
                st.get("doneAt") or "",
                st.get("startDate") or "",
                st.get("dueDate") or "",
                json.dumps(st.get("assignedTo") or [], ensure_ascii=False),
                "[]",
                now, now,
            ))
            new_id = cur.lastrowid
            old_id = st.get("id")
            if old_id is not None:
                id_map[old_id] = new_id
            inserted.append((new_id, st))

        for new_id, st in inserted:
            remapped = [id_map[d] for d in (st.get("dependsOn") or []) if d in id_map]
            conn.execute("UPDATE case_stages SET depends_on=? WHERE id=?",
                         (json.dumps(remapped, ensure_ascii=False), new_id))
            for v in (st.get("visits") or []):
                conn.execute("""
                    INSERT INTO case_stage_visits (stage_id, visit_date, visit_people, note, created_at)
                    VALUES (?,?,?,?,?)
                """, (
                    new_id,
                    v.get("visitDate") or "",
                    int(v.get("visitPeople") or 0),
                    v.get("note") or "",
                    now,
                ))
    conn.commit()


def _m052_fix_stage_json_ids(conn):
    """caseRecord.stages 正規化收尾修正（2026-08-23，同日）：v51 的 backfill migration
    只寫進新的 case_stages 表，刻意沒有回頭修正 quotations.data_json.caseRecord.stages
    裡的舊 id——v51 上線當時前端還沒有任何地方會引用這些 id，這個設計在當下是安全、
    正確的。但同一天稍晚 3b 上線後，case-management.js 開始直接拿 data_json 裡的
    stage id 打 `PUT/DELETE .../stages/{id}` 等 granular 端點；只要一個案件從 v51
    backfill 之後、到 3b 上線這段期間**完全沒有**透過任何 granular 端點被存過一次，
    data_json 裡的 id 就還停留在 backfill 前的舊值，跟 case_stages 表的真實 id
    對不上，使用者一操作階段就會 404（正式機重現：13 個有 case_stages 資料的
    案件裡 12 個中獎，使用者回報「執行進度儲存失敗」）。

    這個 migration 把 case_stages（含 case_stage_visits）目前的內容，重新鏡射回
    每個受影響 quote_no 的 data_json.caseRecord.stages——邏輯照搬
    routers/quotations.py::_sync_stages_to_json()（db.py 不 import router 模組，
    手動照抄一份，保持邏輯一致）。只動 caseRecord.stages 這個欄位，caseRecord
    其他 key 與 quotations 其他欄位（含 updated_at）刻意維持原樣不動——這是
    後端資料一致性修正，不是使用者操作，不該讓任何人手上還開著的頁面因為
    updated_at 被動了而誤觸樂觀鎖 409。"""
    quote_nos = [r["quote_no"] for r in conn.execute(
        "SELECT DISTINCT quote_no FROM case_stages"
    ).fetchall()]
    for quote_no in quote_nos:
        row = conn.execute(
            "SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)
        ).fetchone()
        if not row:
            continue
        try:
            data = json.loads(row["data_json"] or "{}")
        except Exception:
            continue
        stage_rows = conn.execute(
            "SELECT * FROM case_stages WHERE quote_no=? ORDER BY sort_order, id", (quote_no,)
        ).fetchall()
        stages_json = []
        for sr in stage_rows:
            visit_rows = conn.execute(
                "SELECT visit_date, visit_people, note FROM case_stage_visits "
                "WHERE stage_id=? ORDER BY id", (sr["id"],),
            ).fetchall()
            stages_json.append({
                "id":         sr["id"],
                "label":      sr["label"],
                "done":       bool(sr["done"]),
                "doneAt":     sr["done_at"],
                "startDate":  sr["start_date"],
                "dueDate":    sr["due_date"],
                "assignedTo": json.loads(sr["assigned_to"] or "[]"),
                "dependsOn":  json.loads(sr["depends_on"] or "[]"),
                "visits": [
                    {"visitDate": v["visit_date"], "visitPeople": v["visit_people"], "note": v["note"]}
                    for v in visit_rows
                ],
            })
        data.setdefault("caseRecord", {})["stages"] = stages_json
        conn.execute(
            "UPDATE quotations SET data_json=? WHERE quote_no=?",
            (json.dumps(data, ensure_ascii=False), quote_no)
        )
    conn.commit()


def _m053_payment_requests(conn):
    """Create payment_requests（請款單，2026-08-24）：案件款項明細
    （quotations.data_json.caseRecord.payment.items[]）之外，另外提供一種可走
    簽核流程、對內/對客戶要款用的獨立單據——跟 invoice_vouchers（開票申請憑據）
    是同一套設計（凍結快照＋依剩餘可請款額度防超收），差異只在多了 terms_json
    （條款，比照報價單「報價條件」可自由編輯的欄位）跟 ratio_pct（請款比例，
    UI 輸入捷徑，非唯一權威金額——amount 才是，SUM(amount) 用來算剩餘額度，
    邏輯詳見 routers/payment_requests.py::_quote_remaining()）。

    簽核流程比照四種單據 2026-08-24 起統一使用的 system_settings key
    'unified_approval_flow'（見 routers/system.py），不再各自獨立一組。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payment_requests (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            request_no    TEXT    UNIQUE NOT NULL,
            quote_no      TEXT    NOT NULL,
            scope         TEXT    NOT NULL DEFAULT 'amount',
            status        TEXT    NOT NULL DEFAULT '草稿',
            ratio_pct     REAL    DEFAULT 0,
            amount        REAL    NOT NULL DEFAULT 0,
            terms_json    TEXT    NOT NULL DEFAULT '{}',
            snapshot_json TEXT    NOT NULL DEFAULT '{}',
            data_json     TEXT    NOT NULL DEFAULT '{}',
            export_count  INTEGER DEFAULT 0,
            export_log    TEXT    DEFAULT '[]',
            created_by    TEXT    DEFAULT '',
            created_at    TEXT,
            updated_at    TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pr_quote_no ON payment_requests(quote_no)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pr_status ON payment_requests(status)"
    )
    conn.commit()


def _m054_signed_upload_files(conn):
    """已開立出去的單據補上附件上傳能力（2026-08-24，同一輪功能）：報價單
    回簽、出貨單回簽、開票申請憑據開立，事後都應該能補傳客戶簽回/已開立的
    掃描檔，未來直接在系統裡查詢當初內容與檔案，不必再翻紙本或問人。

    - quotations：'回簽'對這張表是全新概念（出貨單已有、報價單原本沒有），
      比照 shipping_notes 既有的 is_signed/signed_by/signed_at/signed_log
      四欄一起補上，再加 signed_files_json 存檔案清單。
    - shipping_notes：回簽狀態機已存在，只補 signed_files_json。
    - invoice_vouchers：沒有「已開立」這個額外狀態機（核准即定稿，見
      routers/invoice_vouchers.py docstring），只補 issued_files_json 讓
      已核准的憑據能掛檔案，不新增狀態欄位。

    所有檔案清單欄位存 JSON 陣列 [{id, filename, path, uploadedBy,
    uploadedAt, size, mime}, ...]，實際檔案存 uploads/{module}/{doc_no}/，
    比照 routers/projects.py 專案照片既有慣例，複用同一套通用
    /api/uploads/{file_path:path} 簽名 URL 服務，不另外新增 serving 端點。"""
    if not _col_exists(conn, "quotations", "is_signed"):
        conn.execute("ALTER TABLE quotations ADD COLUMN is_signed INTEGER NOT NULL DEFAULT 0")
    if not _col_exists(conn, "quotations", "signed_by"):
        conn.execute("ALTER TABLE quotations ADD COLUMN signed_by TEXT DEFAULT ''")
    if not _col_exists(conn, "quotations", "signed_at"):
        conn.execute("ALTER TABLE quotations ADD COLUMN signed_at TEXT DEFAULT ''")
    if not _col_exists(conn, "quotations", "signed_log"):
        conn.execute("ALTER TABLE quotations ADD COLUMN signed_log TEXT NOT NULL DEFAULT '[]'")
    if not _col_exists(conn, "quotations", "signed_files_json"):
        conn.execute("ALTER TABLE quotations ADD COLUMN signed_files_json TEXT NOT NULL DEFAULT '[]'")
    if not _col_exists(conn, "shipping_notes", "signed_files_json"):
        conn.execute("ALTER TABLE shipping_notes ADD COLUMN signed_files_json TEXT NOT NULL DEFAULT '[]'")
    if not _col_exists(conn, "invoice_vouchers", "issued_files_json"):
        conn.execute("ALTER TABLE invoice_vouchers ADD COLUMN issued_files_json TEXT NOT NULL DEFAULT '[]'")
    conn.commit()


def _m030_env_guide(conn):
    """Create env_guide_* tables (場域選型導覽): environments, tiered equipment
    recommendations, and vendor links — ported from the standalone 場域選型導覽.html
    reference tool into an admin-editable ERP module."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS env_guide_environments (
            code       TEXT PRIMARY KEY,
            name       TEXT NOT NULL DEFAULT '',
            group_name TEXT NOT NULL DEFAULT '',
            temp_gate  TEXT NOT NULL DEFAULT '',
            ip_gate    TEXT NOT NULL DEFAULT '',
            cert_gate  TEXT NOT NULL DEFAULT '',
            trap_note  TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS env_guide_recommendations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            env_code    TEXT NOT NULL REFERENCES env_guide_environments(code) ON DELETE CASCADE,
            layer       TEXT NOT NULL DEFAULT '',
            position    TEXT NOT NULL DEFAULT '',
            tier1       TEXT NOT NULL DEFAULT '',
            tier2       TEXT NOT NULL DEFAULT '',
            tier3       TEXT NOT NULL DEFAULT '',
            custom_note TEXT NOT NULL DEFAULT '',
            trap_note   TEXT NOT NULL DEFAULT '',
            sort_order  INTEGER NOT NULL DEFAULT 0,
            updated_at  TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS env_guide_links (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword    TEXT NOT NULL DEFAULT '',
            url        TEXT NOT NULL DEFAULT '',
            label      TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_env_guide_rec_env ON env_guide_recommendations(env_code)"
    )

    # One-time seed from the original standalone tool's dataset. Only runs while
    # the table is empty so later admin edits are never clobbered by a re-run.
    if conn.execute("SELECT 1 FROM env_guide_environments LIMIT 1").fetchone():
        conn.commit()
        return

    from env_guide_seed import ENV_JSON, REC_JSON, LINKS_JSON
    now = datetime.now().isoformat()
    for i, e in enumerate(json.loads(ENV_JSON)):
        conn.execute(
            "INSERT INTO env_guide_environments "
            "(code, name, group_name, temp_gate, ip_gate, cert_gate, trap_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (e[0], e[1], e[2], e[3], e[4], e[5], e[6], i, now),
        )
    for i, r in enumerate(json.loads(REC_JSON)):
        conn.execute(
            "INSERT INTO env_guide_recommendations "
            "(env_code, layer, position, tier1, tier2, tier3, custom_note, trap_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], i, now),
        )
    for i, l in enumerate(json.loads(LINKS_JSON)):
        conn.execute(
            "INSERT INTO env_guide_links (keyword, url, label, sort_order) VALUES (?,?,?,?)",
            (l[0], l[1], l[2], i),
        )
    conn.commit()


def _m031_netarch_guide(conn):
    """Create netarch_* tables (網路架構選型導覽): 技術族系 → 世代/規格 → 產品連結.
    Unlike env_guide (情境×分層×三級), this category's shape is family→generation
    timeline, so it gets its own purpose-fit tables rather than being force-fit
    into the env_guide schema."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS netarch_families (
            code       TEXT PRIMARY KEY,
            name       TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS netarch_generations (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            family_code      TEXT NOT NULL REFERENCES netarch_families(code) ON DELETE CASCADE,
            gen_name         TEXT NOT NULL DEFAULT '',
            key_specs        TEXT NOT NULL DEFAULT '',
            upgrade_note     TEXT NOT NULL DEFAULT '',
            typical_scenario TEXT NOT NULL DEFAULT '',
            tags             TEXT NOT NULL DEFAULT '',
            price_range      TEXT NOT NULL DEFAULT '',
            dependency_note  TEXT NOT NULL DEFAULT '',
            watch_note       TEXT NOT NULL DEFAULT '',
            sort_order       INTEGER NOT NULL DEFAULT 0,
            updated_at       TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS netarch_products (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            generation_id INTEGER NOT NULL REFERENCES netarch_generations(id) ON DELETE CASCADE,
            brand         TEXT NOT NULL DEFAULT '',
            model         TEXT NOT NULL DEFAULT '',
            url           TEXT NOT NULL DEFAULT '',
            label         TEXT NOT NULL DEFAULT '',
            price_note    TEXT NOT NULL DEFAULT '',
            sort_order    INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_netarch_gen_family ON netarch_generations(family_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_netarch_prod_gen ON netarch_products(generation_id)")

    if conn.execute("SELECT 1 FROM netarch_families LIMIT 1").fetchone():
        conn.commit()
        return

    from netarch_guide_seed import FAMILIES_JSON, GENERATIONS_JSON, PRODUCTS_JSON
    now = datetime.now().isoformat()
    for i, f in enumerate(json.loads(FAMILIES_JSON)):
        conn.execute(
            "INSERT INTO netarch_families (code, name, description, sort_order, updated_at) VALUES (?,?,?,?,?)",
            (f[0], f[1], f[2], i, now),
        )
    gen_id_map = {}
    for i, g in enumerate(json.loads(GENERATIONS_JSON)):
        cur = conn.execute(
            "INSERT INTO netarch_generations "
            "(family_code, gen_name, key_specs, upgrade_note, typical_scenario, tags, price_range, dependency_note, watch_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (g[0], g[1], g[2], g[3], g[4], g[5], g[6], g[7], g[8], i, now),
        )
        gen_id_map[(g[0], g[1])] = cur.lastrowid
    for i, p in enumerate(json.loads(PRODUCTS_JSON)):
        gen_id = gen_id_map.get((p[0], p[1]))
        if gen_id is None:
            continue
        conn.execute(
            "INSERT INTO netarch_products (generation_id, brand, model, url, label, price_note, sort_order) "
            "VALUES (?,?,?,?,?,?,?)",
            (gen_id, p[2], p[3], p[4], p[5], p[6], i),
        )
    conn.commit()


def _m032_switch_guide(conn):
    """Create switch_* tables (交換器選型導覽): 產品分類 × 行業情境矩陣式交叉,
    第三個選型導覽類別, 見 routers/switch_guide.py 與 switch_guide_seed.py。
    Reconstructed 2026-08-01 from the production DB backup's actual schema —
    this migration's code was missing from this checkout even though the
    router/seed/frontend files for the feature were already present (see
    CURRENT_VERSION note above); schema verified to match the live backup
    table-for-table before writing this."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS switch_scenarios (
            code       TEXT PRIMARY KEY,
            name       TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS switch_categories (
            code            TEXT PRIMARY KEY,
            name            TEXT NOT NULL DEFAULT '',
            key_specs       TEXT NOT NULL DEFAULT '',
            tags            TEXT NOT NULL DEFAULT '',
            price_range     TEXT NOT NULL DEFAULT '',
            dependency_note TEXT NOT NULL DEFAULT '',
            watch_note      TEXT NOT NULL DEFAULT '',
            sort_order      INTEGER NOT NULL DEFAULT 0,
            updated_at      TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS switch_fit (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_code TEXT NOT NULL REFERENCES switch_scenarios(code) ON DELETE CASCADE,
            category_code TEXT NOT NULL REFERENCES switch_categories(code) ON DELETE CASCADE,
            fit_level     TEXT NOT NULL DEFAULT '',
            fit_note      TEXT NOT NULL DEFAULT '',
            sort_order    INTEGER NOT NULL DEFAULT 0,
            updated_at    TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS switch_products (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_code TEXT NOT NULL REFERENCES switch_categories(code) ON DELETE CASCADE,
            brand         TEXT NOT NULL DEFAULT '',
            model         TEXT NOT NULL DEFAULT '',
            url           TEXT NOT NULL DEFAULT '',
            label         TEXT NOT NULL DEFAULT '',
            price_note    TEXT NOT NULL DEFAULT '',
            sort_order    INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_switch_fit_scenario ON switch_fit(scenario_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_switch_fit_category ON switch_fit(category_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_switch_prod_category ON switch_products(category_code)")

    if conn.execute("SELECT 1 FROM switch_scenarios LIMIT 1").fetchone():
        conn.commit()
        return

    from switch_guide_seed import SCENARIOS_JSON, CATEGORIES_JSON, FIT_JSON, PRODUCTS_JSON
    now = datetime.now().isoformat()
    for i, s in enumerate(json.loads(SCENARIOS_JSON)):
        conn.execute(
            "INSERT INTO switch_scenarios (code, name, description, sort_order, updated_at) VALUES (?,?,?,?,?)",
            (s[0], s[1], s[2], i, now),
        )
    for i, c in enumerate(json.loads(CATEGORIES_JSON)):
        conn.execute(
            "INSERT INTO switch_categories "
            "(code, name, key_specs, tags, price_range, dependency_note, watch_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (c[0], c[1], c[2], c[3], c[4], c[5], c[6], i, now),
        )
    for i, f in enumerate(json.loads(FIT_JSON)):
        conn.execute(
            "INSERT INTO switch_fit (scenario_code, category_code, fit_level, fit_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (f[0], f[1], f[2], f[3], i, now),
        )
    for i, p in enumerate(json.loads(PRODUCTS_JSON)):
        conn.execute(
            "INSERT INTO switch_products (category_code, brand, model, url, label, price_note, sort_order) "
            "VALUES (?,?,?,?,?,?,?)",
            (p[0], p[1], p[2], p[3], p[4], p[5], i),
        )
    conn.commit()


def _m033_switch_products_specs(conn):
    """Add switch_products.specs_json (結構化規格欄位, [[label, value], ...]),
    reconstructed alongside _m032_switch_guide — see that function's docstring."""
    if not _col_exists(conn, "switch_products", "specs_json"):
        conn.execute("ALTER TABLE switch_products ADD COLUMN specs_json TEXT NOT NULL DEFAULT '[]'")
    conn.commit()


def _m034_shipping_notes(conn):
    """Create shipping_notes table (出貨單／回簽單), scoped per quote_no.
    Independent approval flow lives in system_settings key 'shipping_approval_flow',
    separate from quotations' 'approval_flow' — see routers/shipping_notes.py."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shipping_notes (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            note_no          TEXT    UNIQUE NOT NULL,
            quote_no         TEXT    NOT NULL,
            status           TEXT    NOT NULL DEFAULT '草稿',
            ship_date        TEXT    DEFAULT '',
            customer_name    TEXT    DEFAULT '',
            project_name     TEXT    DEFAULT '',
            recipient        TEXT    DEFAULT '',
            delivery_address TEXT    DEFAULT '',
            items_json       TEXT    NOT NULL DEFAULT '[]',
            notes            TEXT    DEFAULT '',
            data_json        TEXT    NOT NULL DEFAULT '{}',
            is_signed        INTEGER NOT NULL DEFAULT 0,
            signed_by        TEXT    DEFAULT '',
            signed_at        TEXT    DEFAULT '',
            signed_log       TEXT    NOT NULL DEFAULT '[]',
            export_count     INTEGER DEFAULT 0,
            export_log       TEXT    DEFAULT '[]',
            created_by       TEXT    DEFAULT '',
            created_at       TEXT,
            updated_at       TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_shipping_notes_quote_no ON shipping_notes(quote_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_shipping_notes_status ON shipping_notes(status)")
    conn.commit()


def _has_unique_module_version(conn) -> bool:
    for idx in conn.execute("PRAGMA index_list(module_versions)").fetchall():
        if not idx["unique"]:
            continue
        cols = [r["name"] for r in conn.execute(f"PRAGMA index_info({idx['name']})").fetchall()]
        if set(cols) == {"module", "version"}:
            return True
    return False


def _m035_module_versions_unique_dedup(conn):
    """Add UNIQUE(module, version) to module_versions and dedupe existing rows.

    Root cause: _sync_module_versions() (helpers/startup.py) runs on every server
    startup and relies on INSERT OR IGNORE to skip rows that already exist, but
    without a UNIQUE constraint there was nothing to conflict on — every restart
    re-inserted the full version_manifest.json (143 entries) as brand-new rows.
    Confirmed on a production db backup: 626,725 rows for only 143 distinct
    (module, version) pairs, accounting for ~270MB of a ~301MB database.

    Rebuild the table (SQLite can't ALTER TABLE ADD CONSTRAINT) keeping exactly one
    row per (module, version): rows created by a real user (updated_by != 'system',
    see routers/module_versions.py POST endpoint) always win over system-synced
    duplicates, so zero user-entered content can ever be lost by this cleanup.
    """
    if _has_unique_module_version(conn):
        return
    conn.executescript("""
        CREATE TABLE module_versions_new (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            module     TEXT    NOT NULL,
            version    TEXT    NOT NULL DEFAULT '',
            updated_at TEXT    NOT NULL,
            content    TEXT    NOT NULL DEFAULT '',
            updated_by TEXT    NOT NULL DEFAULT '',
            UNIQUE(module, version)
        );

        INSERT OR IGNORE INTO module_versions_new
            (id, module, version, updated_at, content, updated_by)
        SELECT id, module, version, updated_at, content, updated_by
        FROM module_versions
        WHERE updated_by != 'system'
        ORDER BY id DESC;

        INSERT OR IGNORE INTO module_versions_new
            (id, module, version, updated_at, content, updated_by)
        SELECT id, module, version, updated_at, content, updated_by
        FROM module_versions
        WHERE updated_by = 'system'
        ORDER BY id DESC;

        DROP TABLE module_versions;
        ALTER TABLE module_versions_new RENAME TO module_versions;
        CREATE INDEX IF NOT EXISTS idx_mv_module ON module_versions(module, updated_at);
    """)
    conn.commit()
    conn.execute("VACUUM")


def _m036_dispatch_personnel(conn):
    """Add personnel_json to contractor_dispatches — snapshot list of contractors
    (外包名冊) roster members assigned to this dispatch, e.g. [{"id":1,"name":"..."}].
    Stored as a self-contained snapshot (same philosophy as items_json) rather than
    a bare id list, so it survives even if the referenced contractors row is later
    deleted or renamed."""
    if not _col_exists(conn, "contractor_dispatches", "personnel_json"):
        conn.execute(
            "ALTER TABLE contractor_dispatches ADD COLUMN personnel_json TEXT NOT NULL DEFAULT '[]'"
        )
    conn.commit()


def _m037_dispatch_vendor_optional(conn):
    """Make contractor_dispatches.vendor_id nullable — some cases have pure
    外包名單人員點工 (day-labor personnel) with no 承攬商 at all, so the vendor
    can no longer be a mandatory field. SQLite can't ALTER a column's NOT NULL
    constraint directly, so rebuild the table (same recreate-and-swap pattern as
    _m035/_m014), copying every existing row across unchanged."""
    if not _col_notnull(conn, "contractor_dispatches", "vendor_id"):
        return
    conn.executescript("""
        CREATE TABLE contractor_dispatches_new (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_no       TEXT    NOT NULL,
            vendor_id      INTEGER,
            dispatch_date  TEXT    DEFAULT '',
            scope          TEXT    DEFAULT '',
            items_json     TEXT    DEFAULT '[]',
            personnel_json TEXT    NOT NULL DEFAULT '[]',
            total_amount   REAL    DEFAULT 0,
            tax_rate       REAL    DEFAULT 0.05,
            status         TEXT    DEFAULT 'draft',
            notes          TEXT    DEFAULT '',
            created_by     TEXT    DEFAULT '',
            created_at     TEXT,
            updated_at     TEXT,
            accepted_at    TEXT    NOT NULL DEFAULT '',
            accepted_by    TEXT    NOT NULL DEFAULT '',
            FOREIGN KEY (vendor_id) REFERENCES vendor_contractors(id)
        );
        INSERT INTO contractor_dispatches_new
            (id, quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json,
             total_amount, tax_rate, status, notes, created_by, created_at, updated_at,
             accepted_at, accepted_by)
        SELECT id, quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json,
               total_amount, tax_rate, status, notes, created_by, created_at, updated_at,
               accepted_at, accepted_by
        FROM contractor_dispatches;
        DROP TABLE contractor_dispatches;
        ALTER TABLE contractor_dispatches_new RENAME TO contractor_dispatches;
        CREATE INDEX IF NOT EXISTS idx_dispatches_quote_no ON contractor_dispatches(quote_no);
        CREATE INDEX IF NOT EXISTS idx_dispatches_vendor ON contractor_dispatches(vendor_id);
    """)
    conn.commit()


def _m038_inventory(conn):
    """Create stock_items table (序號級庫存) — one row per physical unit, keyed by
    (part_no, serial_no). No stock_batches parent table: a "batch" is just N rows
    sharing a batch_no string created together at intake — a parent table would
    only earn its keep if batches needed their own lifecycle (e.g. batch-level
    approval), which nothing here requires. part_no references parts.part_no
    without an enforced FK, matching the rest of this schema's convention of not
    FK-constraining loosely-coupled reference columns."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_items (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            part_no           TEXT    NOT NULL,
            serial_no         TEXT    NOT NULL,
            mac               TEXT    DEFAULT '',
            status            TEXT    NOT NULL DEFAULT 'in_stock',
            batch_no          TEXT    DEFAULT '',
            cost              REAL    DEFAULT 0,
            note              TEXT    DEFAULT '',
            shipping_note_no  TEXT    DEFAULT '',
            quote_no          TEXT    DEFAULT '',
            case_device_id    TEXT    DEFAULT '',
            consumed_at       TEXT    DEFAULT '',
            consumed_by       TEXT    DEFAULT '',
            created_by        TEXT    DEFAULT '',
            created_at        TEXT,
            updated_at        TEXT
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_items_part_serial ON stock_items(part_no, serial_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_items_part_status ON stock_items(part_no, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_items_batch ON stock_items(batch_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_items_shipping_note ON stock_items(shipping_note_no)")
    conn.commit()


def _m039_monitor_guide(conn):
    """Create monitor_* tables (監控系統選型導覽): 相機分類 × 場域情境矩陣式交叉,
    選型資料庫第四個類別，資料形狀與 switch_guide 相同（同一種相機形式在不同場域
    情境下適配度不同，非族系演進、非場域三級）。見 routers/monitor_guide.py 與
    monitor_guide_seed.py。specs_json 這次直接隨建表加入，不必像 switch_guide
    當初分兩版 migration 補（那是重建時才發現生產庫已用 ALTER 補過的歷史包袱）。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_scenarios (
            code       TEXT PRIMARY KEY,
            name       TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_categories (
            code            TEXT PRIMARY KEY,
            name            TEXT NOT NULL DEFAULT '',
            key_specs       TEXT NOT NULL DEFAULT '',
            tags            TEXT NOT NULL DEFAULT '',
            price_range     TEXT NOT NULL DEFAULT '',
            dependency_note TEXT NOT NULL DEFAULT '',
            watch_note      TEXT NOT NULL DEFAULT '',
            sort_order      INTEGER NOT NULL DEFAULT 0,
            updated_at      TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_fit (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_code TEXT NOT NULL REFERENCES monitor_scenarios(code) ON DELETE CASCADE,
            category_code TEXT NOT NULL REFERENCES monitor_categories(code) ON DELETE CASCADE,
            fit_level     TEXT NOT NULL DEFAULT '',
            fit_note      TEXT NOT NULL DEFAULT '',
            sort_order    INTEGER NOT NULL DEFAULT 0,
            updated_at    TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_products (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_code TEXT NOT NULL REFERENCES monitor_categories(code) ON DELETE CASCADE,
            brand         TEXT NOT NULL DEFAULT '',
            model         TEXT NOT NULL DEFAULT '',
            url           TEXT NOT NULL DEFAULT '',
            label         TEXT NOT NULL DEFAULT '',
            price_note    TEXT NOT NULL DEFAULT '',
            specs_json    TEXT NOT NULL DEFAULT '[]',
            sort_order    INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_monitor_fit_scenario ON monitor_fit(scenario_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_monitor_fit_category ON monitor_fit(category_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_monitor_prod_category ON monitor_products(category_code)")

    if conn.execute("SELECT 1 FROM monitor_scenarios LIMIT 1").fetchone():
        conn.commit()
        return

    from monitor_guide_seed import SCENARIOS_JSON, CATEGORIES_JSON, FIT_JSON, PRODUCTS_JSON
    now = datetime.now().isoformat()
    for i, s in enumerate(json.loads(SCENARIOS_JSON)):
        conn.execute(
            "INSERT INTO monitor_scenarios (code, name, description, sort_order, updated_at) VALUES (?,?,?,?,?)",
            (s[0], s[1], s[2], i, now),
        )
    for i, c in enumerate(json.loads(CATEGORIES_JSON)):
        conn.execute(
            "INSERT INTO monitor_categories "
            "(code, name, key_specs, tags, price_range, dependency_note, watch_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (c[0], c[1], c[2], c[3], c[4], c[5], c[6], i, now),
        )
    for i, f in enumerate(json.loads(FIT_JSON)):
        conn.execute(
            "INSERT INTO monitor_fit (scenario_code, category_code, fit_level, fit_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (f[0], f[1], f[2], f[3], i, now),
        )
    for i, p in enumerate(json.loads(PRODUCTS_JSON)):
        conn.execute(
            "INSERT INTO monitor_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (p[0], p[1], p[2], p[3], p[4], p[5], p[6], i),
        )
    conn.commit()


def _m040_access_guide(conn):
    """Create access_* tables (門禁系統選型導覽): 元件分類 × 場域情境矩陣式交叉,
    選型資料庫第五個類別，資料形狀與 switch_guide／monitor_guide 相同。見
    routers/access_guide.py 與 access_guide_seed.py。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS access_scenarios (
            code       TEXT PRIMARY KEY,
            name       TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS access_categories (
            code            TEXT PRIMARY KEY,
            name            TEXT NOT NULL DEFAULT '',
            key_specs       TEXT NOT NULL DEFAULT '',
            tags            TEXT NOT NULL DEFAULT '',
            price_range     TEXT NOT NULL DEFAULT '',
            dependency_note TEXT NOT NULL DEFAULT '',
            watch_note      TEXT NOT NULL DEFAULT '',
            sort_order      INTEGER NOT NULL DEFAULT 0,
            updated_at      TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS access_fit (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_code TEXT NOT NULL REFERENCES access_scenarios(code) ON DELETE CASCADE,
            category_code TEXT NOT NULL REFERENCES access_categories(code) ON DELETE CASCADE,
            fit_level     TEXT NOT NULL DEFAULT '',
            fit_note      TEXT NOT NULL DEFAULT '',
            sort_order    INTEGER NOT NULL DEFAULT 0,
            updated_at    TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS access_products (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_code TEXT NOT NULL REFERENCES access_categories(code) ON DELETE CASCADE,
            brand         TEXT NOT NULL DEFAULT '',
            model         TEXT NOT NULL DEFAULT '',
            url           TEXT NOT NULL DEFAULT '',
            label         TEXT NOT NULL DEFAULT '',
            price_note    TEXT NOT NULL DEFAULT '',
            specs_json    TEXT NOT NULL DEFAULT '[]',
            sort_order    INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_access_fit_scenario ON access_fit(scenario_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_access_fit_category ON access_fit(category_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_access_prod_category ON access_products(category_code)")

    if conn.execute("SELECT 1 FROM access_scenarios LIMIT 1").fetchone():
        conn.commit()
        return

    from access_guide_seed import SCENARIOS_JSON, CATEGORIES_JSON, FIT_JSON, PRODUCTS_JSON
    now = datetime.now().isoformat()
    for i, s in enumerate(json.loads(SCENARIOS_JSON)):
        conn.execute(
            "INSERT INTO access_scenarios (code, name, description, sort_order, updated_at) VALUES (?,?,?,?,?)",
            (s[0], s[1], s[2], i, now),
        )
    for i, c in enumerate(json.loads(CATEGORIES_JSON)):
        conn.execute(
            "INSERT INTO access_categories "
            "(code, name, key_specs, tags, price_range, dependency_note, watch_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (c[0], c[1], c[2], c[3], c[4], c[5], c[6], i, now),
        )
    for i, f in enumerate(json.loads(FIT_JSON)):
        conn.execute(
            "INSERT INTO access_fit (scenario_code, category_code, fit_level, fit_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (f[0], f[1], f[2], f[3], i, now),
        )
    for i, p in enumerate(json.loads(PRODUCTS_JSON)):
        conn.execute(
            "INSERT INTO access_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (p[0], p[1], p[2], p[3], p[4], p[5], p[6], i),
        )
    conn.commit()


def _m041_gateway_guide(conn):
    """Create gateway_* tables（閘道器與控制器選型導覽）：閘道器/控制器分類 × 場域情境
    矩陣式交叉，選型資料庫第六個類別，資料形狀與 switch_guide／monitor_guide／
    access_guide 相同。與 switch_guide 的邊界：switch_guide 只收「交換器」，本類別
    收 Omada 的路由/閘道器（Wired/Wi-Fi/4G-5G/整合型）與硬體控制器（OC 系列），
    兩者是網路架構中不同層級的設備，故獨立成類而非塞進既有交換器分類。見
    routers/gateway_guide.py 與 gateway_guide_seed.py。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gateway_scenarios (
            code       TEXT PRIMARY KEY,
            name       TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gateway_categories (
            code            TEXT PRIMARY KEY,
            name            TEXT NOT NULL DEFAULT '',
            key_specs       TEXT NOT NULL DEFAULT '',
            tags            TEXT NOT NULL DEFAULT '',
            price_range     TEXT NOT NULL DEFAULT '',
            dependency_note TEXT NOT NULL DEFAULT '',
            watch_note      TEXT NOT NULL DEFAULT '',
            sort_order      INTEGER NOT NULL DEFAULT 0,
            updated_at      TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gateway_fit (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_code TEXT NOT NULL REFERENCES gateway_scenarios(code) ON DELETE CASCADE,
            category_code TEXT NOT NULL REFERENCES gateway_categories(code) ON DELETE CASCADE,
            fit_level     TEXT NOT NULL DEFAULT '',
            fit_note      TEXT NOT NULL DEFAULT '',
            sort_order    INTEGER NOT NULL DEFAULT 0,
            updated_at    TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gateway_products (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_code TEXT NOT NULL REFERENCES gateway_categories(code) ON DELETE CASCADE,
            brand         TEXT NOT NULL DEFAULT '',
            model         TEXT NOT NULL DEFAULT '',
            url           TEXT NOT NULL DEFAULT '',
            label         TEXT NOT NULL DEFAULT '',
            price_note    TEXT NOT NULL DEFAULT '',
            specs_json    TEXT NOT NULL DEFAULT '[]',
            sort_order    INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_gateway_fit_scenario ON gateway_fit(scenario_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_gateway_fit_category ON gateway_fit(category_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_gateway_prod_category ON gateway_products(category_code)")

    if conn.execute("SELECT 1 FROM gateway_scenarios LIMIT 1").fetchone():
        conn.commit()
        return

    from gateway_guide_seed import SCENARIOS_JSON, CATEGORIES_JSON, FIT_JSON, PRODUCTS_JSON
    now = datetime.now().isoformat()
    for i, s in enumerate(json.loads(SCENARIOS_JSON)):
        conn.execute(
            "INSERT INTO gateway_scenarios (code, name, description, sort_order, updated_at) VALUES (?,?,?,?,?)",
            (s[0], s[1], s[2], i, now),
        )
    for i, c in enumerate(json.loads(CATEGORIES_JSON)):
        conn.execute(
            "INSERT INTO gateway_categories "
            "(code, name, key_specs, tags, price_range, dependency_note, watch_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (c[0], c[1], c[2], c[3], c[4], c[5], c[6], i, now),
        )
    for i, f in enumerate(json.loads(FIT_JSON)):
        conn.execute(
            "INSERT INTO gateway_fit (scenario_code, category_code, fit_level, fit_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (f[0], f[1], f[2], f[3], i, now),
        )
    for i, p in enumerate(json.loads(PRODUCTS_JSON)):
        conn.execute(
            "INSERT INTO gateway_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (p[0], p[1], p[2], p[3], p[4], p[5], p[6], i),
        )
    conn.commit()


# Ordered list — index+1 is the migration version number.
_MIGRATIONS = [
    _m001_export_columns,        # v1
    _m002_sessions_expires,      # v2
    _m003_contractor_images,     # v3
    _m004_unlock_password,       # v4
    _m005_must_change_password,  # v5
    _m006_hot_columns,           # v6
    _m007_fix_legacy_display_names,  # v7
    _m008_fix_legacy_owner_names,    # v8
    _m009_migrate_legacy_visits,     # v9
    _m010_sales_person_id,           # v10
    _m011_login_rate_limit,          # v11
    _m012_project_assigned_users,    # v12
    _m013_daily_tasks,               # v13
    _m014_weekly_recurrence,         # v14
    _m015_daily_task_password,       # v15
    _m016_daily_task_supervisors,    # v16
    _m017_session_last_active,       # v17
    _m018_module_versions,           # v18
    _m019_daily_task_case_no,        # v19
    _m020_daily_task_edit_log,       # v20
    _m021_completion_edit_count,     # v21
    _m022_vendor_contractors,        # v22
    _m023_dispatch_tax_rate,         # v23
    _m024_entity_codes,              # v24
    _m025_dispatch_acceptance,        # v25
    _m026_case_updates_work_log_case,       # v26
    _m027_dev_crm,                          # v27
    _m028_dev_cases_soft_delete,            # v28
    _m029_contractor_passbook,              # v29
    _m030_env_guide,                         # v30
    _m031_netarch_guide,                     # v31
    _m032_switch_guide,                       # v32
    _m033_switch_products_specs,              # v33
    _m034_shipping_notes,                     # v34
    _m035_module_versions_unique_dedup,       # v35
    _m036_dispatch_personnel,                 # v36
    _m037_dispatch_vendor_optional,            # v37
    _m038_inventory,                           # v38
    _m039_monitor_guide,                       # v39
    _m040_access_guide,                        # v40
    _m041_gateway_guide,                       # v41
    _m042_dev_cases_relink_review,              # v42
    _m043_notification_prefs,                   # v43
    _m044_dispatch_invoice_no,                   # v44
    _m045_contractor_payment_vouchers,           # v45
    _m046_invoice_vouchers,                      # v46
    _m047_invoice_vouchers_amount,                # v47
    _m048_org_structure,                          # v48
    _m049_division_manager,                       # v49
    _m050_project_department,                     # v50
    _m051_case_stages_normalize,                  # v51
    _m052_fix_stage_json_ids,                     # v52
    _m053_payment_requests,                       # v53
    _m054_signed_upload_files,                    # v54
]


# ── Entity code helper ────────────────────────────────────────────────────────

def next_entity_code(conn, table: str, prefix: str, code_col: str = "code") -> str:
    """Return next available code like C-202507-001 (or DN-202508-001 for a
    multi-char prefix) for entity tables. table/prefix/code_col must be
    trusted internal constants (not user input).
    """
    month = datetime.now().strftime("%Y%m")
    pattern = f"{prefix}-{month}-???"
    code_len = len(prefix) + 11   # prefix '-' YYYYMM '-' NNN
    seq_start = len(prefix) + 9    # 1-based SUBSTR offset of the NNN part
    row_max = conn.execute(
        f"SELECT COALESCE(MAX(CAST(SUBSTR({code_col}, {seq_start}, 3) AS INTEGER)), 0) AS mx "
        f"FROM {table} WHERE {code_col} GLOB ? AND LENGTH({code_col}) = {code_len}",
        (pattern,),
    ).fetchone()
    next_seq = (row_max["mx"] if row_max else 0) + 1
    while conn.execute(
        f"SELECT 1 FROM {table} WHERE {code_col}=?",
        (f"{prefix}-{month}-{next_seq:03d}",),
    ).fetchone():
        next_seq += 1
    return f"{prefix}-{month}-{next_seq:03d}"


# ── Settings seed ─────────────────────────────────────────────────────────────

def _seed_setting(conn, key: str, default_value) -> None:
    conn.execute(
        "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO NOTHING",
        (key, json.dumps(default_value, ensure_ascii=False), datetime.now().isoformat()),
    )
