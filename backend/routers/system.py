"""System: approval-flow settings, notifications, audit log, work logs."""
import inspect
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header, Body, UploadFile, File, Depends
from pydantic import BaseModel, model_validator

from db import get_db, CURRENT_VERSION, _MIGRATIONS
from helpers import (
    _require_user, _tok, _audit, _get_setting, _set_setting, _get_edge_path,
    _filter_live_notifications, notify_module_activity,
    approval_flow_setting_key, APPROVAL_DOC_TYPES, DEFAULT_UNIFIED_DOC_TYPES,
    APPROVAL_DOC_TYPE_LABELS, require_any_module,
)
from helpers.quotations import _steps_to_tiers
from photos import _process_project_photo, _photo_root
import trail

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
    # 2026-09-14 使用者裁示：這頁原本沒有對應的模組 key，只能靠角色寫死
    # （`admin` 以上）。既然全站已經改成「未開啟的模組直接不顯示」，就替它
    # 建一個 key（`audit_log`）——「沒有對應模組 key 也建立就沒有這個問題」。
    # 好處是它從此跟其他模組一樣可以逐帳號勾選，不用再為了「誰能看稽核紀錄」
    # 去改程式碼裡的角色判斷式。
    user = _require_user(authorization)
    require_any_module(user, ["audit_log"], "歷史紀錄")
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
    user = _require_user(authorization)
    require_any_module(user, ('work_log', 'case_manage'), "工作日誌")
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
    require_any_module(user, ('work_log', 'case_manage'), "工作日誌")
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
    require_any_module(user, ('work_log', 'case_manage'), "工作日誌")
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
    # 辦公室地址（2026-09-21 §3l）。用途是**算標案離我們多遠**，
    # 所以它跟抬頭／統編不同：沒填的後果不是 PDF 少一行，是整個距離功能不會動。
    # ⇒ 沒填時地圖端點會明白回報 `officeMissing`，不是安靜地不顯示距離。
    address: str = ''
    # Google Maps 金鑰（可選）。**免金鑰的底圖與距離不需要它**，
    # 它只開啟「附近公司」那一塊；空字串 ⇒ 那一塊**不存在**（不是壞掉的按鈕）。
    # ⚠️ 它會被送到前端——那是 Maps JS API 的正常用法，不是洩漏。
    #    但**不可以寫進任何 log**：log 會被打包、被寄出、被放進備份，
    #    而那些地方沒有人在管金鑰。兩者的保存期限完全不同。
    google_maps_api_key: str = ''
    # 手動座標（2026-09-22 §3o A2／A10）。填了就**跳過所有查詢**，
    # 精度是 exact、來源是 manual。
    # 🔑 它存在的理由：圖資認不得台灣的門牌，而使用者知道自己在哪裡。
    # ⚠️ 兩個欄位是 Optional 而不是預設 0.0——
    #    **0.0 是幾內亞灣上的一個點，不是「沒有填」。**
    office_lat: Optional[float] = None
    office_lon: Optional[float] = None


# 🔴 **既有安裝讀得到新欄位，靠的是這裡，不是 `db.py` 的 seed。**
# `_seed_setting` 是 `ON CONFLICT(key) DO NOTHING` ⇒ 對已經存在的那一列
# **一個字都不會改**。新增欄位時只改 seed 的話，新機正常、舊機沒有那個欄位，
# 而開發時手邊兩種都有、注意力只會落在會動的那一台。
# 📌 銀行那四欄 2026-08-24 就走過這條路。
_COMPANY_PROFILE_DEFAULT = {
    "name": "", "tax_id": "", "contact_info": "",
    "bank_name": "", "bank_branch": "", "bank_account_name": "", "bank_account_number": "",
    "address": "", "google_maps_api_key": "",
    "office_lat": None, "office_lon": None,
}


@router.get("/api/settings/company-profile")
def get_company_profile(authorization: str = Header(None)):
    _require_user(authorization)
    # 既有安裝的 DB 值可能是新增銀行欄位前存的舊 shape，缺的鍵補上空字串，
    # 前端才不用每個欄位都自己防 undefined。
    return {**_COMPANY_PROFILE_DEFAULT, **(_get_setting("company_profile", {}) or {})}


