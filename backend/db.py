"""DB connection factory, schema initialisation, and numbered migrations."""
import sqlite3
import os
import re
import json
import shutil
import time
import logging
import threading
import contextlib
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
DEMO_CASE_CLOSING_PDF_ARCHIVE_DIR = os.path.join(
    os.path.dirname(__file__), "_demo_case_closing_pdf_archive")

# Increment this whenever a new _mNNN function is added to _MIGRATIONS.
# ⚠️ 新增 migration 是「三個動作」，少任何一個都不會報錯：
#   ① 寫 _mNNN_xxx(conn)（冪等：ALTER 前先檢查、建表用 IF NOT EXISTS）
#   ② 加進下面的 _MIGRATIONS 清單（位置＝版號，只能往後接、不可插隊或刪除）
#   ③ 把這行下面的 CURRENT_VERSION 加一
#
# 🔴 而**新增資料表**還有兩個動作，它們不在這支檔裡，所以最容易漏：
#   ④ `DEMO_CLEARED_TABLES` 或 `DEMO_FILTERED_CLEARS`（本檔下面）
#      守門 test_demo_reset::test_dm1_every_table_is_classified_as_user_or_system_data
#   ⑤ `archive.py::_daily_backup_tables()`（每日 JSON 備份）
#      守門 test_system_audit::test_every_table_is_either_backed_up_or_explicitly_excluded
# ☠️ 這兩個**在 v93／v95／v97 連續漏了三次** —— 而每一次的症狀都一樣：
#    migration 本身全綠、伺服器照常起來，**而那兩道守門在全量回歸時才紅**。
# 🔑 它們漏掉的真正代價不是紅燈：
#    ④ 漏 ⇒ demo 重置清不掉新表 ⇒ **下一個客戶看得到上一個客戶的資料**
#    ⑤ 漏 ⇒ 新表**不進每日備份** ⇒ 而那要到還原的那一天才會發現
# 漏掉③的症狀是**完全沒有症狀**：_run_migrations() 第一行 current >=
# CURRENT_VERSION 就直接 return，migration 從頭到尾沒被呼叫、log 不會有任何
# 一行、伺服器照常起來，只有實際去 INSERT 新欄位時才炸。2026-09-14 v82 就是
# 這樣漏的，靠重啟真伺服器＋PRAGMA table_info 才發現。改完請實際重啟一次並
# 確認 log 有印出 'DB migration NN/NN: _mNNN_xxx'。
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
# v57: payment_requests.stage（請款單「款項類別」：全額/訂金款/交貨款/驗收款/
# 尾款，手動選擇的業務語意標籤），2026-08-24——跟既有 scope（amount/items，決定
# 金額計算方式）並存，純粹取代客戶端 PDF 上「請款範圍」欄原本顯示的技術性描述
# （自訂金額(X%)/自訂品項）。
# v58: 回填既有已成案/已結案報價單的 data_json.dealWonAt（2026-08-24）——首頁
# 「本月銷售」原本依 quote_date 分組，但 quote_date 是報價單建立當下手動填的
# 日期，常常跟業務員實際簽下這筆案子的月份對不上，導致當月營收看起來是 0。
# routers/quotations.py::update_deal_tag() 之後轉為已成案時會即時寫入
# dealWonAt，這支 migration 只負責把修正前就已成案/已結案的舊資料補上（用
# updated_at 當最佳可得的成交時間代理值）。
# v59: 修正 v58 backfill 的值（2026-08-24，同一天使用者實測就回報「銷售收入
# 趨勢錯誤」）——updated_at 是「最後一次編輯」，案件成案後只要再被動過（哪怕
# 跟 dealTag 完全無關），updated_at 就會被推遲，導致好幾筆案件被錯誤歸到很久
# 之後才成交。改用 audit_log 裡 action='deal_tag.change' 的真實事件時間戳
# （成案當下就寫入、不會被後續無關編輯覆蓋），查不到 audit 紀錄的舊資料則把
# dealWonAt 拿掉、fallback 回 quote_date。
# ⚠️ dealWonAt 這整套（v58/v59）已在同一天被 dashboard.py 的下一輪修正取代
# ——使用者進一步要求「本月銷售」該依實際收款時間（caseRecord.payment.items[].
# receivedAt）分組，不是案件成交（dealTag 轉已成案）的時間，兩者常常是不同
# 月份。dashboard_monthly() 已經改用 receivedAt，不再讀 dealWonAt；
# update_deal_tag() 也已移除寫入。v58/v59 migration 保留純粹是歷史紀錄
# （已套用過的 schema_version 不可回頭刪除/重排），data_json.dealWonAt 這個
# 欄位會留在既有資料裡但目前沒有任何程式碼讀取，之後如果要重新加回「成交時間」
# 這種概念，不要複用這個欄位名稱免得語意混淆。
# v76: case_extra_expenses.change_*（已核准後的編輯＝變更申請，核准才生效）＋
# case_stages.google_calendar_done_event_id / daily_task_id（勾選完成同步行事曆），
# 2026-09-11 第二輪交辦，見 _m076 docstring 與 MOTRIX-ERP-QUICK.md §5.10／§5.11。
# v77: completion_notes（完工單，比照 shipping_notes 同構＋工程完工單特有欄位），
# 2026-09-12 交辦，見 _m077 docstring。
# v78: completion_notes.contact_phone（完工單帶入報價單聯絡人電話），2026-09-12。
# v79: user_activity（在線時數統計），2026-09-13。
# v80: user_request_log（操作軌跡），2026-09-13。
# v81: edit_presence（同時編輯偵測），2026-09-13。
# v82: case_updates.files_json / dev_logs.files_json（案件動態與業務開發記錄
# 的附件，2026-09-14）——兩張表都是 TEXT NOT NULL DEFAULT '[]'，存
# save_document_files() 回傳的清單。刪附件限 admin+，見 routers/quotations.py
# 與 routers/dev_crm.py 的 DELETE .../files/{file_id}。
# v92: tenders.marked_at / tenders.marked_by（標註功能，2026-09-22 §21 補）
#      —— 一個可為 NULL 的時間戳兼任旗標，判定一律 `marked_at IS NOT NULL`。
# v93: account_items 表 ＋ 兩個 TRIGGER（法定項目在**資料層**唯讀，FN1 §69）
# v94: 載入 547 筆法定會計項目（靜態檔，**不呼叫解析器**）
# v95: 傳票五張表（vouchers／voucher_lines／voucher_edit_log／
#      voucher_templates／voucher_template_versions）＋ 索引 ＋ 兩支 TRIGGER
# v96: account_items.is_active —— **停用而不是刪除**（FN1⑤）
# v97: 獎金分潤五張表（bonus_items／bonus_templates／bonus_template_versions／
#      bonus_awards＋**部分**唯一索引／bonus_award_lines）
# v98: FN4 編寫紀錄 —— bonus_award_edit_log ＋ 兩張共同的 retention 欄
# v99: JV2 簽核三格各自的「誰」與「什麼時候」（送審／覆核／主管）
# v108: BN3 bonus_item_people（manual 人員來源指定的帳號清單）
# v109: JV22 §3／BN17 兩張編寫紀錄表的 BEFORE DELETE TRIGGER（資料庫層不可刪）
CURRENT_VERSION = 110

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


@contextlib.contextmanager
def db_conn():
    """`with db_conn() as conn:` —— **一個地方保證關，呼叫端不必各自記得。**

    ## 為什麼是它而不是九個 `try/finally`

    實測 `routers/dashboard.py` 九支端點：
    ```
    正常路徑就洩漏   2 支（dashboard_monthly／dashboard_expenses_monthly）
    例外路徑會洩漏   9 支（全部——沒有任何一支有 finally）
    ```
    🔑 加九個 `try/finally` 對「這會不會讓**第十支**不可能出事」的答案是
    「會少一點」⇒ **那還是在修結果。**
    ⇒ 而那七支「看起來成對」的最危險：**它們在正常路徑下是對的**，
    所以任何「數 open 與 close」的檢查都會說它們沒問題。

    ## ⚠️ 範圍刻意只到 `dashboard.py`
    全庫有 426/562 處是同一個寫法，那個裁定過是**房子風格**，不在這一輪動。
    `dashboard.py` 是例外的理由很具體：**它是首頁端點，七天 1,044 次，全站最高。**

    📌 這不是「唯一正確的寫法」——`try/finally` 與 `contextlib.closing` 在行為上等價。
    **守門釘的是「連線有沒有被關」，不是「你用哪一種寫法」**，
    所以日後有人用別的方式重寫其中一支，那些題目應該照樣綠。
    """
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


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
            # 🔴 **清單是明著寫的，不再從 `sqlite_master` 動態取得**（`DM1`）。
            #
            # ☠️ 動態取得 ⇒ 清單**一定包含 `account_items`** ⇒ 而 `v93` 的
            #    TRIGGER 會 `RAISE(ABORT)` ⇒ `reset_demo_db()` 拋例外 ⇒
            #    **demo 第二次登入 500**（第一次會成功，所以「我登入試了，可以」
            #    漏得掉它）。
            # ⚠️ `PRAGMA foreign_keys=OFF` **對 TRIGGER 無效** —— 那個開關管的是
            #    外鍵約束，不是觸發器。
            #
            # 🔑 而保留 `account_items` 的理由**不是「繞過 TRIGGER」**，是
            #    **那 547 筆是系統資料不是使用者資料** —— demo 使用者沒有建立
            #    它們，也不該因為重置而失去它們。
            # ☠️ 理由寫錯的代價很具體：下一個人會被帶去改那道 TRIGGER，
            #    **而那道 TRIGGER 是對的**。
            present = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            conn.execute("PRAGMA foreign_keys=OFF")
            # 🔴 `v109`：兩張編寫紀錄表有 BEFORE DELETE TRIGGER（正式庫刪不掉），
            #    而展示重置要**整張清空**它們 ⇒ 先把 TRIGGER 拿掉、清完**照原樣建回**。
            #    ⚠️ 建回用的是 `sqlite_master` 裡**那一份定義本身**，不是另抄一份 SQL
            #       —— 兩份的話會漂移，而展示庫的保護會悄悄和正式庫不一樣。
            #    ⚠️ `PRAGMA foreign_keys=OFF` 對 TRIGGER 無效（見上面 account_items 那段）。
            saved_triggers = [(r["name"], r["sql"]) for r in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger'"
                " AND name IN ('voucher_edit_log_no_delete',"
                " 'bonus_award_edit_log_no_delete')")]
            for name, _sql in saved_triggers:
                conn.execute(f"DROP TRIGGER IF EXISTS {name}")
            # ⚠️ 跳過不存在的表：這段 DELETE 跑在 `init_db()` **之前**，
            #    而一個舊的 `demo.db` 可能還沒有比較新的那幾張表。
            for t in DEMO_CLEARED_TABLES:
                if t in present:
                    conn.execute(f"DELETE FROM {t}")
            for t, where in DEMO_FILTERED_CLEARS.items():
                if t in present:
                    conn.execute(f"DELETE FROM {t} WHERE {where}")
            for _name, sql in saved_triggers:
                conn.execute(sql)
            conn.commit()
            conn.execute("VACUUM")
        finally:
            conn.close()
    init_db(DEMO_DB_PATH)
    for d in (DEMO_PROJECT_PHOTOS_DIR, DEMO_UPLOADS_DIR, DEMO_PDF_ARCHIVE_DIR, DEMO_PAYSLIP_ARCHIVE_DIR,
              DEMO_SHIPPING_PDF_ARCHIVE_DIR, DEMO_CONTRACTOR_VOUCHER_PDF_ARCHIVE_DIR,
              DEMO_INVOICE_VOUCHER_PDF_ARCHIVE_DIR, DEMO_PAYMENT_REQUEST_PDF_ARCHIVE_DIR,
              DEMO_CASE_CLOSING_PDF_ARCHIVE_DIR):
        _wipe_dir(d)


# ══════════════════════════════════════════════════════════════════════
# demo 重置的兩份清單（`DM1`，2026-09-23）
# ══════════════════════════════════════════════════════════════════════
#
# 🔑 名字描述的是**會發生什麼**，不是一個語意宣稱：
# ```
# DEMO_CLEARED_TABLES    重置時**整張**清空
# DEMO_FILTERED_CLEARS   重置時**依條件清掉一部分列**（目前只有 account_items）
# ```
# ⚠️ 刻意**不叫**「系統資料／使用者資料」—— 那兩個詞擔不起這份清單：
#    選型資料庫那 28 張目錄表**是系統資料**，而它們在這裡屬於「會被清」的一邊，
#    因為清除迴圈連 `schema_version` 一起清掉 ⇒ `init_db()` 看到版本 0 ⇒
#    **整批 migration 重跑** ⇒ 種子資料全部重灌。
#    🔑 ⇒ **「這張表是不是系統資料」與「它會不會被清」是兩個問題**，
#       而把它們用同一個名字綁在一起，下一個人會照名字做出錯的決定。
#
# 🔴 兩份清單必須**互斥且窮盡**（對 `sqlite_master`）：
# ```
# 少一張   ⇒ 新表沒有人分類 ⇒ 守門紅
# 多一張   ⇒ 清單裡有不存在的表 ⇒ 它爛掉了 ⇒ 守門紅
# 兩邊都有 ⇒ 沒有人真的決定過 ⇒ 守門紅
# ```
# ☠️ 而單向的排除清單可以靠「**把每一張表都放進去**」變綠 ——
#    那樣 demo 從此不再清空任何東西，**而它全綠**。
# 🔴 **粒度是「列」不是「表」。**
#
# ☠️ 整張保留 `account_items` 會換來一個**更安靜**的問題：
# ```
# statutory 的 547 筆留著                       ✅ 本來就要
# 而 demo 使用者自己建的 custom 科目**也留著**   ❌
# ⇒ **下一個客戶看得到上一個客戶建的科目**
# ```
# 🔑 demo 重置的目的是「**每個客戶的展示都從乾淨開始**」——
# ⚠️ 而這個問題不會報錯，要到有人在客戶面前打開科目樹才發現。
#
# ⚠️ 而這個 `WHERE` **不會撞到 `v93` 的 TRIGGER**：那道 TRIGGER 的條件是
#    `OLD.source = 'statutory'`，而這裡刪的正好是 `source != 'statutory'`。
DEMO_FILTERED_CLEARS = {
    "account_items": "source != 'statutory'",
}

#: 給守門用的別名：**被過濾清除**的那幾張表。
#: ⚠️ 它不是「完全不清」—— 那正是上面那段註解在講的事。
DEMO_PARTIALLY_CLEARED_TABLES = frozenset(DEMO_FILTERED_CLEARS)

DEMO_CLEARED_TABLES = frozenset((
    "access_categories", "access_fit", "access_products",
    "access_scenarios", "approval_delegates", "audit_log",
    "automation_categories", "automation_fit", "automation_products",
    "automation_scenarios", "case_action_items", "case_change_requests",
    "case_extra_expenses", "case_stage_visits", "case_stages",
    "case_updates", "completion_notes", "contractor_dispatches",
    "contractor_payment_vouchers", "contractors", "customers",
    "daily_task_completions", "daily_task_edit_log", "daily_tasks",
    "departments", "dev_cases", "dev_logs", "divisions", "edit_presence",
    "env_guide_environments", "env_guide_links",
    "env_guide_recommendations", "gateway_categories", "gateway_fit",
    "gateway_products", "gateway_scenarios", "geocode_cache",
    "geocode_usage", "invoice_vouchers", "login_rate_limit",
    "module_versions", "monitor_categories", "monitor_fit",
    "monitor_products", "monitor_scenarios", "netarch_families",
    "netarch_generations", "netarch_products", "network_plans",
    "notifications", "parts", "payment_requests", "payslip_seq",
    "payslips", "project_logs", "project_stages", "projects",
    "purchase_suggestion_status", "quotations", "quote_seq",
    "schema_version", "sessions", "shipping_notes", "stock_batches",
    "stock_items", "suppliers", "switch_categories", "switch_fit",
    "switch_products", "switch_scenarios", "system_settings",
    "t100_export_confirmations", "tender_fetch_log", "tender_hits",
    "tender_watches", "tenders", "user_activity_daily", "user_list_prefs",
    "user_request_log", "users", "vendor_contractors",
    # ── v95 傳票五張（`SPEC-VOUCHER §八`）──────────────────────────
    #
    # 🔑 五張**都是使用者資料**，整張清 —— 傳票是 demo 使用者自己開的單。
    # ⚠️ 對照 `account_items`：那一張走 `DEMO_FILTERED_CLEARS`（只清 custom），
    #    因為法定 547 筆是**系統資料**。傳票這邊沒有對應的「法定列」。
    #
    # ⚙️ **與 v95 那兩支 TRIGGER 的互動（寫在這裡，否則下一個人會重推一次）**：
    # ```
    # TRIGGER 擋的是「account_items 的某個 code 還被 voucher_lines 引用時，
    #                 不准改那個 code／不准刪那一列」
    # 而重置時 voucher_lines **整張清空** => 引用全部消失
    # => 接著清 account_items 的 custom 列時，TRIGGER 的 WHEN EXISTS 為假
    # => **不會擋**
    # ```
    # 🔑 所以順序上沒有問題，**而它是靠「voucher_lines 在這份清單裡」成立的** ——
    # ☠️ 哪天有人把 voucher_lines 移去 `DEMO_FILTERED_CLEARS`（只清一部分），
    #    殘留的引用會讓 demo 重置**清不掉某些 custom 科目，而且會丟例外**。
    # ⚠️ 這裡列的是 `vouchers_all`（**實表**）不是 `vouchers`（VIEW）——
    #    守門對 `sqlite_master WHERE type='table'` 做笛卡兒積，**VIEW 不在裡面**，
    #    ☠️ 而把 VIEW 寫進來會變成「清單裡有一張不存在的表」⇒ 反向控制會紅。
    # 🔑 而清除也必須打實表：`DELETE FROM vouchers` 對 VIEW 會直接 OperationalError。
    # ── v97 獎金五張（`FN2`）──────────────────────────────────────
    #
    # 🔑 五張**都是使用者資料**，整張清：獎金單是依案件發放的，
    #    而 demo 重置的目的是讓每個客戶的展示都從乾淨開始。
    # ⚠️ `bonus_items`／`bonus_templates` 看起來像「系統預設」那一類，
    #    **而它們不是**：施工圖 `§一` 逐字「項目可由**最高管理者**定義」
    #    ⇒ 那是**使用者建的**，不是我們預載的。
    "bonus_award_edit_log", "bonus_award_lines", "bonus_awards",
    # `BN14` 的群組與成員由最高管理者建立（不是預載）⇒ 使用者資料，整張清（DM1）。
    "bonus_group_members", "bonus_groups", "bonus_item_people", "bonus_items",
    "bonus_template_versions", "bonus_templates",
    # 🔑 `voucher_attachments` 整張清：附件是**使用者上傳的憑證**，
    #    demo 重置要讓每個客戶從乾淨開始。
    # ⚠️ 而**實體檔不在這裡處理** —— 這份清單只管資料表。
    "voucher_attachments",
    "voucher_edit_log", "voucher_lines", "voucher_template_versions",
    "voucher_templates", "vouchers_all",
    "webauthn_credentials", "work_logs",
))


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
    # `WL7` §5⓪①：全新安裝的出廠值改成空字串，不是我們的公司資料。
    # ⚠️ `_seed_setting` 是 `DO NOTHING`（key 已存在就不覆寫），
    # 所以這個改動對既有安裝零影響——已經存在的那一列不會被這裡動到，
    # 而它解決的是往後每一個新客戶：全新安裝不會再印出我們的公司抬頭。
    # （既有安裝的回填是 `_m106_company_profile_identity_backfill`，
    # 只認 `tax_id == "60575481"` 這一個信號，不是這裡。）
    _seed_setting(conn, "company_profile", {
        "name": "",
        "tax_id": "",
        "contact_info": "",
        "bank_name": "", "bank_branch": "", "bank_account_name": "", "bank_account_number": "",
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


def _table_exists(conn, name: str) -> bool:
    """這張表在不在。**正面查詢，不靠例外。**

    🔑 為什麼要有這個東西：`except sqlite3.OperationalError` 沒辦法分辨
    「表不存在」與「鎖住／欄位名不對」—— 它們是**同一個例外類別**。
    ⇒ 想分辨就得在問之前先確認，不能等它爆了再猜它為什麼爆。
    """
    return conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _get_version(conn) -> int:
    """目前的 schema 版本。**查不到版本時不可以回 0。**

    🔴 這裡原本整段包在 `try/except Exception: return 0` 裡，理由推測是
    「新資料庫還沒有 `schema_version` 這張表」。**那個情境到不了**：
    `init_db()` 在第 217 行就 `CREATE TABLE IF NOT EXISTS schema_version`，
    而 `_run_migrations()`（唯一的呼叫端）在第 522 行才跑——**中間隔了 305 行**。

    ⇒ 那個 `except` 實際能捕捉到的是 `database is locked`、`file is not a database`、
    磁碟錯誤這一類，**沒有一種是「這是一個新資料庫」**。
    ☠️ 而回 `0` 的意思是「**當成全新資料庫，從第 1 支 migration 從頭跑一遍**」——
    在一個其實有資料、只是當下讀不到的庫上做這件事，**比直接崩潰危險得多**。
    🔑 **讀不到就要拒絕，不要猜一個看起來最無害的值**：
    `0` 看起來無害，是因為它在唯一到不了的那個情境裡才是對的。

    📌 `fetchone()` 回 `None` 那一支**是對的，不要動**：表建好了但還沒有那一列，
    那就是全新資料庫的正當路徑（`schema_version` 沒有 seed 列）。

    ## 🔄 2026-09-22 更正：上面的論證留著，**結論換掉**
    ⚠️ **上面那段推理是對的**（「例外不能拿來判斷這是不是新資料庫」），
    **只是當時的結論是「那就不判斷」，現在的結論是「換一種方式判斷」。**
    🔑 〈推翻的證據不會自動支持替代方案〉：
    「`except` 分辨不了」推翻的是那個 `except`，**沒有推翻「要分辨」本身**。

    改變結論的事實：`_get_version` 現在**不只有 `_run_migrations` 呼叫**——
    測試與工具腳本會拿一個任意的連線直接問它，而那些連線可能真的沒有那張表。
    ⇒ 「那個情境到不了」在 2026-09-21 是對的，今天不是了。

    **所以：先正面查 `sqlite_master`（`_table_exists`），表不在才回 0。**
    ☠️ **不可以退回 `try/except sqlite3.OperationalError: return 0`**——
    同一個 except 會吞掉「database is locked」「file is not a database」
    「欄位名不是 version」，而那些的正確反應是**拒絕**，不是回 0。
    （守門：`tests/test_spec_debts_2026_09_22.py::test_u8b…` 與 `::test_u9…`）
    """
    if not _table_exists(conn, "schema_version"):
        # 表不在 ＝ 這個庫從來沒跑過 migration ＝ 全新資料庫。
        # ⚠️ **這是唯一一種可以回 0 的情況**，而它是被「問出來的」不是「猜出來的」。
        return 0
    # 表在 ⇒ 底下任何失敗都**讓它拋**。
    # 🔴 回 0 的意思是「當成全新資料庫，從第 1 支 migration 從頭跑一遍」——
    # 在一個其實有資料、只是當下讀不到的庫上做這件事，**比直接崩潰危險得多**。
    row = conn.execute("SELECT version FROM schema_version WHERE id=1").fetchone()
    return row["version"] if row else 0


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
        if current > CURRENT_VERSION:
            # 🔴 **資料庫比程式碼新。** 這不是假想：
            # 「部署新版 → 發現問題 → 回退程式碼」之後就是這個狀態。
            #
            # ⚠️ **記 WARNING，不丟例外**（A 裁定）。丟例外會讓回退**直接起不來**，
            # 那是把「新版有一個 bug」變成「什麼都跑不起來」——**嚴格更糟**。
            # 而靜默 return 的代價是：不認識的欄位會在執行期以各種奇怪的方式冒出來，
            # **而沒有人會聯想到版本**。⇒ 留痕跡，但不要擋路。
            #
            # ⚠️ **兩個數字都要印。** 只印一個的話讀的人無從判斷差多少、
            # 也無從判斷該往前升還是該把程式碼換回去。
            #
            # 🔴 **不可以把 `schema_version` 改小去「修好」它**（U5b 釘這個）。
            # 那之後就再也看不出這個庫跑過更新的 schema 了——
            # **把證據改掉比留著問題更糟。**
            #
            # 🔑 **而「只記 log 就好」這個裁決有一個前提**：
            # 目前每一支 migration 都**只加不改**（新增欄位／新增表），
            # 所以舊程式碼讀不到的新欄位，它就是不讀，不會壞。
            # ⚠️ **那是 migration 的性質，不是這個引擎的性質。**
            # 哪天有人寫了 `DROP COLUMN`／`RENAME`，這裡就必須重新裁決——
            # 守門見 `tests/test_spec_debts_2026_09_22.py`
            # `::test_u5c_no_migration_makes_a_column_disappear`。
            # ⚠️ **這一行原本指向 `test_upgrade_path_2026_09_21.py::test_u5c`，
            # 而那個檔裡沒有那支測試**——它 2026-09-22 才被寫出來，
            # 寫這句話的當下**那個守門的人不存在**。
            # 🔑 一句「已經有人在守」的話，本身不是守門；
            # 而它比沒有註解更糟，因為下一個人讀到它就不會再去確認。
            logger.warning(
                "資料庫 schema 版本是 v%d，比這份程式碼認得的 v%d 新 —— "
                "有些欄位是這份程式碼不認識的。"
                "（常見成因：部署新版後回退了程式碼，而資料庫已經升上去了）",
                current, CURRENT_VERSION,
            )
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
# ⚠️ 這一句從第一天就寫在這裡，而**真的去驗它的東西 2026-09-22 才出現**
# （`tests/test_spec_debts_2026_09_22.py::test_u10_every_migration_can_be_run_twice`
# ——它把每一支跑兩次）。在那之前這是一條**沒有人檢查的規定**。
# 🔑 寫下規則與守住規則是兩件事，而讀起來一模一樣。

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
            updated_at  TEXT    NOT NULL,
            google_calendar_event_id TEXT NOT NULL DEFAULT ''
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
            stage         TEXT    NOT NULL DEFAULT '',
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


def _m058_backfill_deal_won_at(conn):
    """回填既有已成案/已結案報價單的 data_json.dealWonAt（見上方 v58 說明）。
    只補「目前完全沒有 dealWonAt」的舊資料，且用 UPDATE...WHERE 已經先過濾掉
    有值的列，重跑一次不會二次覆蓋——冪等。"""
    rows = conn.execute("""
        SELECT quote_no, data_json, updated_at, quote_date
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
          AND (json_extract(data_json,'$.dealWonAt') IS NULL OR json_extract(data_json,'$.dealWonAt') = '')
    """).fetchall()
    for r in rows:
        won_at = r["updated_at"] or r["quote_date"] or ""
        if not won_at:
            continue
        data = json.loads(r["data_json"] or "{}")
        data["dealWonAt"] = won_at
        conn.execute(
            "UPDATE quotations SET data_json=? WHERE quote_no=?",
            (json.dumps(data, ensure_ascii=False), r["quote_no"])
        )
    conn.commit()


def _m059_fix_deal_won_at_from_audit_log(conn):
    """修正 v58 用 updated_at 猜的 dealWonAt（見上方 v59 說明）。改用 audit_log
    裡 action='deal_tag.change'、detail.to='已成案' 的真實事件時間戳——這是每次
    成案動作當下就寫入、不會被後續無關編輯覆蓋的權威紀錄。取每張報價單最後一次
    轉為已成案的時間（ORDER BY at ASC 逐筆覆蓋，若曾降級又重新成案以最新一次為
    準，符合目前狀態）。完全查不到 audit 紀錄的舊資料（例如匯入時就已經是已成案
    狀態、從未真的呼叫過這支 API）就把 dealWonAt 拿掉，讓查詢邏輯 fallback 回
    quote_date——沒有真實成交時間可用時，寧可維持舊行為也不要用不可靠的猜測值。
    冪等：只在算出來的值跟目前不同時才寫入。"""
    won_events = {}
    for r in conn.execute(
        "SELECT at, target_id, detail FROM audit_log WHERE action='deal_tag.change' ORDER BY at ASC"
    ).fetchall():
        try:
            detail = json.loads(r["detail"] or "{}")
        except Exception:
            continue
        if detail.get("to") == "已成案":
            won_events[r["target_id"]] = r["at"]

    rows = conn.execute("""
        SELECT quote_no, data_json
        FROM quotations
        WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') IN ('已成案','已結案')
    """).fetchall()
    for r in rows:
        data = json.loads(r["data_json"] or "{}")
        true_won_at = won_events.get(r["quote_no"])
        if true_won_at:
            if data.get("dealWonAt") != true_won_at:
                data["dealWonAt"] = true_won_at
                conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?",
                             (json.dumps(data, ensure_ascii=False), r["quote_no"]))
        elif "dealWonAt" in data:
            data.pop("dealWonAt", None)
            conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?",
                         (json.dumps(data, ensure_ascii=False), r["quote_no"]))
    conn.commit()


