"""
MOTRIX ERP — FastAPI 後端
執行：uvicorn main:app --reload --port 666 --host 0.0.0.0
"""
import os
import time
import logging
from datetime import datetime

# ── 啟動逐步耗時（T21-1，2026-09-29）──────────────────────────────────────────
# 正式機啟動到健檢通過從 3～4 秒變 14 秒（server.log 的 CORS 行 → GEO 行 11.2 秒），而 log 分不出是哪一段。
# 每段結束呼叫一次 `_startup_step(名稱)` ⇒ 一行 `STARTUP_STEP <名稱> <毫秒>ms`（距上一段結束）；
# 最後 `_startup_total()` ⇒ `STARTUP_TOTAL <毫秒>ms steps=<段數>`（距 main.py 開始執行；不含 Python／uvicorn 本身載入）。
# 查法：`Select-String -Path logs\server.log -Pattern 'STARTUP_'`（格式固定，守門 tests/platform/test_startup_timing_2026_09_29.py）。
# ⚠️ 只記錄，不改任何啟動行為、順序、例外處理；記錄本身出錯一律吞掉——診斷不可以變成起不來的理由（同 BR1）。
# ⚠️ `logging.basicConfig` 之前的段（import）先暫存，root 有 handler 之後才一起印（uvicorn 只設它自己的 logger，
#    basicConfig 之前印的 INFO 會被丟掉）。
# ⚠️ 不可以放進 `if MOTRIX_DISABLE_SCHEDULERS` 區塊裡：test_geocode_warm_async 逐字執行那個區塊（不認得的名字 ⇒ NameError）。
_STARTUP_T0 = time.monotonic()
_STARTUP_LAST = [_STARTUP_T0]
_STARTUP_PENDING = []
_STARTUP_COUNT = [0]


def _startup_flush():
    if not logging.getLogger().handlers:
        return
    log = logging.getLogger(__name__)
    while _STARTUP_PENDING:
        log.info("%s", _STARTUP_PENDING.pop(0))


def _startup_step(name):
    """記一段啟動耗時（距上一段結束）。不丟例外。"""
    try:
        now = time.monotonic()
        _STARTUP_PENDING.append("STARTUP_STEP %s %dms" % (name, int(round((now - _STARTUP_LAST[0]) * 1000))))
        _STARTUP_LAST[0] = now
        _STARTUP_COUNT[0] += 1
        _startup_flush()
    except Exception:                                        # noqa: BLE001
        pass


def _startup_total():
    """最後一行：main.py 開始執行到現在的總耗時。不丟例外。"""
    try:
        _STARTUP_PENDING.append("STARTUP_TOTAL %dms steps=%d" % (
            int(round((time.monotonic() - _STARTUP_T0) * 1000)), _STARTUP_COUNT[0]))
        _startup_flush()
    except Exception:                                        # noqa: BLE001
        pass


from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import mimetypes
# D 稽核（h-fonts-woff2 觀察 1）：Windows 的 mimetypes 登錄表常沒有 .woff2 ⇒ StaticFiles 回 application/octet-stream；固定成標準型別
mimetypes.add_type("font/woff2", ".woff2")
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from db import get_db, init_db, DEMO_DB_PATH, set_demo_mode
from helpers import (
    init_default_admin, init_demo_account, _cleanup_sessions, _prune_login_locks,
    init_unlock_passwords, flag_weak_passwords,
    _sync_module_versions, DEMO_TOKEN_PREFIX,
)
from archive import _schedule_weekly, _schedule_daily
import trail

from helpers import licensing as license_core
from helpers import geo as geo_core
from core import loader as module_loader, pages as module_pages, registry as module_registry
_startup_step("import_core")
# L1：GCIS 與 /api/now（M08 搬遷 ②）；註解不寫在 import 行尾（test_router_registration 以行解析 import，第六班列車全量抓到）
from routers import company_lookup
from routers import auth, customers, parts, system, module_versions, search, org_structure, list_prefs, uploads, approval_delegates, approval_queue, licensing, map_points
from routers import item_reads
# CUSTOMIZATION-SPEC §3.5 定義文件庫；P8 自訂模組引擎（通用 API）
from routers import definitions, custom_records
from routers import modules
from routers import legal_params
from routers import mail_settings
from routers import platform_menu
from routers import platform_catalog
_startup_step("import_routers")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# L2 模組（modules/*）由載入器登錄；main 不指名任何 L2 模組（CORE-SPEC §2）。
# 載入失敗的模組只記 ERROR，不擋啟動。
# CORE-SPEC §9c：② 未授權（helpers/licensing）> ③ 管理者停用（system_settings.modules_disabled，
# 啟動時讀一次 ⇒ 改了要重啟才生效）。兩者都不 import 該模組，資料不動。
# STATES-PLATFORM P-SW-05：停用清單讀不到（主庫被鎖、損毀）時不可以當成「沒有停用」——
# 沿用上次成功讀到的快取；沒有快取 ⇒ 所有模組暫不載入（寧可少開，不可多開），管理頁與狀態端點標示。
# 這一段在 helpers/module_startup.py（乾跑 migration、V9→新版轉換也要先載模組，模組 migration 才會登記；CORE 1.58）。
from helpers import module_startup as _module_startup
_module_startup.load_modules_like_startup()
_startup_step("load_modules")

from core import paths as _paths
FRONTEND_DIR = _paths.FRONTEND_DIR

#: 🔴 API 文件頁（/openapi.json、/docs、/docs/oauth2-redirect、/redoc）**預設關閉**（2026-09-28 主持裁示；E 盤點：
#: 未登入可讀、整份 API 結構外露）。只有明確環境旗標 `MOTRIX_API_DOCS=1` 才開（開發機要看文件時自己設）。
#: ⚠️ 不可以用安裝路徑猜「這是開發機」（可販售產品：客戶的安裝路徑什麼都有可能）——只認旗標。
API_DOCS_ENV = "MOTRIX_API_DOCS"


def _docs_kwargs(environ=None) -> dict:
    """FastAPI 的文件路由設定。旗標不是 "1" ⇒ 三個都 None（FastAPI 不註冊這些路由；oauth2-redirect 跟著 docs_url）。"""
    on = (os.environ if environ is None else environ).get(API_DOCS_ENV) == "1"
    return {"docs_url": "/docs" if on else None, "redoc_url": "/redoc" if on else None,
            "openapi_url": "/openapi.json" if on else None}


_DOCS = _docs_kwargs()
# ⚠️ 明列關鍵字，不用 `**`（守門 test_case_summary_purpose：非字面值的 ** 呼叫基線 0）
app = FastAPI(title="MOTRIX ERP API", version="1.0.0", docs_url=_DOCS["docs_url"],
              redoc_url=_DOCS["redoc_url"], openapi_url=_DOCS["openapi_url"])

