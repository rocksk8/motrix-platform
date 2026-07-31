"""System: approval-flow settings, notifications, audit log, work logs."""
import json
import os
import secrets
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header, Body
from pydantic import BaseModel

from db import get_db
from helpers import _require_user, _tok, _audit, _get_setting, _set_setting, _get_edge_path
from helpers.quotations import _steps_to_tiers

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


class _SalespersonTarget(BaseModel):
    name:    str   = ''
    revenue: float = 0
    cases:   int   = 0

class _AnnualTarget(BaseModel):
    revenue:         float = 0
    newCases:        int   = 0
    collectionAmount: float = 0
    collectionRate:  float = 0
    avgNetMarginPct: float = 0
    grossProfit:     float = 0

class OperatingTargetsBody(BaseModel):
    year:        int
    annual:      _AnnualTarget          = _AnnualTarget()
    salesperson: List[_SalespersonTarget] = []


def _normalize_flow(raw: dict) -> dict:
    """Convert old {steps:[]} format to new {tiers:[]} format (settings read path).
    NOTE: _active_tiers() in quotations.py handles the active-approval read path separately
    because it must preserve existing status/approvedAt fields."""
    if raw.get("tiers"):
        return raw
    return {"tiers": _steps_to_tiers(raw.get("steps") or [])}


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


# ── Operating targets ─────────────────────────────────────────────────────────

@router.get("/api/settings/operating-targets")
def get_operating_targets(authorization: str = Header(None)):
    _require_user(authorization)
    return _get_setting("operating_targets") or {}