def _m060_dispatch_files(conn):
    """承攬商派發新增 files_json（2026-08-25）：承攬商提供的報價/估價文件
    附件上傳，比照 _m054_signed_upload_files 的通用附件 JSON 陣列存法，實際
    檔案存 uploads/contractor_dispatches/{id}/。跟派發本身既有的 items_json/
    personnel_json（拆解後的品項/人員「內容」）是不同層次——這裡存的是承攬商
    提供的原始報價文件（PDF/圖檔），供事後核對用。"""
    if not _col_exists(conn, "contractor_dispatches", "files_json"):
        conn.execute("ALTER TABLE contractor_dispatches ADD COLUMN files_json TEXT NOT NULL DEFAULT '[]'")
    conn.commit()


def _m061_case_semi_unlock(conn):
    """已結案案件解鎖／半解鎖機制（2026-08-26）：deal_tag='已結案' 的案件目前
    完全鎖定（quotations.py 的相關端點沒有例外）；使用者要求能解鎖成「半解鎖」
    狀態，讓案件記錄（case-record 整包存檔、款項標記收款、款項/叫料附件上傳）
    可以繼續變更，但每一筆變更/上傳都要先送最高管理員審核通過才真的套用，不能
    像未結案案件一樣立即生效。

    quotations 新增三欄記錄目前解鎖狀態（任何登入使用者皆可解鎖/重新上鎖，
    2026-08-26 使用者透過 AskUserQuestion 確認，比照既有附件上傳「任何人皆可
    傳」的最寬鬆權限慣例）：
    - case_semi_unlocked：0/1，是否處於半解鎖狀態
    - case_semi_unlocked_by／case_semi_unlocked_at：最近一次解鎖的操作者/時間
      （純顯示用，不做權限判斷）

    新表 case_change_requests：半解鎖期間每一筆待審核的變更/上傳請求，
    action_type 對應 routers/quotations.py 裡新增的 8 個「暫存待審」端點
    （case_record_update／payment_mark／payment_invoice_upload／
    payment_invoice_delete／material_file_upload／material_file_delete／
    material_invoice_upload／material_invoice_delete）。payload_json 存
    套用該筆變更所需的資料（例如 case_record_update 存整包 caseRecord；
    上傳類存 idx/field，實際檔案先存進 uploads/_pending_case_changes/{id}/，
    staged_files_json 記錄暫存路徑，核准時才搬進正式路徑並寫回 data_json，
    拒絕則直接刪除暫存檔）。status 只有 pending/approved/rejected 三種，
    approve/reject 只限 superadmin（比照已結案案件本身的解鎖/降級規則）。

    刻意不涵蓋的範圍（2026-08-26 設計取捨，非遺漏）：案件執行階段的細項端點
    （新增/編輯/刪除/排序/加入負責人/移除負責人/前置階段/新增拜訪/編輯拜訪/
    刪除拜訪，共 10 支）與款項稅額沖銷申請/撤銷/核准（3 支）——這些端點在
    案件已結案時一律直接 403 擋下（不論
    是否半解鎖都不支援），需要修正時請透過 case-record 整包編輯或款項標記
    收款這幾支已支援排隊審核的端點處理，或聯繫最高管理員直接於資料庫層級
    校正。之後如果要擴大涵蓋範圍，比照本次 case_record_update 的「暫存
    payload_json、核准時重放同一段套用邏輯」模式即可，不需要另立新架構。"""
    if not _col_exists(conn, "quotations", "case_semi_unlocked"):
        conn.execute("ALTER TABLE quotations ADD COLUMN case_semi_unlocked INTEGER NOT NULL DEFAULT 0")
    if not _col_exists(conn, "quotations", "case_semi_unlocked_by"):
        conn.execute("ALTER TABLE quotations ADD COLUMN case_semi_unlocked_by TEXT DEFAULT ''")
    if not _col_exists(conn, "quotations", "case_semi_unlocked_at"):
        conn.execute("ALTER TABLE quotations ADD COLUMN case_semi_unlocked_at TEXT DEFAULT ''")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_change_requests (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_no             TEXT    NOT NULL,
            action_type          TEXT    NOT NULL,
            summary              TEXT    NOT NULL DEFAULT '',
            payload_json         TEXT    NOT NULL DEFAULT '{}',
            staged_files_json    TEXT    NOT NULL DEFAULT '[]',
            status               TEXT    NOT NULL DEFAULT 'pending',
            requested_by         TEXT    NOT NULL DEFAULT '',
            requested_by_display TEXT    DEFAULT '',
            requested_at         TEXT,
            decided_by           TEXT    DEFAULT '',
            decided_at           TEXT,
            reject_reason        TEXT    DEFAULT ''
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ccr_quote_no ON case_change_requests(quote_no)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ccr_status ON case_change_requests(status)"
    )
    conn.commit()


def _m062_case_project_merge(conn):
    """專案管理併入案件管理（2026-08-26）：使用者要求把「專案管理」
    （projects/project_logs/project_stages）的獨有功能收斂進案件管理，讓
    案件本身就有代辦事項兩階段簽核、成員分配、工作日誌可上傳照片，不必再
    跳去另一個模組。

    案件管理原本就有的 case_stages（時間軸）／data_json.caseRecord.materials
    （叫料）已經是對應功能的超集，不需要新增欄位；這裡只補三個真正缺的能力：
    - case_action_items：代辦事項正規化表（比照 case_stages 的風格），取代
      project_logs.action_items 這個 JSON blob 欄位，保留原本「工程主管
      確認 stage1 → 業務主管確認 stage2」兩階段狀態機（比照
      routers/projects.py::approve_action_item() 的欄位設計）。
    - work_logs.photos：既有「動態」分頁合併顯示的 work_logs 目前是純文字，
      補上照片能力（JSON 陣列，欄位結構比照 project_logs.photos）。
    - quotations.assigned_user_ids：案件成員分配，取代
      projects.assigned_user_ids。

    一次性資料搬移（僅此一次，之後 projects/project_logs/project_stages
    不再由任何前端頁面存取，但刻意不 DROP TABLE，保留作歷史紀錄）：只處理
    「恰好關聯 1 個案件」的 project（2026-08-26 查證當下的 2 筆全部符合），
    project_logs 逐筆轉成 work_logs（work_content→content，photos 直接
    搬），action_items 逐筆轉成 case_action_items。project_stages 這次查
    證的內容都是空白預設「新階段」、無任何日期/完成狀態，且案件本身已有一
    份真正在用的 case_stages，為避免時間軸重複顯示混淆，刻意不搬（若之後
    在其他環境套用這支 migration 時 project_stages 有實質內容，需要另外
    人工評估是否要補搬，這裡不自動處理）。沒有恰好 1 個關聯案件的
    project（0 個或多個）一併跳過，資料仍完整保留在原表，不會遺失。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_action_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_no        TEXT    NOT NULL,
            text            TEXT    NOT NULL DEFAULT '',
            status          TEXT    NOT NULL DEFAULT 'pending',
            stage1_approver TEXT    DEFAULT '',
            stage1_at       TEXT    DEFAULT '',
            stage2_approver TEXT    DEFAULT '',
            stage2_at       TEXT    DEFAULT '',
            sort_order      INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT    NOT NULL,
            created_by      TEXT    DEFAULT '',
            updated_at      TEXT    NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_case_action_items_quote_no ON case_action_items(quote_no)"
    )
    if not _col_exists(conn, "work_logs", "photos"):
        conn.execute("ALTER TABLE work_logs ADD COLUMN photos TEXT NOT NULL DEFAULT '[]'")
    if not _col_exists(conn, "quotations", "assigned_user_ids"):
        conn.execute("ALTER TABLE quotations ADD COLUMN assigned_user_ids TEXT NOT NULL DEFAULT '[]'")
    conn.commit()

    # ── 一次性資料搬移：projects → 對應案件 ──
    fallback_row = conn.execute(
        "SELECT id FROM users WHERE role='superadmin' AND active=1 ORDER BY id LIMIT 1"
    ).fetchone()
    fallback_uid = fallback_row["id"] if fallback_row else None

    name_to_uid = {
        r["display_name"]: r["id"]
        for r in conn.execute(
            "SELECT id, display_name FROM users WHERE display_name != ''"
        ).fetchall()
    }

    now = datetime.now().isoformat()
    for proj in conn.execute("SELECT * FROM projects").fetchall():
        linked = json.loads(proj["linked_cases"] or "[]")
        if len(linked) != 1:
            continue
        quote_no = linked[0]
        if not conn.execute(
            "SELECT 1 FROM quotations WHERE quote_no=?", (quote_no,)
        ).fetchone():
            continue

        assigned = json.loads(proj["assigned_user_ids"] or "[]")
        if assigned:
            conn.execute(
                "UPDATE quotations SET assigned_user_ids=? WHERE quote_no=?",
                (json.dumps(assigned, ensure_ascii=False), quote_no)
            )

        for log in conn.execute(
            "SELECT * FROM project_logs WHERE project_id=? ORDER BY id", (proj["id"],)
        ).fetchall():
            author_uid = name_to_uid.get(log["created_by"]) or fallback_uid
            if author_uid is None:
                continue
            content = log["work_content"] or ""
            if log["created_by"] and log["created_by"] not in name_to_uid:
                content = f"（原記錄人：{log['created_by']}）\n{content}"
            conn.execute(
                "INSERT INTO work_logs (log_date, user_id, content, hours, created_at, created_by, case_no, photos) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (log["log_date"], author_uid, content, 8.0, log["created_at"] or now,
                 author_uid, quote_no, log["photos"] or "[]")
            )
            items = json.loads(log["action_items"] or "[]")
            for idx, item in enumerate(items):
                conn.execute("""
                    INSERT INTO case_action_items
                        (quote_no, text, status, stage1_approver, stage1_at,
                         stage2_approver, stage2_at, sort_order, created_at, created_by, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    quote_no, item.get("text") or "", item.get("status") or "pending",
                    item.get("stage1_approver") or "", item.get("stage1_at") or "",
                    item.get("stage2_approver") or "", item.get("stage2_at") or "",
                    idx, log["created_at"] or now, log["created_by"] or "", log["updated_at"] or now,
                ))
    conn.commit()


def _m063_work_log_contact_type(conn):
    """work_logs 新增 contact_type（2026-08-26）：案件管理「動態」分頁發布
    更新時，執行時數（既有 hours 欄位，先前寫死 8 沒有開放填寫）＋聯絡事項
    類型（新欄位，下拉選單＋「其他」時可輸入自訂文字）補成可用的結構化欄位，
    讓案件動態顯示的資訊更完整，不再只有一段自由文字。"""
    if not _col_exists(conn, "work_logs", "contact_type"):
        conn.execute("ALTER TABLE work_logs ADD COLUMN contact_type TEXT NOT NULL DEFAULT ''")
    conn.commit()


