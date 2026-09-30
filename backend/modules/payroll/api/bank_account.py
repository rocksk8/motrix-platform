# -*- coding: utf-8 -*-
"""員工收款帳號 API（payroll v3；規則與遮蔽見 `modules/payroll/bank_account.py`）。

- `GET／PUT /api/me/bank-account`：**本人**（端點不收 user_id ⇒ 沒有 IDOR）。
- `GET /api/bank-accounts`：有資格的人（超級管理員／財務／出納）看「誰登錄了帳號」清單（只有末四碼）。
- `GET /api/bank-accounts/{user_id}?reveal=1`：有資格的人看某人；預設遮蔽，`reveal=1` 才回完整並寫稽核。
- `PUT /api/bank-accounts/{user_id}`：超級管理員或財務改別人的。
- `GET /api/bank-accounts/{user_id}/history`：超級管理員／財務看變更歷史（只有末四碼）。
沒有資格 ⇒ 404（當作不存在，不洩漏「這個人有沒有帳號」）。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _audit, _require_user, _tok
from modules.payroll import bank_account as ba

router = APIRouter(tags=["bank-account"])


def _user_row(conn, user_id):
    r = conn.execute("SELECT id, username, display_name, active FROM users WHERE id=?", (user_id,)).fetchone()
    if r is None:
        raise HTTPException(404, "找不到這位使用者。")
    return r


def _body(body):
    try:
        return ba.validate(body or {})
    except ba.Invalid as e:
        raise HTTPException(400, str(e))


def _save(conn, target, fields, actor, authorization, *, by_admin):
    res = ba.save(conn, target["id"], target["username"], fields, actor["username"])
    if res["noop"]:
        return res
    conn.commit()
    _audit(_tok(authorization), "user.bank_account.update", "user", target["username"], target["display_name"] or target["username"],
           {"fields": res["changed"], "before_last4": res["before_last4"], "after_last4": res["after_last4"], "byAdmin": by_admin})
    return res


@router.get("/api/me/bank-account")
def get_my_account(authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        return {"account": ba.profile(conn, ba.get_active_by_username(conn, user["username"]), user, user["username"])}
    finally:
        conn.close()


@router.put("/api/me/bank-account")
def put_my_account(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    fields = _body(body)
    conn = get_db()
    try:
        target = _user_row(conn, user["id"])
        res = _save(conn, target, fields, user, authorization, by_admin=False)
        return {"ok": True, "changed": res["changed"], "account": ba.profile(conn, ba.get_active_by_username(conn, user["username"]), user, user["username"])}
    finally:
        conn.close()


@router.get("/api/bank-accounts")
def list_accounts(authorization: str = Header(None)):
    user = _require_user(authorization)
    if not ba.may_list_users(user):
        raise HTTPException(404, "Not Found")
    conn = get_db()
    try:
        rows = conn.execute("SELECT u.id, u.username, u.display_name, a.bank_name, a.account_number, a.updated_at FROM users u"
                            " LEFT JOIN user_bank_accounts a ON a.user_id=u.id AND a.active=1 WHERE u.active=1 ORDER BY u.display_name, u.username").fetchall()
        return {"users": [{"id": r["id"], "username": r["username"], "displayName": r["display_name"] or r["username"],
                           "hasAccount": bool(r["account_number"]), "bankName": r["bank_name"] or "", "last4": (r["account_number"] or "")[-4:],
                           "updatedAt": r["updated_at"] or ""} for r in rows],
                "canEdit": ba.may_edit_others(user)}
    finally:
        conn.close()


@router.get("/api/bank-accounts/{user_id}")
def get_account(user_id: int, reveal: int = 0, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        target = _user_row(conn, user_id)
        if not ba.may_see_full(user, target["username"]):          # 有資格＝本人、超管、財務、出納；其餘一律當不存在
            raise HTTPException(404, "Not Found")
        token = _tok(authorization)
        acc = ba.payee_bank_profile(conn, target["username"], user, reveal=bool(reveal), audit_token=token, purpose="profile")
        return {"user": {"id": target["id"], "username": target["username"], "displayName": target["display_name"] or target["username"]},
                "account": acc, "canEdit": ba.may_edit_others(user) or target["username"] == user["username"]}
    finally:
        conn.close()


@router.put("/api/bank-accounts/{user_id}")
def put_account(user_id: int, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        target = _user_row(conn, user_id)
        own = target["username"] == user["username"]
        if not own and not ba.may_edit_others(user):
            raise HTTPException(404, "Not Found")
        fields = _body(body)
        res = _save(conn, target, fields, user, authorization, by_admin=not own)
        return {"ok": True, "changed": res["changed"]}
    finally:
        conn.close()


@router.get("/api/bank-accounts/{user_id}/history")
def get_history(user_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    if not ba.may_edit_others(user):
        raise HTTPException(404, "Not Found")
    conn = get_db()
    try:
        _user_row(conn, user_id)
        return {"history": ba.history(conn, user_id)}
    finally:
        conn.close()
