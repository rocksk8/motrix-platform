"""
MOTRIX ERP — FastAPI 後端
執行：uvicorn main:app --reload --port 666 --host 0.0.0.0
"""
import os
import logging
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from db import get_db, init_db
from helpers import (
    init_default_admin, _cleanup_sessions,
    init_unlock_passwords, flag_weak_passwords,
)
from archive import _ensure_archive_dirs, _schedule_weekly, _schedule_daily

from routers import auth, quotations, customers, suppliers, parts, projects, dashboard, system, reports, contractors, payslips

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = FastAPI(title="MOTRIX ERP API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:666",
        "http://127.0.0.1:666",
        "http://172.16.11.211:666",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

_PUBLIC_API_PATHS = {"/api/auth/login", "/api/auth/logout", "/api/ping"}
# Allowed while must_change_password=1 (everything else returns 403)
_MUST_CHANGE_PW_ALLOWED = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/me",
    "/api/auth/change-password",
    "/api/ping",
}


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    p = request.url.path
    if p.endswith((".html", ".css", ".js")) or p in ("/", ""):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in _PUBLIC_API_PATHS:
        return await call_next(request)
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "未登入"})
    token = auth_header[7:]
    conn  = get_db()
    try:
        now = datetime.now().isoformat()
        row = conn.execute(
            "SELECT u.id, COALESCE(u.must_change_password, 0) AS must_change_password "
            "FROM sessions s JOIN users u ON s.user_id=u.id "
            "WHERE s.token=? AND u.active=1 "
            "AND (s.expires_at IS NULL OR s.expires_at > ?)",
            (token, now),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return JSONResponse(status_code=401, content={"detail": "Session 已過期，請重新登入"})
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
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-XSS-Protection", "1; mode=block")
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
init_default_admin()
flag_weak_passwords()
init_unlock_passwords()
_cleanup_sessions()
_ensure_archive_dirs()
_schedule_daily()
_schedule_weekly()


# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(quotations.router)
app.include_router(customers.router)
app.include_router(suppliers.router)
app.include_router(parts.router)
app.include_router(projects.router)
app.include_router(dashboard.router)
app.include_router(system.router)
app.include_router(reports.router)
app.include_router(contractors.router)
app.include_router(payslips.router)


# ── Static frontend ───────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