def _m064_network_plans(conn):
    """新增 network_plans（網路架構規劃書，2026-08-26）：工程師可在系統內填寫
    一份客戶網路建置案的完整技術規劃文件（WAN／設備清單／VLAN／IP位址配置／
    PortProfile定義／交換器Port對應／防火牆規則／IP-Port群組／無線SSID／線路
    幹線／修訂紀錄），並匯出 Excel／PDF 給客戶。完整設計依據見專案根目錄
    `NETWORK-PLAN-MODULE-DESIGN.md`（已調閱實際業務範本擬定資料模型）。

    quote_no 選填──比照 case_action_items/payment_requests 的慣例，用
    quotations.quote_no 綁定案件，但這裡刻意允許留空，因為規劃書也常用在
    還沒有案件的售前評估/巡檢場景（使用者確認的取捨）。一案最多一份規劃書
    （用 partial unique index 擋重複 quote_no，NULL 不受限），版本管理採
    「單一文件＋修訂紀錄」而非報價單式 R1/R2 改版鎖定，修訂紀錄存在
    data_json.revision_log 裡，不另開資料表。

    9+1 大類明細全部收在 data_json 一個欄位裡（陣列＋自由物件），不比照
    switch_guide 等選型資料庫拆成多張正規化表──跟 quotations/dev_cases
    的 hot-column + data_json 模式一致，理由是每個案子欄位齊全度差異很大
    （不是每案都有無線SSID或線路幹線資料），拆表反而每次都要處理一堆全
    NULL 的列。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS network_plans (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_no       TEXT    UNIQUE NOT NULL,
            quote_no      TEXT,
            site_name     TEXT    NOT NULL DEFAULT '',
            contact_name  TEXT    NOT NULL DEFAULT '',
            contact_phone TEXT    NOT NULL DEFAULT '',
            status        TEXT    NOT NULL DEFAULT '規劃中',
            created_by    TEXT    NOT NULL DEFAULT '',
            updated_by    TEXT    NOT NULL DEFAULT '',
            created_at    TEXT,
            updated_at    TEXT,
            data_json     TEXT    NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_network_plans_status ON network_plans(status)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_network_plans_quote_no "
        "ON network_plans(quote_no) WHERE quote_no IS NOT NULL"
    )
    conn.commit()


def _m065_automation_guide(conn):
    """Create automation_* tables（自動化系統選型導覽）：倉儲/產線自動化設備分類
    （AGV／AMR／協作型機械手臂／工業型機械手臂）× 場域情境矩陣式交叉，選型資料庫
    第七個類別，資料形狀與 switch_guide／monitor_guide／access_guide／gateway_guide
    相同。見 routers/automation_guide.py 與 automation_guide_seed.py。首批只建立
    情境/分類骨架＋適配矩陣，品牌/型號/報價留待後續獨立任務用 WebSearch 查證補上
    （PRODUCTS_JSON 這次是空陣列）。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS automation_scenarios (
            code       TEXT PRIMARY KEY,
            name       TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS automation_categories (
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
        CREATE TABLE IF NOT EXISTS automation_fit (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_code TEXT NOT NULL REFERENCES automation_scenarios(code) ON DELETE CASCADE,
            category_code TEXT NOT NULL REFERENCES automation_categories(code) ON DELETE CASCADE,
            fit_level     TEXT NOT NULL DEFAULT '',
            fit_note      TEXT NOT NULL DEFAULT '',
            sort_order    INTEGER NOT NULL DEFAULT 0,
            updated_at    TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS automation_products (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_code TEXT NOT NULL REFERENCES automation_categories(code) ON DELETE CASCADE,
            brand         TEXT NOT NULL DEFAULT '',
            model         TEXT NOT NULL DEFAULT '',
            url           TEXT NOT NULL DEFAULT '',
            label         TEXT NOT NULL DEFAULT '',
            price_note    TEXT NOT NULL DEFAULT '',
            specs_json    TEXT NOT NULL DEFAULT '[]',
            sort_order    INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_automation_fit_scenario ON automation_fit(scenario_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_automation_fit_category ON automation_fit(category_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_automation_prod_category ON automation_products(category_code)")

    if conn.execute("SELECT 1 FROM automation_scenarios LIMIT 1").fetchone():
        conn.commit()
        return

    from automation_guide_seed import SCENARIOS_JSON, CATEGORIES_JSON, FIT_JSON, PRODUCTS_JSON
    now = datetime.now().isoformat()
    for i, s in enumerate(json.loads(SCENARIOS_JSON)):
        conn.execute(
            "INSERT INTO automation_scenarios (code, name, description, sort_order, updated_at) VALUES (?,?,?,?,?)",
            (s[0], s[1], s[2], i, now),
        )
    for i, c in enumerate(json.loads(CATEGORIES_JSON)):
        conn.execute(
            "INSERT INTO automation_categories "
            "(code, name, key_specs, tags, price_range, dependency_note, watch_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (c[0], c[1], c[2], c[3], c[4], c[5], c[6], i, now),
        )
    for i, f in enumerate(json.loads(FIT_JSON)):
        conn.execute(
            "INSERT INTO automation_fit (scenario_code, category_code, fit_level, fit_note, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (f[0], f[1], f[2], f[3], i, now),
        )
    for i, p in enumerate(json.loads(PRODUCTS_JSON)):
        conn.execute(
            "INSERT INTO automation_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (p[0], p[1], p[2], p[3], p[4], p[5], p[6], i),
        )
    conn.commit()


def _m067_approval_delegates(conn):
    """簽核代理人機制（2026-08-28，企業管理優化）：目前簽核只有「代理送審」
    （approval.delegateSubmitter，申請人請人代為送出申請），沒有「代理簽核」——
    tiers 裡的簽核人若請假，除了 superadmin 外沒有人能代替他完成該層簽核，容易
    卡住整條簽核鏈（尤其正式機目前 superadmin 只有 jeff/corbin 兩人，見
    MOTRIX-ERP-QUICK.md §12 相關討論）。

    新表 approval_delegates：一筆＝「delegator_username 把自己的簽核權限在
    [start_date, end_date] 區間內暫時交給 delegate_username」，可以同時有多筆
    （例如一人請假期間委託兩個不同的人分擔不同天數）。純粹是「誰可以代替誰在
    tiers 裡簽核」的授權表，不影響 tiers 本身記錄的原始 approver username——
    委託人的名字仍照舊出現在 approval.tiers[].approvers[].username，check_approve_
    permission()/check_reject_permission()（見 helpers/tiered_approval.py）
    比對時額外允許「目前對這個 username 持有有效代理權的人」通過，是否真的
    透過代理身分完成的，由呼叫端事後從 _audit() 的操作者本人（非委託人）
    自然看得出來，不需要另外在 tiers JSON 裡疊一份標記。

    active=0 代表已停用（提早結束代理或設錯了想撤銷），不刪列，保留歷史紀錄。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS approval_delegates (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            delegator_username  TEXT    NOT NULL,
            delegate_username   TEXT    NOT NULL,
            start_date          TEXT    NOT NULL,
            end_date            TEXT    NOT NULL,
            reason              TEXT    DEFAULT '',
            active              INTEGER NOT NULL DEFAULT 1,
            created_by          TEXT    DEFAULT '',
            created_at          TEXT    NOT NULL,
            updated_at          TEXT    NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_delegates_delegate ON approval_delegates(delegate_username, active)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_delegates_delegator ON approval_delegates(delegator_username)"
    )
    conn.commit()


def _m072_totp(conn):
    """使用者帳號新增 TOTP 兩步驟驗證欄位（2026-09-07）：架構地圖 §6.2 建議
    superadmin 至少加 TOTP（目前只有密碼＋Bearer token 單因子），採自助啟用
    模式（非強制）——正式機 superadmin 是 jeff/corbin 兩位真人業主，若做成
    下次登入強制進入設定流程，部署當下他們手邊若沒有先裝好驗證 App 會直接
    被鎖在外面，屬於會中斷真實業務的風險；改為任何角色都可以自行到帳號設定
    開啟，`routers/auth.py` 對 admin/superadmin 登入後未開啟時顯示提醒 banner
    （純前端 UI 提醒，不阻擋操作）。

    - `totp_secret`：base32 密鑰明文存放（TOTP 標準做法就是伺服器保有明文密鑰
      才能重新計算驗證碼比對，跟密碼雜湊不同，不能做成不可逆雜湊）；未啟用
      或尚未完成驗證的暫存密鑰也共用此欄位（`totp_enabled=0` 期間視為「設定中
      尚未生效」，重新呼叫 setup 端點會覆蓋掉舊的暫存值）
    - `totp_enabled`：0/1，只有走完「輸入一次正確驗證碼」的確認流程才會被設
      成 1，避免使用者掃了 QR code 但 App 設定錯誤、之後永遠登不進去
    - `totp_recovery_codes`：JSON 陣列，存 10 組一次性救援碼的雜湊值（比照
      密碼用 `_hash_pw()`，不存明文），供驗證 App 遺失時（換手機、App 被刪）
      仍能登入；每組用過就從陣列移除，見 `routers/auth.py` 使用處"""
    for col, ddl in (
        ("totp_secret", "TEXT NOT NULL DEFAULT ''"),
        ("totp_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("totp_recovery_codes", "TEXT NOT NULL DEFAULT '[]'"),
    ):
        if not _col_exists(conn, "users", col):
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
    conn.commit()


def _m073_webauthn_credentials(conn):
    """使用者帳號新增 WebAuthn/Passkey 裝置綁定登入（2026-09-09）：比照 TOTP
    的自助啟用模式（非強制），允許使用者在多個裝置（Windows Hello、Touch ID、
    Yubikey 等）上儲存 Passkey 憑證。

    與 TOTP 不同，Passkey 是每張憑證有自己的生命週期（簽名計數遞增防複製、
    可個別改名/撤銷），所以獨立建表 `webauthn_credentials` 而非 JSON 陣列存在
    users 表（比照 `sessions` 表的先例）。不加 FOREIGN KEY 約束（同 sessions）。

    - `credential_id`：W3C 認證器標準定義的憑證 ID（二進位），BLOB 類型並加
      UNIQUE 約束（全球唯一）
    - `public_key`：COSE 編碼的公鑰（二進位），由 webauthn 庫回傳並透明儲存
    - `name`：使用者自定義易讀名稱（"iPhone"、"Windows Hello"），支援改名
    - `sign_count`：簽名計數，每次成功登入遞增（防重放攻擊偵測用）
    - `created_at`：憑證建立時間
    - `last_used_at`：最後一次成功登入時間（用於排序/顯示使用情況）"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS webauthn_credentials (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            credential_id BLOB NOT NULL UNIQUE,
            public_key   BLOB NOT NULL,
            name         TEXT NOT NULL DEFAULT '',
            sign_count   INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL,
            last_used_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_webauthn_credentials_user_id ON webauthn_credentials(user_id)")
    conn.commit()


def _m074_webauthn_rp_id(conn):
    """`webauthn_credentials` 補上 `rp_id` 欄位（2026-09-11）。

    v73 建表時刻意沒存 rp_id，代價在 2026-09-11 規劃改用公開憑證時才浮現：
    Passkey 憑證是被瀏覽器綁在「註冊當下那個 RP ID」上的，一旦 RP ID 變更，
    所有既有憑證都會失效——**而系統查不出哪一張屬於哪個 RP**，只能：

      - 在設定端點回報「全部 N 張都會失效」（連哪幾張真的受影響都說不準）
      - 讓使用者在裝置清單看到一張外觀正常、實際上永遠驗不過的殭屍憑證
      - 登入失敗時只能回一句概括的「認證失敗」

    補上這個欄位之後，上面三件事都能講清楚：失效的憑證查得出來、清單標得出來、
    登入失敗時能回「此 Passkey 在舊網域註冊，已失效，請重新註冊」。

    ⚠️ **這個欄位救不回已經簽發的憑證**——瀏覽器端的綁定不在我們手上，改了
    RP ID 就是失效。它讓失效變成「可見、可通知、可清理」，不是讓它可逆。
    也因此它必須在**下一次變更 RP ID 之前**就位才有意義。

    回填：既有憑證全部是在目前這組設定下註冊的（本表 2026-09-09 才建立，
    期間 RP ID 只設定過 `motrix.internal` 一次），所以直接回填當前設定值。
    設定為空時留空字串，代表「不明」——查詢端一律把空值當成「與現行相符」，
    以免把還能用的憑證誤標成失效。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(webauthn_credentials)").fetchall()}
    if "rp_id" not in cols:
        conn.execute("ALTER TABLE webauthn_credentials ADD COLUMN rp_id TEXT NOT NULL DEFAULT ''")

    row = conn.execute(
        "SELECT value_json FROM system_settings WHERE key='webauthn_rp_id'").fetchone()
    current_rp = ""
    if row:
        try:
            current_rp = json.loads(row["value_json"]) or ""
        except Exception:
            current_rp = ""
    if current_rp:
        conn.execute("UPDATE webauthn_credentials SET rp_id=? WHERE rp_id=''", (current_rp,))
    conn.commit()


def _m071_paid_bank_account(conn):
    """付款事件新增「MOTRIX 自己是用哪個銀行帳戶付的」欄位（2026-09-01）：
    使用者要求 T100 科目代號要能依銀行帳戶分開設定（一間公司可能有多個銀行
    帳戶，各自對應不同的 T100 銀行存款科目）。

    ⚠️ 這跟 `contractor_payment_vouchers` 既有的 `snapshot_json.bankAccountName/
    bankAccountNumber` 是完全不同的概念，不要混淆：既有欄位是**承攬商（收款方）
    的收款帳戶**（建立申請當下凍結快照，用來告訴財務要匯去哪個戶頭）；這裡新增
    的是**MOTRIX 自己（付款方）用哪個帳戶付出去的**，標記已匯款當下才會知道，
    無法在建立申請時就預先知道，所以是獨立欄位、獨立時機寫入。

    只加在 `contractor_payment_vouchers`／`stock_batches` 兩張表（今天才新增
    的低流量 paid-toggle 流程）。報價單款項收款（`quotations.data_json.
    caseRecord.payment.items[idx]`）走 JSON blob，不需要 migration，直接在
    `mark_payment()` 多存 `bankAccountName`/`bankAccountCode` 兩個 key 即可，
    比照既有 `invoiceNo`/`actualAmount` 的做法。"""
    for col in ("paid_bank_account_name", "paid_bank_account_code"):
        if not _col_exists(conn, "contractor_payment_vouchers", col):
            conn.execute(f"ALTER TABLE contractor_payment_vouchers ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        if not _col_exists(conn, "stock_batches", col):
            conn.execute(f"ALTER TABLE stock_batches ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
    conn.commit()


def _m070_stock_batches(conn):
    """進貨批次新增獨立表頭 `stock_batches`（2026-09-01）：`stock_items` 原本
    沒有獨立批次父表，`batch_no` 只是共用字串，供應商/付款狀態這類「批次層級」
    屬性完全沒地方放（見 `_m068` 附近文件註解「無獨立 stock_batches 父表」）。

    使用者要求把「料件/設備進貨」納入 T100 傳票匯出（現金基礎），但進貨本身
    完全沒有「是否已付款」的追蹤——這是本次要補的前置功能，不只是匯出模組
    的擴充。設計比照 `contractor_payment_vouchers` 既有的 is_paid/paid_by/
    paid_at 三欄模式。

    一個 `create_batch()` 呼叫只會建立單一 part_no 的一批序號（見
    `routers/inventory.py::create_batch()`），batch_no 與 part_no 天生 1:1，
    所以可以安全地把既有資料回填成一筆 stock_batches header。`qty`/
    `total_cost` 刻意不快取在 header（避免跟之後 `adjust_stock_item()`
    的人工調整脫鉤），改由呼叫端即時從 `stock_items` 用 batch_no 群組 SUM。

    **⚠️ 回填的既有批次一律預設 `is_paid=0`（未付款）**——系統過去從未追蹤
    這件事，不能假設「有進貨紀錄＝已付款」，也不能假設「未付款」；這是誠實
    反映「系統從未知道過」的預設值，財務團隊首次使用這個功能時，需要回頭
    逐批確認歷史進貨是否已付款（或用批次匯入方式一次性標記，见 §7.18
    docstring）。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_batches (
            batch_no      TEXT PRIMARY KEY,
            part_no       TEXT NOT NULL DEFAULT '',
            supplier_id   INTEGER,
            supplier_name TEXT NOT NULL DEFAULT '',
            invoice_no    TEXT NOT NULL DEFAULT '',
            is_paid       INTEGER NOT NULL DEFAULT 0,
            paid_by       TEXT NOT NULL DEFAULT '',
            paid_at       TEXT NOT NULL DEFAULT '',
            note          TEXT NOT NULL DEFAULT '',
            created_by    TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL DEFAULT '',
            updated_at    TEXT NOT NULL DEFAULT ''
        )
    """)
    existing = {r["batch_no"] for r in conn.execute("SELECT batch_no FROM stock_batches").fetchall()}
    rows = conn.execute("""
        SELECT batch_no, MIN(part_no) AS part_no, MIN(created_by) AS created_by, MIN(created_at) AS created_at
        FROM stock_items WHERE batch_no != '' GROUP BY batch_no
    """).fetchall()
    for r in rows:
        if r["batch_no"] in existing:
            continue
        conn.execute(
            "INSERT INTO stock_batches (batch_no, part_no, created_by, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (r["batch_no"], r["part_no"] or "", r["created_by"] or "", r["created_at"] or "", r["created_at"] or ""),
        )
    conn.commit()


def _m069_t100_export_confirmations(conn):
    """T100（鼎新）傳票批次匯出的「已匯入確認」追蹤表（2026-09-01）：使用者要求
    「匯入由財務單位確認，已匯入自動排除」——匯出 Excel 本身不代表財務真的把
    這批傳票匯入了 T100（可能匯出後發現資料有誤沒有真的匯入），所以匯出跟
    「標記已匯入」是兩個獨立動作；只有明確標記過的事件才會在之後的匯出範圍
    自動排除，避免同一筆事件被財務重複匯入 T100 造成金額灌水。

    source_type/source_key 是這筆事件在原始資料表的穩定識別碼（不用 accounting_
    export.py 內部產生的 AR0001/AP0002 這種每次匯出重算的流水號，那個不穩定）：
      - 'quotation_payment' → f"{quote_no}::{invoiceNo}"（invoiceNo 是財務開立
        發票時填的自由文字欄位，同一張報價單同一個發票號碼理論上只會出現一次）
      - 'contractor_voucher' → voucher_no（PV-YYYYMM-NNN，全域唯一）
    UNIQUE(source_type, source_key) 讓「標記已匯入」動作天生冪等，同一筆事件
    重複標記不會產生兩筆紀錄。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS t100_export_confirmations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type  TEXT NOT NULL,
            source_key   TEXT NOT NULL,
            event_date   TEXT NOT NULL DEFAULT '',
            amount       REAL NOT NULL DEFAULT 0,
            summary      TEXT NOT NULL DEFAULT '',
            confirmed_by TEXT NOT NULL DEFAULT '',
            confirmed_at TEXT NOT NULL DEFAULT '',
            UNIQUE(source_type, source_key)
        )
    """)
    conn.commit()


def _m068_dispatch_payable_date_invoice_files(conn):
    """承攬商派發新增應付款日期（payable_date）與廠商發票附件（invoice_files_json）
    （2026-08-30）：使用者要求填寫派發時可指定這筆款項的應付款日期，並上傳
    廠商提供的發票（跟既有 invoice_no 純文字發票號碼、files_json 的「承攬商
    報價/估價文件」是不同概念，各自獨立欄位不要混用）。

    產生匯款申請時（contractor_vouchers.py::create_contractor_voucher）會把
    這兩個欄位一併寫入 snapshot_json 凍結快照，供簽核佇列／申請單 PDF 顯示，
    比照既有 bankAccountNumber/bankPassbookImage 凍結快照的做法。"""
    if not _col_exists(conn, "contractor_dispatches", "payable_date"):
        conn.execute("ALTER TABLE contractor_dispatches ADD COLUMN payable_date TEXT DEFAULT ''")
    if not _col_exists(conn, "contractor_dispatches", "invoice_files_json"):
        conn.execute(
            "ALTER TABLE contractor_dispatches ADD COLUMN invoice_files_json TEXT NOT NULL DEFAULT '[]'"
        )
    conn.commit()


def _m066_parts_safety_stock(conn):
    """parts 新增 safety_stock（2026-08-28，視覺化管理優化：庫存水位燈號）：
    料號可設定安全庫存量，庫存管理頁依此對比目前在庫數量顯示紅/黃/綠燈號。
    預設 0＝未設定安全庫存，此時一律顯示綠燈（不強迫每個料號都要設定門檻）。"""
    if not _col_exists(conn, "parts", "safety_stock"):
        conn.execute("ALTER TABLE parts ADD COLUMN safety_stock INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def _m057_payment_request_stage(conn):
    """請款單新增 stage（款項類別：full/deposit/delivery/acceptance/final，
    2026-08-24）：客戶端請款單 PDF「請款範圍」欄要顯示業務語意的分類（全額/
    訂金款/交貨款/驗收款/尾款），而不是內部 scope（amount/items）技術性描述。
    兩個欄位並存，stage 純粹是顯示用標籤，不影響 scope 既有的金額計算方式。"""
    if not _col_exists(conn, "payment_requests", "stage"):
        conn.execute("ALTER TABLE payment_requests ADD COLUMN stage TEXT NOT NULL DEFAULT ''")
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


def _m056_user_list_prefs(conn):
    """每位使用者對各清單（報價單列表／案件管理案件清單／案件內單據子清單…）的
    排序偏好——排序欄位/正倒序，或拖曳自訂順序（DB v56，2026-08-24）。
    list_key 用來區分不同清單/範圍：頂層清單固定字串（如 'quotations'／
    'case_list'），案件內單據子清單則帶上 quote_no 範圍（如
    'shipping_notes:MQ-202608-001'）——後端完全不解析這個字串的內容，純粹
    當作 opaque key，範圍規則由前端呼叫端自行決定。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_list_prefs (
            username     TEXT    NOT NULL,
            list_key     TEXT    NOT NULL,
            sort_mode    TEXT    NOT NULL DEFAULT '',
            sort_dir     TEXT    NOT NULL DEFAULT 'desc',
            custom_order TEXT    NOT NULL DEFAULT '[]',
            updated_at   TEXT    NOT NULL DEFAULT '',
            PRIMARY KEY (username, list_key)
        )
    """)
    conn.commit()


def _m055_case_stage_calendar_event(conn):
    """案件執行進度階段到期日 → Google 行事曆（2026-08-24，helpers/google_calendar.py
    擴充第 7 種推送事件）。跟既有 6 種「只建立、不更新」的事件不同，階段到期日
    常常會被使用者事後調整（延期），這裡需要真正的 upsert 而非每次都新建一筆，
    所以要記住上一次建立的事件 id 才能之後 PATCH／DELETE，比照
    quotations/shipping_notes/invoice_vouchers 把 googleCalendarEventId 存進
    data_json 的既有做法——但 case_stages 是獨立的表沒有 data_json，改開專用欄位。"""
    if not _col_exists(conn, "case_stages", "google_calendar_event_id"):
        conn.execute("ALTER TABLE case_stages ADD COLUMN google_calendar_event_id TEXT NOT NULL DEFAULT ''")
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
def _move_extra_items_for_quote(conn, quote_no, data, sales_person=""):
    """把一張報價單 data_json 裡的 `settlement.extraItems[]` 搬進 `case_extra_expenses`。

    從 `_m075_case_extra_expenses()` 抽出來的單筆版本，理由是**測試也需要同一套邏輯**
    ——歸月日期的四層 fallback 若在測試裡另外複製一份，兩邊遲早會漂移，而漂移的後果
    是「報表數字對不上」這種很難追的問題。回傳搬移筆數。
    """
    stl = (data.get("settlement") or {})
    items = stl.get("extraItems") or []
    if not items:
        return 0

    # 推定填寫人：精算完結人 → 業務 → 留空
    inferred = (stl.get("finalizedBy") or "").strip() or (sales_person or "").strip()

    # ⚠️ 歸月日期的 fallback 必須跟舊的 settlement_extra_expenses() 一致，
    # 否則搬完之後這些錢會從月支出報表整筆消失。實測開發機 7 筆既有資料裡
    # **有 6 筆 expenseDate 與 createdDate 都是空的**，全靠 editHistory 的
    # 精算存檔時間歸月——少了這一層，7,990 元會無聲蒸發，正是 2026-09-09
    # 修過的那一類問題（當月花掉的錢在報表上憑空不見）。
    finalized_at = last_saved_at = ""
    for h in (data.get("editHistory") or []):
        htype = h.get("type") or ""
        if htype == "settlement_finalized":
            finalized_at = h.get("at") or finalized_at
        if htype in ("settlement_finalized", "settlement_draft"):
            last_saved_at = h.get("at") or last_saved_at

    moved = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        created = ((it.get("createdDate") or "").strip()
                   or (it.get("expenseDate") or "").strip()
                   or finalized_at or last_saved_at or "")[:10]
        real_by = (it.get("createdBy") or "").strip()
        conn.execute(
            "INSERT INTO case_extra_expenses "
            "(quote_no, category, description, qty, unit, unit_cost, total_cost, note, "
            " expense_date, doc_no, files_json, created_by_name, created_by_inferred, "
            " created_at, updated_at, status, approval_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                quote_no,
                (it.get("category") or "其他"),
                # description 是精算表單現行的欄位名；name/desc 是更早期的欄位名，
            # 舊的 settlement_extra_expenses() 有這層 fallback，搬移時必須一起帶過來，
            # 否則舊資料的品項說明會整欄變空白（報表明細只剩類別，對不回憑證）
            (it.get("description") or it.get("name") or it.get("desc") or ""),
                float(it.get("qty") or 0),
                (it.get("unit") or ""),
                float(it.get("unitCost") or 0),
                float(it.get("totalCost") or 0),
                (it.get("note") or ""),
                (it.get("expenseDate") or ""),
                (it.get("docNo") or ""),
                json.dumps(it.get("files") or [], ensure_ascii=False),
                real_by or inferred,
                0 if real_by else (1 if inferred else 0),
                created,
                created,
                "已核准",
                json.dumps({"migrated": True,
                            "note": "2026-09-11 從 settlement.extraItems 搬移，"
                                    "建立時尚無送審機制，一律視為已核准"},
                           ensure_ascii=False),
            ),
        )
        moved += 1
    return moved


def _m075_case_extra_expenses(conn):
    """額外支出從 `settlement.extraItems`（data_json）正規化成 `case_extra_expenses` 表（2026-09-11）。

    **為什麼要正規化**：使用者交辦把額外支出從精算頁搬到案件管理，並要求「填寫需送審」
    與記錄「填寫日期／更動日期」。送審狀態與更動軌跡塞在 data_json 的陣列裡會很難查
    （沒有 id 可掛簽核狀態、改一筆要整包重寫、歷史無從追）——比照 `case_stages`
    當初從 data_json 正規化出來的前例，直接建表。規格見 `MOTRIX-ERP-QUICK.md` §5.10。

    **這支 migration 會搬資料，不只是建表**。既有 `settlement.extraItems[]` 全部搬進新表，
    搬完之後**刻意保留** data_json 裡的原陣列不刪除：

      - 萬一新表出問題，原始資料還在，救得回來
      - 但所有讀取端都已改讀新表（`helpers/quotations.py::case_extra_expenses()`），
        原陣列從此是**唯讀的歷史備份，不再被任何程式碼寫入**
      - 清掉它是之後確認新流程穩定後的獨立動作，不在這支 migration 裡做

    **搬過來的資料一律標成「已核准」**：它們是在送審機制存在之前就建立並計入成本的，
    若標成「待審核」會讓所有既有案件突然冒出一堆待簽核項目、並在核准前從成本裡消失，
    是憑空製造的混亂。`approval_json` 記 `migrated: True` 以便日後區分。

    **填寫人回填（使用者指定要回填）**：既有資料沒有記錄誰建立的——`settlement.html`
    寫入 `createdBy` 時取的是 `this.session?.user?.display_name`，那個路徑在這個專案的
    session 結構裡不存在（其他地方都是 `this.session.displayName`），所以**實測 7 筆
    既有項目，createdBy 有值的是 0 筆**。既然沒有真實紀錄，回填只能用推定：

      精算完結人 `settlement.finalizedBy` → 報價單業務 `sales_person` → 留空

    推定的一律把 `created_by_inferred` 設為 1，畫面上要標示「（推定）」。
    **不要把推定值當成事實**——這是回填，不是還原。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_extra_expenses (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_no           TEXT NOT NULL,
            category           TEXT NOT NULL DEFAULT '其他',
            description        TEXT NOT NULL DEFAULT '',
            qty                REAL NOT NULL DEFAULT 1,
            unit               TEXT NOT NULL DEFAULT '',
            unit_cost          REAL NOT NULL DEFAULT 0,
            total_cost         REAL NOT NULL DEFAULT 0,
            note               TEXT NOT NULL DEFAULT '',
            expense_date       TEXT NOT NULL DEFAULT '',
            doc_no             TEXT NOT NULL DEFAULT '',
            files_json         TEXT NOT NULL DEFAULT '[]',
            created_by         TEXT NOT NULL DEFAULT '',
            created_by_name    TEXT NOT NULL DEFAULT '',
            created_by_inferred INTEGER NOT NULL DEFAULT 0,
            payer_username     TEXT NOT NULL DEFAULT '',
            payer_name         TEXT NOT NULL DEFAULT '',
            created_at         TEXT NOT NULL DEFAULT '',
            updated_at         TEXT NOT NULL DEFAULT '',
            updated_by_name    TEXT NOT NULL DEFAULT '',
            status             TEXT NOT NULL DEFAULT '草稿',
            approval_json      TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_case_extra_exp_quote ON case_extra_expenses(quote_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_case_extra_exp_status ON case_extra_expenses(status)")

    # 已經搬過就不要再搬一次（migration 本身要可重跑）
    if conn.execute("SELECT 1 FROM case_extra_expenses LIMIT 1").fetchone():
        return

    rows = conn.execute(
        "SELECT quote_no, data_json, sales_person FROM quotations "
        "WHERE json_extract(data_json,'$.settlement.extraItems') IS NOT NULL"
    ).fetchall()

    moved = 0
    for r in rows:
        try:
            data = json.loads(r["data_json"] or "{}")
        except Exception:
            continue
        moved += _move_extra_items_for_quote(conn, r["quote_no"], data, r["sales_person"])

    if moved:
        logger.info("_m075: 搬移 %d 筆額外支出到 case_extra_expenses（data_json 原陣列保留為唯讀備份）", moved)


def _m076_xe_change_requests_and_stage_done(conn):
    """兩件事（2026-09-11 第二輪交辦）：額外支出的「已核准後編輯＝變更申請」，
    以及案件執行進度「勾選完成」要同步到行事曆。

    **一、`case_extra_expenses` 的三個 change_* 欄位**

    使用者指定：已核准的那筆**金額不動**，編輯內容要等簽核通過才生效。所以不能沿用
    既有的 `status`/`approval_json`（那兩個一動，報表數字當場就變了，等於沒有簽核）。
    改成把「提議的新內容」另外存一份，核准的瞬間才覆蓋回本體：

      - `change_status`        '' / 草稿 / 待審核 / 簽核中 / 已駁回
      - `change_json`          提議的新欄位值 ＋ `addFiles[]`（待核准附件）
      - `change_approval_json` 變更申請自己的簽核狀態（形狀同 `approval_json`）

    **為什麼用獨立欄位而不是共用 `approval_json`**：一筆已核准的支出可能被改很多次，
    每次都是一輪獨立簽核。共用一欄的話，變更申請一送出就會蓋掉「這筆原本是誰核准的」
    ——那正是之後查帳要看的東西。原核准紀錄留在 `approval_json`，歷次變更的結果
    append 進 `approval_json.changeHistory`。

    **二、`case_stages.google_calendar_done_event_id` / `daily_task_id`**

    既有的 `google_calendar_event_id`（v55）記的是**到期日**事件，跟這次要做的
    **完成日**事件是兩個不同日期、不同語意的事件，共用一欄會互相覆蓋（設了到期日
    再勾完成，後者會把前者的事件改成完成日，到期提醒就消失了）。所以另開一欄。

    `daily_task_id` 記的是同步到「每日工作事項」月曆的那一列（使用者要求兩邊都要）。
    取消勾選要能把它刪掉，沒有 id 就只能靠標題比對去猜，改個標題就對不上了。
    """
    for col, ddl in (
        ("change_status",        "TEXT NOT NULL DEFAULT ''"),
        ("change_json",          "TEXT NOT NULL DEFAULT '{}'"),
        ("change_approval_json", "TEXT NOT NULL DEFAULT '{}'"),
    ):
        if not _col_exists(conn, "case_extra_expenses", col):
            conn.execute(f"ALTER TABLE case_extra_expenses ADD COLUMN {col} {ddl}")

    if not _col_exists(conn, "case_stages", "google_calendar_done_event_id"):
        conn.execute("ALTER TABLE case_stages ADD COLUMN google_calendar_done_event_id TEXT NOT NULL DEFAULT ''")
    if not _col_exists(conn, "case_stages", "daily_task_id"):
        conn.execute("ALTER TABLE case_stages ADD COLUMN daily_task_id INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def _m077_completion_notes(conn):
    """完工單（`completion_notes`）——2026-09-12 交辦。

    使用者：「在案件管理內增加完工單的選項，參考出貨單的形式跟內容建立完工單，
    一樣走流程申請完工。」所以這張表刻意跟 `shipping_notes` 同構：一個報價單
    可以有多張完工單（分階段完工／分區完工），走同一套分層簽核，核准後客戶回簽。

    **跟出貨單不一樣的欄位，以及為什麼**（照台灣工程業完工單慣例）：

    | 欄位 | 為什麼要 |
    |---|---|
    | `site_address` | 出貨單問的是「送到哪」，完工單問的是「在哪裡施工」，常常不同地點 |
    | `start_date` / `completion_date` | 完工單的核心就是這兩個日期——保固起算、逾期罰則、工期爭議全看它 |
    | `site_manager` | 我方現場負責人。出了問題要找得到人，不是找開單的人 |
    | `recipient` | 客戶方驗收人。回簽欄位簽的就是他 |
    | `work_summary` | 施工說明／工作摘要，敘述性的，不是逐項清單 |
    | `test_result` | 測試與檢驗結果。弱電／監控／門禁這類驗收一定要有 |
    | `warranty_months` | 保固月數。**保固自完工日起算**，所以非得跟完工日放同一張單不可 |
    | `pending_items` | 遺留事項／待改善。**這欄最重要也最常被省略**——完工不等於零缺失，不留這欄就會變成「先簽了再說」，之後爭議沒有依據 |

    品項 `items_json` 比照出貨單的形狀，多一個 `status`（完成／部分完成／未施作），
    因為完工單的品項本來就可能不是每一項都 100% 完成——那正是 `pending_items`
    要對應的東西。

    **刻意不做的**：不自動建立保固追蹤紀錄。保固模組有自己的資料來源與流程，
    在這裡偷偷塞一筆會變成兩套來源打架；先把 `warranty_months` 存好、PDF 上印
    出保固起訖，要不要接進保固追蹤之後另議。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS completion_notes (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            note_no           TEXT    NOT NULL UNIQUE,
            quote_no          TEXT    NOT NULL,
            status            TEXT    NOT NULL DEFAULT '草稿',
            customer_name     TEXT    NOT NULL DEFAULT '',
            project_name      TEXT    NOT NULL DEFAULT '',
            site_address      TEXT    NOT NULL DEFAULT '',
            start_date        TEXT    NOT NULL DEFAULT '',
            completion_date   TEXT    NOT NULL DEFAULT '',
            site_manager      TEXT    NOT NULL DEFAULT '',
            recipient         TEXT    NOT NULL DEFAULT '',
            items_json        TEXT    NOT NULL DEFAULT '[]',
            work_summary      TEXT    NOT NULL DEFAULT '',
            test_result       TEXT    NOT NULL DEFAULT '',
            warranty_months   INTEGER NOT NULL DEFAULT 12,
            pending_items     TEXT    NOT NULL DEFAULT '',
            notes             TEXT    NOT NULL DEFAULT '',
            data_json         TEXT    NOT NULL DEFAULT '{}',
            is_signed         INTEGER NOT NULL DEFAULT 0,
            signed_by         TEXT    NOT NULL DEFAULT '',
            signed_at         TEXT    NOT NULL DEFAULT '',
            signed_log        TEXT    NOT NULL DEFAULT '[]',
            signed_files_json TEXT    NOT NULL DEFAULT '[]',
            export_count      INTEGER NOT NULL DEFAULT 0,
            export_log        TEXT    NOT NULL DEFAULT '[]',
            created_by        TEXT    NOT NULL DEFAULT '',
            created_at        TEXT    NOT NULL DEFAULT '',
            updated_at        TEXT    NOT NULL DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_completion_notes_quote ON completion_notes(quote_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_completion_notes_status ON completion_notes(status)")
    conn.commit()


def _m078_completion_contact_phone(conn):
    """完工單加 `contact_phone`（2026-09-12）。

    使用者要求「基本資料可拉報價單的地址包含聯絡人」——報價單的聯絡人資訊是
    `contactName` / `contactPhone` / `contactEmail` 三件套，完工單原本只有
    `recipient`（驗收人姓名），少了電話。完工單是會交到客戶手上、之後可能要回頭
    聯絡的文件，只有名字沒有電話等於還要再去翻報價單。

    **開欄位而不是塞 data_json**：這是業務資料不是版面設定（標題那組是後者，所以
    放 data_json）。日後若要「查某支電話關聯哪些完工單」也查得到。
    """
    if not _col_exists(conn, "completion_notes", "contact_phone"):
        conn.execute("ALTER TABLE completion_notes ADD COLUMN contact_phone TEXT NOT NULL DEFAULT ''")
    conn.commit()


def _m079_user_activity(conn):
    """在線時間統計（2026-09-14 使用者要求：「右上角顯示在線成員與數量，並統計每個
    成員在線上的時間，這些數據只有超級管理員看得到」）。

    **為什麼是「每人每天一列」而不是逐次登入的區間表**：需求是「累計時數」，
    而 session 可以同時多個（同一個人電腦＋手機）、可以被閒置逾時砍掉、也可能
    整天不登出。區間表要處理重疊與未關閉的區間，查詢時還得逐段相加；每天一列的
    累加器把那些問題都留在寫入端，查詢就只是 SUM。

    **秒數怎麼來**：`main.py::auth_middleware` 每次請求都會算「距離上次活躍多久」，
    那個差值本來就是既有的閒置判斷在用的。差值在門檻內就視為這段時間人在線上、
    累加進當天；超過門檻代表中間離開過，只重新起算、不補那段空白。
    上限在 `_ACTIVITY_GAP_MAX`（main.py），避免把「昨天關電腦、今天才回來」算成
    連續在線。

    `day` 存台灣本地日期字串（比照全系統其他時間欄位一律用 `datetime.now()`），
    不是 UTC——報表是給人看的，跨日要以人的作息為準。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_activity_daily (
            user_id        INTEGER NOT NULL,
            day            TEXT    NOT NULL,
            active_seconds INTEGER NOT NULL DEFAULT 0,
            first_seen_at  TEXT    NOT NULL DEFAULT '',
            last_seen_at   TEXT    NOT NULL DEFAULT '',
            PRIMARY KEY (user_id, day)
        )
    """)
    # 報表一律以「日期區間 + 全部使用者」查詢，day 放前面才吃得到索引
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_activity_day ON user_activity_daily(day, user_id)")
    conn.commit()


def _m080_user_request_log(conn):
    """逐條操作軌跡（2026-09-14 使用者要求：「在線時數統計，同步能看使用者點了
    什麼看了什麼，逐條紀錄」）。

    **跟既有 `audit_log` 的分工**：`audit_log` 記的是「**改了什麼**」（建立/修改/
    刪除，帶實體與摘要，是業務稽核用的），這張表記的是「**去過哪裡、點了什麼**」
    ——包含純檢視的 GET。兩者不合併：audit_log 的每一列都要有業務語意，塞進 GET
    會把它稀釋成流水帳，反而讓真正的稽核查不動。

    **`page` 欄位來自 Referer**：瀏覽器的 fetch 會自動帶上，等於免費拿到「使用者
    當時站在哪一頁」，不必去每個頁面插埋點。取不到就留空。

    **刻意不記的東西**：
    - 輪詢類端點（通知、模組紅點、在線名單、ping…）——那是機器行為不是人的行為，
      記了只會把軌跡淹掉，見 `trail.py::SKIP_PREFIXES`（2026-09-15 從 main.py 搬過去，
      寫入端與讀取端共用同一份清單）
    - 請求內容（body / query 值）——軌跡是「誰在什麼時候看了哪一頁、動了哪個資源」，
      把內容也記下來等於在資料庫裡多存一份業務資料的副本，外洩風險與價值不成比例
    - 密碼、token 一類自然也不會進來（只存 method + path）

    **保留期限**：`daily_tasks.py::_prune_request_log()` 每天清掉 90 天前的資料。
    這種表不設上限就會變成資料庫裡最大的一張。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_request_log (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            at      TEXT    NOT NULL,
            method  TEXT    NOT NULL,
            path    TEXT    NOT NULL,
            page    TEXT    NOT NULL DEFAULT '',
            status  INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_request_log_user_at ON user_request_log(user_id, at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_request_log_at ON user_request_log(at)")
    conn.commit()


def _m082_feed_attachments(conn):
    """案件動態留言與業務開發記錄可附照片／檔案（2026-09-14 使用者要求：
    「業務開發跟案件的動態都要有上傳照片或是檔案的功能」）。

    **為什麼是 JSON 欄位而不是獨立的附件表**：這兩處的附件沒有任何「跨紀錄查詢」
    的需求——不會有人問「這張照片還被哪幾則留言引用」。附件永遠隨著它所屬的那
    一則留言／記錄一起讀、一起刪，生命週期完全綁定。開一張表要多一次 JOIN、
    多一組外鍵維護，換不到任何查詢能力。這跟 `_m078` 決定「開欄位不塞 data_json」
    的判準是同一個：**看有沒有跨列查詢的需求**，不是看資料長得複雜不複雜。
    報價單／出貨單／開票憑據三處的回簽附件（2026-08-24）也是存 JSON 欄位，
    這裡沿用同一個慣例與同一組 helpers/uploads.py 函式。

    欄位存的是 save_document_files() 回傳的 metadata 陣列
    （id/filename/path/size/mime/uploadedBy/uploadedAt），實體檔案在 uploads/
    底下，由既有的 /api/uploads/{file_path:path} 簽名 URL 端點提供讀取，
    archive.py::_mirror_uploads() 會自動納入雲端備份。

    DEFAULT '[]' 而不是允許 NULL：讀取端一律 json.loads，少一個 None 分支。
    """
    for table in ("case_updates", "dev_logs"):
        if not _col_exists(conn, table, "files_json"):
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN files_json TEXT NOT NULL DEFAULT '[]'"
            )
    conn.commit()


def _m081_edit_presence(conn):
    """同時編輯警示（2026-09-14 使用者要求：「如果有兩個人同時進入報價單、或是修改
    同一個表格的內容，需跳出警示，避免兩人同時修改損失一方資料」）。

    **這是第二道，不是第一道**。第一道早就有：存檔時比對 `updated_at`，對不上就
    409「已被其他人更新，請重新載入後再存」（報價單／案件資料／款項／規劃書／
    業務開發案／派工單都有）。那道保證**資料不會被無聲覆蓋**，但使用者是在打完
    20 分鐘的字之後才知道白做了——這張表補的是「一進去就知道有人在編」。

    **刻意做成 presence 而不是 lock**：
    - 鎖需要處理「誰來解鎖」——人關了分頁、當機、下班沒關，鎖就卡在那裡，最後
      一定要做「強制解鎖」，而強制解鎖又會回到「兩個人同時編」的原點
    - 這間公司同時線上的人數是個位數，衝突罕見但代價高；「看得到彼此」已經足夠
      讓人先喊一聲，不需要用鎖把流程綁死
    - 真的搶著存，還有第一道 409 擋著資料

    `last_seen_at` 由前端心跳更新（30 秒一次），超過 `_PRESENCE_TTL` 沒更新就視為
    離開——不必依賴「關閉頁面時要記得通知伺服器」這種一定會漏的事件。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edit_presence (
            doc_type     TEXT    NOT NULL,
            doc_id       TEXT    NOT NULL,
            user_id      INTEGER NOT NULL,
            username     TEXT    NOT NULL DEFAULT '',
            display_name TEXT    NOT NULL DEFAULT '',
            started_at   TEXT    NOT NULL DEFAULT '',
            last_seen_at TEXT    NOT NULL DEFAULT '',
            PRIMARY KEY (doc_type, doc_id, user_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edit_presence_doc ON edit_presence(doc_type, doc_id, last_seen_at)")
    conn.commit()


def _m083_backup_retention_policy(conn):
    """備份保留政策改版（2026-09-14 使用者裁示）——**這支改的是設定值，不是 schema**。

    新政策：每日 60 天、週 90 天、月備份永久保留（新增的一層，見
    archive.py::_monthly_backup()）。舊預設是每日 1825 天／週 730 天，長期保存
    壓在「每天一份整庫 .db」上，成本隨資料庫大小線性成長。

    **為什麼需要一支 migration 而不是只改 `_BACKUP_RETENTION_DEFAULT`**：
    `_backup_retention()` 的作法是 `{**預設, **system_settings 存的值}`——正式機
    只要曾經呼叫過一次 PATCH /api/settings/backup-retention，那四個舊數字就被
    固化在 DB 裡，之後改預設值**完全不會生效**，而且不會有任何錯誤訊息。
    這種「改了沒反應、也不知道為什麼」正是最難查的那種。

    只覆寫這次政策決定的三個 key，其餘（local_db_keep_days／audit_log_keep_days）
    保留使用者調過的值——那兩個不在這次的裁示範圍內。
    設定不存在時什麼都不做：那種情況本來就直接吃新的預設值。
    """
    row = conn.execute(
        "SELECT value_json FROM system_settings WHERE key='backup_retention'").fetchone()
    if not row:
        return                      # 沒存過 → 直接吃 archive.py 的新預設值
    try:
        cur = json.loads(row["value_json"]) or {}
    except (ValueError, TypeError):
        return                      # 存的值壞掉 → 不猜，留給 _backup_retention() 的 merge 去處理
    if not isinstance(cur, dict):
        return
    cur["cloud_daily_keep_days"]   = 60
    cur["cloud_weekly_keep_days"]  = 90
    cur["cloud_monthly_keep_days"] = 0      # 0 = 永久保留
    cur.setdefault("local_pre_update_keep", 5)
    conn.execute(
        "UPDATE system_settings SET value_json=?, updated_at=? WHERE key='backup_retention'",
        (json.dumps(cur, ensure_ascii=False), datetime.now().isoformat()))
    conn.commit()


def _m084_backfill_role_bypass_modules(conn):
    """取消「角色直通」之前，把直通實際給出去的權限寫成真的模組（2026-09-14）。

    **這支不是新功能，是為了讓另一個改動不傷人**。2026-09-14 使用者裁示
    「管理者一樣依據有開權限的內容去顯示，沒開的就不顯示」，於是
    `helpers/auth.py::require_any_module()` 與 `frontend/static/sidebar.js`
    同步拿掉了三種不是模組的放行：

        role in (superadmin, admin)  → 只剩 superadmin
        role == 'engineer'           → 案件管理（sidebar `|| eng`）
        role != 'viewer'             → 工作日誌／每日工作事項

    直接拿掉會出事：**既有帳號的模組清單早就過時了**，而且正是因為有直通所以
    沒人發現。開發機實測 4 個 admin 各缺 13～17 個 key，缺的包含營運報表、
    出納、網路架構規劃書，以及 2026-08／09 才新增的監控／門禁／閘道器／自動化
    四類選型導覽——那些模組加進了角色樣板，既有帳號卻從來沒有回填。
    不補就等於這些人隔天上班憑空少掉一半功能。

    **補的範圍刻意等於「直通原本給出去的東西」，不多也不少**：

      admin           ← ROLE_MODULES.admin 角色樣板（= 直通原本讓他看到的範圍）
      engineer        ← case_manage
      非 viewer 全部  ← work_log、daily_task

    不用「一律補成角色樣板」的原因：那對 engineer／sales 會**放寬**權限
    （例如樣板含 equipment，但今天沒有 equipment 模組的工程師是看不到設備登載的），
    而這次的目的是讓權限變成真的，不是順手多給。

    一律**只增不減**（聯集），不會動到任何人已經被刻意勾掉的東西；
    已經持有的帳號寫回去的內容跟原本相同，重跑無副作用。
    """
    # 與 frontend/pages/users.html 的 ROLE_MODULES.admin 逐字對應。
    # ⚠️ 兩邊要一起改——這裡是一次性的回填快照，不是執行期的真實來源，
    #    所以沒有做成共用常數；日後角色樣板變動不需要回頭改這支 migration。
    admin_template = [
        "dashboard", "quotation", "case_manage", "customer", "procurement",
        "inventory", "equipment", "finance", "reports", "project_approve_eng",
        "project_approve_biz", "financial_view", "work_log", "daily_task",
        "env_guide", "netarch_guide", "switch_guide", "monitor_guide",
        "access_guide", "gateway_guide", "automation_guide", "cashier",
        # 角色樣板之外、但 admin 直通**確實給得到**的項目。不補這些的話，
        # 取消直通當天 admin 會實際少掉這五個選單入口（核對側欄逐項確認過）：
        #   netplan            網路架構規劃書（原本側欄寫死 || ad || eng，
        #                      且只有 netplan_edit 這個 edit key，沒有檢視 key）
        #   四個稽核／維運頁    原本側欄寫死 || ad，同樣沒有任何 key
        # ⚠️ 刻意**不**補 *_guide_edit 與 settings：那兩類走的是
        #    _require_user(require_superadmin=True, module=...)，本來就不放行
        #    admin（查證過），補了等於憑空放寬權限，不是保留現況。
        "netplan",
        "audit_log", "shipping_export_log", "module_versions", "selection_overview",
    ]

    rows = conn.execute("SELECT id, username, role, modules FROM users").fetchall()
    changed = 0
    for r in rows:
        role = r["role"]
        if role == "superadmin":
            continue                     # 全開，不需要也不該動
        try:
            have = json.loads(r["modules"] or "[]")
        except (ValueError, TypeError):
            have = []
        if not isinstance(have, list):
            have = []

        add = []
        if role == "admin":
            add += admin_template
        if role == "engineer":
            # sidebar 原本那個 "|| eng" 放行給的就是這兩項（cCM 與 cNetPlan）
            add += ["case_manage", "netplan"]
        if role != "viewer":
            add += ["work_log", "daily_task"]

        merged = list(have)
        for k in add:
            if k not in merged:
                merged.append(k)
        if len(merged) != len(have):
            conn.execute("UPDATE users SET modules=? WHERE id=?",
                         (json.dumps(merged, ensure_ascii=False), r["id"]))
            changed += 1
            logger.info("v84 回填模組：%s（%s）%d → %d 個",
                        r["username"], role, len(have), len(merged))
    conn.commit()
    logger.info("v84 模組回填完成：%d/%d 個帳號有異動", changed, len(rows))


def _m085_procurement_lead_time(conn):
    """供應商／料號前置時間，與採購建議的下單狀態（2026-09-21）。

    補的是兩個既有模組**自己在文件裡承認**的缺口：
      - `SELLABLE-AND-MOBILE-SPEC.md` §5.1 第 4 項：`lead_time` 全系統實測 0 處
      - 架構地圖 §6.6：採購建議「v1 刻意不含 ETA」，理由正是「從未追蹤前置時間」

    ⚠️ **`lead_time_days` 預設 NULL，而 NULL 是「未知」不是「0」。**
    這兩者在畫面上都會顯示成「今天到貨」——**那是一個看起來很正常的錯誤答案**，
    採購人員會照著它去排程。補了欄位不等於補了資料：沒填的那些**仍然是未知**，
    ETA 必須跟著回 `null`，不可以因為欄位存在就假裝算得出來。
    （同 `_m070_stock_batches` 對 `is_paid=0` 的處理：誠實反映「系統從未知道過」。）

    解析順序：`parts.lead_time_days` → 該料號最近一筆進貨的供應商 → NULL。
    **料號層級可以覆寫供應商層級**，因為同一家供應商的現貨品項與訂製品項差很多。

    `purchase_suggestion_status` 一個料號一列，記的是**目前那一輪**採購循環。
    採購建議本身是即時從庫存算出來的（`routers/inventory.py::purchase_suggestions`，
    以 `part_no` 為鍵、沒有自己的主鍵），所以狀態只能另存。

    ⚠️ **這張表不參與清單的過濾。** 清單永遠由庫存算出來，狀態只是附註——
    旗標是人設的、會過期，真實狀態是算出來的、會自己更新，**旗標不可以蓋過真實狀態**
    （協定 §5b）。收到貨庫存自然回到水位之上、建議自然消失；若收了貨庫存還是低
    （叫少了），本來就該再建議一次。
    """
    if not _col_exists(conn, "suppliers", "lead_time_days"):
        conn.execute("ALTER TABLE suppliers ADD COLUMN lead_time_days INTEGER")
    if not _col_exists(conn, "parts", "lead_time_days"):
        conn.execute("ALTER TABLE parts ADD COLUMN lead_time_days INTEGER")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS purchase_suggestion_status (
            part_no     TEXT PRIMARY KEY,
            status      TEXT NOT NULL DEFAULT 'suggested',
            ordered_at  TEXT DEFAULT '',
            ordered_by  TEXT DEFAULT '',
            received_at TEXT DEFAULT '',
            received_by TEXT DEFAULT '',
            note        TEXT DEFAULT '',
            updated_at  TEXT DEFAULT ''
        )
    """)
    conn.commit()


def _m086_tender_radar(conn):
    """標案雷達四張表（2026-09-21，細線 6 第 1～3 步）。

    ⚠️ **`tenders` 的唯一鍵是 `(org, case_no)` 不是 `case_no`。**
    這不是查證結果（政府案號會不會跨機關重複，我們沒查），是**失敗方向不對稱**：
      只用 case_no  → 撞號時第二筆**併進第一筆、悄悄消失**，沒有任何訊息
      (org, case_no) → 撞號時多一列重複，**看得見、可以再收斂**
    這條線的承諾是「不會漏掉標案」，而 case_no 唯一鍵的失敗模式正好是漏掉標案。
    **不確定的時候往「最壞只是吵」倒，不要往「最壞是靜默遺失」倒。**

    ⚠️ **`tender_fetch_log.recognised` 可以是 NULL，而 NULL 不等於 0。**
      NULL  ＝ 根本沒解析（抓不到：逾時／403／連不上）
      0     ＝ 解析過了，認不得（對方改版）
      1     ＝ 解析過了，認得
    兩者的處置相反：改版要改解析器，掛掉只要等它好。把「抓不到」記成 0 的話，
    現場會照著「對方改版了」的方向去查一個沒有壞掉的解析器。
    （同一家族的第三個實例，前兩個：前置時間未知、預算沒寫。）

    ⚠️ **`tenders.budget` 可以是 NULL。** 「公告沒寫預算」是 NULL，「預算 0 元」是 0。
    存成 0 的話，任何設了金額下限的 watch 都會**安靜地漏掉**那些標案。
    `deadline`／`published_at` 同理：沒寫就是 NULL，不要填今天。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tender_watches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL DEFAULT '',
            keywords    TEXT    NOT NULL DEFAULT '[]',   -- JSON 陣列，OR
            excludes    TEXT    NOT NULL DEFAULT '[]',   -- JSON 陣列，一中就整筆排除
            org         TEXT,                            -- NULL = 不篩機關
            budget_min  INTEGER,                         -- NULL = 不篩下限
            budget_max  INTEGER,                         -- NULL = 不篩上限
            enabled     INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    DEFAULT '',
            updated_at  TEXT    DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tenders (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            case_no      TEXT    NOT NULL,
            org          TEXT    NOT NULL,
            name         TEXT    NOT NULL DEFAULT '',
            published_at TEXT,          -- 公告日（已轉西元）；沒寫 = NULL
            deadline     TEXT,          -- 截止投標（已轉西元）；沒寫 = NULL
            budget       INTEGER,       -- NULL = 公告沒寫；0 = 真的是 0 元
            url          TEXT    DEFAULT '',
            fetched_at   TEXT    DEFAULT '',
            UNIQUE (org, case_no)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tender_hits (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            watch_id   INTEGER NOT NULL,
            tender_id  INTEGER NOT NULL,
            hit_at     TEXT    DEFAULT '',
            UNIQUE (watch_id, tender_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tender_fetch_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at TEXT    NOT NULL DEFAULT '',
            recognised INTEGER,          -- NULL=沒解析 / 0=認不得 / 1=認得
            dropped    INTEGER NOT NULL DEFAULT 0,
            error      TEXT    DEFAULT ''
        )
    """)
    conn.commit()


def _m087_tender_notify(conn):
    """標案雷達通知所需的兩個欄位（2026-09-21，細線 6 第 5 步）。

    **`tender_hits.notified_at`**：這一筆命中有沒有寄出去過。
    ⚠️ **只能在寄信「成功之後」才寫**。在寄信之前寫的話，SMTP 掛掉那一次的標案
    **永遠不會再出現在任何一封信裡**，而且不會有任何錯誤訊息——
    那是「安靜地少做一件事」的又一個實例（驗收條件 N12）。

    **`tender_fetch_log.suspected`**：這一次有沒有判定「疑似對方改版」。
    ⚠️ 這一欄 §3 沒有要求，是我加的，理由是**邊緣觸發需要「上一次是什麼狀態」**：
    「抓不到」的邊緣可以從既有的 `recognised IS NULL` 推出來，
    但「疑似改版」推不出來（log 裡只有 `dropped`，沒有當次解出幾筆）。
    不記的話，對方改版那週會**每天寄一封**——正是 §T.5 #5 在防的「站台掛一週七封信」。
    ⇒ 兩種告警的邊緣判定因此共用同一個來源（這張表），不必一個看表、一個看設定。

    📌 **首次掃描時間不在這裡**：它存 `system_settings`
    （`tender_radar_first_scan_at`，走 `helpers/settings.py`）。
    ⚠️ 不可以從 `tender_fetch_log` 推算——那張表**不進每日 JSON 備份**（第 4 輪裁決），
    還原之後是空的，7 天純記錄期會**靜默重新開始**。
    """
    if not _col_exists(conn, "tender_hits", "notified_at"):
        conn.execute("ALTER TABLE tender_hits ADD COLUMN notified_at TEXT")
    if not _col_exists(conn, "tender_fetch_log", "suspected"):
        conn.execute("ALTER TABLE tender_fetch_log ADD COLUMN suspected INTEGER")
    conn.commit()


def _m088_tender_detail_fields(conn):
    """標案的地點與兩個列表頁就有的欄位（2026-09-21，第 6 輪）。

    使用者實測回饋：「彙整好標案資訊的信件內容要有大綱，例如標案名稱、地點、
    金額、項目等重要資訊協助判別」。
    🔑 **一鍵轉案再有價值，也建立在他願意每天打開那封信之上。**

    - `location`：履約地點。**只從詳細頁 `id="fkPmsExecuteLocation"` 取**。
      ⚠️ 詳細頁上「地址」出現 10 次，其中 9 次是**每一頁都一樣的樣板**
      （六個監督機關 ＋ 頁尾工程會）。用字樣去找的話，**每一筆標案都會得到
      同一個臺北市信義區的地址，而它看起來完全像一個合法地點**。
      ⚠️ 更陰的是：監督機關裡有一個**也在桃園市**，抽驗時「桃園市」三個字
      會讓人以為抓對了。
    - `procurement_type`／`tender_method`：採購性質與招標方式，
      **從列表頁解析，不增加任何對外請求**。

    ⚠️ 三欄都可以是 NULL，而 **NULL 不是空字串**：
    「沒有這一欄」與「這一欄是空的」是兩件事。`location` 尤其——
    非地名值（「全國」「依契約規定」「多個縣市」）一律存 NULL 不要硬存，
    否則下游「依地點篩選」會篩出一個叫「依契約規定」的縣市。
    （`0` vs `NULL` 那一族的第六個實例。）
    """
    for col in ("location", "procurement_type", "tender_method"):
        if not _col_exists(conn, "tenders", col):
            conn.execute(f"ALTER TABLE tenders ADD COLUMN {col} TEXT")
    conn.commit()



def _m089_geocode_cache(conn):
    """地址 → 座標的快取表（2026-09-22，§3o）。

    ## 為什麼要落地，而不是留在記憶體
    原本是 `helpers/geo.py` 的一個 dict ⇒ **重啟就空**。
    而正式機的 `autostart.bat` 是一個無限迴圈（崩潰就重拉）
    ⇒ **查詢次數由「重啟幾次」決定，不是由使用者決定**，
    而 Google 那一階是要收費的。
    不重複的地址最多 27 個（22 個縣市＋其他＋辦公室）
    ⇒ **存進來 ＝ 一輩子 27 次；不存 ＝ 每次重啟 27 次。**

    ## 🔴 四個欄位，每一個都有它擋著的錯
    - `address` ＋ `source`：**複合唯一鍵**。同一個地址用 OSM 與用 TGOS 查，
      結果不一樣 ⇒ 只用 `address` 當鍵的話，**兩個來源會互相覆蓋**，
      而覆蓋是安靜的。
    - `precision`：☠️ **這個最容易被省略。** 「門牌精度」與「行政區精度」
      **在畫面上都是一個圖釘**，而距離可能差好幾公里。
      不存的話，日後從「縣市中心」升級到「門牌」時，
      **舊的粗結果會被當成新的細結果用**，而畫面上看不出來。
      🔑 **一個數字不帶它的可信度，就會被當成事實。**
    - `created_at`：**給 TTL 用的，不是裝飾。**
      ⚠️ 地址與座標的對應**會變**（門牌改編、行政區調整、圖資被修正）。
      存進資料庫 ＝ 一輩子不再查 ⇒ **那個錯誤會永遠留著**，
      而症狀是「地圖上那個點一直在錯的位置」——**沒有人會報修。**
      🔑 記憶體版沒有這個問題，是因為**它會自己忘記**；
      進資料庫之後那個保護就消失了，所以要自己把它加回來。

    📌 **失敗不存進這張表**（`_m089` 不建欄位給它）：
    `503`／逾時是暫時的，寫進來會讓一次抖動變成永久的空白。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS geocode_cache (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            address    TEXT    NOT NULL,
            source     TEXT    NOT NULL,   -- google / tgos / nominatim / nominatim_district
            lat        REAL    NOT NULL,
            lon        REAL    NOT NULL,
            precision  TEXT    NOT NULL,   -- exact / rooftop / street / district
            created_at TEXT    NOT NULL DEFAULT '',
            UNIQUE (address, source)
        )
    """)
    conn.commit()

def _m090_quotation_location(conn):
    """v90（2026-09-22 §9 QL2）：報價單記下**它屬於哪一個據點**。

    ## 🔴 真欄位，不塞 `data_json`
    `data_json` 裡的東西查不出來也 JOIN 不了，而「這張單屬於哪個據點」
    是要拿來**決定 PDF 印誰的抬頭與帳號**的。

    ## ⚠️ 順序是硬的：**先確保主要據點存在，再把報價單指過去**
    既有安裝的 `company_profile` 有 `address` 而**沒有 `locations`**
    ⇒ 那個時候「主要據點」還不存在。
    ☠️ 順序反過來的話，既有的報價單會指向**一個不存在的 id**，
    🔑 而那比 NULL 更糟：NULL 看得出來沒設定，**一個壞掉的 id 看起來像設定好了**。

    ## 📌 導出的邏輯**寫在這裡**，不呼叫 `routers.system._migrated_locations()`
    〈凍住的歷史不要呼叫活的程式碼〉：那支 helper 會演進，
    而 migration 是歷史 —— 它跑的必須是**當時**的規則。

    ## 🔴 那個 trigger 才是「不可以留 NULL」的實際保證
    ⚠️ 應用層補預設只管得住**走 API 的那條路**。
    ☠️ 而報價單也會被匯入腳本、修復腳本、以及未來的其他端點寫進來 ——
    🔑 **一個只在某一條路上成立的不變量，不是不變量。**
    📌 trigger 讀的是**當下的**主要據點（`json_extract`），不是 migration 當時的值
    ⇒ 使用者改了主要據點之後，新的預設會跟著走。
    """
    if not _col_exists(conn, "quotations", "location_id"):
        conn.execute("ALTER TABLE quotations ADD COLUMN location_id TEXT")

    # ── ① 主要據點：沒有 `locations` 就從 `address` 導一筆（BR3 當時的規則）──
    row = conn.execute(
        "SELECT value_json FROM system_settings WHERE key='company_profile'"
    ).fetchone()
    try:
        profile = json.loads(row["value_json"]) if row and row["value_json"] else {}
    except (TypeError, ValueError):
        profile = {}
    if not isinstance(profile, dict):
        profile = {}
    locations = profile.get("locations")
    if not isinstance(locations, list) or not locations:
        address = str(profile.get("address") or "").strip()
        if address:
            # ⚠️ 地址是空的就**不要造一筆空的據點**（BR3b）——
            # 一筆「有名字沒地址」的據點在地圖上是「定位不到」，
            # 而那與「使用者真的填錯了」長得一模一樣。
            profile["locations"] = [{
                "id": "loc_1", "name": "總公司", "address": address,
                "lat": profile.get("office_lat"), "lon": profile.get("office_lon"),
            }]
            conn.execute(
                "INSERT INTO system_settings (key, value_json, updated_at) "
                "VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET "
                "value_json=excluded.value_json, updated_at=excluded.updated_at",
                ("company_profile",
                 json.dumps(profile, ensure_ascii=False),
                 datetime.now().isoformat()))
            locations = profile["locations"]

    primary_id = ""
    if isinstance(locations, list) and locations and isinstance(locations[0], dict):
        primary_id = str(locations[0].get("id") or "")

    # ── ② 既有的報價單補上主要據點 ──────────────────────────────────
    if primary_id:
        conn.execute(
            "UPDATE quotations SET location_id=? "
            "WHERE location_id IS NULL OR TRIM(location_id)=''", (primary_id,))

    # ── ③ 之後不帶 `location_id` 的 INSERT 一律補成當下的主要據點 ──
    conn.execute("DROP TRIGGER IF EXISTS quotations_default_location")
    conn.execute("""
        CREATE TRIGGER quotations_default_location
        AFTER INSERT ON quotations
        WHEN NEW.location_id IS NULL OR TRIM(NEW.location_id) = ''
        BEGIN
            UPDATE quotations
               SET location_id = (
                     SELECT json_extract(value_json, '$.locations[0].id')
                       FROM system_settings WHERE key = 'company_profile')
             WHERE id = NEW.id;
        END
    """)
    conn.commit()


def _m091_geocode_usage(conn):
    """§16 GB1：Google 額度計數器的落點。

    📌 〈計數器要有落點〉：「累積到 N 就停」要先指出 **N 寫在哪張表**。
    ☠️ 記憶體計數器一重啟就歸零，而**「永遠沒觸發」跟「運作良好」長得一模一樣**。

    ## 🔑 為什麼鍵是 `period_start` 而不是「年月」

    帳單週期起算日**可以設定**（`GB4`），而使用者把它從 1 號改成 15 號的那一刻，
    `"2026-09"` 這個標籤已經累計了 N 次 —— 那 N 次算在哪一期？
    ⇒ 存**實際的週期起日**就沒有這個問題：改設定會開出一個新的週期，
    舊的那一段原封不動留在它自己的起日底下，看得到也對得上。
    `month` 只是顯示用，**不是鍵**。

    ## 🔑 `source` 是 SKU 粒度，不是 provider 粒度

    Google 2025-03-01 起廢掉了每月 $200 的共用 credit，
    改成**每個 SKU 各自一組免費月額度而且不共用**
    ⇒ 「google 用了幾次」這個問題沒有意義。
    ☠️ 用 `'google'` 一個值的話，等 Places 進來時兩個 SKU 的用量會被加在一起
    去對同一個門檻 —— **兩邊都算錯。**
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS geocode_usage ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  period_start TEXT NOT NULL,"      # 週期起日 YYYY-MM-DD（鍵）
        "  month TEXT NOT NULL DEFAULT '',"  # 顯示用標籤，不是鍵
        "  source TEXT NOT NULL,"            # SKU：google:geocoding / nominatim ...
        "  count INTEGER NOT NULL DEFAULT 0,"
        "  updated_at TEXT NOT NULL DEFAULT '',"
        "  UNIQUE(period_start, source)"
        ")")


def _m092_tender_mark(conn):
    """v92（2026-09-22 §21 補 TD5–TD8）：標案可以被**標註**，標註的排在最上方。

    > 使用者原話：「增加一個標註的功能，**當這個標案被標誌，則顯示於標案的最上方**」
    > 使用者裁示：**共用的** —— 一個人標，全部的人看得到。

    ## 🔑 一個可為 NULL 的時間戳**兼任旗標**，不另外開一個 boolean

    ☠️ 兩個欄位（`is_marked` ＋ `marked_at`）**會分岔** —— 有人只更新其中一個，
    而**分岔之後沒有任何東西會紅**：兩欄各自都是合法的值，
    只是它們講的話不一樣了。
    ⇒ 判定一律 `marked_at IS NOT NULL`，**不可以用真假值**（〈null 不等於 0〉）。

    ## 🔑 為什麼標註是 `tenders` 上的欄位，不是 `(user_id, tender_id)` 一張表

    使用者裁示「共用的」⇒ 它是**這一筆標案的屬性**，不是誰的清單。
    ☠️ 做成關聯表的話，「這一筆我們要投」會變成每個人各自的便利貼 ——
    🔑 而那個實作在**單人測試**下與正確的完全無法分辨。

    ## ⚠️ `marked_by` 刻意**不加 FOREIGN KEY**

    照本檔既有體例（`quotations.location_id`、`dev_logs.owner_id` 都沒加）。
    而理由在這裡特別要寫出來：使用者被刪掉時，**標註不應該跟著消失** ——
    ☠️ 一個「有標註但不知道誰標的」比「標註整個不見」好，
    因為後者使用者看到的是「我標的那幾筆不見了」而沒有任何東西會說話。
    ⇒ 讀不到 `marked_by` 對應的人時，畫面顯示「未知」，不是把那一列藏起來。

    ## 📌 可逆性：這一支**降版走得掉**

    `apply_update.ps1` 的回滾會把資料一起還原。而就算不還原資料，
    這兩個欄位對 v91 的程式碼是**看不見的**（既有查詢全是具名欄位或
    `SELECT *` 後取用具名鍵），多兩個欄位不會讓任何舊路徑壞掉。
    ⚠️ 本機 SQLite 是 3.53.1（`DROP COLUMN` 需 ≥ 3.35.0，支援），
    而**這裡不寫 down**：本專案的 migration 引擎只往前走，
    降版靠的是還原整個檔案。寫一個沒有人會呼叫的 down 只會讓人以為有退路。
    🔴 ⇒ **回滾之後標註也會不見**，那一句要寫進交付說明。

    ## ⚠️ 這一支不呼叫任何會演進的 helper

    〈凍住的歷史不要呼叫活的程式碼〉：只有 `_col_exists` 與兩句 DDL，
    兩者都不會因為日後的業務規則而改變意思。
    """
    # 🔑 `_col_exists` 讓它可以重複跑 —— migration 引擎失敗重跑時不會炸。
    if not _col_exists(conn, "tenders", "marked_at"):
        conn.execute("ALTER TABLE tenders ADD COLUMN marked_at TEXT")
    if not _col_exists(conn, "tenders", "marked_by"):
        conn.execute("ALTER TABLE tenders ADD COLUMN marked_by INTEGER")


def _m093_account_items(conn):
    """v93（2026-09-23 `FN1` §69）：會計項目表 ＋ **資料層**的唯讀保護。

    ## 🔑 單表 ＋ `source` 欄位，**不要兩張表**

    法定（官方《商業會計項目表》）與自訂並存。
    ☠️ 拆成兩張表的話，每一個引用點都要 `UNION` ——
       **而漏掉 `UNION` 的那一處會安靜地少一半資料**，不會報錯。

    ## 🔴 `parent_code` 是明確欄位，**不可以靠前綴推**

    官方表的二級是**範圍代號**：
    ```
    一級 1        資產
    二級 11-12    流動資產      ← 是一個範圍，不是單一代號
    三級 111      現金及約當現金
    ☠️ "111".startswith("11-12") 為 False
    ```
    實測活證據三筆：`111→11-12`／`211→21-22`／`723-724→71-72`
    —— **用字串前綴一筆都串不起來。**

    ## 🔴 唯讀擋在**資料層**，不是應用層

    〈應用層的守門只在「有人走那條路徑」時生效〉：
    migration、修復腳本、直接連資料庫**都繞得過**。
    ⇒ 真的不可變的東西要用 TRIGGER ＋ `RAISE(ABORT)`。
    ⚠️ 本專案用過 TRIGGER，**而 `RAISE(ABORT)` 沒有前例** ⇒ A 已實測：
    ```
    UPDATE statutory -> BLOCKED    DELETE statutory -> BLOCKED
    UPDATE custom    -> ALLOWED    DELETE custom    -> ALLOWED   ← 正對照
    ```
    🔑 **正對照那兩格是關鍵**：少了它們，「全部都擋住」也會讓前兩格通過，
       而那會讓使用者**連自己加的科目都改不動** —— 而法條正是允許
       「商業得視實際需要增減其會計項目」。

    ## ⚠️ `RAISE(ABORT, …)` 那句話是使用者唯一看得到的東西

    所以它要說得出**為什麼不准**，不是只說「失敗」。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS account_items ("
        "  code        TEXT PRIMARY KEY,"      # 1 / 11-12 / 111 / 1111 / 自訂
        "  level       INTEGER NOT NULL,"      # 1~4；自訂可自行決定
        "  name        TEXT NOT NULL,"
        "  name_en     TEXT NOT NULL DEFAULT '',"
        "  parent_code TEXT,"                  # 🔴 明確欄位，不靠前綴
        # 🔴 **三態，不是兩態**（§107）：
        #   statutory       官方《商業會計項目表》—— **唯讀**（下面兩個 TRIGGER）
        #   system_default  我們預設帶的常用項目 —— 可停用、可改指向
        #   custom          使用者自己加的
        # ☠️ 把 `system_default` 併進 `custom` 的話，使用者日後**找不到是誰建的**
        #    —— 一個他從來沒建過的項目出現在「我的自訂」裡，而他不敢刪。
        # ⚠️ 而 TRIGGER 的條件**只認 `statutory`**：`system_default` 要能改，
        #    否則我們預設帶的東西會變成第二種不可變的東西，而它沒有法源。
        "  source      TEXT NOT NULL DEFAULT 'custom'"
        "    CHECK (source IN ('statutory', 'system_default', 'custom'))"
        ")")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_account_items_parent"
        " ON account_items(parent_code)")

    # ⚠️ `BEFORE` 不是 `AFTER`：`AFTER` 的話那一列已經被改掉了，
    #    `RAISE(ABORT)` 雖然會回滾，而語意上「先擋住」比「做了再退回」清楚。
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS account_items_statutory_no_update"
        " BEFORE UPDATE ON account_items"
        " FOR EACH ROW WHEN OLD.source = 'statutory'"
        " BEGIN"
        "   SELECT RAISE(ABORT,"
        "     '法定會計項目不可修改：這是經濟部公告的《商業會計項目表》，"
        "要調整請新增自訂項目');"
        " END")
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS account_items_statutory_no_delete"
        " BEFORE DELETE ON account_items"
        " FOR EACH ROW WHEN OLD.source = 'statutory'"
        " BEGIN"
        "   SELECT RAISE(ABORT,"
        "     '法定會計項目不可刪除：這是經濟部公告的《商業會計項目表》，"
        "不需要的項目請在自己的帳上停用，不要刪除');"
        " END")


def _m094_load_account_items(conn):
    """v94（2026-09-23 `FN1` §69(c)）：載入 547 筆法定會計項目。

    ## 🔴 讀**靜態檔**，不呼叫 `parse_account_items`

    〈凍住的歷史不要呼叫活的程式碼〉：migration 是凍結的歷史，
    而那支解析器會演進（官方改版、`pdfplumber` 升級都會改變它的輸出）。
    ☠️ 呼叫它的話，日後解析器一改，**這支 migration 產生的東西就跟當初不一樣**
       —— 而症狀只出現在「**全新安裝**」與「**災難還原**」那條路上，
       也就是最不能出事的兩條。
    ⇒ 這裡讀 `data/account_items_112.json`，那份檔是**產物不是程式**。

    ## ⚠️ 用 `INSERT OR IGNORE`

    migration 引擎失敗重跑時不會炸；而它也不會覆蓋任何既有列 ——
    🔑 **覆蓋是危險的方向**：使用者的自訂項目若不小心用了同一個代號，
       `OR REPLACE` 會把它換掉，而他不會收到任何通知。

    ## 📌 數字（實查靜態檔，不是估的）

    ```
    總筆數 547   層級 L1=8 ／ L2=20 ／ L3=94 ／ L4=425   孤兒 0
    ```
    ⚠️ 一級是 **8 個不是 9** —— `§69` 原本寫 9，那是從「1–9」的編號**推的**；
       實查整份表結束在「88 本期綜合損益總額」，**沒有 9**。
    """
    import json
    import os

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "account_items_112.json")
    if not os.path.exists(path):
        # ⚠️ 缺檔**不要**靜默跳過：那會讓一個沒有科目表的資料庫看起來一切正常，
        # 而傳票的分錄指不到任何東西 —— 那時才發現已經晚了。
        raise RuntimeError(
            "找不到會計項目靜態檔：%s —— v94 無法載入法定項目。" % path)

    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    for it in payload["items"]:
        conn.execute(
            "INSERT OR IGNORE INTO account_items"
            " (code, level, name, name_en, parent_code, source)"
            " VALUES (?,?,?,?,?, 'statutory')",
            (it["code"], it["level"], it["name"],
             it.get("name_en", ""), it["parent_code"]))


def _m110_voucher_category_manual(conn):
    """v110（2026-09-24 `N6`）：傳票類別「手動改過」旗標。

    使用者 2026-09-24 晨間表單：傳票類別「要能手動改」（推翻 09-23 `JV20`
    「傳票不需要有類別的選項」）。`JV29` 起類別由分錄自動判斷；手動改過的
    記 1，之後改分錄**不再自動覆蓋**。既有資料一律 0（視為自動），不回頭重算。

    ⚠️ 只有 `_col_exists` 與一句 DDL，不呼叫任何會演進的 helper。
    """
    if not _col_exists(conn, "vouchers_all", "category_manual"):
        conn.execute("ALTER TABLE vouchers_all ADD COLUMN"
                     " category_manual INTEGER NOT NULL DEFAULT 0")


def _m109_edit_log_no_delete(conn):
    """v109（2026-09-24 `JV22 §3`／`BN17`）：兩張編寫紀錄表在**資料庫層**刪不掉。

    使用者：「長期記憶，這個不能刪除」。在此之前的保護是「沒有人寫刪除」——
    而「沒有人寫」與「刪不掉」是兩件事：哪天有人比照 `_prune_audit_log()`
    寫一支保留期清理，今天沒有任何機制擋得住。
    ⇒ 照 `account_items` 既有 TRIGGER 的形狀：`BEFORE DELETE -> RAISE(ABORT)`。

    ⚠️ SQL 全部寫成字面值、不呼叫任何 helper（凍住的歷史不呼叫活的程式碼）。
    ⚠️ `reset_demo_db()` 會整張清這兩張表（展示資料庫）⇒ 它自己先 DROP、清完再建
       `sqlite_master` 裡那一份定義；`test_edit_log_no_delete_trigger_2026_09_24.py`
       驗重置後仍在、且與重置前（本 migration 建的那一份）逐字相同。
    """
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS voucher_edit_log_no_delete"
        " BEFORE DELETE ON voucher_edit_log"
        " BEGIN SELECT RAISE(ABORT, '傳票編寫紀錄是長期記憶，不可刪除'); END")
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS bonus_award_edit_log_no_delete"
        " BEFORE DELETE ON bonus_award_edit_log"
        " BEGIN SELECT RAISE(ABORT, '獎金分潤單編寫紀錄是長期記憶，不可刪除'); END")


