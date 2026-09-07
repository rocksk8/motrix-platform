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
    # 2026-09-07 修正：這裡曾經 patch archive._ARCHIVE_BASE/_REALTIME_DIR/_WEEKLY_DIR/
    # _DAILY_DIR/_UPLOADS_MIRROR_DIR 這五個大寫常數，但現在的 archive.py 早就沒有
    # 這些常數了（改成 _archive_base()/_realtime_dir() 等會動態掃描磁碟機代號的
    # 函式，見架構地圖 §6.4／2026-09-07 雲端備份可插拔重構）——這幾行 patch 對現在
    # 的程式碼完全是死碼，什麼都沒隔離到。實際驗證發現：任何透過 API 建立/更新
    # 報價單／客戶／供應商的測試都會 spawn_bg_thread 呼叫 _backup_quotation() 等
    # 背景函式，這些函式呼叫的 _archive_base() 完全不受這裡的 patch 影響，會做
    # 真正的磁碟機代號掃描——在這台開發機上（G: 剛好掛載著真實的公司雲端硬碟）
    # 這代表測試產生的假資料曾經真的寫進 G:\我的雲端硬碟\系統存檔\即時備份\ 底下
    # （已在 G: 找到多筆 MQ-TEST-*/MQ-MARKPAY-* 等測試專用假單號的殘留 JSON，
    # 應該是不同時期的測試留下的）。改成直接 patch `_archive_base` 這個函式本身，
    # 讓所有依賴它的 _realtime_dir()/_weekly_dir()/_daily_dir()/_uploads_mirror_dir()/
    # _pdf_mirror_dir() 全部自動跟著隔離，不用每個都個別 patch，也不會再重蹈
    #「archive.py 內部改了實作方式、conftest.py 沒跟著更新」的同一種錯誤。
    archive_base = base / "archive_base"
    archive_base.mkdir()
    archive._archive_base = lambda: str(archive_base)
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

    # reports.py::_check_export_rate() keys its process-global cooldown dict by
    # (user_id, fmt) — user_id is a fresh DB's autoincrement value, so it gets
    # *recycled* across tests (each test starts a brand-new empty DB). Without
    # resetting this dict per test, a test in this file that calls an excel/pdf
    # export endpoint can spuriously 429 because some earlier, unrelated test's
    # user happened to land on the same recycled user_id within the last 5/30
    # seconds of wall-clock time (confirmed flaky failure 2026-09-01, only ever
    # reproduces in a full-suite run, never in isolation — see MOTRIX-ERP-QUICK.md
    # §12 2026-09-01 entries for the feature that surfaced it).
    import routers.reports as reports_module
    monkeypatch.setattr(reports_module, "_export_times", {})

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
