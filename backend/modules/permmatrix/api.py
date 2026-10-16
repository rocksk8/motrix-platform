# -*- coding: utf-8 -*-
"""權限矩陣 API：唯讀狀態探針＋（PM-S2）唯讀檢視端點。全部端點限最高管理者（SPEC PMX14／設計稿 §4）。

寫入端點（PM-S3）另段；服務層錯誤 `PermError` 一律轉成帶中文訊息的 HTTP 錯誤。
"""
from fastapi import APIRouter, Header, HTTPException

from db import get_db
from helpers import _require_user
from modules.permmatrix import service as S
from modules.permmatrix import views as V

router = APIRouter()


def _su(authorization):
    return _require_user(authorization, require_superadmin=True)


def _run(fn):
    """開唯讀連線跑 fn(conn)；PermError ⇒ HTTPException（訊息為中文，不含內部細節）。"""
    conn = get_db()
    try:
        return fn(conn)
    except S.PermError as e:
        raise HTTPException(e.status, str(e))
    finally:
        conn.close()


@router.get("/api/permmatrix/status")
def permmatrix_status(authorization: str = Header(None)):
    """唯讀探針：回應固定為 `{"ok": true}`（probe 規則：回應值不得出現字串）。任何登入者可呼叫。"""
    _require_user(authorization)
    return {"ok": True}


@router.get("/api/permmatrix/matrix")
def permmatrix_matrix(authorization: str = Header(None)):
    _su(authorization)
    return _run(V.matrix_view)


@router.get("/api/permmatrix/users")
def permmatrix_users(authorization: str = Header(None)):
    _su(authorization)
    return _run(V.users_view)


@router.get("/api/permmatrix/users/{user_id}/effective")
def permmatrix_user_effective(user_id: int, authorization: str = Header(None)):
    _su(authorization)
    return _run(lambda c: V.user_effective(c, user_id))


@router.get("/api/permmatrix/pending")
def permmatrix_pending(authorization: str = Header(None)):
    _su(authorization)
    return _run(lambda c: {"items": S.list_pending(c)})


@router.get("/api/permmatrix/versions")
def permmatrix_versions(authorization: str = Header(None)):
    _su(authorization)
    return _run(lambda c: {"items": S.list_versions(c)})


@router.get("/api/permmatrix/delegations")
def permmatrix_delegations(authorization: str = Header(None)):
    _su(authorization)
    return _run(lambda c: {"items": S.list_delegations(c)})