def _m108_bonus_item_people(conn):
    """v108（2026-09-24 `BN3`）：`manual` 人員來源——項目直接掛一份帳號清單。

    `SPEC-BN2-BN5.md §2`：新表，不用 `bonus_items` 的 JSON 欄——
    ① 要能回答「這個人被哪些項目指定」（JSON 查不動）
    ② 綁的是 `users.username`（UNIQUE、不在可改欄位白名單裡），不是顯示名稱或自由文字：
       打錯一個字那個人就領不到，而畫面上一切正常。
    ⚠️ 只新增，不動既有表；既有兩個來源（sales_person／case_stages.assigned_to）不讀這張表。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bonus_item_people ("
        " bonus_item_id INTEGER NOT NULL REFERENCES bonus_items(id),"
        " username      TEXT    NOT NULL,"
        " created_at    TEXT    NOT NULL DEFAULT '',"
        " PRIMARY KEY (bonus_item_id, username))")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bonus_item_people_username"
        " ON bonus_item_people(username)")


def _m107_deactivate_legacy_demo_account(conn):
    """v107（2026-09-23 `IA2` §3③）：既有安裝的 `demo` 展示帳號停用，不刪除。

    ## 🔴 為什麼要有這支

    `helpers/startup.py::init_demo_account()` 改版前無條件建立 `demo`
    superadmin，密碼固定是公司統一編號、`must_change_password=0`，且明文
    寫進 `logs/server.log`。這一輪改成 `MOTRIX_DEMO_ACCOUNT=1` 才建立
    （`demo_account_on()`），但**既有安裝已經有這一列了**——開關只管
    「以後要不要建」，管不到「已經建好的」，而 `init_demo_account()`
    看到那一列已存在就不會再動它（見它自己的 docstring）。

    ## ⚠️ 停用，不刪列

    `audit_log` 裡有指向它的登入歷史（demo 登入會寫一筆 `auth.login`）；
    而停用是可逆的——要重新啟用展示模式，把這一列的 `active` 改回 1 就好，
    不必重建帳號、也不會遺失它的歷史紀錄。

    ## ✅ 冪等，且不取決於這次開機當下的環境變數

    只在目前 `active=1` 時才改，可重跑兩次
    （`test_u10_every_migration_can_be_run_twice`）。**不看
    `MOTRIX_DEMO_ACCOUNT` 的值**——這是一次性把「無條件建立時代」留下的
    既有列收斂成新規則的起始狀態，之後要不要重新啟用是另一個、獨立的
    人工動作，不是每次開機都用當下的環境變數重判一次
    （那樣的話開著這個環境變數開機一次，帳號會被這裡設回 1，
    而下一次沒設就又被設回 0——行為會跟著誰最後開機是誰而變，
    不是一個穩定的狀態）。

    ## 🔴 這支會關掉使用者自己正在用的東西，要留一列**他查得到**的紀錄

    `SPEC-IA2.md §6①` 的依據是「展示模式對我們的業務展示有用」——這支
    migration 一跑，既有安裝上的 demo 帳號就會被停用，而使用者只有在
    下次想展示時才會發現，那時他不會知道是這次升級關的。**`server.log`
    沒有人在看**（`EM7 §6` 查過它零消費端），`audit_log` 才是他查得到的
    地方（`audit-log.html` 讀的是這張表）——所以**只在真的把一列
    `active` 從 1 改成 0 時**才寫一筆，讓「這件事發生過」是可查的，而不是
    只留在我們的 commit message 裡。

    ⚠️ **不 import `helpers/audit.py` 的 `_audit()`**：那支會自己
    `get_db()` 開一條新連線，migration 已經有 `conn` 了，兩條連線各自
    commit 沒有必要；直接在同一個 `conn`、同一個交易裡寫，跟 `UPDATE`
    綁在一起，要嘛兩件事都發生要嘛都不發生。`token` 留空、`user_id`
    留空的寫法沿用既有慣例（`routers/auth.py:1245`
    `_audit("", "auth.webauthn_replay_detected", ...)`：系統自己觸發、
    沒有操作者的稽核列本來就這樣記）。
    """
    row = conn.execute(
        "SELECT id FROM users WHERE username='demo' AND active=1").fetchone()
    if row is None:
        return  # 沒有既有的 active demo 帳號——沒有東西要停用，也不寫 audit_log
    conn.execute("UPDATE users SET active=0 WHERE username='demo' AND active=1")
    conn.execute(
        "INSERT INTO audit_log "
        "(at,user_id,username,display_name,action,target_type,target_id,"
        " target_label,detail) VALUES (?,?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(), None, "", "",
         "system.demo_account.deactivated", "user", str(row["id"]),
         "展示帳號（demo）",
         json.dumps(
             {"reason": "IA2：出貨阻擋處置，既有安裝的展示帳號收斂成停用，"
                        "可逆——要恢復請把這一列的 active 改回 1"},
             ensure_ascii=False)))
    conn.commit()


def _m106_company_profile_identity_backfill(conn):
    """v106（2026-09-23 `WL7` §5⓪②）：`DEFAULT_IDENTITY` 清空前，先把「已經在
    跑的這一份」的值原封不動搬進 `company_profile`。

    ## 🔴 為什麼要有這支：`DEFAULT_IDENTITY` 本來是每一份單據的第四層 fallback

    `helpers/company_identity.py` 的解析鏈：據點欄 → 主要據點欄 →
    `company_profile` 頂層欄 → `DEFAULT_IDENTITY`。`DEFAULT_IDENTITY` 目前
    **就是我們的公司資料**（改版前這組值寫死在 32 行 PDF 產生碼裡，搬進
    常數時原封不動搬了過來）——這一輪 `DEFAULT_IDENTITY` 的五欄要清空
    （`WL7` §5⓪），若不先把值搬到第三層，**這台機器自己產的單據會立刻
    印出空白公司抬頭**（`pdf_gen.py` 的 8 支 builder 都讀這條鏈）。

    ## 🔴 而它絕對不可以在客戶的全新安裝上寫入我們的資料

    ⇒ **只認一個信號**：`company_profile.tax_id == "60575481"`
    （我們自己的統一編號，`SPEC-WL7.md §1` D 也拿它當交叉驗證用的獨立尺）。
    ```
    全新安裝        company_profile 這一列在這支 migration 跑的當下還不存在
                   （`_seed_setting` 排在 `_run_migrations` 之後，且 §5① 已把
                   種子值改成空字串）=> tax_id 讀出來是 "" != "60575481"
                   => 直接跳過，不寫入任何東西
    別人的既有安裝   tax_id 是他自己的統編，一樣 != "60575481" => 跳過
    我們自己這台     tax_id 本來就是 "60575481" => 才會走進去回填
    ```
    ⚠️ 不是「只做一次」或「只挑特定機器跑」這種需要人工操作的旗標——
    這個統編字面值本身就是唯一需要的判準，**判準寫死在程式碼裡，不是操作規程**。

    ## ⚠️ `company_name`／`tax_id`／`phone`／`email` 從這台自己現有的資料回填

    〈凍住的歷史不要呼叫活的程式碼〉——這支 migration**不 import**
    `company_identity.DEFAULT_IDENTITY`（那個常數這一輪就要被清空，
    migration 引用會演進的常數＝歷史被回溯改寫）。這四欄直接從這一列
    `company_profile` 自己已經有的 `name`／`tax_id`／`contact_info`
    （`"Tel: 04-3610-6566｜info@miactw.com"` 這種形狀）現算，不是抄一份
    寫死在別處的字串。

    ## ⚠️ 唯一的例外：`company_name_en`

    `company_profile` 的既有 shape（`_COMPANY_PROFILE_DEFAULT`）從來沒有
    英文公司名欄位，這一列**沒有任何地方**可以現算出它——只能是一個凍結的
    字面值。✅ 而這裡是安全的：能走到這一步，前面已經先驗過
    `tax_id == "60575481"`，這一步只可能在**我們自己**的資料列上執行。

    ## ✅ 逐欄不覆蓋，可重跑兩次（`test_u10_every_migration_can_be_run_twice`）

    每一欄只在目前是空的時候才寫，不論是「使用者已經自己填了」還是
    「這支 migration 上次已經跑過」，第二次跑都是 no-op。
    """
    row = conn.execute(
        "SELECT value_json FROM system_settings WHERE key='company_profile'"
    ).fetchone()
    try:
        profile = json.loads(row["value_json"]) if row and row["value_json"] else {}
    except (TypeError, ValueError):
        profile = {}
    if not isinstance(profile, dict):
        profile = {}

    if str(profile.get("tax_id") or "").strip() != "60575481":
        return  # 不是我們自己這台——不寫入任何東西

    changed = [False]

    def _backfill(key, value):
        value = str(value or "").strip()
        if not value:
            return
        if str(profile.get(key) or "").strip():
            return
        profile[key] = value
        changed[0] = True

    _backfill("company_name", profile.get("name"))
    _backfill("tax_id", profile.get("tax_id"))

    contact = str(profile.get("contact_info") or "")
    email_m = re.search(r"[^\s｜|]+@[^\s｜|]+", contact)
    email = email_m.group(0) if email_m else ""
    phone = contact[:email_m.start()] if email_m else contact
    phone = re.sub(r"(?i)^\s*tel[:：]\s*", "", phone).strip(" ｜|")
    _backfill("phone", phone)
    _backfill("email", email)

    # 凍結字面值——唯一沒有現有欄位可以回填的一項，見上方 docstring。
    _backfill("company_name_en", "MOTRIX Synergy Integration Corp.")

    if changed[0]:
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) "
            "VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET "
            "value_json=excluded.value_json, updated_at=excluded.updated_at",
            ("company_profile", json.dumps(profile, ensure_ascii=False),
             datetime.now().isoformat()))
    conn.commit()


def _m105_bonus_award_lines_manual_basis(conn):
    """v105（2026-09-23 `BN18`）：手動指定人員時，記一筆「本來是哪個來源」。

    使用者原話：「產生獎金單時能手動指定人」——解決「案件資料裡沒有執行人
    而我知道是誰該領」這個洞（`case_stages.assigned_to` 今天 100% 是空的）。

    ## 🔴 手動指定是**完全取代**，不是「在來源之上加減」（`SPEC-BN18.md §4c`）

    「在來源之上加減」會把「這一次的例外」變成一個結構（`excluded`／
    `added` 欄位），而結構會被重用——下一個人會拿它去做「永久排除」，
    變成一份沒有人維護的第二份群組定義。

    ⇒ `manual_basis` 只存**覆寫前這個項目原本宣告的來源**（例如
    `"group"`／`"sales_person"`），**一筆紀錄，不是可查詢／可篩選的
    結構**——不記「原本解析出誰」（那份資訊在很多情況下根本算不出來：
    案件沒有執行人才需要手動指定，而那正是 `people_for_item()` 沒東西
    可回的狀態）。
    """
    if not _col_exists(conn, "bonus_award_lines", "manual_basis"):
        conn.execute(
            "ALTER TABLE bonus_award_lines ADD COLUMN"
            " manual_basis TEXT NOT NULL DEFAULT ''")
    conn.commit()


def _m104_bonus_groups(conn):
    """v104（2026-09-23 `BN14`）：獎金人員來源加「群組」。

    使用者原話：「獎金分潤的人員來源要有群組的區分，可以把後勤單位的人
    列入人員來源，如有複數人員自動計算比例」。

    ## 🔴 不接組織架構（`divisions`／`departments`），獎金模組自己建群組

    使用者裁：「後勤單位只在這邊獨立設定，不需要共用」——`bonus_groups`
    與既有的組織架構表**沒有任何關聯**，是刻意的。

    ## ✅ 新表不用 `system_settings` 的 JSON（`SPEC-BN14.md §2b`）

    要稽核「誰把某人加進群組」、要能回答「這個人在哪些群組」、要讓
    「同一個人加兩次」在資料層被擋——JSON 三件都做不到。

    ## 🔴 `bonus_group_members.username` 有 FK 約束到 `users(username)`

    〈綁帳號不存自由文字〉這條界線（`BN3` 留下來的）在這裡靠資料層擋，
    不是只靠應用層記得檢查——打錯一個字會直接 `IntegrityError`，不是
    等到「產生獎金單」那一刻才在應用層發現。

    ## 🔴 `bonus_items.person_source_ref`：型別與實例分開存

    `PERSON_SOURCES` 的值是**型別**（`"group"`）不是**實例**（哪一個
    群組）。不編碼成 `"group:2"` 這種字串——那樣 `person_source_snapshot`
    存進 `bonus_award_lines` 之後，群組被刪掉時那個字串仍然在，看起來
    像一個合法的來源；分開存讓 `assert source in PERSON_SOURCES` 仍然
    對「型別」成立。
    """
    if not _table_exists(conn, "bonus_groups"):
        conn.execute(
            "CREATE TABLE bonus_groups ("
            "  id         INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  name       TEXT    NOT NULL UNIQUE,"
            "  is_active  INTEGER NOT NULL DEFAULT 1,"
            "  created_by TEXT    NOT NULL,"
            "  created_at TEXT    NOT NULL,"
            "  updated_at TEXT    NOT NULL"
            ")")
    if not _table_exists(conn, "bonus_group_members"):
        conn.execute(
            "CREATE TABLE bonus_group_members ("
            "  id       INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  group_id INTEGER NOT NULL REFERENCES bonus_groups(id),"
            "  username TEXT    NOT NULL REFERENCES users(username),"
            "  UNIQUE(group_id, username)"
            ")")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_bonus_group_members_group"
            " ON bonus_group_members(group_id)")
        # 🔑 `SPEC-BN14.md §2b②`：要能回答「這個人在哪些群組裡」。
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_bonus_group_members_user"
            " ON bonus_group_members(username)")
    if not _col_exists(conn, "bonus_items", "person_source_ref"):
        conn.execute(
            "ALTER TABLE bonus_items ADD COLUMN"
            " person_source_ref INTEGER REFERENCES bonus_groups(id)")
    conn.commit()


def _m103_bonus_award_lines_username(conn):
    """v103（2026-09-23 `QS1-a`）：`bonus_award_lines.username` 回填成帳號。

    ## 🔴 成因：`people_for_item()` 兩個來源回傳兩種識別

    `case_stages.assigned_to` 本來就存帳號；`quotations.sales_person`
    存的是**顯示名**（'黃玉龍'／'高晟耀'），而兩者一律被當成 username
    寫進 `bonus_award_lines.username`——只有 `sales_person` 那一支是壞的
    （詳見 `docs/windows/SPEC-QS1-a.md §1`）。

    ## 🔑 只處理 `person_source_snapshot == 'sales_person'` 的列

    `case_stages.assigned_to` 那些**不動**——本來就是帳號，去比對
    `display_name` 只會查不到（或更糟，剛好撞到別人）。

    ## ⚠️ 不依賴「全是測試資料」（A 裁）：解不出就原值保留＋記一筆

    解析順序：
    ```
    ① 這一列所屬案件的 quotations.sales_person_id -> users.username（FK，可靠）
    ② 解不出：users.display_name == username AND active=1（退路，會留 log）
    ③ 兩條都解不出：原值保留，id 與原值一起記進 log
    ```
    ☠️ 猜一個值比留一個未知更難發現——這一欄的下游是「誰領到錢」。

    ## ⚙️ 冪等：**已經是帳號的列直接跳過**

    判斷「是不是已經是帳號」用 `username IN (SELECT username FROM users)`——
    這支 migration 若被重跑第二次（`test_u10_every_migration_can_be_run_twice`），
    第一次已經回填過的列會被這個判斷跳過，不會二次處理、也不會因為
    這時候的 `username` 已經不是顯示名而誤判成「解不出」。
    """
    if not _table_exists(conn, "bonus_award_lines"):
        return
    rows = conn.execute(
        "SELECT id, username, person_source_snapshot, award_id"
        " FROM bonus_award_lines").fetchall()

    fk_count = 0
    name_count = 0
    kept = []
    for r in rows:
        rid, uname, src, award_id = (
            r["id"], r["username"], r["person_source_snapshot"], r["award_id"])
        if src != "sales_person":
            continue
        already = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (uname,)).fetchone()
        if already:
            continue

        award_row = conn.execute(
            "SELECT quote_no FROM bonus_awards WHERE id = ?", (award_id,)
        ).fetchone()
        resolved = None
        if award_row is not None:
            q_row = conn.execute(
                "SELECT sales_person_id FROM quotations WHERE quote_no = ?",
                (award_row["quote_no"],)).fetchone()
            if q_row is not None and q_row["sales_person_id"]:
                u_row = conn.execute(
                    "SELECT username FROM users WHERE id = ?",
                    (q_row["sales_person_id"],)).fetchone()
                if u_row is not None and u_row["username"]:
                    resolved = u_row["username"]
                    fk_count += 1
            if resolved is None:
                u_row2 = conn.execute(
                    "SELECT username FROM users"
                    " WHERE display_name = ? AND active = 1", (uname,)).fetchone()
                if u_row2 is not None and u_row2["username"]:
                    resolved = u_row2["username"]
                    name_count += 1
                    logger.warning(
                        "m103: bonus_award_lines id=%s 帳號經 display_name 退路"
                        "解析 %r -> %r", rid, uname, resolved)

        if resolved:
            conn.execute("UPDATE bonus_award_lines SET username = ? WHERE id = ?",
                        (resolved, rid))
        else:
            kept.append((rid, uname))

    logger.warning(
        "m103 bonus_award_lines 回填：經 FK %d 筆／經顯示名 %d 筆／未變更 %d 筆",
        fk_count, name_count, len(kept))
    for rid, orig in kept:
        logger.warning("m103 未變更：id=%s username=%r（無法解析成帳號，原值保留）",
                       rid, orig)
    conn.commit()


def _m102_bonus_award_approval(conn):
    """v102（2026-09-23 `BN8`）：獎金分潤單成為第九個 doc type。

    ## 🔴 照抄 `v101`，不另創形狀（`SPEC-BN8.md §1` 逐字）

    `approval_json` 與傳票一模一樣：`DEFAULT '{}'`，讀取端一律
    `json.loads(... or "{}")`，NULL 與 `'{}'` 在那裡等價。

    ## ✅ 而獎金單比傳票乾淨一格：**沒有投影欄位要維護**

    ```
    傳票    v99 已有 submitted_by/at、checked_by/at、manager_by/at
            => signatures_of() 有鏈時照鏈畫，沒鏈時退回那六欄
    獎金單  一格都沒有（bonus_awards 只有 created_by／created_at）
            => bonus_signatures_of() 只讀 approval_json，沒有 fallback 分支
    ```
    ⚠️ 「製表」那一格（對應傳票的「製票」）仍然是 `created_by`／`created_at`
    —— 那兩欄本來就在，這裡不必加。

    ## `paid_manually_*` 三欄：`§5c` 的「已發放」退路

    「已發放」有兩條路：出納開發放傳票回填 `voucher_no_payment`（既有欄位，
    `v97` 已建），或最高管理者手動標記（走系統外管道，例如臨時現金）。
    ⚠️ 手動標記**不可以偽造一個傳票號**——`voucher_no_payment` 留空，
    另外記**誰標的／何時／為什麼**，兩條路才分得清楚。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(bonus_awards)")}
    if "approval_json" not in cols:
        # ⚠️ 同 `v101`：`DEFAULT '{}'` 不是 NULL，讓「沒有鏈」只有一種寫法。
        conn.execute(
            "ALTER TABLE bonus_awards ADD COLUMN approval_json TEXT NOT NULL DEFAULT '{}'")
    # ⚠️ 冪等：ALTER 前先看欄位在不在（migration 引擎失敗重跑時不會炸）。
    for name in ("paid_manually_by", "paid_manually_at", "paid_manually_reason"):
        if name not in cols:
            conn.execute(
                "ALTER TABLE bonus_awards ADD COLUMN %s TEXT NOT NULL DEFAULT ''"
                % name)