_DEFAULT_CORS_ORIGINS = [
    "http://localhost:666",
    "http://127.0.0.1:666",
    "http://172.16.10.177:666",
    # 2026-08-27：正式機導入 HTTPS 後（見 backend/tools/https_setup.ps1），
    # 保留原本 http 三筆是因為開發機仍是明文運作，共用同一份 main.py
    "https://localhost:666",
    "https://127.0.0.1:666",
    "https://172.16.10.177:666",
]


def _resolve_cors_origins(env_value: str = None) -> list:
    """決定 CORS 白名單：有設 `MOTRIX_CORS_ORIGINS` 就用它（逗號分隔），否則用預設。

    2026-09-11：先前這份清單是直接寫死在 `add_middleware()` 呼叫裡，換機器或換 IP
    就得改程式碼重新部署（`DR-SOP.md` §5 長期列為待改進）。改成環境變數之後，
    **未設定時的行為與改動前逐字相同**——預設值就是原本那六筆，不是空清單，
    所以忘了設環境變數不會把所有人擋在外面。

    ⚠️ 這是安全邊界，不是一般設定：`MOTRIX_CORS_ORIGINS` 一旦設了就**完全取代**
    預設清單（不是附加），設錯會讓正式機的前端打不到自己的 API。設定格式範例：
        MOTRIX_CORS_ORIGINS=https://erp.example.com:666,https://192.168.1.10:666

    註：目前 `motrix.internal`（正式機 2026-09-11 起的正式網址）**不在預設清單裡**。
    今天沒事是因為前端跟 API 由同一個 FastAPI 服務提供、屬同源請求，CORS 根本不會
    介入；但若哪天前端被拆到別的來源，這裡要記得補。
    """
    raw = os.getenv("MOTRIX_CORS_ORIGINS") if env_value is None else env_value
    parsed = [o.strip() for o in (raw or "").split(",") if o.strip()]
    return parsed or list(_DEFAULT_CORS_ORIGINS)


# 🔴 `BR1`：**這個行程載入的是哪一份程式碼**，在啟動時就說出來。
#
# ☠️ 2026-09-23 的事故：666 的行程 05:56 起來、載入 dd50d2e，
#    而磁碟上已經往前 25 個 commit ⇒ **使用者在瀏覽器上一個都沒看到**。
#    git 是對的、全量是綠的、他的畫面是舊的，而**三邊都不會報錯**。
# 🔑 「我改好了」與「他看得到」之間有一個沒有人在看的間隔。
# ⚠️ 而 log 只是三格裡的第一格 —— 真正被看到的是頁尾那一格
#    （只做 log ＝ 把它放進一個沒有人會去看的地方，而現在的問題正是沒有人去看）。
try:
    from helpers.build_info import startup_line as _build_startup_line
    logger.info("%s", _build_startup_line())
except Exception as _e:                                  # noqa: BLE001
    # 取版本是**診斷**不是功能 —— 它不可以變成伺服器起不來的理由。
    logger.warning("BR1 啟動版本資訊不可得：%s", type(_e).__name__)
_startup_step("build_info")

_cors_origins = _resolve_cors_origins()
logger.info(
    "CORS allow_origins（%s）：%s",
    "來自 MOTRIX_CORS_ORIGINS" if os.getenv("MOTRIX_CORS_ORIGINS") else "預設值",
    ", ".join(_cors_origins),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
_startup_step("app_cors")

_PUBLIC_API_PATHS = {
    "/api/auth/login", "/api/auth/login/totp", "/api/auth/logout",
    "/api/ping", "/api/system/version",
    # 2026-09-26 A8d：登入頁的公司名稱（統編只在帶有效登入時回，見 routers/auth.py::system_branding）
    "/api/system/branding",
    # 2026-09-27 H10：品牌圖檔（登入頁 LOGO、favicon 由瀏覽器直接抓，沒有 header）；內容本來就是公開頁面上的圖
    "/api/system/branding/logo", "/api/system/branding/logo-dark", "/api/system/branding/favicon",
    # 2026-09-08：手機掃 QR 核准登入——手機打開確認頁面時完全沒有任何 session，
    # 這三個端點本身各自用 challenge_token／密碼做驗證，見 routers/auth.py。
    "/api/auth/login/qr-info", "/api/auth/login/qr-approve", "/api/auth/login/qr-status",
    # 2026-09-09：WebAuthn/Passkey 未登入登入流程——login/begin 查詢帳號 Passkey 清單，
    # login/complete 驗證認證器簽名；皆自行驗證，無需 Bearer token。
    "/api/auth/webauthn/login/begin", "/api/auth/webauthn/login/complete",
    # 2026-09-08：供本機部署儀表板工具（deploy_dashboard.py）查詢正式機目前
    # 部署版本用，純讀 commit 資訊，無敏感內容，不需要密碼／session。
    "/api/system/deployed-version",
    # 2026-09-10：WebAuthn 設定狀態檢查（未登入時）——login.html 和 change-password.html
    # 需要知道 WebAuthn 是否已配置，以決定是否顯示 Passkey 登入/註冊按鈕。
    "/api/system/webauthn-config-status",
}
_IDLE_TIMEOUT_SECONDS = 8 * 3600  # 8 hours（一般角色）
# 2026-08-28 資安優化：superadmin/admin 能看財務/稽核紀錄/使用者管理等敏感資料，
# 沿用一般角色的 8 小時閒置門檻風險偏高（電腦沒鎖畫面就離開一整個上班日都還有效）；
# 這兩層角色改用較短的門檻，其餘（last_active 讀寫、300 秒節流寫入、首次補值）邏輯
# 完全共用下方既有機制，只有超時判斷用的門檻值依角色不同。
_ADMIN_IDLE_TIMEOUT_SECONDS = 2 * 3600  # 2 hours（superadmin/admin）
# Allowed while must_change_password=1 (everything else returns 403)
_MUST_CHANGE_PW_ALLOWED = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/me",
    "/api/auth/change-password",
    "/api/ping",
}

