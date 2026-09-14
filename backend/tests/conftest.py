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
def isolated_archive(client, tmp_path, monkeypatch):
    """每一題自己一個全新的雲端存檔根目錄，回傳該路徑（str）。

    **為什麼需要這個**：`_app` fixture 建的 archive_base 是 **session 級**的，
    整個 test session 共用一份。`client` fixture 只換 DB，不換存檔目錄——
    所以上一題跑完 `_daily_backup()` 留下的 `每日備份/{today}/.done`、
    `月備份/{YYYY-MM}/.done` 會原封不動留給下一題，讓下一題的備份直接早退，
    斷言看到的是**別題造成的狀態**。2026-09-14 寫月備份測試時就先踩到：
    「月備份失敗不寫 .done」那題紅在前一題留下的 marker 上，跟受測邏輯無關。

    只有真的會寫進存檔目錄的測試需要用它；一般 API 測試不必，維持原本的
    session 共用即可（那些測試根本不碰這個目錄）。
    """
    import archive
    base = tmp_path / "archive_base_isolated"
    base.mkdir()
    monkeypatch.setattr(archive, "_archive_base", lambda: str(base))
    monkeypatch.setattr(archive, "_LOCAL_DB_BACKUP", str(tmp_path / "db_backups_isolated"))
    # 存檔所有權判定有 300 秒 TTL 快取（archive._archive_owner_ok()）。換了存檔
    # 根目錄就一定要讓舊判定失效，否則上一題留下的結論會直接套用到這一題——
    # 2026-09-14 實測：所有權測試把快取設成 False 之後，同一個 xdist worker 裡
    # 接著跑的月備份測試全部被那個 False 擋掉（序列執行時剛好沒撞到，只有平行
    # 執行才紅，是最難查的那種）。
    monkeypatch.setitem(archive._owner_cache, "base", None)
    monkeypatch.setitem(archive._owner_cache, "ok", None)
    monkeypatch.setitem(archive._owner_cache, "checked_at", 0.0)
    monkeypatch.setitem(archive._owner_cache, "reason", "")
    return str(base)


# 角色預設模組——對應 frontend/pages/users.html 的 ROLE_MODULES，
# 再加上 2026-09-14 新建的幾個 key（見下方 _make 的說明）。
_ROLE_DEFAULT_MODULES = {
    "superadmin": [],          # superadmin 直通，給不給都一樣
    "admin": [
        "dashboard", "quotation", "case_manage", "customer", "procurement",
        "inventory", "equipment", "finance", "reports", "project_approve_eng",
        "project_approve_biz", "financial_view", "work_log", "daily_task",
        "env_guide", "netarch_guide", "switch_guide", "monitor_guide",
        "access_guide", "gateway_guide", "automation_guide", "cashier",
        "netplan", "audit_log", "shipping_export_log", "module_versions",
        "selection_overview",
    ],
    "sales": [
        "dashboard", "quotation", "case_manage", "customer", "financial_view",
        "project_approve_biz", "work_log", "daily_task",
    ],
    "engineer": [
        "dashboard", "case_manage", "project_approve_eng", "equipment",
        "work_log", "daily_task", "netplan",
    ],
    "viewer": ["dashboard"],
}


@pytest.fixture()
def make_user():
    """Insert a user directly into the (already-isolated) real DB and return
    (username, password, token-fetching helper info) — avoids depending on
    init_default_admin()'s random-password-to-file flow for tests."""
    import db
    from helpers.auth import _hash_pw

    def _make(username="tester", password="Test-Pass-123", role="admin", modules=None):
        """`modules=None`（不指定）→ 用該角色的預設模組樣板。

        2026-09-14 改的：在此之前預設是**空陣列**，而當時 `require_any_module()`
        讓 admin 直通，所以「admin 測試帳號一個模組都沒有」完全看不出問題。
        取消直通之後這個預設立刻讓 31 題變紅——但那不是產品壞了，是**測試帳號
        一直都不像真實帳號**：正式機的 admin 都持有完整的角色樣板。

        這正是 MODULE-AUDIT §5 記的那件事：「模組檢查最危險的失敗模式是擋錯人，
        而後端測試全綠，因為測試多半用 admin 帳號、admin 直通」。那層遮蔽現在
        沒了，所以測試帳號必須拿真實的模組清單。

        要驗「沒有模組會被擋」的測試請**明確傳 `modules=[]`**——空陣列不是 None，
        不會被樣板取代。
        """
        import json
        if modules is None:
            modules = _ROLE_DEFAULT_MODULES.get(role, [])
        conn = db.get_db()
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name, role, modules, "
                "active, created_at, must_change_password) VALUES (?,?,?,?,?,1,?,0)",
                (username, _hash_pw(password), username, role,
                 json.dumps(modules), "2026-01-01T00:00:00"),
            )
            conn.commit()
        finally:
            conn.close()
        return username, password

    return _make


@pytest.fixture()
def seed_extra_expense():
    """直接在 `case_extra_expenses` 表種一筆額外支出（2026-09-11，migration v75 之後）。

    在那之前額外支出是存在 `quotations.data_json` 的 `settlement.extraItems[]` 裡，
    所以舊測試都是「組一包 settlement 塞進 data_json」。資料搬到獨立表之後那個做法
    種出來的東西報表讀不到——不是測試壞了，是資料的家換了。這個 fixture 讓所有
    相關測試走同一條路徑，不必各自拼 INSERT。

    `status` 預設「已核准」：多數測試關心的是金額有沒有被算進報表，而不是簽核流程；
    要測「送審中也要照樣計入成本、但標記 pending」時才明確傳其他狀態。
    """
    import db

    def _seed(quote_no, *, total_cost=0, category="其他", description="",
              expense_date="", created_at="", doc_no="", files=None,
              status="已核准", created_by_name="", payer_name="", qty=1, unit="", unit_cost=0):
        import json as _json
        conn = db.get_db()
        try:
            cur = conn.execute(
                "INSERT INTO case_extra_expenses "
                "(quote_no, category, description, qty, unit, unit_cost, total_cost, "
                " expense_date, doc_no, files_json, created_by_name, payer_name, "
                " created_at, updated_at, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (quote_no, category, description, qty, unit, unit_cost, total_cost,
                 expense_date, doc_no, _json.dumps(files or [], ensure_ascii=False),
                 created_by_name, payer_name, created_at or expense_date,
                 created_at or expense_date, status),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    return _seed
