"""簽核代理人（2026-08-28，企業管理優化）：讓一位簽核人在請假等情境下，把自己在
tiers 裡的簽核權限暫時交給另一個人，取代原本「除了 superadmin 沒有人能代簽」的
唯一解法。實際生效邏輯集中在 helpers/tiered_approval.py::check_approve_permission()/
check_reject_permission()，這裡只是這張表的 CRUD，見該模組與 db.py
_m067_approval_delegates() 的完整設計說明。

權限模型：任何登入使用者都可以「把自己的簽核權限委託給別人」（delegatorUsername
預設就是自己，不能指定別人）；superadmin 額外可以代替任何人設定/停用（例如
本人突然請假忘記自己先設定），比照這個專案「附件上傳任何人皆可、關鍵狀態變更才
限管理員」的既有權限慣例。"""
import json
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Header

from db import get_db
from helpers import _require_user, _tok, _audit

router = APIRouter()


def _row_to_dict(r) -> dict:
    return {
        "id":                r["id"],
        "delegatorUsername": r["delegator_username"],
        "delegateUsername":  r["delegate_username"],
        "startDate":         r["start_date"],
        "endDate":           r["end_date"],
        "reason":            r["reason"] or "",
        "active":            bool(r["active"]),
        "createdBy":         r["created_by"] or "",
        "createdAt":         r["created_at"] or "",
        "updatedAt":         r["updated_at"] or "",
    }


@router.get("/api/approval-delegates")
def list_approval_delegates(authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        if user["role"] == "superadmin":
            rows = conn.execute(
                "SELECT * FROM approval_delegates ORDER BY active DESC, end_date DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM approval_delegates WHERE delegator_username=? OR delegate_username=? "
                "ORDER BY active DESC, end_date DESC",
                (user["username"], user["username"]),
            ).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


@router.post("/api/approval-delegates", status_code=201)
def create_approval_delegate(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    delegator_username = (body.get("delegatorUsername") or user["username"]).strip()
    delegate_username  = (body.get("delegateUsername") or "").strip()
    start_date = (body.get("startDate") or "").strip()
    end_date   = (body.get("endDate") or "").strip()
    reason     = (body.get("reason") or "").strip()

    if delegator_username != user["username"] and user["role"] != "superadmin":
        raise HTTPException(403, "僅能設定自己的簽核代理人，如需代替他人設定請聯絡最高管理員")
    if not delegate_username:
        raise HTTPException(400, "請指定代理人")
    if delegate_username == delegator_username:
        raise HTTPException(400, "代理人不能是委託人本人")
    if not start_date or not end_date:
        raise HTTPException(400, "請指定代理起訖日期")
    if end_date < start_date:
        raise HTTPException(400, "結束日期不得早於開始日期")

    conn = get_db()
    try:
        delegator_row = conn.execute(
            "SELECT id FROM users WHERE username=? AND active=1", (delegator_username,)
        ).fetchone()
        if not delegator_row:
            raise HTTPException(404, f"找不到委託人帳號「{delegator_username}」或帳號已停用")
        delegate_row = conn.execute(
            "SELECT id, display_name FROM users WHERE username=? AND active=1", (delegate_username,)
        ).fetchone()
        if not delegate_row:
            raise HTTPException(404, f"找不到代理人帳號「{delegate_username}」或帳號已停用")

        now = datetime.now().isoformat()
        conn.execute("""
            INSERT INTO approval_delegates
                (delegator_username, delegate_username, start_date, end_date, reason,
                 active, created_by, created_at, updated_at)
            VALUES (?,?,?,?,?,1,?,?,?)
        """, (delegator_username, delegate_username, start_date, end_date, reason,
              user["username"], now, now))
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    finally:
        conn.close()

    label = f"{delegator_username} → {delegate_username}（{start_date}~{end_date}）"
    _audit(_tok(authorization), "approval_delegate.create", "approval_delegate", str(new_id), label)
    return {"id": new_id, "ok": True}


@router.patch("/api/approval-delegates/{delegate_id}/deactivate")
def deactivate_approval_delegate(delegate_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM approval_delegates WHERE id=?", (delegate_id,)).fetchone()
        if not row:
            raise HTTPException(404, "找不到此代理設定")
        if row["delegator_username"] != user["username"] and user["role"] != "superadmin":
            raise HTTPException(403, "僅委託人本人或最高管理員可停用此代理設定")
        if not row["active"]:
            raise HTTPException(409, "此代理設定已是停用狀態")
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE approval_delegates SET active=0, updated_at=? WHERE id=?", (now, delegate_id)
        )
        conn.commit()
    finally:
        conn.close()

    label = f"{row['delegator_username']} → {row['delegate_username']}"
    _audit(_tok(authorization), "approval_delegate.deactivate", "approval_delegate", str(delegate_id), label)
    return {"ok": True}