# 本公司資料未設定時仍可用的 API（COMPANY-SETUP-GATE §4.1，D 稽核 CG-M2）：**精確的 (方法, 路由樣板)**，每條附理由；
# 不收萬用字元、不收描述性條目。其餘 /api 一律 428（預設擋：新 API 自動被擋，不必記得加）。
# 不在這裡的：備份還原、模組管理、使用者管理、部署與更新、所有業務與報表——未設定時要用 ⇒ 經 72 小時暫時放行。
# 守門：tests/test_company_setup_gate_2026_09_28.py（每條存在於路由表、方法相符、理由 ≥ 20 字；_MUST_CHANGE_PW_ALLOWED 與
# licensing.LICENSE_EXEMPT_PATHS 都被涵蓋）。_PUBLIC_API_PATHS 在登入檢查之前就放行，本來就不經過這道閘門。
_COMPANY_SETUP_ALLOWED = {
    ("POST", "/api/auth/login"): "帳號本身必要：登入（同「必須先改密碼」白名單）",
    ("POST", "/api/auth/logout"): "帳號本身必要：登出（同「必須先改密碼」白名單）",
    ("GET", "/api/auth/me"): "帳號本身必要：前端取目前使用者與角色，決定導向設定頁或說明頁",
    ("PATCH", "/api/auth/change-password"): "帳號本身必要：改密碼（同「必須先改密碼」白名單；首次登入要先改密碼）",
    ("GET", "/api/ping"): "健康檢查：部署工具與前端判斷服務是否在線（不含任何資料）",
    ("GET", "/api/license/status"): "授權自救（licensing.LICENSE_EXEMPT_PATHS）：兩道閘門同時生效時要能看到授權狀態",
    ("GET", "/api/settings/company-profile"): "設定頁讀取本公司資料（最高管理員才看得到完整內容，端點自己驗權限）",
    ("PUT", "/api/settings/company-profile"): "設定頁存檔與「確認本公司資料」（限最高管理員，端點自己驗權限）",
    ("PUT", "/api/settings/branding/{kind}"): "設定頁上傳品牌圖（LOGO／favicon；限最高管理員，端點自己驗權限）",
    ("GET", "/api/settings/branding"): "設定頁「品牌與公司名稱」卡讀取目前的品牌圖狀態（限最高管理員，端點自己驗權限）",
    ("DELETE", "/api/settings/branding/{kind}"): "設定頁品牌圖「恢復預設」（刪除上傳的圖；限最高管理員，端點自己驗權限）",
    ("GET", "/api/settings/company-setup/status"): "前端判斷要導向設定頁還是說明頁、以及橫幅內容",
    ("GET", "/api/platform/menu"): "側欄：未設定時只顯示設定頁入口（回應內容已依權限過濾）",
    ("GET", "/api/auth/totp/status"): "帳號安全狀態（設定頁頂端提示是否已啟用兩階段驗證）",
    ("POST", "/api/auth/totp/setup"): "帳號本身必要：首次綁定兩階段驗證（產生金鑰）",
    ("POST", "/api/auth/totp/enable"): "帳號本身必要：首次綁定兩階段驗證（確認驗證碼後啟用）",
}


# 慢請求記錄（2026-09-10）
#
# 起因：追 flaky e2e 時發現 db.py 的 `sqlite3.connect(path, timeout=30)` 表示任何
# 一次寫入在鎖被佔住時最多會等 30 秒。逐段計時證實卡的是主 INSERT/commit 本身
# （不是 commit 後那幾筆 notification/audit 寫入——那是當時的錯誤推論），也就是
# SQLite 單一寫入者的本質，不是哪一段程式碼寫錯。
#
# 接著把可能長時間佔鎖的地方全查過一遍：`reset_demo_db()` 的 VACUUM 只動 demo
# 那個獨立檔案、另一個 VACUUM 在 migration 裡（啟動時跑一次）、三處 BEGIN
# IMMEDIATE 都是刻意的短交易。**正式路徑沒有任何東西會長時間佔住寫入鎖**，
# 所以沒有對寫入路徑動刀——那會是沒有根據的改動。
#
# 但這種事真的發生時是完全看不見的（使用者只覺得「這次存檔特別久」，不會回報，
# 也沒有任何紀錄）。這條 middleware 就是那道保險：超過門檻只寫一行 log，不改變
# 任何行為。日後若有人回報「存報價單偶爾要等很久」，先看 server.log 裡的
# `SLOW REQUEST`——有紀錄就是真的撞到鎖，沒有就要往別的方向查。
_SLOW_REQUEST_SECONDS = float(os.environ.get("MOTRIX_SLOW_REQUEST_SECONDS", "5"))

# 在線時間統計（2026-09-14，DB v79）
#
# 「這段時間人在線上」的認定：兩次請求之間的間隔在 _ACTIVITY_GAP_MAX 以內就整段
# 算進在線時數，超過就視為中間離開過、只重新起算不補空白。門檻取 600 秒是因為
# 上面那段 `idle_secs > 300` 的節流：last_active 最快也要 300 秒才寫一次，門檻若
# 也設 300 會卡在邊界上，一半的請求會被判成「離開過」。
#
# ⚠️ 這是「活躍時間」不是「登入時長」——開著分頁去開會不會被算進去（沒有請求就
# 沒有累加）。要改成後者得改用心跳，那會讓每個閒置分頁每分鐘打一次伺服器。
_ACTIVITY_GAP_MAX = 600


def _record_user_activity(user_id: int, now_dt, gap_seconds: float) -> None:
    """把這一段間隔累加進當天的在線時數（見 db.py::_m079_user_activity）。

    寫入失敗一律吞掉：這是統計資料，不該讓它擋下任何一個正常請求。
    """
    if gap_seconds <= 0 or gap_seconds > _ACTIVITY_GAP_MAX:
        return
    day = now_dt.strftime("%Y-%m-%d")
    now_iso = now_dt.isoformat()
    try:
        ac = get_db()
        ac.execute(
            "INSERT INTO user_activity_daily (user_id, day, active_seconds, first_seen_at, last_seen_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(user_id, day) DO UPDATE SET "
            "  active_seconds = active_seconds + excluded.active_seconds, "
            "  last_seen_at   = excluded.last_seen_at",
            (user_id, day, int(gap_seconds), now_iso, now_iso),
        )
        ac.commit()
        ac.close()
    except Exception:
        pass