def _check_office_coord(body: "CompanyProfile") -> None:
    """手動座標的範圍檢查。超出範圍 ⇒ 422。

    ⚠️ **緯度 ±90、經度 ±180 是地球的範圍，不是台灣的。**
    刻意不收窄到台灣：使用者哪天要標一個國外的案子，
    而**一個「為了你好」而擋住合法輸入的驗證，會被繞過去**。
    """
    pairs = (("office_lat", 90.0), ("office_lon", 180.0))
    for field, limit in pairs:
        if field not in body.model_fields_set:
            continue
        value = getattr(body, field)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise HTTPException(422, f"{field} 必須是數字")
        if not -limit <= number <= limit:
            raise HTTPException(
                422, f"{field} 超出範圍（{-limit:g} ~ {limit:g}）：{number}")


@router.put("/api/settings/company-profile")
def set_company_profile(body: CompanyProfile, authorization: str = Header(None)):
    """部分更新：**這次沒送的欄位保留現值。**

    🔴 原本是 `body.model_dump()` 整筆覆蓋，而 `CompanyProfile` 每個欄位都有
    `= ''` 預設 ⇒ **任何沒送齊欄位的呼叫端，會把沒送的欄位清成空字串**，
    而且**不會報錯**。畫面上是「欄位都在、只是空的」——
    跟「新裝的機器還沒填」長得一模一樣。
    ⚠️ 具體情境不是假想：一個在部署**之前**就開著的分頁（跑的是舊 JS，
    不知道有 `address`），存一次檔就把 address 清掉了。

    ## ⚠️ 這裡不能用 `key in body`

    收的是 **Pydantic 模型不是 dict** ⇒ Pydantic 會先把沒送的欄位填成 `''`，
    進到這裡時「沒送」與「送了空字串」**已經被壓成同一個值**。
    （`routers/tender_radar.py` 那邊收的是 `dict = Body(...)`，所以那邊
    `key in body` 成立——**兩邊不一樣，抄過來會失效而且安靜。**）

    ⇒ 用 `model_fields_set`（這次請求真的送了哪幾個），形狀照 `suppliers.py:106`。
    📌 那裡的註解 2026 年就寫著同一件事：「不知道有這個欄位的舊前端，
    不應該因為存了一次供應商就把它清掉。」**全庫只有那一處在用它。**

    🔑 而「明確送空字串」必須真的清掉（不可以寫成「空字串一律忽略」），
    否則使用者**永遠刪不掉**填錯的銀行帳號。
    **「沒送」與「送了空字串」是兩件事。**
    """
    _require_user(authorization, require_superadmin=True, module='settings')
    # 🔴 **先驗證，再寫入。** 「回了錯誤碼」與「沒有存進去」是兩件事——
    # 一邊驗一邊寫的話，使用者會看到 422 而值已經生效了。
    _check_office_coord(body)
    cur = {**_COMPANY_PROFILE_DEFAULT,
           **(_get_setting("company_profile", {}) or {})}
    sent = body.model_dump(include=body.model_fields_set)
    value = {**cur, **sent}
    _set_setting("company_profile", value)
    # ⚠️ 稽核留的是**公司名**，不是整包 value —— 那包裡有金鑰。
    _audit(_tok(authorization), "settings.company_profile.update", "settings",
           "company_profile", value.get("name", ""))
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

def _require_passkey_enabled() -> None:
    """Passkey 總開關守門——**轉呼叫** `routers/auth.py` 的同名函式。

    刻意不在這裡複製那三行：開關只能有一個判斷點，兩份遲早會分岔（其中一邊
    被改成 403、或忘了跟著恢復）。函式內 import 是為了避開 router 之間的
    模組層相依。開關本身在 `helpers/auth.py::PASSKEY_ENABLED`。
    """
    from routers.auth import _require_passkey_enabled as _guard
    _guard()


def _validate_webauthn_pair(rp_id: str, origin: str) -> None:
    """RP ID／Origin 的格式與相依關係檢查，不合規直接 400。"""
    import ipaddress as _ipaddress
    import re as _re
    from urllib.parse import urlparse as _urlparse

    if _re.search(r"[:/]", rp_id):
        raise HTTPException(400, f"RP ID 只能是網域名稱本身，不要含 http(s):// 或連接埠（收到：{rp_id}）")
    if not _re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*", rp_id):
        raise HTTPException(400, f"RP ID 不是合法的網域名稱（收到：{rp_id}）")

    # IP 位址不能當 RP ID。W3C WebAuthn 規格要求 RP ID 是「可註冊網域後綴」，
    # IP 位址不具備這個性質，Chrome/Edge/Safari 一律直接拒絕註冊。
    # 這一條特別容易踩到：這台正式機平常就是用 172.16.10.177:666 存取，
    # 很自然會想直接把 IP 填進去——填了會存得進資料庫、前端 Passkey 按鈕
    # 也會亮起來（configured=true），但實際點下去只會拿到一句沒有上下文的
    # SecurityError，看起來像功能壞掉。必須先有內部 DNS 名稱指向這台機器。
    try:
        _ipaddress.ip_address(rp_id)
    except ValueError:
        pass  # 不是 IP，正常情況
    else:
        raise HTTPException(
            400,
            f"RP ID 不能是 IP 位址（收到：{rp_id}）。WebAuthn 規格要求 RP ID 是可註冊的網域"
            f"後綴，瀏覽器會直接拒絕 IP。請先在內部 DNS 建一個指向這台主機的名稱"
            f"（例如 erp.miactw.local），再用那個名稱設定。"
        )

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


