"""通用簽名 URL 上傳檔案服務（2026-08-26 從 routers/projects.py 拆出，專案管理
業務端點下線後獨立成一支router——這裡的端點是完全通用的檔案服務，被叫料附件/
報價回簽/出貨單回簽/開票申請憑據/工作日誌照片等各種單據共用，不隨專案管理模組
一起下線）。"""
import hashlib
import hmac
import os
import secrets
import time

from fastapi import APIRouter, HTTPException, Header, Query
from fastapi.responses import FileResponse

from db import get_db
from helpers import _require_user
from helpers import uploads as _uploads_helper

_PHOTO_TOKEN_TTL = 3600  # seconds
_PHOTO_SECRET_CACHE: bytes | None = None

from core import paths as _paths
UPLOADS_ROOT = _paths.UPLOADS_ROOT

router = APIRouter()


def _resolve_upload_path(rel_path: str) -> str | None:
    """Resolve rel_path against UPLOADS_ROOT and reject any path that escapes it
    (e.g. via '..' traversal). Returns the absolute path, or None if out of bounds."""
    full = os.path.realpath(os.path.join(UPLOADS_ROOT, rel_path.lstrip('/\\')))
    if os.path.commonpath([full, UPLOADS_ROOT]) != UPLOADS_ROOT:
        return None
    return full


def _get_photo_secret() -> bytes:
    """Return persistent HMAC key stored in system_settings; generate once if absent."""
    global _PHOTO_SECRET_CACHE
    if _PHOTO_SECRET_CACHE is not None:
        return _PHOTO_SECRET_CACHE
    from helpers import _get_setting, _set_setting
    stored = _get_setting("photo_secret")
    if not stored:
        stored = secrets.token_hex(32)
        _set_setting("photo_secret", stored)
    _PHOTO_SECRET_CACHE = bytes.fromhex(stored)
    return _PHOTO_SECRET_CACHE


def _make_photo_token(path: str, ttl: int = _PHOTO_TOKEN_TTL) -> str:
    expires = int(time.time()) + ttl
    msg = f"{path}:{expires}".encode()
    sig = hmac.new(_get_photo_secret(), msg, hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def _verify_photo_token(path: str, token: str) -> bool:
    try:
        expires_str, sig = token.split(".", 1)
        expires = int(expires_str)
    except (ValueError, AttributeError):
        return False
    if time.time() > expires:
        return False
    msg = f"{path}:{expires}".encode()
    expected = hmac.new(_get_photo_secret(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


#: 看不到與查無同一句（c-case404 慣例：不讓人用回應差別探知單據／檔案存不存在）
_NOT_FOUND = "檔案不存在"


def _canonical_or_403(raw: str) -> str:
    rel = _uploads_helper.canonical_upload_path(raw)
    if rel is None or _resolve_upload_path(rel) is None:
        raise HTTPException(403, "無效路徑")
    return rel


def _authorize_read(user: dict, rel: str, ctx_type: str = None, ctx_id: str = None) -> None:
    """放行條件（2026-09-30 安全修正 P0；原本只要求登入）：
    1. 路徑的擁有單據看得到（`helpers.uploads.upload_readable`：擁有模組經 `uploads.path_access` 用那張單據自己的規則）；或
    2. 帶了簽核佇列情境 (type, id)：詳情守門放行，而且詳情真的列出這個路徑（簽核人常常不是案件的人）。
    其餘 ⇒ 404（與查無同一句）。"""
    conn = get_db()
    try:
        if _uploads_helper.upload_readable(conn, rel, user):
            return
    finally:
        conn.close()
    if ctx_type and ctx_id:
        from routers import approval_queue as _aq
        conn = get_db()
        try:
            try:
                paths = _aq.detail_file_paths(conn, user, ctx_type, ctx_id)
            except HTTPException as e:
                if e.status_code not in (400, 404):
                    raise
                paths = set()
        finally:
            conn.close()
        if rel in paths:
            return
    raise HTTPException(404, _NOT_FOUND)


@router.get("/api/photo-token")
def get_photo_token(path: str = Query(...), type: str = Query(None), id: str = Query(None),
                    authorization: str = Header(None)):
    """換 `?pt=` 短效簽章（綁單一路徑、1 小時）。**只簽發給讀得到該檔擁有單據的人**（見 `_authorize_read`）；
    `type`／`id`＝簽核佇列詳情的情境（approval-queue 頁帶）。不合法路徑 403；看不到與查無同一個 404。"""
    user = _require_user(authorization)
    rel = _canonical_or_403(path)
    _authorize_read(user, rel, type, id)
    return {"token": _make_photo_token(rel), "ttl": _PHOTO_TOKEN_TTL}


@router.get("/api/uploads/{file_path:path}")
def serve_upload(
    file_path: str,
    authorization: str = Header(None),
    pt: str = Query(None),
):
    """檔案服務。**兩條路：`Authorization` 標頭，或 `?pt=` 簽章。**

    ## 🔴 2026-09-22 拿掉了第三條：`?token=`（§8 FX21）
    它把**完整的 session token** 放在 query string 裡
    ⇒ ☠️ 寫進 uvicorn 的 access log（`logs/server.log`，永久追加），
    也會進瀏覽器歷史、`Referer`、任何中間的代理。
    ⚠️ **而它不是短效的** —— 那是使用者當下的 session，撿到就等於登入。

    🔑 `?pt=` 正是為了**同一個問題**（`<img src>` 設不了 header）而做的，
    **而且做對了**：HMAC 簽章、1 小時、**綁定單一路徑**。
    ⇒ 撿到一個 `pt` 只能看那一張圖一小時；撿到一個 `token` 是整個帳號。

    📌 實查過再拿掉的：前端用 `?token=` 打 uploads **0 處**、用 `?pt=` **8 處**，
    `backend/tests/` 也沒有任何一支在用。**一條沒有人走、而仍然打開著的路。**
    """
    rel = _canonical_or_403(file_path)
    full = _resolve_upload_path(rel)
    if pt:
        # 簽章在簽發時已查過權限（`get_photo_token`）；簽章綁的是同一個正規路徑
        if not _verify_photo_token(rel, pt):
            raise HTTPException(403, "照片連結已過期或無效，請重新載入")
    else:
        # 🔴 2026-09-30 P0：標頭這條原本也只要求登入 ⇒ 與 photo-token 同一個洞，一起補
        _authorize_read(_require_user(authorization), rel)
    if not os.path.isfile(full):
        raise HTTPException(404, _NOT_FOUND)
    return FileResponse(full)