@app.middleware("http")
async def slow_request_log(request: Request, call_next):
    _t0 = time.monotonic()
    request.state.t0 = _t0      # W-6：給 _unhandled_handler 算「開始到出錯」幾秒
    response = await call_next(request)
    _elapsed = time.monotonic() - _t0
    if _elapsed >= _SLOW_REQUEST_SECONDS and request.url.path.startswith("/api/"):
        logger.warning(
            "SLOW REQUEST %.1fs  %s %s  status=%s"
            "（DB 寫入鎖等待上限 30s，見 db.py::_connect）",
            _elapsed, request.method, request.url.path, response.status_code,
        )
    return response


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    p = request.url.path
    # 2026-09-08 修復：外部函式庫自架後（見 §9「外部函式庫自架」），vendor 目錄下的
    # 檔案是版本號釘死在檔名裡的第三方函式庫（如 alpine-3.17.1.min.js），跟會頻繁
    # 覆寫的頁面 .html/.css/.js 完全不同類——版本升級一定會改檔名，同名檔案內容
    # 保證不變，可以安全長效快取。原本這條規則不分青紅皂白把 .js/.css 全部設成
    # no-store，CDN 自架前沒差（CDN 自己另外設了快取表頭），自架後這些函式庫變成
    # 每次換頁都要向本機同一個 uvicorn process 重新要一次，徒增同源請求量與延遲。
    if p.startswith("/static/vendor/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
    # 2026-09-26（D 調查 O5）：字型 4 支 otf 共約 21 MB，原本沒有任何快取表頭 ⇒ 每開一頁都可能重抓，
    # 首頁的 load 事件被兩支約 5 MB 的字型綁住。字型檔名沒有帶版本號（換字型不一定換檔名）⇒ 不用 immutable，
    # 給 7 天、到期用 ETag／Last-Modified 重新驗證（StaticFiles 本來就帶）。
    if p.startswith("/fonts/"):
        response.headers["Cache-Control"] = "public, max-age=604800"
        return response
    if p.endswith((".html", ".css", ".js")) or p in ("/", ""):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# 逐條操作軌跡（2026-09-14，DB v80）
#
# 只記「人的行為」：輪詢與開頁自動打的端點一律跳過，否則每個開著的分頁每分鐘就會
# 塞進好幾列，真正有意義的動作會被淹掉。
#
# 2026-09-15：「哪些不記」「一次點擊打出的一串請求怎麼收斂」都搬到 `trail.py`
# ——讀取端（routers/system.py 的軌跡端點）要用同一份清單把舊資料也一起藏起來，
# 兩邊各存一份遲早不同步，而不同步的那一刻讀取端就會露出這裡決定不要的東西。
def _record_request_trail(user_id: int, now_dt, method: str, path: str,
                          referer: str, status: int) -> None:
    """把一次請求記進操作軌跡。失敗一律吞掉——這是觀測資料，不該擋下正常請求。"""
    if trail.should_skip(path):
        return
    page = ""
    if referer:
        try:
            page = referer.split("?")[0].rstrip("/").split("/")[-1] or ""
        except Exception:
            page = ""
    now_iso = now_dt.isoformat()
    try:
        tc = get_db()
        # 開一張案件會同時撈 base + finance-summary + material-orders + …，那是
        # 一次點擊而不是六次。同一個群組在去重秒數內只留第一筆（見
        # trail.collapse_group 的說明，包含為什麼不能只用 LIKE 前綴比對）。
        group = trail.collapse_group(method, path)
        if group:
            last = tc.execute(
                "SELECT at FROM user_request_log WHERE user_id=? AND method=? "
                "AND (path=? OR path LIKE ?) ORDER BY id DESC LIMIT 1",
                (user_id, method, group[0], group[0] + "/%")
            ).fetchone()
        else:
            last = tc.execute(
                "SELECT at FROM user_request_log WHERE user_id=? AND method=? AND path=? "
                "ORDER BY id DESC LIMIT 1", (user_id, method, path)
            ).fetchone()
        if last:
            try:
                if (now_dt - datetime.fromisoformat(last["at"])).total_seconds() < trail.DEDUPE_SECONDS:
                    tc.close()
                    return
            except Exception:
                pass
        tc.execute(
            "INSERT INTO user_request_log (user_id, at, method, path, page, status) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, now_iso, method, path, page, int(status or 0)),
        )
        tc.commit()
        tc.close()
    except Exception:
        pass


# ⚠️ 這支**寫在 auth_middleware 前面**是刻意的，不是排版隨意。
#
# Starlette 的 middleware：**後宣告的在外層、先跑**（本檔 `security_headers` 上方那句
# 「Registered last = outermost」講的就是這件事，已用最小 app 實測確認）。
# 所以要讓「先確認是誰，再確認這台機器有沒有買」成立，這支必須宣告在
# `auth_middleware` **之前**，它才會在 auth 之後才跑。
#
# 寫反了不會有任何錯誤訊息，只會變成：未登入的請求收到 402 而不是 401，
# 而且會對還沒通過身分驗證的人洩漏「這台機器沒有授權」。
@app.middleware("http")
async def license_gate_middleware(request: Request, call_next):
    """授權守門（細線 1 第 3 步）。**預設完全不介入。**

    `LICENSE_GATE_ENABLED` 是 False 時**連 `verify_license()` 都不呼叫** ——
    不要留「算了但不擋」的中間狀態，那會付出效能成本卻換不到任何好處。

    ⚠️ 透過 `license_core.` 讀那兩個名字（而不是 `from ... import` 進來），
    是為了讓它們在**呼叫時**才被讀到：測試要 monkeypatch 它們，import 進來的
    副本 monkeypatch 不掉。

    ⚠️ 這裡刻意**不包 try/except**。`verify_license()` 契約上任何情況都不丟例外，
    而且 C 有測試釘住這件事。萬一它真的丟了，讓它變成 500 是對的：
    500 會被報修，而「出錯就放行」是降級——降級不會有人報修。
    """
    if not license_core.LICENSE_GATE_ENABLED:
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    # 非 /api/ 一律放行：前端靜態檔要載得出來，否則客戶連「為什麼被擋」都看不到。
    if not path.startswith("/api/"):
        return await call_next(request)
    # 豁免清單 ∪ 既有公開端點——未授權時這些仍要通，否則客戶連自救都做不到。
    if path in license_core.LICENSE_EXEMPT_PATHS or path in _PUBLIC_API_PATHS:
        return await call_next(request)

    # ⚠️⚠️ 這一行**刻意沒有包 try/except**。不是漏寫的，不要順手補上去。
    #
    # `verify_license()` 契約上任何情況都不丟例外（C 有測試釘住 missing／malformed／
    # 截斷／亂碼各種路徑）。萬一它還是丟了，三條路只能選一條：
    #   包起來放行 → 授權形同虛設，而且**不會有人發現**
    #   包起來擋住 → 付費客戶整套系統癱瘓
    #   不包       → 那一支 API 回 500
    # 選最後一條：500 會被報修，「出錯就放行」是降級，而**降級不會有人報修**。
    # 授權模組壞掉本來就該是全站停下來的等級。（A 於 2026-09-21 覆核通過）
    status = license_core.verify_license()
    if license_core.license_blocks_request(status):
        # 402 Payment Required，不是 403。
        # 403＝「你這個人沒權限」，402＝「這台機器沒買」。客服現場要分得開。
        return JSONResponse(
            status_code=402,
            content={
                "detail": license_core.license_block_message(status),
                "reason": status["reason"],
                "code":   "license_required",
            },
        )
    return await call_next(request)


from helpers import company_setup as _company_setup                     # noqa: E402
_COMPANY_SETUP_ALLOWED_COMPILED = _company_setup.compile_allowed(_COMPANY_SETUP_ALLOWED)


@app.exception_handler(_company_setup.CompanySetupRequired)
async def _company_setup_required_handler(request: Request, exc):
    """輸出端第二道（COMPANY-SETUP-GATE §5）：與中介層同形的 428 JSON（`code` 在最外層，notif.js 以它判斷）。"""
    body = {"detail": exc.detail, "code": exc.code, "canFix": False,
            "settingsUrl": _company_setup.SETTINGS_URL}
    if exc.missing:
        body["missing"] = exc.missing
    return JSONResponse(status_code=428, content=body)


def _company_setup_gate_kind(token: str) -> str:
    """這個請求看到的閘門狀態。demo 帳號與正式帳號同一套判定（demo 登入時種虛構示範公司＋demo 專用確認紀錄，
    `gate` 依 db.is_demo_mode 取 demo 庫判定；〔~~第三段前 demo 先不擋~~ 段③ 拿掉豁免〕）。
    判定一律經 `_company_setup.gate`（呼叫時才取模組屬性：測試換得掉）；它不丟例外。"""
    conn = get_db()
    try:
        kind, _st = _company_setup.gate(conn)
        conn.commit()
        return kind
    except Exception:                                                  # noqa: BLE001
        logger.exception("company setup gate failed")
        return _company_setup.GATE_UNDETERMINED
    finally:
        conn.close()


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if not path.startswith("/api/") or path in _PUBLIC_API_PATHS:
        return await call_next(request)
    # uploads auth is handled by the route handler:
    #   ?pt=  → HMAC signed token (P2) —— 綁定單一路徑、1 小時
    #
    # 🔴 2026-09-22：`?token=` 那一條**拿掉了**（§8 FX21）。
    # 它把完整的 session token 放在 query string ⇒ 進 access log、
    # 進瀏覽器歷史、進 Referer，☠️ **而它不是短效的**。
    # ⚠️ 原本那行註解寫著它是「img src pattern」——
    # **那描述的是被 `?pt=` 取代掉的舊做法**，而留著它的話，
    # 🔑 下一個人會照著那句話把這條路加回來。
    if path.startswith("/api/uploads/") and request.query_params.get("pt"):
        return await call_next(request)
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "未登入"})
    token = auth_header[7:]
    # Demo showcase account: session only exists in the isolated demo DB, so
    # flip routing BEFORE the session lookup below (and before any downstream
    # get_db() calls in the route handler / _require_user() / _audit()).
    set_demo_mode(token.startswith(DEMO_TOKEN_PREFIX))
    now_dt  = datetime.now()
    now_iso = now_dt.isoformat()
    conn    = get_db()
    try:
        row = conn.execute(
            "SELECT u.id, u.role, COALESCE(u.must_change_password, 0) AS must_change_password, "
            "s.last_active "
            "FROM sessions s JOIN users u ON s.user_id=u.id "
            "WHERE s.token=? AND u.active=1 "
            "AND (s.expires_at IS NULL OR s.expires_at > ?)",
            (token, now_iso),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return JSONResponse(status_code=401, content={"detail": "Session 已過期，請重新登入"})

    is_high_priv = row["role"] in ("superadmin", "admin")
    idle_limit = _ADMIN_IDLE_TIMEOUT_SECONDS if is_high_priv else _IDLE_TIMEOUT_SECONDS

    # Idle timeout check (only if last_active is already set)
    la_str = row["last_active"]
    if la_str:
        idle_secs = (now_dt - datetime.fromisoformat(la_str)).total_seconds()
        if idle_secs > idle_limit:
            # Expire this session
            try:
                ec = get_db()
                ec.execute("DELETE FROM sessions WHERE token=?", (token,))
                ec.commit()
                ec.close()
            except Exception:
                pass
            limit_label = "2 小時" if is_high_priv else "8 小時"
            return JSONResponse(status_code=401, content={"detail": f"閒置超過 {limit_label}，請重新登入"})
        if idle_secs > 300:
            try:
                uc = get_db()
                uc.execute("UPDATE sessions SET last_active=? WHERE token=?", (now_iso, token))
                uc.commit()
                uc.close()
            except Exception:
                pass
            # 在線時間統計（2026-09-14）：沿用同一個節流點，不額外增加寫入頻率——
            # 每 5 分鐘一列 UPDATE，跟原本就在做的 last_active 同一個數量級。
            _record_user_activity(row["id"], now_dt, idle_secs)
    else:
        # First request after migration — stamp last_active without any check
        try:
            uc = get_db()
            uc.execute("UPDATE sessions SET last_active=? WHERE token=?", (now_iso, token))
            uc.commit()
            uc.close()
        except Exception:
            pass

    if row["must_change_password"] and path not in _MUST_CHANGE_PW_ALLOWED:
        return JSONResponse(
            status_code=403,
            content={
                "detail": "必須先修改密碼才能繼續使用系統",
                "code": "must_change_password",
            },
        )
    # AB-S7（使用者裁示）：只有 demo 庫的 migration 沒完成的模組，demo 模式明說缺席（正式使用者照常）
    if token.startswith(DEMO_TOKEN_PREFIX):
        _demo_why = _module_startup.demo_absent_reason(path)
        if _demo_why:
            return JSONResponse(status_code=404, content={"detail": _demo_why})
    # 本公司資料設定閘門（COMPANY-SETUP-GATE §4.1、§3.6）：未設定 ⇒ 白名單外一律 428；判定失敗 ⇒ 放行＋標頭（Q7＝C）
    _gate_kind = _company_setup_gate_kind(token)
    if _gate_kind == _company_setup.GATE_REQUIRED and not _company_setup.is_allowed(
            _COMPANY_SETUP_ALLOWED_COMPILED, request.method, path):
        return JSONResponse(status_code=428, content={
            "detail": _company_setup.MSG_REQUIRED, "code": _company_setup.CODE_REQUIRED,
            "canFix": row["role"] == "superadmin", "settingsUrl": _company_setup.SETTINGS_URL})
    response = await call_next(request)
    # 操作軌跡（2026-09-14）：記在**回應之後**才拿得到狀態碼——被擋下來的操作
    # （403/404）跟成功的一樣重要，甚至更重要。
    _record_request_trail(row["id"], now_dt, request.method, path,
                          request.headers.get("Referer", ""), response.status_code)
    if _gate_kind in (_company_setup.GATE_UNDETERMINED, _company_setup.GATE_GRACE):
        response.headers[_company_setup.HEADER] = (
            "status_error" if _gate_kind == _company_setup.GATE_UNDETERMINED else "grace")
    return response


# Registered last = outermost: applies security headers to all responses (incl. 401/403)
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    # 🔴 `https://*.tile.openstreetmap.org` 是給地圖底圖的。
    # ⚠️ **萬用字元只到子網域，不可以寫成 `*`**：Leaflet 的 `{s}` 會輪替 a/b/c，
    # 所以需要子網域萬用，**但那跟「允許任何來源的圖片」差了一整個等級**。
    # 📌 這一行原本沒有它 ⇒ 地圖按下去是一片灰，
    # **而我寫的錯誤提示會說「這台機器可能沒有對外連線」——那個診斷是錯的。**
    # 🔑 一個會講錯原因的錯誤訊息比沒有訊息更難查：它會讓人去查網路，而網路是對的。
    # 📌 收窄成**單一主機名**。原本是 `https://*.tile.openstreetmap.org`，
    # 因為 Leaflet 的 `{s}` 會輪替 a/b/c —— 而 OSM 條款說那是**舊形式**、
    # 其他子網域「可能更慢或隨時撤除」。改用 `tile.openstreetmap.org` 之後，
    # **這一條也跟著變緊，不是變鬆。**
    "img-src 'self' data: blob: https://tile.openstreetmap.org; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-src 'self' blob:; "
    "object-src 'none'; "
    "frame-ancestors 'self'"
)