@router.get("/api/settings/webauthn-config", dependencies=[Depends(_require_passkey_enabled)])
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


@router.patch("/api/settings/webauthn-config", dependencies=[Depends(_require_passkey_enabled)])
def set_webauthn_config(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    rp_id = (body.get("rp_id") or "").strip()
    origin = (body.get("origin") or "").strip()
    if (rp_id and not origin) or (origin and not rp_id):
        raise HTTPException(400, "RP ID 與 Origin 必須同時設定或同時清空")
    if rp_id:
        _validate_webauthn_pair(rp_id, origin)

    # 既有 Passkey 是被瀏覽器綁在「註冊當下那個 RP ID」上的，改動 RP ID 之後
    # 那些憑證會在下次登入時直接失效，而且**無法救回**（綁定在瀏覽器端，不在
    # 我們手上）。這裡不擋（第一次設定本來就必須能寫入，superadmin 也有權決定），
    # 但把受影響的張數與人數回傳、寫進稽核，讓「使用者突然說 Passkey 不能用了」
    # 這種回報有跡可循。
    #
    # 2026-09-11（DB v74）：`webauthn_credentials` 補上 rp_id 欄位之後，這裡從
    # 「回報全表張數」改成**精準計算真正會失效的那幾張**。原本的作法在只有一種
    # RP ID 時剛好等於正確答案，但只要出現過兩種以上就會高估——而且說不出是誰的。
    previous_rp = _get_setting("webauthn_rp_id") or ""
    invalidated = 0
    affected_users = 0
    if previous_rp and previous_rp != rp_id:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c, COUNT(DISTINCT user_id) AS u "
                "FROM webauthn_credentials WHERE rp_id != '' AND rp_id != ?",
                (rp_id,)
            ).fetchone()
            invalidated = row["c"]
            affected_users = row["u"]
        finally:
            conn.close()

    _set_setting("webauthn_rp_id", rp_id)
    _set_setting("webauthn_origin", origin)
    detail = f"rp_id={rp_id}, origin={origin}" if rp_id else "（清空）"
    if invalidated:
        detail += (f"；RP ID 由 {previous_rp} 變更為 {rp_id or '（清空）'}，"
                   f"{affected_users} 位使用者的 {invalidated} 張 Passkey 失效（無法復原，須重新註冊）")
    _audit(_tok(authorization), "settings.webauthn_config.update", "settings", "webauthn", detail)
    notify_module_activity("系統設定", "變更 WebAuthn 設定", actor.get("display_name") or actor["username"],
                            f"rp_id={rp_id}" if rp_id else "（清空）", "notification-settings.html")
    return {"ok": True, "invalidatedCredentials": invalidated, "affectedUsers": affected_users}


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
    # 2026-09-14 新增的兩個都給預設值，舊 client 只送原本 4 個欄位仍然能用
    # （這支端點沒有前端頁面，但打包過的舊腳本／curl 範例可能還在流傳）。
    cloud_monthly_keep_days: int = 0    # 0 = 永久保留（使用者裁示的預設政策）
    local_pre_update_keep:   int = 5    # 份數，不是天數


