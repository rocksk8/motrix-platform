# -*- coding: utf-8 -*-
"""POST /api/platform/menu/preview（BP-1）：整份選單的發布前預覽。唯讀（不寫任何資料；POST 只為了帶草稿 ops）。

只有最高管理者；設定 `builder_menu.enabled` 關著 ⇒ 404（不洩漏功能存在）。邏輯見 helpers/menu_builder。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _require_user
from helpers import menu_builder as MB

router = APIRouter()


@router.post("/api/platform/menu/preview")
def menu_preview(payload: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        if not MB.enabled(conn):
            raise HTTPException(404, "Not Found")
        try:
            return MB.preview(conn, u, payload)
        except ValueError as e:
            raise HTTPException(422, {"problems": e.args[0]})
        except LookupError as e:
            raise HTTPException(404, str(e))
    finally:
        conn.close()
