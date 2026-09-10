"""
MOTRIX ERP — FastAPI 後端
執行：uvicorn main:app --reload --port 666 --host 0.0.0.0
"""
import os
import time
import logging
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from db import get_db, init_db, DEMO_DB_PATH, set_demo_mode
from helpers import (
    init_default_admin, init_demo_account, _cleanup_sessions,
    init_unlock_passwords, flag_weak_passwords,
    _sync_module_versions, DEMO_TOKEN_PREFIX,
)
from archive import _ensure_archive_dirs, _schedule_weekly, _schedule_daily

from routers import auth, quotations, customers, suppliers, parts, dashboard, system, reports, contractors, payslips, daily_tasks, module_versions, vendor_contractors, dev_crm, env_guide, netarch_guide, switch_guide, shipping_notes, inventory, search, monitor_guide, access_guide, gateway_guide, automation_guide, contractor_vouchers, invoice_vouchers, org_structure, payment_requests, list_prefs, case_action_items, uploads, network_plans, network_plans_quick, approval_delegates, cashier, accounting_export, material_orders

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = FastAPI(title="MOTRIX ERP API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:666",
        "http://127.0.0.1:666",
        "http://172.16.10.177:666",
        # 2026-08-27：正式機導入 HTTPS 後（見 backend/tools/https_setup.ps1），
        # 保留原本 http 三筆是因為開發機仍是明文運作，共用同一份 main.py
        "https://localhost:666",
        "https://127.0.0.1:666",
        "https://172.16.10.177:666",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

_PUBLIC_API_PATHS = {
    "/api/auth/login", "/api/auth/login/totp", "/api/auth/logout",
    "/api/ping", "/api/system/version",
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


@app.middleware("http")
async def slow_request_log(request: Request, call_next):
    _t0 = time.monotonic()
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
    if p.endswith((".html", ".css", ".js")) or p in ("/", ""):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if not path.startswith("/api/") or path in _PUBLIC_API_PATHS:
        return await call_next(request)
    # uploads auth is handled by the route handler:
    #   ?pt=  → HMAC signed token (P2)
    #   ?token= → session token forwarded as Bearer by route handler (img src pattern)
    if path.startswith("/api/uploads/") and (
        request.query_params.get("pt") or request.query_params.get("token")
    ):
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
    return await call_next(request)


# Registered last = outermost: applies security headers to all responses (incl. 401/403)
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-src 'self' blob:; "
    "object-src 'none'; "
    "frame-ancestors 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-XSS-Protection", "1; mode=block")
    response.headers.setdefault("Content-Security-Policy", _CSP)
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
    logger.error(
        "Unhandled %s at %s %s",
        type(exc).__name__, request.method, request.url.path,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "伺服器發生內部錯誤，請聯絡管理員"},
    )


# ── Startup ───────────────────────────────────────────────────────────────────

init_db()
init_db(DEMO_DB_PATH)
init_default_admin()
init_demo_account()
flag_weak_passwords()
init_unlock_passwords()
_cleanup_sessions()
_ensure_archive_dirs()
_schedule_daily()
_schedule_weekly()
auth.init_rate_limiting()
daily_tasks.schedule_overdue_check()
reports.schedule_monthly_report()
dev_crm.schedule_dev_case_stale_check()
_sync_module_versions()


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(quotations.router)
app.include_router(material_orders.router)
app.include_router(customers.router)
app.include_router(suppliers.router)
app.include_router(parts.router)
app.include_router(dashboard.router)
app.include_router(system.router)
app.include_router(reports.router)
app.include_router(contractors.router)
app.include_router(payslips.router)
app.include_router(daily_tasks.router)
app.include_router(module_versions.router)
app.include_router(vendor_contractors.router)
app.include_router(dev_crm.router, prefix="/api")
app.include_router(env_guide.router)
app.include_router(netarch_guide.router)
app.include_router(switch_guide.router)
app.include_router(monitor_guide.router)
app.include_router(access_guide.router)
app.include_router(gateway_guide.router)
app.include_router(automation_guide.router)
app.include_router(shipping_notes.router)
app.include_router(inventory.router)
app.include_router(search.router)
app.include_router(contractor_vouchers.router)
app.include_router(invoice_vouchers.router)
app.include_router(org_structure.router)
app.include_router(payment_requests.router)
app.include_router(list_prefs.router)
app.include_router(case_action_items.router)
app.include_router(uploads.router)
app.include_router(network_plans.router)
app.include_router(network_plans_quick.router)
app.include_router(approval_delegates.router)
app.include_router(cashier.router)
app.include_router(accounting_export.router)


# ── Static frontend ───────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