def _m101_voucher_approval(conn):
    """v101（2026-09-23 `AS2`）：傳票的簽核鏈存哪裡。

    ## 🔴 使用者裁示推翻了 `§161`

    「**傳票的簽核需要在簽核設定中出現**」⇒ 「兩層」是**預設值不是常數**，
    要改的是**它從哪裡來**。

    ## ⚠️ 形狀選 `approval_json` 欄，而理由是**實查出來的**

    ```
    規格建議新建一張 voucher_approvals 明細表，前提是
      「既有六個單據類型都已經走 tiered_approval 的明細形狀」
    而實查（PRAGMA 掃全庫）：
      有 approval_json 欄的表 **只有 1 張**（case_extra_expenses）
      其餘存在 **data_json.$.approval**（quotations.py:3745 等）
    ⇒ 既有**已經是兩種形狀**，不是一種 ⇒ 新建明細表會是**第三種**
    ```
    ⇒ 與**最近一個**加進來的 doc type（`extra_expense`，2026-09-11）完全同形，
      `tiered_approval` 那一整套原樣可用，一行都不用改。

    ## 🔑 v99 那六個欄位**不動**，它們退成「版面上的簽名格」

    ```
    submitted_by/at ／ checked_by/at ／ manager_by/at
    ```
    它們現在是 `signatures_of()` **唯一的來源**，而 `JV5` 的版面正在讀它
    ⇒ 改成相容層的代價比加一個欄位高得多。
    📌 ⇒ 簽核鏈是**真相**，那六欄是**投影**；超過兩層的部分只存在鏈裡，
       而版面本來就是「回幾格畫幾列」（`JV5` 已落地）。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(vouchers_all)")}
    if "approval_json" not in cols:
        # ⚠️ `DEFAULT '{}'` 而不是 NULL：讀取端一律 `json.loads(... or "{}")`，
        #    NULL 與 '{}' 在那裡等價，而 NOT NULL 讓「沒有鏈」只有一種寫法。
        conn.execute("ALTER TABLE vouchers_all ADD COLUMN"
                     " approval_json TEXT NOT NULL DEFAULT '{}'")


def _m100_voucher_attachments(conn):
    """v100（2026-09-23 `JV3`）：傳票附件。**這個 repo 第一張附件資料表。**

    ## 🔴 為什麼是資料表，而既有附件都是 JSON 欄位

    ```
    既有：附件只被它的擁有者讀               => JSON 陣列夠用（實查 94 張表，0 張附件表）
    JV3：要回答「這個檔案被哪幾張傳票引用過」 => JSON 欄位**查不動**
    ```
    📌 而那個查詢不是想像的：`JV7` 的來源清單要標示「已被引用」，否則同一張發票
       會被帶進兩張傳票而**沒有人看得出來** ⇒ 重複入帳。

    ## 🔴 綁 `voucher_id`，**不綁 `voucher_no`**

    ```
    voucher_no  退回升版 X -> X-R1 -> X-R2   **會變**
    voucher_id  AUTOINCREMENT 主鍵            **不變**
    ```
    依據是 `helpers/voucher.py::can_send_back` 的 docstring 逐字：退回是**同一張單**
    （清簽核、單號升版），作廢重開才是另開一張。⇒ 升版不換列 ⇒ id 跨版穩定。
    ☠️ 綁單號的失敗方式不是錯誤：升版後清單是空的，
       **看起來像這張單本來就沒有附件**。
    📌 `voucher_lines` 與 `voucher_edit_log`（v95）已經都綁 `voucher_id` ⇒ 沿用，
       不是新慣例。

    ## 🔴 軟刪除：`deleted_at` 非空 ＝ 已刪，**而實體檔留著**

    使用者裁定（`§163` ②）。理由在 `archive.py::_mirror_uploads()` 那一段：
    鏡像「只增不減」⇒ 已進雲端的檔刪了也還在，
    ☠️ **而當天上傳、當天刪掉的檔從來沒被鏡像過** ⇒ 硬刪等於不可復原。
    ⚠️ ⇒ `helpers/uploads.py::delete_document_file()` **不可以重用**（它會 `os.remove`）。

    ## ⚠️ `idx_vatt_file` 是 UNIQUE：同一個 `file_id` 只能有一列

    它擋得住「兩列同一個 id」，**擋不住「兩列指向同一個實體檔」**
    ⇒ 作廢重開複製時，實體檔也要真的複製一份（規格 `§1` 裁定 ①）。
    ☠️ 共用實體檔的失敗方式很安靜：在新單刪掉一個附件**成功了**，
       而少掉的是一張已作廢傳票的憑證 —— 沒有人會在當下發現。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS voucher_attachments ("
        "  id             INTEGER PRIMARY KEY AUTOINCREMENT,"
        # 🔴 指向**實表** `vouchers_all`，不是 VIEW —— 外鍵指到 VIEW 建不起來，
        #    而語意上也該如此：作廢單的附件必須留著（稽核要看得到）。
        "  voucher_id     INTEGER NOT NULL REFERENCES vouchers_all(id),"
        "  file_id        TEXT    NOT NULL,"
        "  filename       TEXT    NOT NULL,"
        "  path           TEXT    NOT NULL,"
        "  size           INTEGER NOT NULL DEFAULT 0,"
        "  mime           TEXT    NOT NULL DEFAULT '',"
        # 🔑 來源三欄是**決定性連結**，不是一段描述文字：
        #    `source_doc_no` 對傳票來源存的是 **id 不是單號**（單號會升版）。
        "  source_type    TEXT    NOT NULL DEFAULT '',"
        "  source_doc_no  TEXT    NOT NULL DEFAULT '',"
        "  source_file_id TEXT    NOT NULL DEFAULT '',"
        "  uploaded_by    TEXT    NOT NULL,"
        "  uploaded_at    TEXT    NOT NULL,"
        # 🔴 軟刪除。非空 ＝ 已刪，**而實體檔留著**（見 docstring）。
        "  deleted_at     TEXT    NOT NULL DEFAULT '',"
        "  deleted_by     TEXT    NOT NULL DEFAULT ''"
        ")")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vatt_voucher"
                 " ON voucher_attachments(voucher_id, deleted_at)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_vatt_file"
                 " ON voucher_attachments(file_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vatt_source"
                 " ON voucher_attachments(source_type, source_doc_no)")