@router.put("/api/settings/operating-targets")
def put_operating_targets(body: OperatingTargetsBody, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    _set_setting("operating_targets", body.model_dump())
    _audit(_tok(authorization), "settings.operating_targets.update", "settings",
           "operating_targets", f"{body.year} 年度目標",
           {"year": body.year, "changedBy": user.get("display_name") or user["username"]})
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

_MODULE_ACTION_PREFIXES: dict = {
    "dev_crm":    ("dev_case.", "dev_log."),
    "quotation":  ("quotation.",),
    "case_manage": ("deal_tag.",),
    "customer":   ("customer.",),
    "procurement": ("supplier.", "part.", "vendor."),
    "equipment":  ("device.", "warranty."),
    "finance":    ("payment.", "sales_order.", "settlement."),
    "work_log":   ("work_log.",),
    "daily_task": ("daily_task.",),
    "projects":   ("project.",),
}

# Actions that should NOT contribute to the module badge (e.g. deletion meta-events)
_MODULE_EXCLUDE_ACTIONS: dict = {
    "dev_crm": (
        "dev_case.delete",
        "dev_case.delete_request",
        "dev_case.delete_cancel",
        "dev_case.delete_reject",
    ),
}


@router.post("/api/audit-log/module-counts")
def audit_module_counts(body: dict = Body(...), authorization: str = Header(None)):
    """Return per-module count of audit_log entries after given timestamps, excluding the caller's own actions."""
    user = _require_user(authorization)
    modules_since = (body.get("modules") or {}) if isinstance(body, dict) else {}
    if not isinstance(modules_since, dict) or not modules_since:
        return {}
    conn = get_db()
    result = {}
    try:
        for mod_key, since_ts in modules_since.items():
            prefixes = _MODULE_ACTION_PREFIXES.get(mod_key)
            if not prefixes or not since_ts:
                result[mod_key] = 0
                continue
            conds = " OR ".join("action LIKE ?" for _ in prefixes)
            params = [p + "%" for p in prefixes] + [since_ts, user["username"]]
            excl = _MODULE_EXCLUDE_ACTIONS.get(mod_key, ())
            if excl:
                excl_ph = ", ".join("?" for _ in excl)
                sql = (f"SELECT COUNT(*) FROM audit_log "
                       f"WHERE ({conds}) AND at > ? AND username != ? "
                       f"AND action NOT IN ({excl_ph})")
                params = params + list(excl)
            else:
                sql = (f"SELECT COUNT(*) FROM audit_log "
                       f"WHERE ({conds}) AND at > ? AND username != ?")
            count = conn.execute(sql, params).fetchone()[0]
            result[mod_key] = count
    finally:
        conn.close()
    return result


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
    date:     Optional[str] = None,
    month:    Optional[str] = None,
    user_id:  Optional[int] = None,
    case_no:  Optional[str] = None,
    authorization: str = Header(None),
):
    _require_user(authorization)
    conn = get_db()
    sql = """
        SELECT w.id, w.log_date, w.user_id, w.content, w.hours, w.created_at,
               w.case_no, u.display_name, u.username
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
    if case_no:
        sql += " AND w.case_no = ?"
        params.append(case_no)
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
    case_no  = (body.get("case_no") or "").strip()
    if not log_date or not user_id or not content:
        raise HTTPException(400, "log_date / user_id / content 必填")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO work_logs (log_date, user_id, content, hours, created_at, created_by, case_no) "
        "VALUES (?,?,?,?,?,?,?)",
        (log_date, user_id, content, hours, now, u["id"], case_no)
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
    for field in ("log_date", "user_id", "content", "hours", "case_no"):
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


# ── Email notification settings ───────────────────────────────────────────────

_EMAIL_DEFAULTS = {
    "enabled":       False,
    "smtp_host":     "smtp.gmail.com",
    "smtp_port":     587,
    "smtp_user":     "",
    "smtp_password": "",
    "from_name":     "MOTRIX營運系統",
    "base_url":      "http://172.16.11.211:666",
}

_MASKED = "••••••••"


@router.get("/api/settings/email-notify")
def get_email_notify(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    cfg = _get_setting("email_notify", {}) or {}
    safe = {**_EMAIL_DEFAULTS, **cfg}
    safe.pop("admin_emails", None)
    safe["smtp_password"] = _MASKED if cfg.get("smtp_password") else ""
    # Show which admin/superadmin users will receive admin notifications
    from helpers.email_notify import _admin_emails
    safe["admin_email_preview"] = _admin_emails()
    return safe


@router.put("/api/settings/email-notify")
def set_email_notify(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    current = _get_setting("email_notify", {}) or {}
    data = {k: body[k] for k in _EMAIL_DEFAULTS if k in body}
    data = {**_EMAIL_DEFAULTS, **data}
    if data.get("smtp_password") in ("", _MASKED):
        data["smtp_password"] = current.get("smtp_password", "")
    _set_setting("email_notify", data)
    _audit(_tok(authorization), "settings.email_notify.update", "settings",
           "email_notify", "Email 通知設定")
    return {"ok": True}


@router.post("/api/settings/email-notify/test")
def test_email_notify(authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    from helpers.email_notify import _send_raising, _admin_emails
    to = _admin_emails()
    if not to:
        raise HTTPException(400, "找不到可發送對象：請至「使用者管理」為 admin 或 superadmin 帳號填寫 Email")
    html = (
        "<div style='font-family:Arial,sans-serif;padding:24px'>"
        "<h2 style='color:#1a1a1a'>MOTRIX營運系統 — Email 通知測試</h2>"
        "<p>此為測試郵件，SMTP 設定正常。</p>"
        f"<p style='color:#888;font-size:12px'>由 {user.get('display_name') or user['username']} 觸發</p>"
        "</div>"
    )
    try:
        _send_raising(to, "[MOTRIX] 測試通知", html)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"SMTP 連線失敗：{e}")
    return {"ok": True, "sent_to": to}


# ── Custom roles ───────────────────────────────────────────────────────────────

_VALID_BASE_ROLES = {"superadmin", "admin", "sales", "engineer", "viewer"}


@router.get("/api/settings/custom-roles")
def get_custom_roles(authorization: str = Header(None)):
    _require_user(authorization)
    return {"items": _get_setting("custom_roles", []) or []}


@router.post("/api/settings/custom-roles", status_code=201)
def create_custom_role(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "角色名稱不得為空")
    base_role = body.get("baseRole", "viewer")
    if base_role not in _VALID_BASE_ROLES:
        raise HTTPException(400, "無效的基礎角色")
    roles = _get_setting("custom_roles", []) or []
    if any(r["name"] == name for r in roles):
        raise HTTPException(409, "角色名稱已存在")
    new_role = {
        "id":       secrets.token_hex(4),
        "name":     name,
        "baseRole": base_role,
        "modules":  body.get("modules", []),
    }
    roles.append(new_role)
    _set_setting("custom_roles", roles)
    _audit(_tok(authorization), "settings.custom_role.create", "settings", new_role["id"], name)
    return new_role


@router.put("/api/settings/custom-roles/{rid}")
def update_custom_role(rid: str, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    roles = _get_setting("custom_roles", []) or []
    idx = next((i for i, r in enumerate(roles) if r["id"] == rid), None)
    if idx is None:
        raise HTTPException(404, "找不到此自訂角色")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "角色名稱不得為空")
    base_role = body.get("baseRole", "viewer")
    if base_role not in _VALID_BASE_ROLES:
        raise HTTPException(400, "無效的基礎角色")
    if any(r["name"] == name and r["id"] != rid for r in roles):
        raise HTTPException(409, "角色名稱已存在")
    roles[idx]["name"]     = name
    roles[idx]["baseRole"] = base_role
    roles[idx]["modules"]  = body.get("modules", [])
    _set_setting("custom_roles", roles)
    _audit(_tok(authorization), "settings.custom_role.update", "settings", rid, name)
    return roles[idx]


@router.delete("/api/settings/custom-roles/{rid}", status_code=204)
def delete_custom_role(rid: str, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    roles = _get_setting("custom_roles", []) or []
    new_roles = [r for r in roles if r["id"] != rid]
    if len(new_roles) == len(roles):
        raise HTTPException(404, "找不到此自訂角色")
    _set_setting("custom_roles", new_roles)
    _audit(_tok(authorization), "settings.custom_role.delete", "settings", rid, rid)


# ── Role Labels ────────────────────────────────────────────────────────────────

_DEFAULT_ROLE_LABELS = {
    "superadmin": "超級管理員",
    "admin":      "管理員",
    "sales":      "業務",
    "engineer":   "工程師",
    "viewer":     "檢視者",
}


@router.get("/api/settings/role-labels")
def get_role_labels(authorization: str = Header(None)):
    _require_user(authorization)
    stored = _get_setting("role_labels") or {}
    return {**_DEFAULT_ROLE_LABELS, **stored}


class RoleLabelsBody(BaseModel):
    superadmin: str = "超級管理員"
    admin:      str = "管理員"
    sales:      str = "業務"
    engineer:   str = "工程師"
    viewer:     str = "檢視者"


@router.put("/api/settings/role-labels")
def put_role_labels(body: RoleLabelsBody, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    labels = {k: v.strip() for k, v in body.dict().items()}
    for k, v in labels.items():
        if not v:
            raise HTTPException(422, f"角色名稱不可空白：{k}")
    _set_setting("role_labels", labels)
    _audit(_tok(authorization), "settings.role_labels.update", "settings",
           "role_labels", json.dumps(labels, ensure_ascii=False))
    return labels