#: 🔴 地圖頁的 CSP（第十五班 ②(b)：有地圖金鑰時載 Maps JavaScript API）。
#: 來源：Google「Content Security Policy Guide」（developers.google.com/maps/documentation/javascript/
#: content-security-policy，2026-09-28 逐字查，Last updated 2026-09-24）的 **Allowlist CSP** 範例：
#:   script-src 'self' 'unsafe-inline' 'unsafe-eval' https://*.googleapis.com https://*.gstatic.com *.google.com
#:              https://*.ggpht.com *.googleusercontent.com blob:;
#:   img-src 'self' https://*.googleapis.com https://*.gstatic.com *.google.com *.googleusercontent.com data:;
#:   frame-src *.google.com;  connect-src 'self' https://*.googleapis.com *.google.com https://*.gstatic.com data: blob:;
#:   font-src https://fonts.gstatic.com;  style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;  worker-src blob:;
#: ⚠️ **只給這一頁**（同 Referrer-Policy 的做法）：整站放寬等於讓每一頁都能載 Google 網域的腳本。
#: 📌 我們現行的 script-src 已經有 'unsafe-inline'（Alpine），所以不走 nonce 的 strict CSP（那要全站改寫）。
_CSP_MAP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net "
    "https://*.googleapis.com https://*.gstatic.com *.google.com https://*.ggpht.com *.googleusercontent.com blob:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data: blob: https://tile.openstreetmap.org "
    "https://*.googleapis.com https://*.gstatic.com *.google.com *.googleusercontent.com; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "connect-src 'self' https://*.googleapis.com *.google.com https://*.gstatic.com data: blob:; "
    "frame-src 'self' blob: *.google.com; "
    "worker-src blob:; "
    "object-src 'none'; "
    "frame-ancestors 'self'"
)
_CSP_MAP_PATHS = frozenset({"/pages/map.html"})


