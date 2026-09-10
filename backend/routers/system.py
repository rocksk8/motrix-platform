"""System: approval-flow settings, notifications, audit log, work logs."""
import inspect
import json
import os
import secrets
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header, Body, UploadFile, File
from pydantic import BaseModel, model_validator

from db import get_db, CURRENT_VERSION, _MIGRATIONS
from helpers import (
    _require_user, _tok, _audit, _get_setting, _set_setting, _get_edge_path,
    _filter_live_notifications, notify_module_activity,
    approval_flow_setting_key, APPROVAL_DOC_TYPES, DEFAULT_UNIFIED_DOC_TYPES,
    APPROVAL_DOC_TYPE_LABELS,
)
from helpers.quotations import _steps_to_tiers
from photos import _process_project_photo, _photo_root

router = APIRouter()


# ── Models ────────────────────────────────────────────────────────────────────

class ApprovalFlowApprover(BaseModel):
    # 手動挑人（既有格式）：userId/username/displayName 三個都要有
    # 部門主管自動簽核（2026-08-22g）：sourceType='department_manager' + departmentId
    # 處主管自動簽核（2026-08-22h）：sourceType='division_manager' + divisionId
    # 實際簽核人在送審當下即時解析（見 helpers/tiered_approval.py::resolve_tier_approvers）
    sourceType:   Optional[str] = None
    departmentId: Optional[int] = None
    divisionId:   Optional[int] = None
    userId:       Optional[int] = None
    username:     Optional[str] = None
    displayName:  Optional[str] = None

    @model_validator(mode="after")
    def _check_shape(self):
        if self.sourceType == "department_manager":
            if not self.departmentId:
                raise ValueError("department_manager 簽核層需要指定 departmentId")
        elif self.sourceType == "division_manager":
            if not self.divisionId:
                raise ValueError("division_manager 簽核層需要指定 divisionId")
        elif not (self.userId and self.username):
            raise ValueError("手動指定的簽核人需要 userId／username")
        return self

class ApprovalFlowTier(BaseModel):
    order:     int = 0
    approvers: List[ApprovalFlowApprover] = []

