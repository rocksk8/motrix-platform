# -*- coding: utf-8 -*-
"""清單檢視偏好的端點（T66 L2；設計：docs/platform/plans/T66-LIST-PREFS-DESIGN.md）。旗標 `list_prefs.enabled`（＋建構器治理）關閉 ⇒ 全部 404。

- `GET    /api/list-views`            登入者：自己的清單摘要（代號、名稱、是否有個人設定）。
- `GET    /api/list-views/{list_id}`  登入者：這份清單對自己的限制（可用欄位、金額欄標記、可排序欄位、預設排序）與每頁筆數（目前值、來源、可選項）＋ etag。
- `PUT    /api/list-views/{list_id}`  登入者：存自己的每頁筆數 `{pageSize}`；`If-Match` 帶 etag。不合法 422、etag 不符 409、公司不開放 403。
- `DELETE /api/list-views/{list_id}`  登入者：回到公司預設。
個人的欄位顯示／順序與排序仍走既有 `/api/list-prefs/{list_key}`（版面引擎）；本組端點不複製它，只提供限制規則。只讀寫呼叫者自己的資料（路徑沒有帳號參數）。
"""
from typing import Optional

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _audit, _require_user, _tok
from helpers import list_view_prefs as LV

router = APIRouter()


def _off():
    raise HTTPException(404, "未開放")


def _fail(e):
    raise HTTPException(e.status, {"message": str(e), "problems": e.problems} if e.problems else str(e))


@router.get("/api/list-views")
def list_views(authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        if not LV.enabled(conn):
            _off()
        return {"lists": LV.list_summaries(conn, user)}
    finally:
        conn.close()


@router.get("/api/list-views/{list_id}")
def get_list_view(list_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        if not LV.enabled(conn):
            _off()
        view = LV.constraints(conn, user, list_id)
        if view is None:
            raise HTTPException(404, "沒有這份清單")
        return view
    finally:
        conn.close()


@router.put("/api/list-views/{list_id}")
def put_list_view(list_id: str, body: dict = Body(default={}), if_match: Optional[str] = Header(None), authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        if not LV.enabled(conn):
            _off()
        try:
            view = LV.save_page_size(conn, user, list_id, body, if_match)
        except LV.ViewError as e:
            _fail(e)
        _audit(_tok(authorization), "list_views.save", "list_view", list_id, "調整清單每頁筆數", {"pageSize": view["pageSize"]["value"]})
        return view
    finally:
        conn.close()


@router.delete("/api/list-views/{list_id}")
def delete_list_view(list_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        if not LV.enabled(conn):
            _off()
        try:
            view = LV.reset(conn, user, list_id)
        except LV.ViewError as e:
            _fail(e)
        _audit(_tok(authorization), "list_views.reset", "list_view", list_id, "清單偏好回到公司預設", {})
        return view
    finally:
        conn.close()
