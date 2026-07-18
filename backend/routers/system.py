"""System: approval-flow settings, notifications, audit log, work logs."""
import json
import os
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header, Body
from pydantic import BaseModel

from db import get_db
from helpers import _require_user, _tok, _audit, _get_setting, _set_setting, _get_edge_path

router = APIRouter()


# ── Models ────────────────────────────────────────────────────────────────────

class ApprovalFlowApprover(BaseModel):
    userId:      int
    username:    str
    displayName: str

class ApprovalFlowTier(BaseModel):
    order:     int = 0
    approvers: List[ApprovalFlowApprover] = []

class ApprovalFlowSettings(BaseModel):
    tiers: List[ApprovalFlowTier] = []


def _normalize_flow(raw: dict) -> dict:
    """Convert old {steps:[]} format to new {tiers:[]} format."""
    if raw.get("tiers"):
        return raw
    old_steps = raw.get("steps") or []
    return {
        "tiers": [
            {"order": i, "approvers": [{"userId": s.get("userId", 0), "username": s["username"], "displayName": s.get("displayName", s["username"])}]}
            for i, s in enumerate(old_steps)
        ]
    }


# ── Approval flow settings ────────────────────────────────────────────────────

@router.get("/api/settings/approval-flow")
def get_approval_flow_settings(authorization: str = Header(None)):
    _require_user(authorization)
    raw = _get_setting("approval_flow", {"tiers": []}) or {}
    return _normalize_flow(raw)


