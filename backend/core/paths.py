# -*- coding: utf-8 -*-
"""資料位置的唯一來源（DATA-COMPAT §4 A-1，CORE-SPEC「使用者裁示」原地讀取）。

[單位] plat:paths    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] AUTOSTART_BAT, BACKEND_DIR, BACKUP_ALERT_DIR, BUILD_COMMIT_FILE, CERTS_DIR, CERT_PEM, DB_PATH,
    DEMO_CASE_CLOSING_PDF_ARCHIVE_DIR, DEMO_CONTRACTOR_VOUCHER_PDF_ARCHIVE_DIR, DEMO_DB_PATH,
    DEMO_INVOICE_VOUCHER_PDF_ARCHIVE_DIR, DEMO_PAYMENT_REQUEST_PDF_ARCHIVE_DIR,
    DEMO_PAYSLIP_ARCHIVE_DIR, DEMO_PDF_ARCHIVE_DIR, DEMO_PROJECT_PHOTOS_DIR,
    DEMO_SHIPPING_PDF_ARCHIVE_DIR, DEMO_UPLOADS_DIR, DEPLOYED_COMMIT_FILE, DatabaseMissing,
    FRONTEND_DIR, FRONTEND_PAGES_DIR, HEARTBEAT_CONFIG, INITIAL_ADMIN_CREDENTIALS, INITIAL_DEMO_CREDENTIALS, INSTALL_ROOT,
    LICENSE_PATH, LOCAL_DB_BACKUP_DIR, LOGS_DIR, NEW_DB_FLAG, NO_CLOUD_MARKER, NO_EMAIL_SEND_MARKER,
    PDF_ARCHIVES, PROJECT_PHOTOS_DIR, SERVER_LOG, STATIC_DATA_DIR, UPLOADS_ROOT, VERSION_MANIFEST,
    backend, modules_disabled_cache, require_db, root
[不變式] 錨點是安裝根目錄，不是呼叫者的 __file__；值與 V9 原位置逐一相同（原地讀取）
[契約題] tests/platform/test_core_paths.py, tests/platform/test_no_file_relative_data_paths.py
[注意] 全 backend 唯一允許用 __file__ 算資料路徑的地方；本檔不 import DB（system_settings 覆寫由呼叫端讀）

🔴 **錨點是安裝根目錄，不是呼叫者的 `__file__`。**
模組搬進 `modules/<key>/api/` 之後，`dirname(__file__)` 算出來的位置會靜默往下偏一層：
`db.py` 搬進 `core/` ⇒ 指到 `backend/core/motrix_erp.db` ⇒ sqlite 建一個空庫、
從 v1 跑到 v116 ⇒ **系統正常啟動、資料全空**。那不是報錯，是成功。
⇒ 產品碼一律從這裡取路徑；本檔是全 backend 唯一允許用 `__file__` 算資料路徑的地方
（守門：`tests/platform/test_no_file_relative_data_paths.py`）。

值與 V9 原位置**逐一相同**（原地讀取）；只收斂計算方式，不搬任何東西。
各呼叫端仍保留原本的模組層級名字（`db.DB_PATH`、`archive._LOCAL_DB_BACKUP`…），
測試 monkeypatch 那些名字的方式不變。

`system_settings` 可覆寫的位置（6 個 `*_pdf_base_path`、`payslip_archive_path`）
在這裡只提供**預設值**；讀設定仍由各呼叫端做（本檔不 import DB，避免循環）。
"""
import logging
import os

logger = logging.getLogger(__name__)

#: backend/ —— 本檔位於 backend/core/paths.py
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: 安裝根目錄（backend/ 的上一層；uploads/、PDF 目錄、frontend/ 在這裡）
INSTALL_ROOT = os.path.dirname(BACKEND_DIR)


def backend(*parts: str) -> str:
    return os.path.join(BACKEND_DIR, *parts)


def root(*parts: str) -> str:
    return os.path.join(INSTALL_ROOT, *parts)


# ── 資料庫 ─────────────────────────────────────────────────────────────────
DB_PATH = backend("motrix_erp.db")
DEMO_DB_PATH = backend("motrix_erp_demo.db")
#: 凍結 migration v94 讀的會計科目靜態檔（隨程式碼出貨）
STATIC_DATA_DIR = backend("data")

# ── 上傳 ───────────────────────────────────────────────────────────────────
#: 原本 5 處各自計算（helpers/uploads、routers/uploads、photos、archive、db）
UPLOADS_ROOT = os.path.realpath(root("uploads"))
PROJECT_PHOTOS_DIR = os.path.join(UPLOADS_ROOT, "projects")
DEMO_PROJECT_PHOTOS_DIR = os.path.join(UPLOADS_ROOT, "_demo_projects")
DEMO_UPLOADS_DIR = os.path.join(UPLOADS_ROOT, "_demo_uploads")

# ── PDF 存檔（預設值；system_settings 可覆寫）──────────────────────────────
#: 鍵＝pdf_gen 的單據代號；值＝(system_settings 鍵, 預設目錄)
PDF_ARCHIVES = {
    "quotation":          ("pdf_base_path",                    root("報價單PDF")),
    "shipping":           ("shipping_pdf_base_path",           root("出貨單PDF")),
    "contractor_voucher": ("contractor_voucher_pdf_base_path", root("承攬商匯款申請PDF")),
    "invoice_voucher":    ("invoice_voucher_pdf_base_path",    root("開票申請憑據PDF")),
    "payment_request":    ("payment_request_pdf_base_path",    root("請款單PDF")),
    "case_closing":       ("case_closing_pdf_base_path",       root("結案報表PDF")),
    #: 勞報單：V9 只有寫死的 backend/export_archive，沒有設定鍵（DATA-COMPAT A-3 補上）
    "payslip":            ("payslip_archive_path",             backend("export_archive")),
}

