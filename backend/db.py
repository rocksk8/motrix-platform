"""DB connection factory, schema initialisation, and numbered migrations."""
import sqlite3
import os
import re
import json
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "motrix_erp.db")

# Increment this whenever a new _mNNN function is added to _MIGRATIONS.
CURRENT_VERSION = 25


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        pass
    return conn


# ── Schema init ───────────────────────────────────────────────────────────────

def init_db():
    conn = get_db()
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
            must_change_password INTEGER NOT NULL DEFAULT 0
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
            updated_by TEXT    NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_mv_module
            ON module_versions(module, updated_at);
    """)
    _run_migrations(conn)
    _seed_setting(conn, "edge_path", "")
    _seed_setting(conn, "company_profile", {
        "name": "允碩整合集創股份有限公司",
        "tax_id": "60575481",
        "contact_info": "Tel: 04-3602-2818｜info@miactw.com"
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


def _m025_dispatch_acceptance(conn):
    """Add accepted_at / accepted_by to contractor_dispatches for acceptance flow node."""
    for col, defn in [("accepted_at", "TEXT NOT NULL DEFAULT ''"),
                      ("accepted_by", "TEXT NOT NULL DEFAULT ''")]:
        if not _col_exists(conn, "contractor_dispatches", col):
            conn.execute(f"ALTER TABLE contractor_dispatches ADD COLUMN {col} {defn}")
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
    _m025_dispatch_acceptance,       # v25
]


# ── Entity code helper ────────────────────────────────────────────────────────

def next_entity_code(conn, table: str, prefix: str) -> str:
    """Return next available code like C-202507-001 for entity tables.
    table and prefix must be trusted internal constants (not user input).
    """
    month = datetime.now().strftime("%Y%m")
    pattern = f"{prefix}-{month}-???"
    row_max = conn.execute(
        f"SELECT COALESCE(MAX(CAST(SUBSTR(code, 10, 3) AS INTEGER)), 0) AS mx "
        f"FROM {table} WHERE code GLOB ? AND LENGTH(code) = 12",
        (pattern,),
    ).fetchone()
    next_seq = (row_max["mx"] if row_max else 0) + 1
    while conn.execute(
        f"SELECT 1 FROM {table} WHERE code=?",
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