#: 🔴 **只有這一頁放寬 `Referrer-Policy`。**
#:
#: OSM 的圖磚條款逐字要求兩件事，而我們**兩件都踩到了**：
#:   *You must not: Set a restrictive Referrer-Policy that prevents the
#:    HTTP Referer header being sent.*
#:   *From web pages, ensure a valid HTTP Referer header is sent.*
#: 而 `same-origin` 的意思正是「跨網域一律不送 Referer」
#: ⇒ 瀏覽器去要圖磚時湊成「瀏覽器 UA ＋ 沒有 Referer」⇒ **被回一張封鎖圖**。
#:
#: ⚠️ **實測矩陣**（同 IP、同時間）證明變因是 Referer 不是 UA：
#:     瀏覽器UA ＋ Referer   → 33,914 bytes ✅
#:     瀏覽器UA 無 Referer   →  6,987 bytes ❌ 封鎖圖
#:     MOTRIX UA 無 Referer  → 33,923 bytes ✅
#:
#: 🔴 **不可以整站放寬。** `same-origin` 是全站的隱私設定——
#: 使用者點一個外部連結時，不該把「他剛剛在看哪一頁」送給對方。
#: 🔴 **也不可以用 `unsafe-url`**：那會連**完整路徑**一起送出去
#: （`/pages/quotation-form.html?id=MQ-2026-001` 這種）。
#: ⇒ `strict-origin-when-cross-origin`：跨網域**只送來源**（`http://host:666/`），
#:   OSM 拿得到它要的 Referer，而我們不洩漏使用者正在看哪一頁。
_REFERER_RELAXED_PATHS = frozenset({"/pages/map.html"})
_REFERRER_POLICY_DEFAULT = "same-origin"
_REFERRER_POLICY_MAP = "strict-origin-when-cross-origin"


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    # ⚠️ 比對的是**路徑**，不是「有沒有 map 這個字」——
    # 子字串比對會讓 `/pages/sitemap.html` 之類的東西意外跟著放寬。
    referrer = (_REFERRER_POLICY_MAP
                if request.url.path in _REFERER_RELAXED_PATHS
                else _REFERRER_POLICY_DEFAULT)
    response.headers.setdefault("Referrer-Policy", referrer)
    response.headers.setdefault("X-XSS-Protection", "1; mode=block")
    response.headers.setdefault("Content-Security-Policy",
                                _CSP_MAP if request.url.path in _CSP_MAP_PATHS else _CSP)
    return response


# ── Exception handlers ────────────────────────────────────────────────────────
# HTTPException is handled by FastAPI's built-in handler (exact type match wins).
# RequestValidationError → 422 with a clean Chinese message (no field-level details exposed).
# Exception → 500 with full traceback in server log, generic message to client.

@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    logger.warning("Validation error %s %s: %s", request.method, request.url.path, exc.errors())
    return JSONResponse(status_code=422, content={"detail": "請求格式錯誤，請確認欄位是否完整"})


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception):
    # W-6（2026-09-24）：sqlite 例外多記擴充錯誤碼與「請求開始到出錯」的秒數。
    # 走查時 0.3 秒內 6 筆 database is locked，光看寫出時間分不出「立即失敗（BUSY_SNAPSHOT 等不經
    # busy handler 的路徑）」與「一起等滿 30 秒 busy_timeout 才逾時（有人握寫鎖 ≥30 秒）」。只加記錄、不改行為。
    t0 = getattr(request.state, "t0", None)
    elapsed = ("%.3fs" % (time.monotonic() - t0)) if t0 is not None else None
    logger.error(
        "Unhandled %s at %s %s sqlite_errorname=%s sqlite_errorcode=%s elapsed=%s",
        type(exc).__name__, request.method, request.url.path,
        getattr(exc, "sqlite_errorname", None), getattr(exc, "sqlite_errorcode", None), elapsed,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "伺服器發生內部錯誤，請聯絡管理員"},
    )
_startup_step("middleware_setup")


# ── Startup ───────────────────────────────────────────────────────────────────

# 🔴 主庫不存在 ⇒ 拒絕啟動，不要讓 sqlite 默默建一個空庫（core.paths.require_db；
# 全新安裝設 MOTRIX_CREATE_NEW_DB=1 啟動一次）。只守**預設位置**：測試與工具
# 明確改指 db.DB_PATH 時，那個位置由改指的人負責。
import db as _db_for_guard
if _db_for_guard.DB_PATH == _paths.DB_PATH:
    _paths.require_db(_db_for_guard.DB_PATH)
_startup_step("require_db")
init_db()
_startup_step("init_db_main")
init_db(DEMO_DB_PATH)
_startup_step("init_db_demo")
# 模組 migration 沒完成（回原因）的模組：改記 failed、路由不掛（稽核 A AB-S3；要在 mount_modules 之前）
_module_startup.fail_incomplete_modules(_db_for_guard.DB_PATH, DEMO_DB_PATH)   # 主庫決定上下線（AB-S7）
_startup_step("fail_incomplete_modules")
# S-CD02：部分損毀的主庫照常啟動（init_db 不會發現）⇒ 啟動時做一次 quick_check，
# 不通過 ⇒ ERROR 告警（寄信、BACKUP_ALERT、audit；升級預檢會因告警而擋）。不擋啟動：營運不中斷。
def _startup_integrity_check():
    import db as _dbq
    res = _dbq.quick_check(_dbq.DB_PATH)
    if res != "ok":
        logger.error("主庫 quick_check 不通過：%s", res)
        try:
            import archive as _arch
            _arch._write_backup_alert("主庫完整性檢查（quick_check）不通過：%s —— 資料庫檔可能損毀，"
                                      "每日快照會拒收直到修復；請從最後一份通過檢查的快照還原" % res[:200],
                                      level="ERROR")
        except Exception:                                    # noqa: BLE001
            logger.exception("主庫損毀告警本身失敗")
    return res