@router.get("/api/settings/backup-retention")
def get_backup_retention_setting(authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    from archive import _backup_retention
    return _backup_retention()


@router.patch("/api/settings/backup-retention")
def set_backup_retention_setting(body: BackupRetentionBody, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    value = body.model_dump()
    # 三種欄位語意不同，不能再像原本那樣一律套「1～3650 天」：
    #   *_keep_days      天數，至少 1 天
    #   cloud_monthly_*  天數，但 0 有特殊意義＝永久保留（預設政策）
    #   local_pre_update_keep 是「份數」不是天數，上限用 100 份就夠荒謬了
    for label, days in value.items():
        if label == "local_pre_update_keep":
            if days < 0 or days > 100:
                raise HTTPException(400, f"{label} 需介於 0～100 份之間（0 = 不清理）")
        elif label == "cloud_monthly_keep_days":
            if days < 0 or days > 3650:
                raise HTTPException(400, f"{label} 需介於 0～3650 天之間（0 = 永久保留）")
        elif days < 1 or days > 3650:
            raise HTTPException(400, f"{label} 需介於 1～3650 天之間")
    _set_setting("backup_retention", value)
    _monthly_label = ("永久保留" if value["cloud_monthly_keep_days"] <= 0
                      else f"{value['cloud_monthly_keep_days']}天")
    _audit(_tok(authorization), "settings.backup_retention.update", "settings", "backup_retention",
           f"本機DB快照{value['local_db_keep_days']}天／雲端每日{value['cloud_daily_keep_days']}天／"
           f"雲端週{value['cloud_weekly_keep_days']}天／雲端月{_monthly_label}／"
           f"套用前快照{value['local_pre_update_keep']}份／稽核紀錄{value['audit_log_keep_days']}天")
    notify_module_activity("系統設定", "變更備份保留天數", actor.get("display_name") or actor["username"],
                            f"每日{value['cloud_daily_keep_days']}天／週{value['cloud_weekly_keep_days']}天",
                            "notification-settings.html")
    return {"ok": True}


# ── 報價條款組（2026-09-14 使用者交辦）────────────────────────────────────────
#
# 使用者裁示：「報價單可以增加付款條件的選項，名稱也可以自定義，例如純購料，
# 他有自己的付款條件、驗收標準、保固條件，可由報價人手動點選方塊做切換，
# 只有超級管理員可以點選設為預設付款條件的功能跟建立，像是完工單內單據用語
# 這樣的選項」。
#
# 形狀：`system_settings.quote_terms_presets = {presets: [...], defaultKey: "..."}`
# 每一組 = {key, name, paymentTerms, deliveryTerms, acceptanceTerms,
#           warrantyTerms, afterSales}
#
# **報價單存的是文字不是 key**（前端切換時把五段文字複製進 data_json）：
# 已經開出去的報價單長什麼樣就是什麼樣，不能因為有人事後改了條款組內容
# 或把那組刪掉，就讓歷史單據的條款跟著變。這跟同日做的「單據原始版本存檔」
# 是同一個判準。`termsPresetKey` 只當「這張單是從哪一組起手的」的線索，
# 用來做「與該組不同」的比對提示，不是資料來源。
#
# 讀取端點**不限 superadmin**——報價人要用它切換；寫入才限 superadmin。

_TERMS_FIELDS = ("paymentTerms", "deliveryTerms", "acceptanceTerms",
                 "warrantyTerms", "afterSales")


class QuoteTermsPreset(BaseModel):
    key:             str = ""
    name:            str
    paymentTerms:    str = ""
    deliveryTerms:   str = ""
    acceptanceTerms: str = ""
    warrantyTerms:   str = ""
    afterSales:      str = ""


class QuoteTermsPresetsBody(BaseModel):
    presets:    List[QuoteTermsPreset]
    defaultKey: str = ""


def _quote_terms_presets() -> dict:
    """目前設定；沒設定過時回傳空清單（前端會退回它內建的 DEFAULT_TERMS）。

    **不在這裡自動種一組預設**：前端 `quotation-form.html` 本來就有一份
    `DEFAULT_TERMS` 當作「沒有任何設定時」的內容，後端再種一份就變成兩個
    事實來源，而且兩邊一旦分岔沒有任何地方會報錯。沒設定＝維持改動前的行為。
    """
    raw = _get_setting("quote_terms_presets", {}) or {}
    if not isinstance(raw, dict):
        return {"presets": [], "defaultKey": ""}
    presets = raw.get("presets")
    if not isinstance(presets, list):
        presets = []
    return {"presets": presets, "defaultKey": raw.get("defaultKey") or ""}


@router.get("/api/settings/quote-terms-presets")
def get_quote_terms_presets(authorization: str = Header(None)):
    """報價人要靠它切換條款組，所以只要求登入（內容不是機密，是公司對外條款）。"""
    _require_user(authorization)
    return _quote_terms_presets()


@router.put("/api/settings/quote-terms-presets")
def set_quote_terms_presets(body: QuoteTermsPresetsBody, authorization: str = Header(None)):
    """整組覆寫（建立／改名／改內容／刪除／設預設都走這一支）。

    整組覆寫而不是逐筆 CRUD：這份設定最多十來組、只有 superadmin 會動、
    而且前端本來就是把整份清單抓下來編輯。逐筆 CRUD 要多三支端點與一組
    併發處理，換不到任何東西。
    """
    actor = _require_user(authorization, require_superadmin=True)

    if len(body.presets) > 30:
        raise HTTPException(400, "條款組最多 30 組")

    seen, cleaned = set(), []
    for p in body.presets:
        name = (p.name or "").strip()
        if not name:
            raise HTTPException(400, "條款組名稱不可空白")
        if len(name) > 30:
            raise HTTPException(400, f"條款組名稱過長（{name[:10]}…），上限 30 字")
        key = (p.key or "").strip() or uuid.uuid4().hex[:8]
        if key in seen:
            raise HTTPException(400, f"條款組 key 重複：{key}")
        seen.add(key)
        item = {"key": key, "name": name}
        for f in _TERMS_FIELDS:
            v = getattr(p, f) or ""
            if len(v) > 5000:
                raise HTTPException(400, f"「{name}」的{f}內容過長（上限 5000 字）")
            item[f] = v
        cleaned.append(item)

    default_key = (body.defaultKey or "").strip()
    if default_key and default_key not in seen:
        # 刪掉了被設為預設的那一組 → 靜默落到第一組，而不是留一個指向不存在
        # 的 key（那會讓新報價單完全拿不到預設條款，而且看不出為什麼）
        default_key = ""
    if not default_key and cleaned:
        default_key = cleaned[0]["key"]

    value = {"presets": cleaned, "defaultKey": default_key}
    _set_setting("quote_terms_presets", value)
    default_name = next((p["name"] for p in cleaned if p["key"] == default_key), "（無）")
    _audit(_tok(authorization), "settings.quote_terms_presets.update", "settings",
           "quote_terms_presets",
           f"報價條款組共 {len(cleaned)} 組，預設為「{default_name}」")
    notify_module_activity("系統設定", "變更報價條款組",
                            actor.get("display_name") or actor["username"],
                            f"{len(cleaned)} 組，預設「{default_name}」",
                            "quotation-form.html")
    return value


# ── Cloud backup storage target（2026-09-07，架構地圖 §6.4）────────────────────
# 選擇備份要寫去哪裡：本機掛載的雲端硬碟磁碟機（預設，沿用 archive.py 既有邏輯，
# 已知磁碟機代號會漂移）或 S3 相容物件儲存（AWS S3／Backblaze B2 等，見
# cloud_storage.py）。**憑證一律不存這裡**——走 boto3 標準憑證鏈（環境變數／
# ~/.aws/credentials／instance profile），這裡只存 bucket/endpoint/region/prefix
# 2026-09-11 更正：這段原本寫「這類非機密設定值，無對應前端頁面（比照
# edge-path/pdf-base-path 等技術設定慣例，透過 API 直接調整）」——**那不是慣例，
# 是還沒做**。把「還沒做」寫成「慣例」之後，四支設定端點就這樣一直沒有入口，
# 直到打包新增的入口檢查（check_endpoint_entrypoints.py）把它們掃出來。
# 現在四支都有畫面了：company-profile-settings.html 的「系統技術設定」區塊
# （備份保留天數／PDF 存檔根目錄／Edge 路徑／雲端備份目標），superadmin 限定，
# e2e 見 tests/test_e2e_system_settings_ui_2026_09_11.py。

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
    Used by login.html and change-password.html to show/hide Passkey buttons.

    2026-09-16：功能總開關關閉時回 `configured:false, enabled:false`。
    這支**不回 404**——三個前端頁面都靠它決定要不要畫出 Passkey 區塊，回 200
    才能同時關掉按鈕（`configured`）與整張卡片（`enabled`）。

    停用時 `configured` 一併壓成 false 是刻意的：前端若是舊版（部署不同步、
    或瀏覽器吃到快取的 HTML），它只認得 `configured`，壓成 false 才能保證
    按鈕不會冒出來——按下去也只會拿到 404。
    """
    from helpers import auth as _auth_helpers
    if not _auth_helpers.PASSKEY_ENABLED:
        return {"configured": False, "enabled": False}
    rp_id = _get_setting("webauthn_rp_id") or ""
    origin = _get_setting("webauthn_origin") or ""
    configured = bool(rp_id.strip() and origin.strip())
    return {"configured": configured, "enabled": True}


# ── 在線成員與在線時數（2026-09-14，DB v79）─────────────────────────────────
#
# 使用者要求：「右上角可顯示在線成員跟數量，並且後台統計每個成員（含管理員、
# 最高管理者）在線上的時間，這些數據只有最高管理者看得到」。
#
# 兩支端點都限 superadmin：在線名單本身就是「誰在不在」的行蹤資訊，時數更是。
# 累加寫在 `main.py::auth_middleware`（沿用既有的 last_active 節流點），這裡只讀。

_ONLINE_WINDOW_SECONDS = 300   # 與 main.py 的 last_active 節流同步：最久 5 分鐘寫一次


@router.get("/api/online-users")
def list_online_users(authorization: str = Header(None)):
    """目前在線的成員與人數（限最高管理者）。

    「在線」＝該帳號任一 session 的 `last_active` 在 5 分鐘內。用 sessions 而不是
    另做心跳：心跳會讓每個閒置分頁固定打伺服器，而 `last_active` 本來就在更新。

    ⚠️ 時間精度的取捨：`last_active` 每 5 分鐘才寫一次（main.py 的節流），所以剛
    登入的人最慢 5 分鐘後才會出現在名單上、離開的人最多晚 5 分鐘才消失。要更即時
    就得縮短節流（每次請求都寫），那是用資料庫寫入量換秒級精度，目前不划算。
    """
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT u.id, u.username, u.display_name, u.role, "
            "       MAX(s.last_active) AS last_active, COUNT(*) AS session_count "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE u.active=1 AND s.last_active IS NOT NULL AND s.last_active != '' "
            "GROUP BY u.id ORDER BY last_active DESC"
        ).fetchall()
    finally:
        conn.close()

    now = datetime.now()
    online = []
    for r in rows:
        try:
            secs = (now - datetime.fromisoformat(r["last_active"])).total_seconds()
        except Exception:
            continue
        if secs <= _ONLINE_WINDOW_SECONDS:
            online.append({
                "userId": r["id"],
                "username": r["username"],
                "displayName": r["display_name"] or r["username"],
                "role": r["role"],
                "lastActive": r["last_active"],
                "secondsAgo": int(secs),
                "sessionCount": r["session_count"],
            })
    return {"count": len(online), "windowSeconds": _ONLINE_WINDOW_SECONDS, "users": online}


@router.get("/api/user-activity")
def user_activity_stats(start: Optional[str] = None, end: Optional[str] = None,
                        authorization: str = Header(None)):
    """每位成員的在線時數統計（限最高管理者）。

    `start`／`end` 是 `YYYY-MM-DD`（含），預設當月。回傳每人合計與逐日明細。

    **統計的是「活躍時間」不是「登入時長」**：開著分頁去開會不會被算進去（沒有
    請求就沒有累加），見 `main.py::_record_user_activity` 的說明。這一點寫在回傳
    的 `note` 欄位裡，前端直接顯示，免得有人拿它當出勤紀錄。
    """
    _require_user(authorization, require_superadmin=True)
    today = datetime.now()
    start = (start or today.strftime("%Y-%m-01"))[:10]
    end = (end or today.strftime("%Y-%m-%d"))[:10]

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT a.user_id, a.day, a.active_seconds, u.username, u.display_name, u.role "
            "FROM user_activity_daily a JOIN users u ON u.id = a.user_id "
            "WHERE a.day >= ? AND a.day <= ? "
            "ORDER BY a.day",
            (start, end),
        ).fetchall()
        # 2026-09-15：軌跡的成員篩選要能選到**每一個**使用者，所以名單走 users 表
        # 而不是上面那批有時數的人——沒有活躍時數但有操作紀錄（或這段期間請假）的
        # 人，本來就選不到，而那常常正是想查的人。停用帳號一併列出：離職前做了
        # 什麼是最需要查的。
        members = [{
            "userId": r["id"],
            "username": r["username"],
            "displayName": r["display_name"] or r["username"],
            "role": r["role"],
            "active": bool(r["active"]),
        } for r in conn.execute(
            "SELECT id, username, display_name, role, active FROM users "
            "ORDER BY active DESC, display_name, username"
        ).fetchall()]
    finally:
        conn.close()

    by_user = {}
    for r in rows:
        u = by_user.setdefault(r["user_id"], {
            "userId": r["user_id"],
            "username": r["username"],
            "displayName": r["display_name"] or r["username"],
            "role": r["role"],
            "totalSeconds": 0,
            "days": {},
        })
        u["totalSeconds"] += r["active_seconds"] or 0
        u["days"][r["day"]] = (u["days"].get(r["day"]) or 0) + (r["active_seconds"] or 0)

    items = sorted(by_user.values(), key=lambda x: x["totalSeconds"], reverse=True)
    return {
        "start": start,
        "end": end,
        "items": items,
        "members": members,
        "note": "統計的是有實際操作的「活躍時間」，不是分頁開著的時間；每 5 分鐘累計一次。",
    }


_METHOD_LABELS = {"GET": "檢視", "POST": "新增／執行", "PUT": "修改",
                  "PATCH": "修改", "DELETE": "刪除"}

# 同一個人、同一句說明、這個秒數內相鄰的紀錄，回傳時併成一列（帶 `repeat` 次數）。
# 寫入端從 2026-09-15 起就收斂了，這道是給**已經存在的舊資料**用的：軌跡保留 90
# 天，不併的話接下來三個月每開一張案件都還是六列一模一樣的字。
_TRAIL_MERGE_SECONDS = 60


@router.get("/api/user-activity/trail")
def user_activity_trail(user: Optional[str] = None, start: Optional[str] = None,
                        end: Optional[str] = None, limit: int = 200,
                        before_id: Optional[int] = None,
                        authorization: str = Header(None)):
    """逐條操作軌跡（限最高管理者）——誰、什麼時候、在哪一頁、做了什麼。

    2026-09-14 使用者要求「在線時數統計，同步能看使用者點了什麼看了什麼，逐條紀錄」；
    2026-09-15 追加「用更直覺的語言，而且要能篩選每個使用者」。

    參數：`user`（帳號，不給就是全部人）、`start`／`end`（`YYYY-MM-DD`，含）、
    `limit`（上限 500）、`before_id`（往前翻頁，傳上一頁最後一筆的 id）。

    每一筆的 `summary` 是一句人話（「送審出貨單 #7」），`kind` 是檢視／變更／
    刪除／簽核／匯出，`resultLabel` 把 HTTP 狀態碼翻成「成功」「沒有權限（被
    擋下）」。翻譯規則在 `trail.py`，原則是**不猜**：對不到就原樣顯示路徑。
    `path` 仍然照原樣回傳——畫面上可以開起來對照，出事時要查的是原始事實。
    """
    _require_user(authorization, require_superadmin=True)
    limit = max(1, min(int(limit or 200), 500))

    sql = ("SELECT r.id, r.at, r.method, r.path, r.page, r.status, "
           "       u.username, u.display_name, u.role "
           "FROM user_request_log r JOIN users u ON u.id = r.user_id WHERE 1=1")
    params: list = []
    if user:
        sql += " AND u.username = ?"
        params.append(user)
    if start:
        sql += " AND r.at >= ?"
        params.append(start[:10] + "T00:00:00")
    if end:
        sql += " AND r.at <= ?"
        params.append(end[:10] + "T23:59:59")
    if before_id:
        sql += " AND r.id < ?"
        params.append(int(before_id))
    sql += " ORDER BY r.id DESC LIMIT ?"
    params.append(limit)

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    # 翻頁游標取**原始**最後一筆的 id：下面會藏掉雜訊、併掉重複，顯示的列數比
    # 撈出來的少，拿併完的清單算游標會讓「載入更早的紀錄」跳過還沒看過的資料。
    next_before_id = rows[-1]["id"] if len(rows) == limit else None

    items = []
    for r in rows:
        # 寫入端（main.py）從 2026-09-15 起就不記這些了，但 90 天內的舊資料還在。
        if trail.should_skip(r["path"]):
            continue
        d = trail.describe(r["method"], r["path"])
        prev = items[-1] if items else None
        # 時間比對的基準固定是群組裡**最新**那一筆（prev["at"] 不改寫）：若改成每次
        # 跟前一筆比，每 59 秒發生一次的相同動作會一路串下去併成一列，把「這個人
        # 十分鐘內開了同一張案件十次」這件事藏起來。
        if (prev and prev["username"] == r["username"] and prev["summary"] == d["summary"]
                and _within(prev["at"], r["at"], _TRAIL_MERGE_SECONDS)):
            prev["repeat"] += 1
            continue
        items.append({
            "id": r["id"],
            "at": r["at"],
            "username": r["username"],
            "displayName": r["display_name"] or r["username"],
            "role": r["role"],
            "method": r["method"],
            "methodLabel": _METHOD_LABELS.get(r["method"], r["method"]),
            "path": r["path"],
            "summary": d["summary"],
            "kind": d["kind"],
            "kindLabel": d["kindLabel"],
            "module": d["module"],
            "label": d["module"],         # 舊欄位名，保留給既有呼叫端
            "page": r["page"],
            "pageLabel": trail.page_label(r["page"]),
            "status": r["status"],
            "resultLabel": trail.status_label(r["status"]),
            "ok": trail.status_ok(r["status"]),
            "repeat": 1,
        })
    return {
        "items": items,
        "nextBeforeId": next_before_id,
        "note": "只記人的操作：輪詢、心跳、下拉選單與欄位偏好這類頁面自動發出的請求不記；"
                "一次點擊連帶打出的多支請求算一次。",
    }


def _within(later_iso: str, earlier_iso: str, seconds: int) -> bool:
    """兩個時間戳是不是差在 `seconds` 以內（解析失敗就當成不是，寧可多列一行）。"""
    try:
        return abs((datetime.fromisoformat(later_iso)
                    - datetime.fromisoformat(earlier_iso)).total_seconds()) <= seconds
    except Exception:
        return False


# ── 同時編輯警示（2026-09-14，DB v81）───────────────────────────────────────
#
# 第一道防線（存檔時比對 updated_at 回 409）早就存在；這裡補的是「一進去就知道
# 有人在編」，讓人來得及先喊一聲，而不是打完字才發現白做。
#
# 任何登入者都可以回報與查詢——這不是敏感資料，而且**擋住查詢反而讓功能失效**：
# 看不到別人在編，就等於沒有警示。

_PRESENCE_TTL = 90          # 秒：超過沒心跳就視為離開（前端每 30 秒送一次）


class EditPresenceIn(BaseModel):
    doc_type: str
    doc_id: str


def _active_presence(conn, doc_type: str, doc_id: str, exclude_user_id: int = None):
    cutoff = (datetime.now() - timedelta(seconds=_PRESENCE_TTL)).isoformat()
    rows = conn.execute(
        "SELECT user_id, username, display_name, started_at, last_seen_at "
        "FROM edit_presence WHERE doc_type=? AND doc_id=? AND last_seen_at >= ? "
        "ORDER BY started_at",
        (doc_type, doc_id, cutoff),
    ).fetchall()
    return [{
        "userId": r["user_id"],
        "username": r["username"],
        "displayName": r["display_name"] or r["username"],
        "startedAt": r["started_at"],
        "lastSeenAt": r["last_seen_at"],
    } for r in rows if not exclude_user_id or r["user_id"] != exclude_user_id]


@router.post("/api/edit-presence")
def edit_presence_heartbeat(body: EditPresenceIn, authorization: str = Header(None)):
    """回報「我正在編這份文件」，並取回目前還有誰在編（不含自己）。

    前端每 30 秒送一次（`edit-presence.js`），超過 `_PRESENCE_TTL`(90s) 沒更新就
    視為離開——**不依賴「關頁面時要記得通知伺服器」**，那種事件在當機、斷網、
    直接關電腦時一定收不到。`DELETE` 只是讓正常離開更即時，不是正確性的依賴。
    """
    user = _require_user(authorization)
    doc_type = (body.doc_type or "").strip()[:40]
    doc_id = (body.doc_id or "").strip()[:80]
    if not doc_type or not doc_id:
        raise HTTPException(400, "缺少 doc_type / doc_id")

    now = datetime.now().isoformat()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO edit_presence (doc_type, doc_id, user_id, username, display_name, "
            "started_at, last_seen_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(doc_type, doc_id, user_id) DO UPDATE SET last_seen_at=excluded.last_seen_at",
            (doc_type, doc_id, user["id"], user["username"],
             user["display_name"] or user["username"], now, now),
        )
        conn.commit()
        others = _active_presence(conn, doc_type, doc_id, exclude_user_id=user["id"])
    finally:
        conn.close()
    return {"docType": doc_type, "docId": doc_id, "others": others, "ttlSeconds": _PRESENCE_TTL}


@router.delete("/api/edit-presence")
def edit_presence_release(body: EditPresenceIn, authorization: str = Header(None)):
    """離開編輯畫面時主動釋放（讓其他人更快看到警示消失）。"""
    user = _require_user(authorization)
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM edit_presence WHERE doc_type=? AND doc_id=? AND user_id=?",
            ((body.doc_type or "").strip()[:40], (body.doc_id or "").strip()[:80], user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}