class ApprovalFlowSettings(BaseModel):
    tiers: List[ApprovalFlowTier] = []
    # 系統內建「申請人部門主管自動簽核」層開關（2026-08-22i），預設 True——
    # 送審時會在 tiers 最前面自動插入這一層，管理員在設定頁關掉才會存 False。
    # 這一層永遠不會出現在 tiers 陣列裡（只由 helpers/tiered_approval.py 合成），
    # 這裡刻意不接受前端在 tiers 裡塞 sourceType='submitter_manager' 的項目。
    includeSubmitterManagerTier: bool = True


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
    because it must preserve existing status/approvedAt fields.

    Uses key presence ("tiers" in raw), not truthiness (raw.get("tiers")) — a legitimately
    saved empty tier list ([]) is falsy in Python and would otherwise be misrouted through
    the legacy steps-conversion path below (2026-08-28, defensive hardening)."""
    if "tiers" in raw:
        return raw
    return {"tiers": _steps_to_tiers(raw.get("steps") or [])}


# ── Approval flow settings ────────────────────────────────────────────────────

@router.get("/api/settings/approval-flow")
def get_approval_flow_settings(authorization: str = Header(None)):
    """統一簽核設定（2026-08-24 起）：本設定預設套用於報價單／開票申請憑據／出貨單／
    請款單四種單據，取代原本各自獨立的 approval_flow / invoice_voucher_approval_flow /
    shipping_approval_flow 三組設定——舊三組不再讀取，正式機上線後需重新設定一次。

    2026-08-28 起「預設套用」變成可設定：見下方 approval_flow_scope 相關端點，
    管理員可把任一文件類型從這裡切出去、改走自己獨立的 {doc_type}_approval_flow——
    這把 unified_approval_flow key 本身的讀寫方式完全沒變，只是「誰在用它」
    多了一層可設定的間接層。"""
    _require_user(authorization)
    raw = _get_setting("unified_approval_flow", {"tiers": []}) or {}
    return _normalize_flow(raw)


@router.put("/api/settings/approval-flow")
def set_approval_flow_settings(body: ApprovalFlowSettings, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    total_approvers = sum(len(t.approvers) for t in body.tiers)
    value = {
        "tiers": [t.model_dump() for t in body.tiers],
        "includeSubmitterManagerTier": body.includeSubmitterManagerTier,
    }
    _set_setting("unified_approval_flow", value)
    _audit(_tok(authorization), "settings.unified_approval_flow.update", "settings", "unified_approval_flow",
           "統一簽核流程設定（報價單／開票申請憑據／出貨單／請款單）",
           {"tierCount": len(body.tiers), "approverCount": total_approvers,
            "includeSubmitterManagerTier": body.includeSubmitterManagerTier})
    return {"ok": True}


# ── 簽核流程套用範圍（2026-08-28）：五種文件類型可各自勾選要不要走統一流程 ────────
#
# 「編輯」跟「套用」是兩件事，刻意分開：
#   - 編輯：unified_approval_flow／{doc_type}_approval_flow 六把 key 各自永遠可直接
#     讀寫（見下面 get/set_approval_flow_for_doc_type()），跟 scope 設定無關。
#   - 套用：scope 只決定各 router 送審/無簽核層 fallback 那兩處「當下該讀哪把 key」
#     （helpers/tiered_approval.py::approval_flow_setting_key()），本身不影響任何
#     一把 key 的實際內容。
# 這樣「切換」永遠不會弄丟另一邊的既有設定，勾來勾去也不會互相覆蓋。

class ApprovalFlowScopeSettings(BaseModel):
    # 刻意不給預設值——PUT 這個模型永遠代表「完整覆蓋」整組 scope，五個欄位都
    # 必須明確帶值。2026-08-28 code review 抓到：若欄位有預設值，前端載入 scope
    # 失敗（例如 GET 失敗留下空物件 `{}`）又剛好按了儲存，PUT body 會是 `{}`，
    # Pydantic 會靜默把每個缺漏欄位填回這裡的預設值，等於在使用者毫無所覺的
    # 情況下把已自訂的 scope 洗回預設分組。改成必填後，這種殘缺 body 會直接
    # 422，而不是靜默套用預設值。
    quotation:          bool
    shipping:           bool
    invoice_voucher:    bool
    payment_request:    bool
    contractor_voucher: bool


@router.get("/api/settings/approval-flow-scope")
def get_approval_flow_scope(authorization: str = Header(None)):
    _require_user(authorization)
    raw = _get_setting("approval_flow_scope", {}) or {}
    return {dt: raw.get(dt, dt in DEFAULT_UNIFIED_DOC_TYPES) for dt in APPROVAL_DOC_TYPES}


@router.put("/api/settings/approval-flow-scope")
def set_approval_flow_scope(body: ApprovalFlowScopeSettings, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    old_scope  = _get_setting("approval_flow_scope", {}) or {}
    new_scope  = body.model_dump()
    unified_flow = _get_setting("unified_approval_flow", {"tiers": []}) or {"tiers": []}
    seeded = []
    for dt, is_unified in new_scope.items():
        was_unified = old_scope.get(dt, dt in DEFAULT_UNIFIED_DOC_TYPES)
        if was_unified and not is_unified:
            # 剛從統一流程勾掉、改成獨立設定：把目前統一流程的內容複製一份當起點，
            # 避免行為在切換的當下突然改變（使用者 2026-08-28 討論時選定的預設）。
            #
            # ⚠️ 只在該類型自己的 key 目前是空的（從沒設定過，或這輪之前從沒獨立過）
            # 時才複製——2026-08-28 code review 抓到：若不加這個判斷，反覆切換
            # 統一/獨立（例如透過 contractor_vouchers.py 仍保留的專屬設定頁面先手動
            # 設定好一份 tiers，之後切成統一、再切回獨立）會讓這裡無條件覆蓋，
            # 悄悄洗掉先前已經設定好的獨立內容。
            existing = _get_setting(f"{dt}_approval_flow", {"tiers": []}) or {"tiers": []}
            if not (existing.get("tiers") or []):
                _set_setting(f"{dt}_approval_flow", unified_flow)
                seeded.append(dt)
    _set_setting("approval_flow_scope", new_scope)
    _audit(_tok(authorization), "settings.approval_flow_scope.update", "settings", "approval_flow_scope",
           "簽核流程套用範圍設定", {"scope": new_scope, "seededFromUnified": seeded})
    return {"ok": True, "seededFromUnified": seeded}


@router.get("/api/settings/approval-flow/{doc_type}")
def get_approval_flow_for_doc_type(doc_type: str, authorization: str = Header(None)):
    """獨立設定專用：不管 scope 目前怎麼設，永遠直接讀該文件類型自己的
    {doc_type}_approval_flow key（跟 unified_approval_flow 分開存放）。"""
    _require_user(authorization)
    if doc_type not in APPROVAL_DOC_TYPES:
        raise HTTPException(404, f"不支援的文件類型：{doc_type}")
    raw = _get_setting(f"{doc_type}_approval_flow", {"tiers": []}) or {}
    return _normalize_flow(raw)


@router.put("/api/settings/approval-flow/{doc_type}")
def set_approval_flow_for_doc_type(doc_type: str, body: ApprovalFlowSettings, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    if doc_type not in APPROVAL_DOC_TYPES:
        raise HTTPException(404, f"不支援的文件類型：{doc_type}")
    total_approvers = sum(len(t.approvers) for t in body.tiers)
    value = {
        "tiers": [t.model_dump() for t in body.tiers],
        "includeSubmitterManagerTier": body.includeSubmitterManagerTier,
    }
    key = f"{doc_type}_approval_flow"
    _set_setting(key, value)
    label = APPROVAL_DOC_TYPE_LABELS.get(doc_type, doc_type)
    _audit(_tok(authorization), f"settings.{key}.update", "settings", key,
           f"{label}獨立簽核流程設定",
           {"tierCount": len(body.tiers), "approverCount": total_approvers,
            "includeSubmitterManagerTier": body.includeSubmitterManagerTier})
    return {"ok": True}


# ── Operating targets ─────────────────────────────────────────────────────────

@router.get("/api/settings/operating-targets")
def get_operating_targets(authorization: str = Header(None)):
    u = _require_user(authorization)
    if u["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員以上可查閱年度目標")
    return _get_setting("operating_targets") or {}


@router.put("/api/settings/operating-targets")
def put_operating_targets(body: OperatingTargetsBody, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    _set_setting("operating_targets", body.model_dump())
    _audit(_tok(authorization), "settings.operating_targets.update", "settings",
           "operating_targets", f"{body.year} 年度目標",
           {"year": body.year, "changedBy": user.get("display_name") or user["username"]})
    return {"ok": True}


# ── Monthly report recipients（2026-08-27，取代原本寫死只寄 superadmin 的規則）────

class MonthlyReportRecipientsBody(BaseModel):
    userIds: List[int] = []


@router.get("/api/settings/monthly-report-recipients")
def get_monthly_report_recipients(authorization: str = Header(None)):
    _require_user(authorization)
    return _get_setting("monthly_report_recipients") or {"userIds": []}


@router.put("/api/settings/monthly-report-recipients")
def put_monthly_report_recipients(body: MonthlyReportRecipientsBody, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    _set_setting("monthly_report_recipients", body.model_dump())
    _audit(_tok(authorization), "settings.monthly_report_recipients.update", "settings",
           "monthly_report_recipients", f"{len(body.userIds)} 位收件人",
           {"userIds": body.userIds, "changedBy": user.get("display_name") or user["username"]})
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
    rows = _filter_live_notifications(conn, rows)
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
               w.case_no, w.photos, w.contact_type, u.display_name, u.username
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
    result = []
    for r in rows:
        d = dict(r)
        d["photos"] = json.loads(d.get("photos") or "[]")
        result.append(d)
    return result


@router.post("/api/work-logs")
def create_work_log(body: dict = Body(...), authorization: str = Header(None)):
    u = _require_user(authorization)
    log_date = body.get("log_date", "")
    user_id  = body.get("user_id")
    content  = body.get("content", "").strip()
    hours    = float(body.get("hours", 8.0))
    case_no  = (body.get("case_no") or "").strip()
    contact_type = (body.get("contact_type") or "").strip()
    if not log_date or not user_id or not content:
        raise HTTPException(400, "log_date / user_id / content 必填")
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO work_logs (log_date, user_id, content, hours, created_at, created_by, case_no, contact_type) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (log_date, user_id, content, hours, now, u["id"], case_no, contact_type)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    notify_module_activity("工作日誌", "建立", u.get("display_name") or u["username"],
                            log_date, "work-log.html", detail=content)
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
    for field in ("log_date", "user_id", "content", "hours", "case_no", "contact_type"):
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
    notify_module_activity("工作日誌", "刪除", u.get("display_name") or u["username"],
                            str(wid), "work-log.html")
    return {"ok": True}


# ── Work Log Photos（2026-08-26 專案管理併入案件管理：案件動態的工作日誌
#    補上照片能力，處理邏輯/儲存位置整段沿用 routers/projects.py 既有的
#    upload_project_photos()/delete_project_photo()（含 GPS/浮水印處理與
#    demo 帳號隔離，經同一支 _photo_root() 判斷），子資料夾用 worklog_{id}
#    區分，不需要另外新增 demo 專用目錄或清空清單項目）───────────────────────

@router.post("/api/work-logs/{wid}/photos", status_code=201)
async def upload_work_log_photos(
    wid: int,
    files: List[UploadFile] = File(...),
    authorization: str = Header(None),
):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM work_logs WHERE id=?", (wid,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "找不到日誌")
    if user["role"] not in ("superadmin", "admin") and user["id"] != row["user_id"]:
        conn.close(); raise HTTPException(403, "只能替自己的工作日誌上傳照片")

    existing = json.loads(row["photos"] or "[]")
    today = datetime.now().strftime("%Y-%m-%d")
    base_dir, url_prefix = _photo_root()
    save_dir = os.path.join(base_dir, f"worklog_{wid}", today)
    os.makedirs(save_dir, exist_ok=True)

    new_photos = []
    for upload in files:
        raw_bytes = await upload.read()
        processed, gps_str, wm_str = _process_project_photo(raw_bytes, user['display_name'])
        ext   = os.path.splitext(upload.filename or 'photo.jpg')[1] or '.jpg'
        fname = uuid.uuid4().hex[:14] + ext.lower()
        with open(os.path.join(save_dir, fname), 'wb') as f:
            f.write(processed)
        new_photos.append({
            "id":          uuid.uuid4().hex[:8],
            "filename":    fname,
            "path":        f"{url_prefix}/worklog_{wid}/{today}/{fname}",
            "gps":         gps_str,
            "watermark":   wm_str,
            "uploaded_by": user['display_name'],
            "uploaded_at": datetime.now().isoformat(),
        })

    all_photos = existing + new_photos
    conn.execute("UPDATE work_logs SET photos=? WHERE id=?",
                 (json.dumps(all_photos, ensure_ascii=False), wid))
    conn.commit()
    conn.close()
    notify_module_activity("工作日誌", "上傳照片", user['display_name'],
                            f"日誌 #{wid}（{len(new_photos)} 張）", "work-log.html")
    return {"ok": True, "added": len(new_photos), "photos": new_photos}


@router.delete("/api/work-logs/{wid}/photos/{photo_id}")
def delete_work_log_photo(wid: int, photo_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row  = conn.execute("SELECT * FROM work_logs WHERE id=?", (wid,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "找不到日誌")
    if user["role"] not in ("superadmin", "admin") and user["id"] != row["user_id"]:
        conn.close(); raise HTTPException(403, "只能刪除自己工作日誌的照片")
    photos = json.loads(row["photos"] or "[]")
    photo  = next((p for p in photos if p.get('id') == photo_id), None)
    if not photo:
        conn.close(); raise HTTPException(404, "照片不存在")
    try:
        base_dir, _url_prefix = _photo_root()
        fp = os.path.join(base_dir, '..', photo['path'])
        if os.path.isfile(fp):
            os.remove(fp)
    except Exception:
        pass
    photos = [p for p in photos if p.get('id') != photo_id]
    conn.execute("UPDATE work_logs SET photos=? WHERE id=?",
                 (json.dumps(photos, ensure_ascii=False), wid))
    conn.commit()
    conn.close()
    notify_module_activity("工作日誌", "刪除照片", user.get("display_name") or user["username"],
                            f"日誌 #{wid}", "work-log.html")
    return {"ok": True}


# ── Company profile（甲方設定，勞報單使用）────────────────────────────────────

class CompanyProfile(BaseModel):
    name:                str = ''
    tax_id:              str = ''
    contact_info:        str = ''
    bank_name:           str = ''  # 收款帳戶資訊（2026-08-24 新增，供請款單 PDF 顯示）
    bank_branch:         str = ''
    bank_account_name:   str = ''
    bank_account_number: str = ''


_COMPANY_PROFILE_DEFAULT = {
    "name": "", "tax_id": "", "contact_info": "",
    "bank_name": "", "bank_branch": "", "bank_account_name": "", "bank_account_number": "",
}


@router.get("/api/settings/company-profile")
def get_company_profile(authorization: str = Header(None)):
    _require_user(authorization)
    # 既有安裝的 DB 值可能是新增銀行欄位前存的舊 shape，缺的鍵補上空字串，
    # 前端才不用每個欄位都自己防 undefined。
    return {**_COMPANY_PROFILE_DEFAULT, **(_get_setting("company_profile", {}) or {})}


@router.put("/api/settings/company-profile")
def set_company_profile(body: CompanyProfile, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module='settings')
    value = body.model_dump()
    _set_setting("company_profile", value)
    _audit(_tok(authorization), "settings.company_profile.update", "settings",
           "company_profile", body.name)
    return {"ok": True}


# ── Quotation default payment terms ───────────────────────────────────────────

DEFAULT_PAYMENT_TERMS = """本專案總價款分三期給付，本報價不含運費與關稅，前述相關衍生費用由買方另行負擔。
第一期：定金款（總價款50%），買方給付本期款項後，本專案即確認執行，賣方應開立憑證予買方。
第二期：交貨款（總價款30%），設備運抵買方指定地點並完成硬體點交後，賣方得開立憑證請款，付款方式為賣方提交憑證之次月份25日支付。
第三期：驗收款（總價款20%），設備安裝、系統設定及缺失改善完成，並經買方驗收合格後，賣方得開立憑證請款，付款方式為賣方提交憑證之次月份25日支付。"""


class PaymentTermsBody(BaseModel):
    text: str = ''


@router.get("/api/settings/payment-terms")
def get_default_payment_terms(authorization: str = Header(None)):
    _require_user(authorization)
    return {"text": _get_setting("default_payment_terms", DEFAULT_PAYMENT_TERMS)}


@router.put("/api/settings/payment-terms")
def set_default_payment_terms(body: PaymentTermsBody, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    _set_setting("default_payment_terms", body.text)
    _audit(_tok(authorization), "settings.payment_terms.update", "settings",
           "default_payment_terms", "報價單預設付款條件")
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
    actor = _require_user(authorization, require_superadmin=True)
    path = (body.get("path") or "").strip()
    if path and not os.path.exists(path):
        raise HTTPException(400, f"路徑不存在：{path}")
    _set_setting("edge_path", path)
    _audit(_tok(authorization), "settings.edge_path.update", "settings", "edge_path",
           path or "（清空，使用自動偵測）")
    notify_module_activity("系統設定", "變更 Edge 路徑", actor.get("display_name") or actor["username"],
                            path or "（清空，使用自動偵測）", "notification-settings.html")
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
    actor = _require_user(authorization, require_superadmin=True)
    path = (body.get("path") or "").strip()
    if path and not os.path.isdir(path):
        raise HTTPException(400, f"目錄不存在：{path}")
    _set_setting("pdf_base_path", path)
    _audit(_tok(authorization), "settings.pdf_base_path.update", "settings", "pdf_base_path",
           path or "（清空，使用預設路徑）")
    notify_module_activity("系統設定", "變更 PDF 存檔路徑", actor.get("display_name") or actor["username"],
                            path or "（清空，使用預設路徑）", "notification-settings.html")
    return {"ok": True}


# ── WebAuthn RP ID / Origin settings ──────────────────────────────────────────
# 2026-09-10（f8198e9）從環境變數改成這裡的 system_settings 可動態設定。
# 這兩個值填錯的代價特別高，所以下面的驗證不是形式主義：
#   - RP ID 必須是「純網域名稱」（不含 scheme／port／路徑）
#   - Origin 必須是完整來源（scheme://host[:port]）
#   - Origin 的 host 必須等於 RP ID，或是它的子網域
# 任何一條不成立，瀏覽器只會丟一句沒有上下文的 "invalid domain"／
# SecurityError，看起來像前端壞掉——而這正是 f8198e9 這次改動想消滅的症狀。
# 與其讓使用者在瀏覽器主控台猜，不如在存檔當下就擋掉並說清楚哪裡不對。

def _validate_webauthn_pair(rp_id: str, origin: str) -> None:
    """RP ID／Origin 的格式與相依關係檢查，不合規直接 400。"""
    import re as _re
    from urllib.parse import urlparse as _urlparse

    if _re.search(r"[:/]", rp_id):
        raise HTTPException(400, f"RP ID 只能是網域名稱本身，不要含 http(s):// 或連接埠（收到：{rp_id}）")
    if not _re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*", rp_id):
        raise HTTPException(400, f"RP ID 不是合法的網域名稱（收到：{rp_id}）")

    parsed = _urlparse(origin)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise HTTPException(400, f"Origin 必須是完整來源，例如 https://erp.example.local:666（收到：{origin}）")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise HTTPException(400, f"Origin 不可包含路徑或查詢字串（收到：{origin}）")

    host = parsed.hostname.lower()
    rp = rp_id.lower()
    if host != rp and not host.endswith("." + rp):
        raise HTTPException(
            400,
            f"Origin 的主機（{host}）必須等於 RP ID（{rp}）或是它的子網域，"
            f"否則瀏覽器會拒絕註冊 Passkey。"
        )
    # localhost 是 WebAuthn 規格唯一允許走 http 的例外；其餘一律要 https，
    # 否則瀏覽器同樣直接拒絕（這台正式機本來就已經是 HTTPS，見 §1）。
    if parsed.scheme == "http" and host != "localhost":
        raise HTTPException(400, "除了 localhost 之外，Origin 必須是 https://（瀏覽器規格要求）")


@router.get("/api/settings/webauthn-config")
def get_webauthn_config(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        cred_count = conn.execute("SELECT COUNT(*) AS c FROM webauthn_credentials").fetchone()["c"]
    finally:
        conn.close()
    return {
        "rp_id": _get_setting("webauthn_rp_id") or "",
        "origin": _get_setting("webauthn_origin") or "",
        # 讓設定頁能提醒「改了會讓現有 N 張 Passkey 失效」——見下方 PATCH 的說明
        "credentialCount": cred_count,
    }


@router.patch("/api/settings/webauthn-config")
def set_webauthn_config(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    rp_id = (body.get("rp_id") or "").strip()
    origin = (body.get("origin") or "").strip()
    if (rp_id and not origin) or (origin and not rp_id):
        raise HTTPException(400, "RP ID 與 Origin 必須同時設定或同時清空")
    if rp_id:
        _validate_webauthn_pair(rp_id, origin)

    # 既有 Passkey 是被瀏覽器綁在「註冊當下那個 RP ID」上的，而
    # `webauthn_credentials`（db.py _m073）刻意沒有存 rp_id 欄位——
    # 也就是說改動 RP ID 之後，所有既有憑證會在下次登入時直接失效，
    # 而且系統這邊查不出它們原本屬於哪個 RP。這裡不擋（第一次設定時
    # 本來就必須能寫入，而且 superadmin 有權決定），但把受影響張數
    # 回傳並寫進稽核，讓「使用者突然說 Passkey 全部不能用了」這種
    # 回報有跡可循。
    previous_rp = _get_setting("webauthn_rp_id") or ""
    invalidated = 0
    if previous_rp and previous_rp != rp_id:
        conn = get_db()
        try:
            invalidated = conn.execute("SELECT COUNT(*) AS c FROM webauthn_credentials").fetchone()["c"]
        finally:
            conn.close()

    _set_setting("webauthn_rp_id", rp_id)
    _set_setting("webauthn_origin", origin)
    detail = f"rp_id={rp_id}, origin={origin}" if rp_id else "（清空）"
    if invalidated:
        detail += f"；RP ID 由 {previous_rp} 變更，既有 {invalidated} 張 Passkey 將失效"
    _audit(_tok(authorization), "settings.webauthn_config.update", "settings", "webauthn", detail)
    notify_module_activity("系統設定", "變更 WebAuthn 設定", actor.get("display_name") or actor["username"],
                            f"rp_id={rp_id}" if rp_id else "（清空）", "notification-settings.html")
    return {"ok": True, "invalidatedCredentials": invalidated}


# ── Backup retention settings ─────────────────────────────────────────────────
# 2026-09-01：本機/雲端備份保留天數原本寫死在 archive.py（見該檔 _BACKUP_RETENTION_
# DEFAULT 註解），使用者要求可調整避免雲端空間被逐年累積的每日/週備份塞爆，改成
# 存進 system_settings.backup_retention，這裡提供 API 讀寫（無對應前端頁面，
# 比照 edge-path／pdf-base-path 這類低頻技術設定的既有慣例，透過 API 直接調整）。

class BackupRetentionBody(BaseModel):
    local_db_keep_days:    int
    cloud_daily_keep_days: int
    cloud_weekly_keep_days: int
    audit_log_keep_days:   int


@router.get("/api/settings/backup-retention")
def get_backup_retention_setting(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from archive import _backup_retention
    return _backup_retention()


@router.patch("/api/settings/backup-retention")
def set_backup_retention_setting(body: BackupRetentionBody, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    value = body.model_dump()
    for label, days in value.items():
        if days < 1 or days > 3650:
            raise HTTPException(400, f"{label} 需介於 1～3650 天之間")
    _set_setting("backup_retention", value)
    _audit(_tok(authorization), "settings.backup_retention.update", "settings", "backup_retention",
           f"本機DB快照{value['local_db_keep_days']}天／雲端每日{value['cloud_daily_keep_days']}天／"
           f"雲端週{value['cloud_weekly_keep_days']}天／稽核紀錄{value['audit_log_keep_days']}天")
    notify_module_activity("系統設定", "變更備份保留天數", actor.get("display_name") or actor["username"],
                            f"每日{value['cloud_daily_keep_days']}天／週{value['cloud_weekly_keep_days']}天",
                            "notification-settings.html")
    return {"ok": True}


# ── Cloud backup storage target（2026-09-07，架構地圖 §6.4）────────────────────
# 選擇備份要寫去哪裡：本機掛載的雲端硬碟磁碟機（預設，沿用 archive.py 既有邏輯，
# 已知磁碟機代號會漂移）或 S3 相容物件儲存（AWS S3／Backblaze B2 等，見
# cloud_storage.py）。**憑證一律不存這裡**——走 boto3 標準憑證鏈（環境變數／
# ~/.aws/credentials／instance profile），這裡只存 bucket/endpoint/region/prefix
# 這類非機密設定值，無對應前端頁面（比照 edge-path/pdf-base-path 等技術設定慣例，
# 透過 API 直接調整）。

class CloudBackupS3Body(BaseModel):
    bucket: str = ""
    endpoint_url: str = ""
    region: str = "us-east-1"
    prefix: str = "motrix-erp-backups/"


class CloudBackupTargetBody(BaseModel):
    backend: str
    s3: CloudBackupS3Body = CloudBackupS3Body()


@router.get("/api/settings/cloud-backup-target")
def get_cloud_backup_target_setting(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from cloud_storage import cloud_backup_target
    return cloud_backup_target()


@router.put("/api/settings/cloud-backup-target")
def set_cloud_backup_target_setting(body: CloudBackupTargetBody, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    if body.backend not in ("local_drive", "s3"):
        raise HTTPException(400, "backend 需為 local_drive 或 s3")
    if body.backend == "s3" and not body.s3.bucket:
        raise HTTPException(400, "選擇 s3 時 bucket 為必填")
    value = {"backend": body.backend, "s3": body.s3.model_dump()}
    _set_setting("cloud_backup_target", value)
    import cloud_storage
    cloud_storage.reset_s3_client_cache()
    cloud_storage.reset_s3_available_cache()
    _audit(_tok(authorization), "settings.cloud_backup_target.update", "settings", "cloud_backup_target",
           f"備份目標改為 {body.backend}" + (f"（bucket={body.s3.bucket}）" if body.backend == "s3" else ""))
    notify_module_activity("系統設定", "變更雲端備份目標", actor.get("display_name") or actor["username"],
                            body.backend, "notification-settings.html")
    return {"ok": True}


# ── Email notification settings ───────────────────────────────────────────────

_EMAIL_DEFAULTS = {
    "enabled":       False,
    "smtp_host":     "smtp.gmail.com",
    "smtp_port":     587,
    "smtp_user":     "",
    "smtp_password": "",
    "from_name":     "MOTRIX專案管理系統",
    "base_url":      "https://172.16.10.177:666",  # 2026-08-27：見 backend/tools/https_setup.ps1
    "dev_mode":      False,  # 開發機測試模式：寄出信件標題加註「【開發機測試】」，
                             # 存在本機 DB，不隨部署流程移動到正式機（2026-08-26）
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


# ── Google 行事曆設定（2026-08-21，push only Phase 1）─────────────────────────

_GCAL_DEFAULTS = {
    "enabled":       False,
    "client_id":     "",
    "client_secret": "",
    "calendar_id":   "primary",
    "refresh_token": "",
}


@router.get("/api/settings/google-calendar")
def get_google_calendar(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    cfg = _get_setting("google_calendar", {}) or {}
    safe = {**_GCAL_DEFAULTS, **cfg}
    safe["client_secret"] = _MASKED if cfg.get("client_secret") else ""
    safe["connected"] = bool(cfg.get("refresh_token"))
    safe.pop("refresh_token", None)
    # 提示管理員授權時要用哪個 Gmail 帳號（跟寄信用的 SMTP 帳號同一組）
    email_cfg = _get_setting("email_notify", {}) or {}
    safe["smtp_user_hint"] = email_cfg.get("smtp_user", "")
    return safe


@router.put("/api/settings/google-calendar")
def set_google_calendar(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    current = _get_setting("google_calendar", {}) or {}
    data = {k: body[k] for k in _GCAL_DEFAULTS if k in body}
    data = {**_GCAL_DEFAULTS, **current, **data}
    if data.get("client_secret") in ("", _MASKED):
        data["client_secret"] = current.get("client_secret", "")
    # refresh_token 只由一次性授權腳本寫入，這個端點絕不清空/覆蓋它
    data["refresh_token"] = current.get("refresh_token", "")
    _set_setting("google_calendar", data)
    _audit(_tok(authorization), "settings.google_calendar.update", "settings",
           "google_calendar", "Google 行事曆設定")
    return {"ok": True}


@router.post("/api/settings/google-calendar/test")
def test_google_calendar(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from helpers.google_calendar import create_test_event
    try:
        event_id = create_test_event()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"建立測試事件失敗：{e}")
    return {"ok": True, "event_id": event_id}


@router.post("/api/settings/email-notify/test")
def test_email_notify(authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    from helpers.email_notify import _send_raising, _admin_emails
    to = _admin_emails()
    if not to:
        raise HTTPException(400, "找不到可發送對象：請至「使用者管理」為 admin 或 superadmin 帳號填寫 Email")
    html = (
        "<div style='font-family:Arial,sans-serif;padding:24px'>"
        "<h2 style='color:#1a1a1a'>MOTRIX專案管理系統 — Email 通知測試</h2>"
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
    actor = _require_user(authorization, require_superadmin=True)
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
    notify_module_activity("系統設定", "建立自訂角色", actor.get("display_name") or actor["username"],
                            name, "users.html")
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
    actor = _require_user(authorization, require_superadmin=True)
    roles = _get_setting("custom_roles", []) or []
    new_roles = [r for r in roles if r["id"] != rid]
    if len(new_roles) == len(roles):
        raise HTTPException(404, "找不到此自訂角色")
    _set_setting("custom_roles", new_roles)
    _audit(_tok(authorization), "settings.custom_role.delete", "settings", rid, rid)
    notify_module_activity("系統設定", "刪除自訂角色", actor.get("display_name") or actor["username"],
                            rid, "users.html")


# ── Role Labels ────────────────────────────────────────────────────────────────

_DEFAULT_ROLE_LABELS = {
    "superadmin": "超級管理員",
    "admin":      "管理員",
    "sales":      "業務",
    "engineer":   "工程師",
    "viewer":     "檢視者",
}


@router.get("/api/system/schema-status")
def get_schema_status(authorization: str = Header(None)):
    """唯讀 schema/migration 診斷資訊：目前版本、目標版本、完整 migration 清單。
    不提供任何觸發/操作動作——migration 已在伺服器啟動時自動套用，「重新對現有
    db 跑一次」永遠是 no-op，沒有診斷價值；真正有意義的乾跑驗證在部署階段
    （見 backend/tools/apply_update.ps1），不是活著的伺服器本身。"""
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    row = conn.execute("SELECT version, applied_at FROM schema_version WHERE id=1").fetchone()
    conn.close()
    current = row["version"] if row else 0
    applied_at = row["applied_at"] if row else ""
    migrations = [
        {
            "version": i,
            "name": fn.__name__,
            "description": inspect.getdoc(fn) or "",
            "applied": i <= current,
        }
        for i, fn in enumerate(_MIGRATIONS, start=1)
    ]
    return {
        "currentVersion": current,
        "targetVersion": CURRENT_VERSION,
        "upToDate": current >= CURRENT_VERSION,
        "lastAppliedAt": applied_at,
        "migrations": migrations,
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


# ── WebAuthn config status (public, no auth) ──────────────────────────────────

@router.get("/api/system/webauthn-config-status")
def get_webauthn_config_status():
    """Public endpoint: check whether WebAuthn RP ID and Origin are configured.
    Used by login.html and change-password.html to show/hide Passkey buttons."""
    rp_id = _get_setting("webauthn_rp_id") or ""
    origin = _get_setting("webauthn_origin") or ""
    configured = bool(rp_id.strip() and origin.strip())
    return {"configured": configured}