@router.put("/api/settings/approval-flow")
def set_approval_flow_settings(body: ApprovalFlowSettings, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    total_approvers = sum(len(t.approvers) for t in body.tiers)
    value = {"tiers": [t.model_dump() for t in body.tiers]}
    _set_setting("approval_flow", value)
    _audit(_tok(authorization), "settings.approval_flow.update", "settings", "approval_flow",
           "簽核流程設定", {"tierCount": len(body.tiers), "approverCount": total_approvers})
    return {"ok": True}


# ── Notifications ─────────────────────────────────────────────────────────────

@router.get("/api/notifications/mine")
def get_my_notifications(authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, type, ref_id, ref_label, message, is_read, created_at "
        "FROM notifications WHERE username=? ORDER BY created_at DESC LIMIT 50",
        (user["username"],)
    ).fetchall()
    conn.close()
    items = [dict(r) for r in rows]
    unread = sum(1 for i in items if not i["is_read"])
    return {"items": items, "unread": unread}


@router.patch("/api/notifications/{notif_id}/read")
def mark_notification_read(notif_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    conn.execute(
        "UPDATE notifications SET is_read=1 WHERE id=? AND username=?",
        (notif_id, user["username"])
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.patch("/api/notifications/read-all")
def mark_all_notifications_read(authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    conn.execute(
        "UPDATE notifications SET is_read=1 WHERE username=?",
        (user["username"],)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/api/audit-log")
def list_audit_log(
    limit:  int = 100,
    offset: int = 0,
    action: str = None,
    q:      str = None,
    authorization: str = Header(None),
):
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "稽核記錄僅管理員以上可查閱")
    conn = get_db()
    where, params = [], []
    if action:
        where.append("action=?");   params.append(action)
    if q:
        like = f'%{q}%'
        where.append("(target_label LIKE ? OR username LIKE ? OR display_name LIKE ? OR target_id LIKE ?)")
        params.extend([like, like, like, like])
    cond = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM audit_log {cond}", params).fetchone()[0]
    rows  = conn.execute(
        f"SELECT * FROM audit_log {cond} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()
    conn.close()
    return {"total": total, "items": [dict(r) for r in rows]}


# ── Work Logs ─────────────────────────────────────────────────────────────────

@router.get("/api/work-logs")
def list_work_logs(
    date:    Optional[str] = None,
    month:   Optional[str] = None,
    user_id: Optional[int] = None,
    authorization: str = Header(None),
):
    _require_user(authorization)
    conn = get_db()
    sql = """
        SELECT w.id, w.log_date, w.user_id, w.content, w.hours, w.created_at,
               u.display_name, u.username
        FROM work_logs w
        LEFT JOIN users u ON u.id = w.user_id
        WHERE 1=1
    """
    params = []
    if date:
        sql += " AND w.log_date = ?"
        params.append(date)
    elif month:
        sql += " AND w.log_date LIKE ?"
        params.append(month + "-%")
    if user_id:
        sql += " AND w.user_id = ?"
        params.append(user_id)
    sql += " ORDER BY w.log_date DESC, w.id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/work-logs")
def create_work_log(body: dict = Body(...), authorization: str = Header(None)):
    u = _require_user(authorization)
    log_date = body.get("log_date", "")
    user_id  = body.get("user_id")
    content  = body.get("content", "").strip()
    hours    = float(body.get("hours", 8.0))
    if not log_date or not user_id or not content:
        raise HTTPException(400, "log_date / user_id / content 必填")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO work_logs (log_date, user_id, content, hours, created_at, created_by) VALUES (?,?,?,?,?,?)",
        (log_date, user_id, content, hours, now, u["id"])
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return {"id": new_id, "ok": True}


@router.put("/api/work-logs/{wid}")
def update_work_log(wid: int, body: dict = Body(...), authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM work_logs WHERE id=?", (wid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到日誌")
    if u["role"] not in ("superadmin", "admin") and u["id"] != row["user_id"]:
        conn.close()
        raise HTTPException(403, "只能修改自己的工作日誌")
    sets, params = [], []
    for field in ("log_date", "user_id", "content", "hours"):
        if field in body:
            sets.append(f"{field}=?")
            params.append(body[field])
    if not sets:
        conn.close()
        return {"ok": True}
    params.append(wid)
    conn.execute(f"UPDATE work_logs SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    conn.close()
    return {"ok": True}


@router.delete("/api/work-logs/{wid}")
def delete_work_log(wid: int, authorization: str = Header(None)):
    u = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT user_id FROM work_logs WHERE id=?", (wid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到日誌")
    if u["role"] not in ("superadmin", "admin") and u["id"] != row["user_id"]:
        conn.close()
        raise HTTPException(403, "只能刪除自己的工作日誌")
    conn.execute("DELETE FROM work_logs WHERE id=?", (wid,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Company profile（甲方設定，勞報單使用）────────────────────────────────────

class CompanyProfile(BaseModel):
    name:         str = ''
    tax_id:       str = ''
    contact_info: str = ''


@router.get("/api/settings/company-profile")
def get_company_profile(authorization: str = Header(None)):
    _require_user(authorization)
    return _get_setting("company_profile", {"name": "", "tax_id": "", "contact_info": ""})


@router.put("/api/settings/company-profile")
def set_company_profile(body: CompanyProfile, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    value = body.model_dump()
    _set_setting("company_profile", value)
    _audit(_tok(authorization), "settings.company_profile.update", "settings",
           "company_profile", body.name)
    return {"ok": True}


# ── Edge path setting ─────────────────────────────────────────────────────────

@router.get("/api/settings/edge-path")
def get_edge_path_setting(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    configured = (_get_setting("edge_path") or "").strip()
    try:
        resolved = _get_edge_path()
    except RuntimeError:
        resolved = ""
    return {"configured": configured, "resolved": resolved}


@router.patch("/api/settings/edge-path")
def set_edge_path_setting(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    path = (body.get("path") or "").strip()
    if path and not os.path.exists(path):
        raise HTTPException(400, f"路徑不存在：{path}")
    _set_setting("edge_path", path)
    _audit(_tok(authorization), "settings.edge_path.update", "settings", "edge_path",
           path or "（清空，使用自動偵測）")
    return {"ok": True}


# ── PDF base path setting ─────────────────────────────────────────────────────

@router.get("/api/settings/pdf-base-path")
def get_pdf_base_path_setting(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from pdf_gen import _PDF_BASE_DEFAULT, _get_pdf_base
    configured = (_get_setting("pdf_base_path") or "").strip()
    return {"configured": configured, "resolved": _get_pdf_base(), "default": _PDF_BASE_DEFAULT}


@router.patch("/api/settings/pdf-base-path")
def set_pdf_base_path_setting(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    path = (body.get("path") or "").strip()
    if path and not os.path.isdir(path):
        raise HTTPException(400, f"目錄不存在：{path}")
    _set_setting("pdf_base_path", path)
    _audit(_tok(authorization), "settings.pdf_base_path.update", "settings", "pdf_base_path",
           path or "（清空，使用預設路徑）")
    return {"ok": True}