DEMO_PDF_ARCHIVE_DIR = backend("_demo_pdf_archive")
DEMO_PAYSLIP_ARCHIVE_DIR = backend("_demo_payslip_archive")
DEMO_SHIPPING_PDF_ARCHIVE_DIR = backend("_demo_shipping_pdf_archive")
DEMO_CONTRACTOR_VOUCHER_PDF_ARCHIVE_DIR = backend("_demo_contractor_voucher_pdf_archive")
DEMO_INVOICE_VOUCHER_PDF_ARCHIVE_DIR = backend("_demo_invoice_voucher_pdf_archive")
DEMO_PAYMENT_REQUEST_PDF_ARCHIVE_DIR = backend("_demo_payment_request_pdf_archive")
DEMO_CASE_CLOSING_PDF_ARCHIVE_DIR = backend("_demo_case_closing_pdf_archive")

# ── 備份 ───────────────────────────────────────────────────────────────────
LOCAL_DB_BACKUP_DIR = backend("db_backups")
BACKUP_ALERT_DIR = root("backup_alerts")
#: 開發機不上雲端的標記（.gitignore 內，永不進部署包）
NO_CLOUD_MARKER = root(".no_cloud_archive")
#: 開發機不寄信的標記（2026-09-25 使用者裁示：預設寄信，開發機放這個擋；.gitignore 內）
NO_EMAIL_SEND_MARKER = root(".no_email_send")

# ── log ────────────────────────────────────────────────────────────────────
LOGS_DIR = backend("logs")
SERVER_LOG = os.path.join(LOGS_DIR, "server.log")

# ── 設定、憑證、身分檔 ─────────────────────────────────────────────────────
HEARTBEAT_CONFIG = backend("heartbeat_config.json")
LICENSE_PATH = backend("license.key")
CERTS_DIR = backend("certs")
CERT_PEM = os.path.join(CERTS_DIR, "cert.pem")
INITIAL_ADMIN_CREDENTIALS = backend(".initial_admin_credentials.txt")
INITIAL_DEMO_CREDENTIALS = backend(".initial_demo_credentials.txt")
BUILD_COMMIT_FILE = backend(".build_commit")
DEPLOYED_COMMIT_FILE = backend(".deployed_commit.json")
VERSION_MANIFEST = backend("version_manifest.json")
#: 排程啟動腳本。內含**這台機器的設定**（對外連線總開關、安裝路徑），不是程式碼（稽核 X-9b M-4）
AUTOSTART_BAT = backend("autostart.bat")
FRONTEND_DIR = root("frontend")
#: L1 頁面（與還沒搬家的模組頁面）；模組頁面的實際位置由 core.pages 依 module.json 決定（階段 C）
FRONTEND_PAGES_DIR = os.path.join(FRONTEND_DIR, "pages")


def modules_disabled_cache(db_path: str) -> str:
    """停用清單的「上一次成功讀到」快取（STATES-PLATFORM P-SW-05）：主庫旁的 `<主庫>.modules_disabled.json`。

    F4（可重建）：不上雲、不進每日匯出、不進部署包（.gitignore）。放在主庫旁而不是固定路徑：
    測試夾具換掉 `db.DB_PATH` 時，快取跟著隔離，不會寫到真實目錄。"""
    return str(db_path) + ".modules_disabled.json"


# ── 主庫不存在時拒絕啟動 ───────────────────────────────────────────────────
#: 全新安裝旗標。只在「第一次啟動、確定要建新庫」時設，建好後移除。
NEW_DB_FLAG = "MOTRIX_CREATE_NEW_DB"


class DatabaseMissing(RuntimeError):
    """主庫檔不存在且沒有全新安裝旗標。"""


def require_db(path: str = None, env=None) -> None:
    """啟動前確認主庫存在；不存在就拒絕，除非帶 `MOTRIX_CREATE_NEW_DB=1`。

    🔴 不存在時 sqlite3.connect 會**默默建一個空檔**，init_db 再把它升到最新 ⇒
    「路徑算錯」「磁碟機沒掛上」「庫被搬走」三種情況全部長成「一套乾淨的新系統」。
    拒絕啟動是唯一會被人看見的反應。

    旗標仍設著而庫已存在 ⇒ 只記 WARNING（旗標忘了移除會讓下一次事故失去這道守門）。
    """
    path = path or DB_PATH
    env = os.environ if env is None else env
    flag_on = (env.get(NEW_DB_FLAG) or "").strip() == "1"
    if os.path.isfile(path):
        if flag_on:
            logger.warning("%s=1 仍設著，但資料庫已存在（%s）——請移除旗標，"
                           "否則日後庫檔遺失時會默默建一個新空庫。", NEW_DB_FLAG, path)
        return
    if flag_on:
        logger.warning("找不到資料庫 %s，因 %s=1 視為全新安裝，將建立新庫。", path, NEW_DB_FLAG)
        return
    raise DatabaseMissing(
        "找不到資料庫：%s\n"
        "若這是既有安裝：檢查安裝目錄、磁碟、還原備份（backend/db_backups/），不要重新建庫。\n"
        "若確定是全新安裝：設定環境變數 %s=1 後啟動一次，建好後移除。" % (path, NEW_DB_FLAG))
