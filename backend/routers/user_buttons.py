# -*- coding: utf-8 -*-
"""使用者自訂按鈕的端點（T61 S6；設計：docs/platform/plans/T61-S6-ACTION-CATALOG-DESIGN.md）。旗標 `builder_actions.enabled` 關閉 ⇒ 全部不給。

- `GET  /api/user-buttons/{module}/{page}`          登入者：這一頁、這位使用者看得到的按鈕（已發布定義，逐顆用檢視者的權限過濾）。
                                                      旗標關閉 ⇒ `{enabled:false, buttons:[]}`；不是登記的頁面 ⇒ 404。
- `GET  /api/user-buttons/catalog`                  僅最高管理者：可導向的頁面、可執行的匯出、插槽（編輯器的下拉）。旗標關閉 ⇒ 404。
- `POST /api/user-buttons/{module}/{page}/preview`  僅最高管理者、唯讀：`{buttons, user?}` ⇒ 以指定使用者的真實權限預覽。旗標關閉 ⇒ 404。
定義的編輯、發布、還原走既有 `/api/definitions/user_buttons/module:<模組>/…`（僅最高管理者）。按鈕不授權：匯出端點與目標頁面自己驗證。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _require_user
from helpers import user_buttons as UB

router = APIRouter()


def _slot_page_or_404(module, page):
    if (module, page) not in UB.SLOTS:
        raise HTTPException(404, "這一頁沒有可放按鈕的位置")


@router.get("/api/user-buttons/catalog")
def get_catalog(authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    if not UB.enabled():
        raise HTTPException(404, "未開放")
    from helpers.auth import effective_modules
    return UB.catalog(effective_modules(u.get("role"), u.get("modules"), user_id=u.get("id")), True)


@router.get("/api/user-buttons/{module}/{page}")
def get_buttons(module: str, page: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _slot_page_or_404(module, page)
    if not UB.enabled():
        return {"enabled": False, "buttons": []}
    conn = get_db()
    try:
        return {"enabled": True, "buttons": UB.visible_buttons(conn, user, module, page)}
    finally:
        conn.close()


@router.post("/api/user-buttons/{module}/{page}/preview")
def preview_buttons(module: str, page: str, body: dict = Body(default={}), authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    _slot_page_or_404(module, page)
    if not UB.enabled():
        raise HTTPException(404, "未開放")
    conn = get_db()
    try:
        return UB.preview(conn, u, {"buttons": (body or {}).get("buttons", [])}, module, page, username=(body or {}).get("user"))
    except ValueError as e:
        raise HTTPException(422, {"problems": e.args[0]})
    except LookupError as e:
        raise HTTPException(404, str(e))
    finally:
        conn.close()
