"""Shared fixtures for API-level integration tests.

Boots the *real* FastAPI app (main.app) — same middleware, same routers,
same startup sequence — but redirects every file-system touchpoint (SQLite
DBs, local backup snapshots, cloud archive dirs, backup alert files) into a
throwaway pytest tmp_path first. This lets tests exercise real HTTP requests
through the real auth/demo-isolation logic without ever touching the actual
motrix_erp.db or backend/db_backups/.

Two things make this delicate and are the reason for the extra patching below
(see inline comments): (1) main.py's startup code runs once, at module import
time, not inside an @app.on_event handler — so all patching must happen
*before* `import main` executes; (2) archive.py and main.py each do
`from db import ... DB_PATH` / `DEMO_DB_PATH` *by value*, so patching
db.DB_PATH alone does not update their already-bound copies — both modules'
own attributes need patching too.
"""
import importlib
import sys

import pytest


@pytest.fixture(scope="session")
def _app(tmp_path_factory):
    """Import main.app exactly once per test session, with all startup-time
    file I/O redirected into a session-scoped tmp dir. DB *content* isolation
    between individual tests is handled separately by the `client` fixture
    below (which re-points db.DB_PATH/DEMO_DB_PATH per test) — this fixture
    only needs to get `import main` to complete without touching real files."""
    if "main" in sys.modules:
        pytest.fail(
            "main.py was already imported before the integration-test fixture "
            "could patch its file paths — some other test/module imported it "
            "too early, so this fixture can no longer guarantee it won't touch "
            "the real motrix_erp.db / backend/db_backups/. Fix the import order."
        )

    base = tmp_path_factory.mktemp("motrix_app")

    import db
    db.DB_PATH = str(base / "motrix_erp.db")
    db.DEMO_DB_PATH = str(base / "motrix_erp_demo.db")

    import archive
    archive.DB_PATH = db.DB_PATH  # archive.py imported DB_PATH by value — repoint it too
    archive_base = base / "archive_base"
    archive_base.mkdir()
    archive._ARCHIVE_BASE = str(archive_base)
    archive._REALTIME_DIR = str(archive_base / "即時備份")
    archive._WEEKLY_DIR = str(archive_base / "週備份")
    archive._DAILY_DIR = str(archive_base / "每日備份")
    archive._UPLOADS_MIRROR_DIR = str(archive_base / "上傳檔案鏡像")
    archive._LOCAL_DB_BACKUP = str(base / "db_backups")
    archive._ALERT_DIR = str(base / "backup_alerts")
    archive._UPLOADS_DIR = str(base / "uploads")  # empty — don't let tests read the real uploads/

    main = importlib.import_module("main")  # runs the real startup sequence now, isolated
    return main.app


@pytest.fixture()
def client(_app, tmp_path, monkeypatch):
    """Function-scoped: every test gets its own fresh, empty, fully-migrated
    real+demo DB pair, so tests can't see each other's data."""
    import db
    import helpers

    real_path = str(tmp_path / "motrix_erp.db")
    demo_path = str(tmp_path / "motrix_erp_demo.db")
    monkeypatch.setattr(db, "DB_PATH", real_path)
    monkeypatch.setattr(db, "DEMO_DB_PATH", demo_path)

    db.init_db(real_path)
    db.init_db(demo_path)
    helpers.init_demo_account()  # seed the real-DB 'demo' gatekeeper row (see db.py comments)

    # helpers/uploads.py (signed-file attachments for quotations/shipping_notes/
    # invoice_vouchers) computes its own UPLOADS_ROOT independent of archive.py's
    # _UPLOADS_DIR — redirect it too, or tests would write real files into the
    # actual repo uploads/ directory (confirmed happening before this patch was
    # added: test PNGs landed in uploads/quotations/MQ-SIGN-001/ etc. on disk).
    import helpers.uploads as uploads_helper
    monkeypatch.setattr(uploads_helper, "UPLOADS_ROOT", str(tmp_path / "uploads"))

    # photos.py computes its own project-photo storage roots independent of
    # archive.py/uploads_helper above too (used by projects.py's project-log
    # photos and, since 2026-08-26, system.py's work-log photos) — redirect
    # both the real and demo variants or tests would write into the actual
    # repo uploads/projects//_demo_projects/.
    import photos
    monkeypatch.setattr(photos, "_PHOTO_UPLOAD_BASE", str(tmp_path / "uploads" / "projects"))
    monkeypatch.setattr(db, "DEMO_PROJECT_PHOTOS_DIR", str(tmp_path / "uploads" / "_demo_projects"))

    from fastapi.testclient import TestClient
    return TestClient(_app)


@pytest.fixture()
def make_user():
    """Insert a user directly into the (already-isolated) real DB and return
    (username, password, token-fetching helper info) — avoids depending on
    init_default_admin()'s random-password-to-file flow for tests."""
    import db
    from helpers.auth import _hash_pw

    def _make(username="tester", password="Test-Pass-123", role="admin", modules=None):
        import json
        conn = db.get_db()
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name, role, modules, "
                "active, created_at, must_change_password) VALUES (?,?,?,?,?,1,?,0)",
                (username, _hash_pw(password), username, role,
                 json.dumps(modules or []), "2026-01-01T00:00:00"),
            )
            conn.commit()
        finally:
            conn.close()
        return username, password

    return _make