def _m099_voucher_signatures(conn):
    """v99（2026-09-23 `JV2`）：簽核三格各自的人與時間。

    ## 🔴 為什麼要加欄位：**單子印出來，簽名格有名字而沒有日期**

    使用者原話逐字：「**你還問過我審核日期等**」。
    而 `vouchers_all` 的時間戳實查只有：
    ```
    posted_at ／ voided_at ／ created_at ／ updated_at
    ⇒ **送審、覆核、主管各自的時間都沒有**
    ```
    簽核紀錄表也沒有（`audit_log` 與 `approval_delegates` 都不是那個東西）。

    ## ⚠️ 三格**各有自己的欄位**，不可以共用 `updated_at`

    ☠️ 共用的話，任何一次編輯都會把「覆核是什麼時候簽的」推掉 ——
       而那一列**看起來完全正常**：有人、有時間，只是時間是錯的。
    ⚙️ 驗法（C 釘的）：**簽完主管之後，覆核的時間戳沒有被改掉**。
       🔑 而**不是**「三格時間不可以相同」—— 小公司常常同一個人連按兩次，
          **真的會同一秒** ⇒ 那個斷言會紅在一個正確的實作上。

    ## 📌 用欄位不用另一張表（`§106c` 允許兩者，由 B 決定）

    ```
    欄位    三格是**固定的**（製票／覆核／主管），版面上就是三格
            => 一列一張單，讀寫都不必 JOIN
    紀錄表  適合**層數不固定**的流程
    ```
    而 A `§161` 已裁「簽核兩層寫死、**不接既有 `approval_settings`**」
    ⇒ 層數不會變 ⇒ 欄位是對的形狀。
    ⚠️ 而**製票**不需要新欄位：它就是 `created_by`／`created_at`
       —— 建立者即製票人，那是版面上的第一格，不是一個獨立的簽核動作。

    ## ⚠️ 退回時這幾格要**清掉**

    `§一`：退回 ⇒ 清除簽核 ＋ 單號升版。
    ☠️ 不清的話，一張退回重送的單會帶著**上一輪的簽名**走完流程 ——
       而簽過的人不知道他簽的已經被改過了。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(vouchers_all)")}
    # ⚠️ 冪等：ALTER 前先看欄位在不在（migration 引擎失敗重跑時不會炸）。
    for name in ("submitted_by", "submitted_at",
                 "checked_by", "checked_at",
                 "manager_by", "manager_at"):
        if name not in cols:
            conn.execute(
                "ALTER TABLE vouchers_all ADD COLUMN %s TEXT NOT NULL DEFAULT ''"
                % name)

    # ⚙️ **VIEW 不必重建** —— 實測（sqlite 3.53.1）：
    #    `CREATE VIEW v AS SELECT * FROM t` 的 `*` 是**查詢時展開**的，
    #    `ALTER TABLE t ADD COLUMN` 之後 `PRAGMA table_info(v)` 立刻多一欄。
    #
    # 🔑 這一段留著，因為我原本**推論相反**：我以為 `SELECT *` 是建立當下的
    #    快照、新欄位不會出現，差一點就寫一句 `DROP VIEW` ＋ 一句假的註解進來。
    # ☠️ 那句註解的危害比多餘的 SQL 大：下一個人會照它去「修」一個不存在的問題，
    #    而它讀起來像查證過的。


def _m098_edit_log_retention(conn):
    """v98（2026-09-23 `FN4`）：獎金的編寫紀錄 ＋ 兩張共同的 `retention`。

    ## 🔴 **兩張表，不是一張共用表**

    施工圖 `§三3.1`：傳票與獎金各一張。理由是**外鍵**——
    一張共用表無法同時對 `vouchers_all(id)` 與 `bonus_awards(id)` 宣告
    `REFERENCES`，而拿掉外鍵就等於拿掉「指到一張不存在的單」那道防線。
    ⚠️ 而**不抽成共用函式**也是刻意的：共用函式壞掉 ⇒ **兩個模組同時失效**。
    ⇒ 選的是「同形狀 ＋ 同命名」，不是「同一份實作」。

    ## ⚠️ 兩張的欄位形狀必須一致（扣掉各自的外鍵欄）

    ```
    id ／ changed_by ／ changed_at ／ changes_json ／ retention
    ```
    ☠️ 不一致不會報錯 —— 它讓「查任一模組的編寫歷史」那種工具
       **只在其中一張上壞掉**，而那支工具還沒有人寫，所以現在看不出來。

    ## 🔴 `retention` 的值域只有兩個，而**這裡不訂天數**

    ```
    permanent  「誰**匯出**過」—— 資料離開系統的證據
    term       「誰**預覽**過」—— 保留期可設
    ```
    ⚠️ **刻意不放天數**：法條的起算點是「年度決算辦理終了後」，
       **而系統沒有記錄那個時點** ⇒ 任何寫進去的天數都是猜的。
    🔑 會計師答了之後**改設定值，不改結構**（`FN6`）。
    ☠️ 而值域外的值不會報錯，它只是讓清理排程**跳過那一列** ——
       那一列會永遠留著，**而沒有人知道為什麼**。
    ⇒ 用 `CHECK` 擋在資料層（實測：`ALTER TABLE … ADD COLUMN … CHECK`
       在 SQLite 可行，且非法值會被 `IntegrityError` 擋下）。

    ## 📌 `①` 執行歷史**不建表**

    它答的是「這個月實際發生了什麼」⇒ 資料來源是**業務表自己**。
    ☠️ 另建一份副本 ⇒ 兩份會分岔，而**分岔之後哪一份是真的沒有定義**。
    🔑 而「取消的那一筆要消失」正是靠業務表自己的欄位做到的
       （`contractor_vouchers.is_paid=0`）—— 副本做不到，它只會多一列「已取消」。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bonus_award_edit_log ("
        "  id           INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  award_id     INTEGER NOT NULL REFERENCES bonus_awards(id),"
        "  changed_by   TEXT    NOT NULL,"
        "  changed_at   TEXT    NOT NULL,"
        "  changes_json TEXT    NOT NULL DEFAULT '[]',"   # 改前 → 改後
        "  retention    TEXT    NOT NULL DEFAULT 'term'"
        "    CHECK (retention IN ('permanent', 'term'))"
        ")")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bael_award"
        " ON bonus_award_edit_log(award_id, changed_at)")

    # `voucher_edit_log` 在 `v95` 就建好了，這裡補上同一欄。
    # ⚠️ 冪等：ALTER 前先看欄位在不在（migration 引擎失敗重跑時不會炸）。
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(voucher_edit_log)")}
    if "retention" not in cols:
        conn.execute(
            "ALTER TABLE voucher_edit_log ADD COLUMN"
            " retention TEXT NOT NULL DEFAULT 'term'"
            " CHECK (retention IN ('permanent', 'term'))")


