# -*- coding: utf-8 -*-
"""權限矩陣 API：唯讀狀態探針＋（PM-S2）唯讀檢視端點＋（PM-S3）寫入端點。除探針外全部限最高管理者（SPEC PMX14／PMX16／PMX17、設計稿 §4）。

寫入端點只做「驗證輸入 → 呼叫服務層 → 轉錯誤」：高風險放寬走設定帳本待生效（確認期間＋第二位最高管理者核准）、原因必填、稽核與資料同交易，全部在服務層（`service.py`）。
服務層錯誤 `PermError` 一律轉成帶中文訊息的 HTTP 錯誤。
"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, StrictBool, StrictInt

from db import get_db
from helpers import _require_user
from modules.permmatrix import service as S
from modules.permmatrix import views as V

router = APIRouter()


def _su(authorization):
    return _require_user(authorization, require_superadmin=True)


def _run(fn):
    """開連線跑 fn(conn)（服務層的寫入函式自己 begin_write／commit）；PermError ⇒ HTTPException（訊息為中文，不含內部細節）。"""
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


# ── PM-S3 寫入端點 ─────────────────────────────────────────────────────────────────
class RoleCapIn(BaseModel):
    role: str
    cap: str
    granted: StrictBool
    reason: str = ""


class UserOverrideIn(BaseModel):
    user_id: StrictInt
    cap: str
    effect: str
    reason: str = ""


class ReasonIn(BaseModel):
    reason: str = ""


@router.post("/api/permmatrix/role-cap/preview")
def permmatrix_role_cap_preview(body: RoleCapIn, authorization: str = Header(None)):
    _su(authorization)
    return _run(lambda c: S.preview_role_cap(c, body.role, body.cap, body.granted))


@router.post("/api/permmatrix/role-cap")
def permmatrix_role_cap(body: RoleCapIn, authorization: str = Header(None)):
    actor = _su(authorization)
    return _run(lambda c: S.set_role_cap(c, actor, body.role, body.cap, body.granted, body.reason))


@router.post("/api/permmatrix/user-override/preview")
def permmatrix_user_override_preview(body: UserOverrideIn, authorization: str = Header(None)):
    _su(authorization)
    return _run(lambda c: S.preview_user_override(c, body.user_id, body.cap, body.effect))


@router.post("/api/permmatrix/user-override")
def permmatrix_user_override(body: UserOverrideIn, authorization: str = Header(None)):
    actor = _su(authorization)
    return _run(lambda c: S.set_user_override(c, actor, body.user_id, body.cap, body.effect, body.reason))


@router.delete("/api/permmatrix/user-override")
def permmatrix_user_override_clear(user_id: int, cap: str, reason: str = "", authorization: str = Header(None)):
    actor = _su(authorization)
    return _run(lambda c: S.clear_user_override(c, actor, user_id, cap, reason))


@router.post("/api/permmatrix/pending/{pid}/cancel")
def permmatrix_pending_cancel(pid: int, body: ReasonIn, authorization: str = Header(None)):
    actor = _su(authorization)
    return _run(lambda c: S.cancel_pending(c, actor, pid, body.reason))


@router.post("/api/permmatrix/pending/{pid}/approve")
def permmatrix_pending_approve(pid: int, body: ReasonIn, authorization: str = Header(None)):
    actor = _su(authorization)
    return _run(lambda c: S.approve_pending(c, actor, pid, body.reason))


@router.post("/api/permmatrix/versions/{version_id}/restore")
def permmatrix_version_restore(version_id: int, body: ReasonIn, authorization: str = Header(None)):
    actor = _su(authorization)
    return _run(lambda c: S.restore_version(c, actor, version_id, body.reason))


@router.post("/api/permmatrix/undo")
def permmatrix_undo(authorization: str = Header(None)):
    actor = _su(authorization)
    return _run(lambda c: S.undo_last_change(c, actor))