_startup_integrity_check()
_startup_step("integrity_check")


def _startup_company_setup():
    """本公司資料設定閘門（COMPANY-SETUP-GATE §3.4、§6.1）：安裝識別檔不在就建（庫裡已有確認紀錄 ⇒ ERROR＋告警）；
    既有安裝升級時補一次確認紀錄（每庫一次）。兩支都不丟例外；這裡再包一層：閘門的問題不可以讓服務起不來。"""
    from helpers import company_setup as _cs
    conn = get_db()
    try:
        _cs.startup_install_check(conn)
        _cs.backfill_once(conn)
        conn.commit()
    except Exception:                                        # noqa: BLE001
        logger.exception("本公司資料設定閘門啟動檢查失敗（服務照常啟動）")
    finally:
        conn.close()


_startup_company_setup()
_startup_step("company_setup")
init_default_admin()
_startup_step("init_default_admin")
init_demo_account()
_startup_step("init_demo_account")
flag_weak_passwords()
_startup_step("flag_weak_passwords")
init_unlock_passwords()
_startup_step("init_unlock_passwords")
_cleanup_sessions()
_startup_step("cleanup_sessions")

# ── 背景排程（2026-09-14 起可停用）────────────────────────────────────────────
#
# `MOTRIX_DISABLE_SCHEDULERS=1` 時整批略過。**只給測試用**，正式機與開發機
# 手動啟動都不會設這個變數，行為與改動前逐字相同。
#
# 為什麼需要：`import main` 是 module-level 執行（不是 @app.on_event），所以
# **每一個 pytest-xdist worker 都會在 import 當下立刻跑一次完整備份**——
# `_schedule_daily()` 第一件事就是 `_daily_backup()`：SQLite 整庫快照 ＋ 41 張表
# JSON 匯出 ＋ 月備份 ＋ uploads/PDF 鏡像 ＋ 過期清理，而 `_schedule_weekly()`
# 再來一次週備份，`schedule_overdue_check()` 另起執行緒補跑九種檢查。
# `-n auto` 在 12 執行緒機器上開 12 個 worker，等於**同一次測試跑了 12 遍完整
# 備份**，純粹是浪費。
#
# 而且這不只是慢：QUICK.md 記過「e2e 全套跟單檔結果不同」的根因正是
# 「整個 pytest session 期間有背景排程在寫 db，SQLite 寫鎖被佔住時
# `connect(timeout=30)` 最多會等 30 秒」——停掉排程就一併拆掉那個放大因子。
#
# 直接呼叫這些函式的測試不受影響（它們 import 之後自己叫），停的只有
# 「啟動時自動跑一次」。
if os.getenv("MOTRIX_DISABLE_SCHEDULERS") != "1":
    # BK20：`_ensure_archive_dirs()` 原本在模組層 ⇒ import 當下就在真實
    # 磁碟上建目錄，比 conftest 的隔離還早。完整理由寫在該函式的 docstring。
    # B54-S2（2026-09-28 A）：它與每日／週備份的第一輪都改在背景 Timer 跑（archive._schedule_daily），
    # 這兩行立即返回 ⇒ 雲端存檔路徑慢或卡住時 import main 不被拖住（套用後健康檢查有時限）。
    _schedule_daily()
    _schedule_weekly()
    # 2026-09-26：每日 08:00 檢查改由 L1 執行器跑（模組以 daily.check 登記；系統健康檢查不依賴任何 L2 模組）
    from helpers import daily_checks as _daily_checks
    _daily_checks.schedule_daily_checks()
    # 營運報表月報信：M08 搬遷後由 modules/analytics 的 ModuleSpec.schedulers 在 mount_modules() 之後啟動
    # L2 模組的排程在下面「模組路由」那一段、mount_modules() 之後才啟動（STATES-PLATFORM P-LD-07：
    # 路由衝突而不掛的模組，排程不可以已經在跑）。
    # 背景把地址查成座標（2026-09-22 §3v）。使用者裁示「不要他按按鈕」。
    # ⚠️ 受 GEO_ENABLED 管：關著時一次都不發（不是「發了失敗」）。
    # 🔴 它有每日上限與連續失敗停止 —— 一個會自己跑的迴圈，
    # 失控的樣子就是**被對方封 IP**，而那時的畫面是「地圖上沒有點，
    # 而 geoEnabled 仍然是 true」，看起來像使用者地址填錯。
    # 📌 待辦清單由 `routers/map_points.py` 註冊（`geo` 不認識業務表），
    # 所以這一行必須在那個模組**匯入之後**才有東西可做。
    # ✅ 實測過（不是從行號推的）：`from routers import …, map_points` 在第 28 行、
    #    這一行在第 553 行，而 `import main` 之後
    #    `geo._WARM_SOURCES == ['_map_geocode_backlog']`。
    # ⚠️ 註冊發生在**匯入**時，不是 `include_router` 時 ——
    #    我原本寫「第一趟會空跑」，那是**從位置推的，而且是錯的**。
    geo_core.schedule_geocode_warm()
else:
    logger.info("MOTRIX_DISABLE_SCHEDULERS=1 —— 已略過所有背景排程（測試模式）")
_startup_step("schedulers")

# ── 標案雷達：只記「開著」那一側 ──────────────────────────────────────────────
#
# 🔴 **刻意只記開著、不記關著。** 兩種錯的可見度差很多：
#   忘了設 ⇒ 按了掃描什麼都沒發生（吵，使用者自己會發現）
#   不小心設了而沒人知道 ⇒ **一台被認為不會對外連線的機器，每天在連政府網站**
#     （安靜：沒有畫面、沒有錯誤、沒有人報修）
# ⇒ 記錄要記在**安靜**的那一側。
# 🔑 而且反過來也是必要的：若兩邊都印，**每一台機器都有那一行，就標不出哪一台是測試機**
#     ——一個永遠出現的訊號不是訊號。
#
# ⚠️ **這一行不可以搬進上面那個排程閘門裡。**
# 「這台機器會不會對外連線」與排程開不開**無關**：排程關著時，使用者按「立即掃描」
# 照樣會連出去。放進閘門裡的話，「排程關、雷達開」的機器就不印了——
# **而那正是測試機的組態，最需要被標記的那一台剛好不會被標記。**
# （模組的啟動提示在下面 mount_modules() 之後才印：被判路由衝突的模組不算開著。）
# ⚠️ **地理查詢也要有啟動痕跡**（2026-09-22 §8 FX1a）。
# 它先前完全沒有 ⇒ 一台「以為開了而其實沒開」的機器，
# 症狀是「地圖上沒有點」—— ☠️ 而那與「地址查不到」「還沒暖快取」
# 「權限不足」長得一模一樣，**今晚已經有五個成因長成那個樣子**。
#
# 🔑 而這一行回答的是「**這個行程實際拿到什麼**」，不是「檔案裡寫了什麼」：
# `geo_core.geo_on()` 讀的是 `os.environ`。
# 📌 為什麼重要：兩個 `set` 在 `autostart.bat` 的 `:loop` **之前**
# ⇒ **部署之後不重跑排程工作的話，跑的還是舊環境變數的那個行程**，
# 而部署紀錄裡「重跑排程」這一步出現次數是 **0**。
if geo_core.geo_on():
    logger.info("MOTRIX_GEO=1 —— 地址定位已開，"
                "這台機器會對外連線（OpenStreetMap／Nominatim）")