def _m097_bonus(conn):
    """v97（2026-09-23 `FN2`）：獎金分潤五張表。

    施工圖：`docs/windows/SPEC-BONUS.md`（251 行改版）。
    第一行逐字：`# 獎金分潤 `FN2` —— **施工圖**`

    ## 🔴 `bonus_awards.quote_no` 是**單一欄位**，不是清單

    使用者原話：「**依案件獨立發放**」。
    ⇒ 落實它的是**欄位的形狀**（一個 TEXT，不是 JSON 陣列），**不是唯一性**：
    ```
    單一欄位   => 一筆獎金**結構上不可能**橫跨多案
    JSON 清單  => 可以塞兩個案號進去，而唯一索引照樣過
    ```

    ## 🔴 而那個唯一索引是**部分**唯一：`WHERE voided_at = ''`

    它強制的是**另一件事**：「一個案件同時只能有一筆**有效**獎金」。
    ☠️ 寫成完全唯一（無 WHERE）的後果是 **發錯了改不了** ——
    而傳票那邊有完整的作廢重開鏈（使用者親口裁的）
    ⇒ 兩個模組對「錯了怎麼辦」會不一致，**而獎金還會開傳票**。
    ⚙️ 三步驗收：第二筆未作廢 ⇒ 擋／作廢後重開 ⇒ 過／再一筆 ⇒ 擋，
       而那個案號**留 2 列**（有效 1 列、歷史留著）。

    ## 🔴 `bonus_items.person_source` 必填

    ☠️ 可以是空的話，那個獎金項目**每次都算出 0 個人** ——
       而畫面上它只是**從來沒有出現在任何一張獎金單上**，
    🔑 **沒有人會發現一個從來不出現的東西。**
    ⚠️ `NOT NULL` 擋不住空字串 ⇒ **應用層還要擋一次**，這裡只是最便宜的一半。

    ## 📌 範本拆兩張，理由與傳票範本同一個

    `AUTOINCREMENT` 只能用在單一 `INTEGER PRIMARY KEY`，
    複合主鍵 `(template_id, version)` 下 id 無法自動產生。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bonus_items ("
        "  id            INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  name          TEXT    NOT NULL,"
        # 🔴 必填：這個項目的人從哪裡來（業務→sales_person／
        #    專案執行→case_stages.assigned_to）。空的 ⇒ 永遠 0 人。
        "  person_source TEXT    NOT NULL,"
        "  sort_order    INTEGER NOT NULL DEFAULT 0,"
        "  is_active     INTEGER NOT NULL DEFAULT 1,"
        "  created_by    TEXT    NOT NULL,"
        "  created_at    TEXT    NOT NULL,"
        "  updated_at    TEXT    NOT NULL"
        ")")

    conn.execute(
        "CREATE TABLE IF NOT EXISTS bonus_templates ("
        "  id         INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  name       TEXT    NOT NULL,"
        "  created_by TEXT    NOT NULL,"
        "  created_at TEXT    NOT NULL"
        ")")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bonus_template_versions ("
        "  template_id INTEGER NOT NULL REFERENCES bonus_templates(id),"
        "  version     INTEGER NOT NULL,"
        "  body_json   TEXT    NOT NULL,"
        "  edited_by   TEXT    NOT NULL,"
        "  edited_at   TEXT    NOT NULL,"
        "  is_current  INTEGER NOT NULL DEFAULT 1,"
        "  PRIMARY KEY (template_id, version)"
        ")")

    conn.execute(
        "CREATE TABLE IF NOT EXISTS bonus_awards ("
        "  id                 INTEGER PRIMARY KEY AUTOINCREMENT,"
        # 🔴 **單一欄位**：一筆獎金結構上不可能橫跨多案（見 docstring）。
        "  quote_no           TEXT    NOT NULL,"
        # **凍結**的基數。取自精算的已存值，不在這裡重算。
        "  base_amount        INTEGER NOT NULL,"
        "  base_source        TEXT    NOT NULL"
        "    DEFAULT 'settlement.summary.netProfit',"
        "  template_id        INTEGER NOT NULL DEFAULT 0,"
        # 🔴 凍結版本：**改模板不影響已發放的那幾張**。
        "  template_version   INTEGER NOT NULL DEFAULT 0,"
        "  status             TEXT    NOT NULL DEFAULT '草稿',"
        "  voucher_no_accrual TEXT    NOT NULL DEFAULT '',"   # 核定那筆傳票
        "  voucher_no_payment TEXT    NOT NULL DEFAULT '',"   # 發放那筆傳票
        # 作廢／重開鏈 —— 與傳票同一條原則：**原單留著**。
        "  voided_at          TEXT    NOT NULL DEFAULT '',"
        "  voided_by          TEXT    NOT NULL DEFAULT '',"
        "  void_reason        TEXT    NOT NULL DEFAULT '',"
        "  supersedes_id      INTEGER NOT NULL DEFAULT 0,"
        "  created_by         TEXT    NOT NULL,"
        "  created_at         TEXT    NOT NULL,"
        "  updated_at         TEXT    NOT NULL"
        ")")
    # 🔴 **部分**唯一索引。`WHERE voided_at = ''` 那一段是整個設計的重點：
    #    少了它 ⇒ 發錯了改不了；而有了它 ⇒ 有效的只有一筆，歷史全部留著。
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bonus_awards_case_active"
        " ON bonus_awards(quote_no) WHERE voided_at = ''")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bonus_awards_quote"
        " ON bonus_awards(quote_no)")

    conn.execute(
        "CREATE TABLE IF NOT EXISTS bonus_award_lines ("
        "  id                     INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  award_id               INTEGER NOT NULL REFERENCES bonus_awards(id),"
        "  bonus_item_id          INTEGER NOT NULL REFERENCES bonus_items(id),"
        # 凍結：項目可能改名，而已發放的那一張要印出當時的名字。
        "  item_name_snapshot     TEXT    NOT NULL,"
        "  username               TEXT    NOT NULL,"
        # 凍結：這個人是從哪個來源來的（同一人身兼兩職會有兩列）。
        "  person_source_snapshot TEXT    NOT NULL,"
        # 🔑 比例一律用**基點**（1/10000）的整數，不用浮點：
        #    浮點相加不等於 1 是一個**沒有錯誤訊息**的缺陷。
        "  total_pct              INTEGER NOT NULL,"
        "  person_pct             INTEGER NOT NULL,"
        "  amount                 INTEGER NOT NULL"
        ")")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bonus_lines_award"
        " ON bonus_award_lines(award_id)")
    # 🔑 可見性是「本人只看自己那一列」⇒ 用 username 查是熱路徑。
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bonus_lines_user"
        " ON bonus_award_lines(username)")


def _m096_account_item_active(conn):
    """v96（2026-09-23 `FN1⑤`）：`account_items.is_active` —— 停用，不是刪除。

    ## 🔴 意圖早就寫在 `v93` 的註解裡，而**承載它的欄位不存在**

    `_m093_account_items` 逐字寫著 `system_default`「**可停用**、可改指向」。
    ⇒ 那句話從落地的第一天起就沒有東西實現它。

    ## ☠️ 少了它，使用者面對一個用不到的科目只有兩條路

    ```
    留著  => 下拉選單愈來愈長，而他每次都要略過它
    刪掉  => 已被傳票引用的刪不掉（v95 的 TRIGGER）
            **而沒被引用的，刪掉就沒了**
    ```
    🔑 而「刪掉就沒了」在會計上不可接受：**歷史單據的科目要留著。**
    📌 停用與刪除的差別正是這個：停用之後**過去的傳票還印得出科目名稱**。

    ## 🔴 為什麼是**欄位**不是塞進 JSON

    C 釘了這一句，而理由是查得動：
    ```
    欄位  SELECT ... WHERE is_active = 1        <= 「只列出還在用的」寫得出來
    JSON  每一列都要拉回 Python 再過濾          <= 而下拉選單每次都要全表掃描
    ```

    ## ⚠️ 預設 1（啟用），而**法定那 547 筆也一樣**

    停用是**使用者的決定**，不是資料的性質 ——
    ☠️ 把法定項目預設停用的話，使用者第一次打開科目樹會看到一片空的，
       而他不會知道那是預設值造成的。
    📌 而法定列被 `v93` 的 TRIGGER 擋著不可 UPDATE ⇒ **法定項目目前停不掉**。
       🔑 那是 TRIGGER 的範圍問題，不是這一支的：`BEFORE UPDATE ON account_items`
          擋的是整列。要讓法定項目可停用而其餘欄位仍唯讀，
          得把它改成 `BEFORE UPDATE OF code, name, level, parent_code`。
       ⚠️ **本輪不改** —— 沒有派工，而它會動到一個已經有測試釘著的 TRIGGER。
          已回報 A。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(account_items)")}
    if "is_active" not in cols:
        conn.execute(
            "ALTER TABLE account_items ADD COLUMN"
            " is_active INTEGER NOT NULL DEFAULT 1")
    # 🔑 下拉選單與科目樹每次都要用它過濾 ⇒ 給它索引。
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_account_items_active"
        " ON account_items(is_active)")


