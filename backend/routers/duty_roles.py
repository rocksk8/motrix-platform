# -*- coding: utf-8 -*-
"""職責角色化 R1 的管理 API（**僅最高管理者**，使用者裁示 Q1 a）。邏輯在 `helpers/duty_roles.py`，本檔只做授權、轉換錯誤、寫 audit_log。

- `GET  /api/duty-roles`                 角色清單＋可授權的鍵（含高敏感標記）
- `POST /api/duty-roles`                 建立角色 {key, name, description, permissions[], reason}
- `PUT  /api/duty-roles/{id}`            改角色 {name?, description?, permissions?, active?, reason}（沒有刪除端點；要停用用 active=false）
- `GET  /api/duty-roles/users`           每位使用者的綁定／扣項／生效清單
- `POST /api/duty-roles/bindings`        綁角色 {userId, roleId, reason}
- `POST /api/duty-roles/bindings/remove` 解除綁定 {userId, roleId, reason}
- `POST /api/duty-roles/subtracts`       設個人扣項 {userId, key, reason}
- `POST /api/duty-roles/subtracts/remove` 解除扣項 {userId, key, reason}
- `POST /api/duty-roles/preview`        生效權限預覽（唯讀）{userId, modules[], roleIds[], subtracts[], role?}
- `GET  /api/duty-roles/changes`         權限變更紀錄（只讀；沒有任何更新／刪除端點）
原因：只有高敏感變更必填（≥4 字，見 helpers/duty_roles.py）。
"""
from fastapi import APIRouter, Body, Header, HTTPException, Request

from db import get_db
from helpers import _require_user
from helpers import duty_roles as dr

router = APIRouter()


def _ip(request: Request) -> str:
    try:
        return request.client.host if request and request.client else ""
    except Exception:                                   # noqa: BLE001
        return ""


def _run(fn):
    """fn(conn)：服務層的 DutyError ⇒ HTTPException（不用 ** 傳參數，守門禁止）。"""
    conn = get_db()
    try:
        return fn(conn)
    except dr.DutyError as e:
        conn.rollback()
        raise HTTPException(e.status, str(e))
    finally:
        conn.close()


def _int(v, label):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise HTTPException(400, "%s必須是整數" % label)


@router.get("/api/duty-roles")
def get_roles(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from helpers import module_registry as mr
    conn = get_db()
    try:
        roles = dr.list_roles(conn)
    finally:
        conn.close()
    keys = [{"key": k, "label": l, "group": g, "highSensitive": k in dr.HIGH_SENSITIVITY_KEYS, "financeKey": k in dr.FINANCE_KEYS}
            for k, l, g in tuple(mr.MODULES) + tuple(mr.dynamic_modules())]
    return {"roles": roles, "keys": keys, "highSensitiveKeys": list(dr.HIGH_SENSITIVITY_KEYS)}


@router.post("/api/duty-roles", status_code=201)
def create_role(request: Request, body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    rid = _run(lambda c: dr.create_role(c, actor, body.get("key"), body.get("name"), body.get("description"), body.get("permissions"),
                                        body.get("reason"), _ip(request)))
    return {"id": rid}


@router.put("/api/duty-roles/{role_id}")
def update_role(role_id: int, request: Request, body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    ver = _run(lambda c: dr.update_role(c, actor, role_id, name=body.get("name"), description=body.get("description"),
                                        permissions=body.get("permissions"), active=body.get("active"), reason=body.get("reason"), ip=_ip(request)))
    return {"ok": True, "version": ver}


@router.get("/api/duty-roles/users")
def get_users(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        out = []
        for u in conn.execute("SELECT id, username, display_name, role, modules, active FROM users ORDER BY id").fetchall():
            d = {"id": u["id"], "username": u["username"], "displayName": u["display_name"], "role": u["role"], "active": bool(u["active"])}
            d.update(dr.effective_preview(conn, dict(u)))
            out.append(d)
        return {"users": out}
    finally:
        conn.close()


@router.post("/api/duty-roles/preview")
def preview(body: dict = Body(...), authorization: str = Header(None)):
    """生效權限預覽（唯讀；`users.html` 編輯視窗用）：{userId, modules[], roleIds[], subtracts[], role?} ⇒ 伺服器算出的生效清單。不寫任何東西。"""
    _require_user(authorization, require_superadmin=True)
    uid = _int(body.get("userId"), "userId")
    return _run(lambda c: dr.preview_whatif(c, uid, body.get("modules") or [], body.get("roleIds") or [], body.get("subtracts") or [],
                                            role=body.get("role") or None))


def _body_ids(body):
    return _int(body.get("userId"), "userId")


@router.post("/api/duty-roles/bindings", status_code=201)
def bind(request: Request, body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    uid, rid = _body_ids(body), _int(body.get("roleId"), "roleId")
    _run(lambda c: dr.bind_role(c, actor, uid, rid, body.get("reason"), _ip(request)))
    return {"ok": True}


@router.post("/api/duty-roles/bindings/remove")
def unbind(request: Request, body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    uid, rid = _body_ids(body), _int(body.get("roleId"), "roleId")
    _run(lambda c: dr.unbind_role(c, actor, uid, rid, body.get("reason"), _ip(request)))
    return {"ok": True}


@router.post("/api/duty-roles/subtracts", status_code=201)
def subtract(request: Request, body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    uid, key = _body_ids(body), str(body.get("key") or "")
    _run(lambda c: dr.set_subtract(c, actor, uid, key, body.get("reason"), _ip(request)))
    return {"ok": True}


@router.post("/api/duty-roles/subtracts/remove")
def unsubtract(request: Request, body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    uid, key = _body_ids(body), str(body.get("key") or "")
    _run(lambda c: dr.unset_subtract(c, actor, uid, key, body.get("reason"), _ip(request)))
    return {"ok": True}


@router.get("/api/duty-roles/changes")
def get_changes(targetType: str = "", targetId: int = None, limit: int = 200, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        return {"items": dr.list_changes(conn, targetType, targetId, limit)}
    finally:
        conn.close()