_startup_step("geo_notice")

_prune_login_locks()
_startup_step("prune_login_locks")
auth.init_rate_limiting()
_startup_step("init_rate_limiting")
_sync_module_versions()
_startup_step("sync_module_versions")


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(customers.router)
app.include_router(parts.router)
app.include_router(company_lookup.router)
app.include_router(system.router)
app.include_router(module_versions.router)
app.include_router(search.router)
app.include_router(org_structure.router)
app.include_router(list_prefs.router)
app.include_router(uploads.router)
app.include_router(definitions.router)
app.include_router(custom_records.router)
app.include_router(approval_delegates.router)
app.include_router(approval_queue.router)     # 待我簽核佇列（L1，2026-09-27 自 M01 搬入）
app.include_router(licensing.router)
# 地圖是**共用能力**，不是標案雷達的一部分（2026-09-21 使用者裁示）。
app.include_router(map_points.router)
app.include_router(item_reads.router)
app.include_router(modules.router)
app.include_router(legal_params.router)
app.include_router(mail_settings.router)
app.include_router(platform_menu.router)
app.include_router(platform_catalog.router)
_startup_step("include_routers")

# ── L2 模組：路由、排程、啟動提示（STATES-PLATFORM P-LD-07）──────────────────────
# 🔴 必須在**所有** L1 include_router 之後、StaticFiles 之前：同方法同路徑的兩條路由都會掛上、
#    先掛的默默勝出 ⇒ 模組先掛就能蓋掉 L1。mount_modules() 比對已掛的路由，撞到的模組整個不掛、
#    記 failed＋原因。排程與啟動提示只取「掛上之後」仍在 registry.loaded() 裡的模組。
# 頁面衝突比照路由衝突（階段 C／C1）：**在 mount_modules 之前**檢查，衝突的模組改記 failed ⇒ 路由、排程都不掛。
_PAGE_MAP = module_pages.check_and_register(module_loader.MODULES_DIR, _paths.FRONTEND_PAGES_DIR)
platform_menu.set_page_map(_PAGE_MAP)          # /api/platform/menu 的完整 pageModules（登入後；C4-O3）
_startup_step("page_map")
module_loader.mount_modules(app)
_startup_step("mount_modules")
if os.getenv("MOTRIX_DISABLE_SCHEDULERS") != "1":
    # 例：標案雷達；關著時 run_scan() 立刻返回、不對外連線。只跑 registry.loaded() 的
    # （停用／未授權不 import、路由衝突已 unload ⇒ 不跑）；子行程守門呼叫同一個函式驗證。
    module_loader.start_schedulers()
_startup_step("module_schedulers")
# B55（稽核 D DB-S4）：這次啟動的模組載入結果 ⇒ logs/module_states.json（單模組更新的健檢讀它）。
# 〔稽核 D DB5-S1：**不綁排程閘門**——以 MOTRIX_DISABLE_SCHEDULERS=1 啟動的安裝（例：演練）也要寫，否則健檢會把
#   「沒有狀態檔」誤判成「模組沒載入」（同第十六班事故：演練與正式機條件不同）。只在 pytest 之下不寫（不寫進 repo 的 logs/）；
#   檔內另記 schedulers_disabled，讓健檢說得出原因〕
if "pytest" not in __import__("sys").modules:
    module_loader._write_module_states(os.path.join(_paths.LOGS_DIR, "module_states.json"))
_startup_step("module_states_file")
# ⚠️ 啟動提示**不可以**放進排程閘門：「這台機器會不會對外連線」與排程開不開無關（理由見上面「標案雷達：
#    只記開著那一側」）。
for _m in module_registry.loaded():
    for _notice in _m.spec.startup_notices:
        _msg = _notice()
        if _msg:
            logger.info(_msg)
_startup_step("startup_notices")


# ── 頁面（階段 C／C1，core.pages）──────────────────────────────────────────────
# 🔴 必須在 StaticFiles 之前（mount "/" 會接走所有路徑）。每個請求現查模組狀態（管理頁、測試都會改）。
# 模組沒有載入 ⇒ HTTP 404＋伺服器產生的提示頁（裁示 D2 選項 A，與 P-FE-03 並存）；不屬於任何模組 ⇒ L1 頁面目錄（_paths.FRONTEND_PAGES_DIR）。

def _module_state(key):
    return next((s for s in module_registry.module_states() if s["key"] == key), None)


@app.api_route("/pages/{name:path}", methods=["GET", "HEAD"], include_in_schema=False)
def module_page(name: str):
    r = module_pages.page_response(name, _PAGE_MAP, _paths.FRONTEND_PAGES_DIR,
                                   module_registry.is_loaded, _module_state)
    if r is None:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if r[0] == "file":
        return FileResponse(r[1])
    return HTMLResponse(r[1], status_code=404)


# ── 地圖覆蓋層腳本（IP-101 `map.overlay`；helpers.map_overlays）───────────────────────
# 🔴 必須在 StaticFiles 之前（同 /pages）。`<script src>` 帶不了 Authorization ⇒ 不在 /api 底下（腳本是程式碼，不含資料；
# 資料一律經模組自己的 /api 端點、各自檢查權限）。只提供「已載入模組宣告、檔案在該模組 pages/ 底下」的腳本，其餘 404。
@app.api_route("/map-overlays/{module_key}/{script}", methods=["GET", "HEAD"], include_in_schema=False)
def map_overlay_script(module_key: str, script: str):
    from helpers import map_overlays as _map_overlays
    path = _map_overlays.script_path(module_key, script)
    if path is None:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return FileResponse(path, media_type="application/javascript; charset=utf-8")


# ── 選單宣告（階段 C／C4）：/static/sidebar.js 前置 window.MOTRIX_MENU ────────────────
# 🔴 必須在 StaticFiles 之前（同 /pages）。與使用者無關（這個請求沒有 token）；內容見 routers/platform_menu.sidebar_js_source。
@app.api_route("/static/sidebar.js", methods=["GET", "HEAD"], include_in_schema=False)
def sidebar_js():
    return Response(platform_menu.sidebar_js_source(_PAGE_MAP, FRONTEND_DIR), media_type="application/javascript; charset=utf-8")


# ── Static frontend ───────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
_startup_step("page_and_static_routes")
_startup_total()