def _m095_vouchers(conn):
    """v95（2026-09-23）：傳票五張表 ＋ 索引 ＋ 兩支 TRIGGER。

    規格：`docs/windows/SPEC-VOUCHER.md`（施工圖）`§二`／`§七`。
    第一行逐字：`🔴 **這一份是施工圖：單一版本、無修訂層。照這一份做。**`
    ⚠️ **不要照 `SPEC-VOUCHER-HISTORY.md`** —— 它的 DDL 是被推翻的那一版。

    ## ⚙️ 前置實查（施工圖 `§七` 要求，2026-09-23 實跑）

    ```
    backend/motrix_erp.db        schema_version=92   傳票五張表：都不存在
    backend/motrix_erp_demo.db   schema_version=92   傳票五張表：都不存在
    ```
    ⇒ 沒有任何一個持久化 .db 已經有這些表 ⇒ **可以是新的一支，不必改既有的**。

    ## 🔴 範本拆兩張表，不是一張

    `AUTOINCREMENT` 只能用在**單一** `INTEGER PRIMARY KEY`，
    而 `(id, version)` 複合主鍵下 id 無法自動產生
    ⇒ `voucher_templates` 管 id（穩定）／`voucher_template_versions` 管歷史
       （每次編輯**新增一列，不覆蓋**）。

    ## 🔴 兩支 TRIGGER 防的是「FK 被關掉的那一條路」

    `voucher_lines.account_code` 已經宣告 `REFERENCES account_items(code)`，
    **而 SQLite 的外鍵強制隨時可能是關的**：
    ```
    db.py `PRAGMA foreign_keys=ON`  包在 try/except 裡  => 失敗會靜默
    demo 重置路徑                    **明著關掉它**
    ```
    ⇒ 光靠 `REFERENCES` 擋不住「改掉一個已被引用的科目代號」。
    ☠️ 而那個後果很安靜：`voucher_lines.account_code` 指向一個**不存在的代號**
       ⇒ 傳票印出來那一行是空白的科目名稱，**而它不報錯**。
    ⚠️ **它們不是「以防萬一」** —— 上面那兩條是實際存在的路徑，
       所以這段註解要留著，否則日後會有人**正當地**把它們當成多餘的東西刪掉。
    """
    # ══════════════════════════════════════════════════════════
    # 🔴 實表叫 `vouchers_all`，而 `vouchers` 是**只露出未作廢的 VIEW**
    # ══════════════════════════════════════════════════════════════
    #
    # ## 成因：`status` 被兩個問題共用
    # ```
    # 「走到流程哪裡」  => status（草稿／待審核／…／已過帳）
    # 「現在算不算數」  => **voided_at**
    # ```
    # 一張已過帳的傳票被作廢之後，`status` **仍然是「已過帳」**
    # （會計上正確：作廢不是把過帳收回去，帳上看得到那一次作廢）
    # ☠️ ⇒ 「本月已過帳的傳票」這個查詢**包含已作廢的那些** ⇒ **金額重複計算**。
    # 🔑 而失敗的樣子是**一個偏大的數字，不是一個錯誤** ⇒ 沒有人會報修它。
    # ⚠️ 而作廢＋重開是使用者裁定的**正常流程**，不是邊緣情境 ⇒ 它一定會發生。
    #
    # ## ⇒ 讓「預設查到的就是有效的」
    # ```
    # SELECT ... FROM vouchers      => 自動排除作廢單（絕大多數查詢要的）
    # SELECT ... FROM vouchers_all  => **明著寫才查得到全部**（稽核／寫入）
    # ```
    #
    # ## ✅ VIEW 不可寫入，而那是**優點**
    # ```
    # INSERT INTO vouchers / UPDATE vouchers  ->  OperationalError（當場炸）
    # ```
    # ⇒ 寫錯會**當場報錯**，不會安靜地做錯事。
    # 🔴 **不要為它加 `INSTEAD OF` trigger 去繞過** —— 那會把這個優點拆掉。
    #
    # ## ☠️ 而缺陷沒有消失，它**換了形狀**
    # ```
    # 舊：忘記加 WHERE voided_at = ''   => 多算
    # 新：**打錯表名**寫成 vouchers_all  => 🔴 不報錯，而它包含作廢單 => 一樣多算
    # ```
    # ⇒ 所以**每一處 `vouchers_all` 都要有一行註解說明「為什麼要查全部」**
    #    （C 的守門會檢查，而它配了反向控制）。
    #
    # ## ☠️☠️ `CREATE TABLE IF NOT EXISTS vouchers` 撞到同名 VIEW ⇒ **靜默**
    # 實跑（sqlite 3.53.1）：
    # ```
    # CREATE TABLE IF NOT EXISTS vouchers(...)  -> **OK，不報錯，而表沒有被建**
    #   之後 sqlite_master.type 仍是 'view'     <= **零訊息**
    # CREATE TABLE vouchers(...)（無 IF NOT EXISTS） -> OperationalError ✅
    # DROP TABLE vouchers ／ INSERT ／ UPDATE        -> OperationalError ✅
    # ```
    # 🔑 **五種寫法裡只有一種是靜默的，而它正好是 `init_db()` 全檔在用的那一種。**
    # ⚠️ ⇒ 日後有人很自然地寫 `CREATE TABLE IF NOT EXISTS vouchers`
    #    （邏輯實體本來就叫 vouchers）⇒ 表沒被建 ⇒ 寫入失敗、讀出來是過濾過的，
    #    **而症狀離成因很遠**。守門：型別檢查（`vouchers` 必須是 view）。
    conn.execute(
        "CREATE TABLE IF NOT EXISTS vouchers_all ("
        "  id                      INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  voucher_no              TEXT    NOT NULL,"          # YYYYMMDD-NNN[-Rn]
        # 🔴 可編輯，**僅草稿**，預設建檔當天（使用者 2026-09-23 改裁）。
        # ☠️ 做成「隨時可改」的後果：一張已過帳的傳票被改掉日期 ⇒
        #    **它換了一個會計期間，而帳上那一筆沒有跟著動。**
        "  voucher_date            TEXT    NOT NULL,"
        "  category                TEXT    NOT NULL DEFAULT '轉',"   # 沿用 T100
        "  summary                 TEXT    NOT NULL DEFAULT '',"
        "  status                  TEXT    NOT NULL DEFAULT '草稿',"
        "  created_by              TEXT    NOT NULL,"          # 製票（版面三格之一）
        "  posted_at               TEXT    NOT NULL DEFAULT '',"
        "  posted_by               TEXT    NOT NULL DEFAULT '',"
        "  posted_with_warning     INTEGER NOT NULL DEFAULT 0,"
        # 🔑 存**當時警示的內容**，不只是一個旗標：
        #    旗標只說「有警示」，而事後沒有人回得出「那時警示的是什麼」。
        "  posted_warning_snapshot TEXT    NOT NULL DEFAULT '',"
        "  voided_at               TEXT    NOT NULL DEFAULT '',"
        "  voided_by               TEXT    NOT NULL DEFAULT '',"
        "  void_reason             TEXT    NOT NULL DEFAULT '',"
        "  supersedes_no           TEXT    NOT NULL DEFAULT '',"  # 本張取代了哪一張
        "  ledger_confirmed        INTEGER NOT NULL DEFAULT 0,"   # 0 ⇒ 進首頁未確認計數
        "  custom_fields           TEXT    NOT NULL DEFAULT '{}',"  # 只在草稿可新增
        "  created_at              TEXT    NOT NULL,"
        "  updated_at              TEXT    NOT NULL"
        ")")
    # ⚠️ 索引一律建在**實表**上 —— VIEW 沒有自己的索引。
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_vouchers_no"
                 " ON vouchers_all(voucher_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_status"
                 " ON vouchers_all(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_date"
                 " ON vouchers_all(voucher_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_ledger"
                 " ON vouchers_all(ledger_confirmed)")
    # 🔑 `voided_at` 也要索引：VIEW 的 `WHERE voided_at = ''` 每一次查詢都會用到它。
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_voided"
                 " ON vouchers_all(voided_at)")

    # 🔴 VIEW 本身。`IF NOT EXISTS` 在這裡是安全的（同名實表存在時會報錯，
    #    不是靜默）—— 靜默的那一種是 `CREATE TABLE IF NOT EXISTS` 撞 VIEW。
    conn.execute(
        "CREATE VIEW IF NOT EXISTS vouchers AS"
        " SELECT * FROM vouchers_all WHERE voided_at = ''")

    conn.execute(
        "CREATE TABLE IF NOT EXISTS voucher_lines ("
        "  id                       INTEGER PRIMARY KEY AUTOINCREMENT,"
        # 🔴 指向**實表** `vouchers_all`，不是 VIEW —— 外鍵指到 VIEW 建不起來。
        # 📌 而語意上也該如此：作廢單的分錄**必須留著**（稽核要看得到）。
        "  voucher_id               INTEGER NOT NULL REFERENCES vouchers_all(id),"
        "  line_no                  INTEGER NOT NULL,"
        "  account_code             TEXT    NOT NULL REFERENCES account_items(code),"
        # 🔑 **過帳時凍結**：版面要印科目名稱，而科目名稱日後可能被改。
        "  account_name_snapshot    TEXT    NOT NULL DEFAULT '',"
        "  summary                  TEXT    NOT NULL DEFAULT '',"   # 產生當下凍結
        "  summary_template_id      INTEGER NOT NULL DEFAULT 0,"    # 追溯：哪個範本
        "  summary_template_version INTEGER NOT NULL DEFAULT 0,"    # 追溯：哪一版
        "  debit                    INTEGER NOT NULL DEFAULT 0,"    # 兩欄式，沿用 T100
        "  credit                   INTEGER NOT NULL DEFAULT 0,"    # 其中一欄為 0
        "  dept_code                TEXT    NOT NULL DEFAULT '',"
        "  source_type              TEXT    NOT NULL DEFAULT '',"   # 決定性連結：型別
        "  source_id                INTEGER NOT NULL DEFAULT 0,"    # 決定性連結：主鍵
        # 帶入當時的來源金額 ⇒ 日後比對「來源單據被改了沒」的基準。
        "  source_amount_snapshot   INTEGER NOT NULL DEFAULT 0,"
        "  counterparty             TEXT    NOT NULL DEFAULT ''"
        ")")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vlines_voucher"
                 " ON voucher_lines(voucher_id, line_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vlines_account"
                 " ON voucher_lines(account_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vlines_source"
                 " ON voucher_lines(source_type, source_id)")

    # ⚠️ `DEFAULT '[]'` **擋不住空紀錄** —— 一筆 `changes_json='[]'` 的留痕
    #    看起來像「有記錄」，而它什麼都沒說。
    # ⇒ 「缺改前值就寫入失敗」必須在**應用層**擋（施工圖 `§2.3`）。
    conn.execute(
        "CREATE TABLE IF NOT EXISTS voucher_edit_log ("
        "  id           INTEGER PRIMARY KEY AUTOINCREMENT,"
        # 🔴 同上：指實表。作廢單的異動紀錄是稽核的一部分。
        "  voucher_id   INTEGER NOT NULL REFERENCES vouchers_all(id),"
        "  changed_by   TEXT    NOT NULL,"
        "  changed_at   TEXT    NOT NULL,"
        "  changes_json TEXT    NOT NULL DEFAULT '[]'"          # 改前 → 改後
        ")")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vel_voucher"
                 " ON voucher_edit_log(voucher_id, changed_at)")

    conn.execute(
        "CREATE TABLE IF NOT EXISTS voucher_templates ("
        "  id          INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  name        TEXT    NOT NULL,"
        "  created_by  TEXT    NOT NULL,"
        "  created_at  TEXT    NOT NULL"
        ")")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS voucher_template_versions ("
        "  template_id INTEGER NOT NULL REFERENCES voucher_templates(id),"
        "  version     INTEGER NOT NULL,"
        "  body        TEXT    NOT NULL,"
        "  edited_by   TEXT    NOT NULL,"
        "  edited_at   TEXT    NOT NULL,"
        "  is_current  INTEGER NOT NULL DEFAULT 1,"
        "  PRIMARY KEY (template_id, version)"
        ")")

    # ── 兩支 TRIGGER（建在 `account_items` 上）────────────────────
    #
    # ⚙️ 正對照（施工圖 `§2.5`）：對 `source='custom'` 且**未被引用**的科目
    #    改 code ⇒ **必須成功**。少了這個方向，「全部都擋住」也會讓上半綠，
    #    ☠️ 而那會讓使用者連自己加的、沒有人用的科目都改不動。
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS account_items_referenced_code_no_update"
        " BEFORE UPDATE OF code ON account_items"
        " WHEN EXISTS (SELECT 1 FROM voucher_lines WHERE account_code = OLD.code)"
        " BEGIN"
        "   SELECT RAISE(ABORT, '此科目已被傳票引用，代號不可修改');"
        " END")
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS account_items_referenced_no_delete"
        " BEFORE DELETE ON account_items"
        " WHEN EXISTS (SELECT 1 FROM voucher_lines WHERE account_code = OLD.code)"
        " BEGIN"
        "   SELECT RAISE(ABORT, '此科目已被傳票引用，不可刪除');"
        " END")


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
    _m055_case_stage_calendar_event,              # v55
    _m056_user_list_prefs,                        # v56
    _m057_payment_request_stage,                   # v57
    _m058_backfill_deal_won_at,                    # v58
    _m059_fix_deal_won_at_from_audit_log,          # v59
    _m060_dispatch_files,                          # v60
    _m061_case_semi_unlock,                        # v61
    _m062_case_project_merge,                      # v62
    _m063_work_log_contact_type,                   # v63
    _m064_network_plans,                           # v64
    _m065_automation_guide,                        # v65
    _m066_parts_safety_stock,                      # v66
    _m067_approval_delegates,                      # v67
    _m068_dispatch_payable_date_invoice_files,      # v68
    _m069_t100_export_confirmations,                # v69
    _m070_stock_batches,                            # v70
    _m071_paid_bank_account,                        # v71
    _m072_totp,                                     # v72
    _m073_webauthn_credentials,                     # v73
    _m074_webauthn_rp_id,                           # v74
    _m075_case_extra_expenses,                      # v75
    _m076_xe_change_requests_and_stage_done,        # v76
    _m077_completion_notes,                         # v77
    _m078_completion_contact_phone,                 # v78
    _m079_user_activity,                            # v79
    _m080_user_request_log,                         # v80
    _m081_edit_presence,                            # v81
    _m082_feed_attachments,                         # v82
    _m083_backup_retention_policy,                  # v83
    _m084_backfill_role_bypass_modules,             # v84
    _m085_procurement_lead_time,                    # v85
    _m086_tender_radar,                             # v86
    _m087_tender_notify,                            # v87
    _m088_tender_detail_fields,                     # v88
    _m089_geocode_cache,                            # v89
    _m090_quotation_location,                       # v90
    _m091_geocode_usage,                            # v91
    _m092_tender_mark,                              # v92
    _m093_account_items,                            # v93
    _m094_load_account_items,                       # v94
    _m095_vouchers,                                 # v95
    _m096_account_item_active,                      # v96
    _m097_bonus,                                    # v97
    _m098_edit_log_retention,                       # v98
    _m099_voucher_signatures,                       # v99
    _m100_voucher_attachments,                      # v100
    _m101_voucher_approval,                         # v101
    _m102_bonus_award_approval,                     # v102
    _m103_bonus_award_lines_username,               # v103
    _m104_bonus_groups,                              # v104
    _m105_bonus_award_lines_manual_basis,           # v105
    _m106_company_profile_identity_backfill,        # v106
    _m107_deactivate_legacy_demo_account,           # v107
    _m108_bonus_item_people,                        # v108
    _m109_edit_log_no_delete,                       # v109
    _m110_voucher_category_manual,                  # v110
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
