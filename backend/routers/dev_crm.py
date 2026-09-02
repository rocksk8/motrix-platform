"""業務開發 CRM — 前期案件追蹤 + 開發記錄 (pre-quotation)."""
import json
import logging
from datetime import datetime, timedelta, date
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field, ConfigDict

from db import get_db, spawn_bg_thread
import threading
from helpers import (
    _require_user, _tok, _audit, notify_module_activity, notify_dev_case_delete_request,
    notify_dev_case_relink_request,
    _notify, _get_setting, _set_setting, notify_dev_case_stale, _purge_notifications,
    push_event_for_dev_case_converted, push_event_for_dev_case_stale,
)

router = APIRouter()
_logger = logging.getLogger(__name__)

_STATUS_OPTIONS = ["洽談中", "成案", "未成案", "暫擱置"]
_TW_NOW = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Pydantic models ──────────────────────────────────────────────────────────

class DevCaseIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    case_name: str
    customer_name: Optional[str] = ''
    customer_id: Optional[int] = None
    status: Optional[str] = '洽談中'
    sales_persons: Optional[List[int]] = []
    planners: Optional[List[int]] = []
    # 樂觀鎖（選填，見 update_dev_case）——比照 customers.py/suppliers.py/
    # vendor_contractors.py 的 expectedUpdatedAt 慣例，camelCase 對外、
    # snake_case 對內
    expected_updated_at: Optional[str] = Field(None, alias="expectedUpdatedAt")


class DevCaseStatusIn(BaseModel):
    status: str


class DevCaseConvertIn(BaseModel):
    quote_no: str


class DevCaseRelinkRequestIn(BaseModel):
    # 留空＝申請解除連結（清空 converted_quote_no），非空＝申請改連結至該單號
    quote_no: Optional[str] = ''
    reason: Optional[str] = ''


class DevCaseRelinkApproveIn(BaseModel):
    approve: bool
    reject_reason: Optional[str] = ''


class DevCaseDeleteRequestIn(BaseModel):
    reason: Optional[str] = ''


class DevCaseDeleteApproveIn(BaseModel):
    approve: bool
    reject_reason: Optional[str] = ''


class DevLogIn(BaseModel):
    log_date: str
    log_by: int
    channel: Optional[str] = ''
    content: Optional[str] = ''
    next_action: Optional[str] = ''
    status_snapshot: Optional[str] = ''


# ── Permission helpers ────────────────────────────────────────────────────────

def _require_dev(authorization: str) -> dict:
    user = _require_user(authorization)
    mods = json.loads(user.get("modules") or "[]")
    if user["role"] not in ("superadmin", "admin") and "dev_crm" not in mods:
        raise HTTPException(403, "無業務開發模組權限")
    return user


def _is_admin(user: dict) -> bool:
    return user["role"] in ("superadmin", "admin")


def _can_access_case(user: dict, row) -> bool:
    """Non-admin users can only access cases they created or are assigned to."""
    if _is_admin(user):
        return True
    uid = user["id"]
    try:
        sp = json.loads(row["sales_persons"] or "[]")
    except Exception:
        sp = []
    try:
        pl = json.loads(row["planners"] or "[]")
    except Exception:
        pl = []
    return row["created_by"] == uid or uid in sp or uid in pl


# ── Customer visit sync ──────────────────────────────────────────────────────

def _sync_customer_visit(conn, case_id: int, log_id: int, action: str, log_data: dict = None):
    """Sync a dev_log to ALL linked customers' visits (data_json.visits).
    Syncs to customer_id AND to customer_name match (both, if different).
    action: 'upsert' | 'delete'
    """
    case = conn.execute(
        "SELECT customer_id, customer_name, case_name FROM dev_cases WHERE id=?", (case_id,)
    ).fetchone()
    if not case:
        return

    # Collect all customer IDs to sync (deduplicated)
    cids: set = set()
    if case["customer_id"]:
        cids.add(case["customer_id"])
    if case["customer_name"]:
        row = conn.execute(
            "SELECT id FROM customers WHERE name=?", (case["customer_name"],)
        ).fetchone()
        if row:
            cids.add(row["id"])
    if not cids:
        return

    visit_id = f"dcl_{log_id}"

    # Build the new visit entry once (shared for all target customers)
    new_v = None
    if action != "delete" and log_data:
        channel      = (log_data.get("channel") or "").strip()
        content      = (log_data.get("content") or "").strip()
        next_a       = (log_data.get("next_action") or "").strip()
        full_content = f"【{case['case_name']}】{content}"
        if next_a:
            full_content += f"\n→ 下一步：{next_a}"
        new_v = {
            "id":       visit_id,
            "date":     log_data.get("log_date", ""),
            "type":     channel if channel else "業務開發",
            "content":  full_content,
            "source":   "dev_crm",
            "devLogId": log_id,
        }

    for cid in cids:
        cust = conn.execute("SELECT data_json FROM customers WHERE id=?", (cid,)).fetchone()
        if not cust:
            continue
        try:
            d = json.loads(cust["data_json"] or "{}")
        except Exception:
            d = {}

        visits = d.get("visits", [])
        if action == "delete":
            visits = [v for v in visits if v.get("id") != visit_id]
        else:
            idx = next((i for i, v in enumerate(visits) if v.get("id") == visit_id), -1)
            if idx >= 0:
                visits[idx] = new_v
            else:
                visits.insert(0, new_v)

        d["visits"] = visits
        conn.execute(
            "UPDATE customers SET data_json=?, updated_at=? WHERE id=?",
            (json.dumps(d, ensure_ascii=False), _TW_NOW(), cid),
        )
    conn.commit()


# ── Row serializers ──────────────────────────────────────────────────────────

def _user_map(conn) -> dict:
    rows = conn.execute(
        "SELECT id, display_name, username FROM users WHERE active=1"
    ).fetchall()
    return {r["id"]: (r["display_name"] or r["username"]) for r in rows}


def _case_row(row, umap: dict) -> dict:
    try:
        sp = json.loads(row["sales_persons"] or "[]")
    except Exception:
        sp = []
    try:
        pl = json.loads(row["planners"] or "[]")
    except Exception:
        pl = []
    return {
        "id": row["id"],
        "caseName": row["case_name"],
        "customerName": row["customer_name"] or "",
        "customerId": row["customer_id"],
        "status": row["status"],
        "salesPersonIds": sp,
        "salesPersonNames": [umap.get(i, str(i)) for i in sp],
        "plannerIds": pl,
        "plannerNames": [umap.get(i, str(i)) for i in pl],
        "convertedQuoteNo": row["converted_quote_no"] or "",
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "pendingDelete": bool(row["pending_delete"] if "pending_delete" in row.keys() else 0),
        "deleteRequestedBy": row["delete_requested_by"] if "delete_requested_by" in row.keys() else "",
        "deleteRequestedAt": row["delete_requested_at"] if "delete_requested_at" in row.keys() else "",
        "deleteReason": row["delete_reason"] if "delete_reason" in row.keys() else "",
        "pendingRelink": bool(row["pending_relink"] if "pending_relink" in row.keys() else 0),
        "relinkRequestedBy": row["relink_requested_by"] if "relink_requested_by" in row.keys() else "",
        "relinkRequestedAt": row["relink_requested_at"] if "relink_requested_at" in row.keys() else "",
        "relinkReason": row["relink_reason"] if "relink_reason" in row.keys() else "",
        "relinkTargetQuoteNo": row["relink_target_quote_no"] if "relink_target_quote_no" in row.keys() else "",
    }


def _log_row(row, umap: dict) -> dict:
    return {
        "id": row["id"],
        "caseId": row["case_id"],
        "logDate": row["log_date"],
        "logById": row["log_by"],
        "logByName": umap.get(row["log_by"], str(row["log_by"])) if row["log_by"] else "",
        "channel": row["channel"] or "",
        "content": row["content"] or "",
        "nextAction": row["next_action"] or "",
        "statusSnapshot": row["status_snapshot"] or "",
        "needsApproval": bool(row["needs_approval"]),
        "approvedById": row["approved_by"],
        "approvedByName": umap.get(row["approved_by"], "") if row["approved_by"] else "",
        "approvedAt": row["approved_at"] or "",
        "createdById": row["created_by"],
        "createdByName": umap.get(row["created_by"], "") if row["created_by"] else "",
        "createdAt": row["created_at"],
    }


# ── Dev Cases ────────────────────────────────────────────────────────────────

@router.get("/dev-cases")
def list_dev_cases(
    q: str = "",
    status: str = "",
    authorization: str = Header(""),
):
    user = _require_dev(authorization)
    conn = get_db()
    try:
        umap = _user_map(conn)
        clauses, params = ["is_deleted = 0"], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if q:
            clauses.append("(case_name LIKE ? OR customer_name LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        where = "WHERE " + " AND ".join(clauses)
        rows = conn.execute(
            f"SELECT * FROM dev_cases {where} ORDER BY updated_at DESC",
            params,
        ).fetchall()
        if not _is_admin(user):
            rows = [r for r in rows if _can_access_case(user, r)]
        return [_case_row(r, umap) for r in rows]
    finally:
        conn.close()


@router.post("/dev-cases", status_code=201)
def create_dev_case(body: DevCaseIn, authorization: str = Header("")):
    user = _require_dev(authorization)
    now = _TW_NOW()
    conn = get_db()
    try:
        cur = conn.execute("""
            INSERT INTO dev_cases
              (case_name, customer_name, customer_id, status,
               sales_persons, planners, converted_quote_no, created_by, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            body.case_name.strip(),
            (body.customer_name or "").strip(),
            body.customer_id,
            body.status or "洽談中",
            json.dumps(body.sales_persons or []),
            json.dumps(body.planners or []),
            "",
            user["id"],
            now, now,
        ))
        conn.commit()
        row = conn.execute("SELECT * FROM dev_cases WHERE id=?", (cur.lastrowid,)).fetchone()
        umap = _user_map(conn)
        _audit(_tok(authorization), "dev_case.create", "dev_case",
               str(cur.lastrowid), body.case_name.strip())
        notify_module_activity(
            "業務開發", "新增案件",
            user.get("display_name") or user["username"],
            body.case_name.strip(), "dev-crm.html",
        )
        return _case_row(row, umap)
    finally:
        conn.close()


@router.get("/dev-cases/{case_id}")
def get_dev_case(case_id: int, authorization: str = Header("")):
    user = _require_dev(authorization)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not _can_access_case(user, row):
            raise HTTPException(403, "無權限查看此案件")
        return _case_row(row, _user_map(conn))
    finally:
        conn.close()


@router.put("/dev-cases/{case_id}")
def update_dev_case(case_id: int, body: DevCaseIn, authorization: str = Header("")):
    user = _require_dev(authorization)
    now = _TW_NOW()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not _can_access_case(user, row):
            raise HTTPException(403, "無權限修改此案件")
        # 樂觀鎖：業務開發案件可能有多位業務/企劃同時有編輯權（見 §3.4 sales_persons/
        # planners），沒有鎖的話兩人同時存檔會後寫覆蓋前寫且完全沒有提示
        if body.expected_updated_at and row["updated_at"] and body.expected_updated_at != row["updated_at"]:
            raise HTTPException(409, "案件資料已被其他人更新，請重新載入後再存")
        conn.execute("""
            UPDATE dev_cases
               SET case_name=?, customer_name=?, customer_id=?,
                   status=?, sales_persons=?, planners=?, updated_at=?
             WHERE id=?
        """, (
            body.case_name.strip(),
            (body.customer_name or "").strip(),
            body.customer_id,
            body.status or row["status"],
            json.dumps(body.sales_persons or []),
            json.dumps(body.planners or []),
            now,
            case_id,
        ))
        conn.commit()
        updated = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
        _audit(_tok(authorization), "dev_case.update", "dev_case",
               str(case_id), body.case_name.strip())
        return _case_row(updated, _user_map(conn))
    finally:
        conn.close()


@router.post("/dev-cases/{case_id}/request-delete", status_code=200)
def request_dev_case_delete(case_id: int, body: DevCaseDeleteRequestIn,
                            authorization: str = Header("")):
    """Admin+ 申請刪除案件 → 送交最高管理者審核。"""
    user = _require_dev(authorization)
    if not _is_admin(user):
        raise HTTPException(403, "僅管理員可申請刪除案件")
    now = _TW_NOW()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if row["pending_delete"]:
            raise HTTPException(409, "此案件已有待審核的刪除申請")
        requester_display = user.get("display_name") or user["username"]
        conn.execute(
            "UPDATE dev_cases SET pending_delete=1, delete_requested_by=?,"
            " delete_requested_at=?, delete_reason=? WHERE id=?",
            (requester_display, now, body.reason or '', case_id),
        )
        conn.commit()
        _audit(_tok(authorization), "dev_case.delete_request", "dev_case",
               str(case_id), row["case_name"])
        spawn_bg_thread(
            notify_dev_case_delete_request,
            args=(case_id, row["case_name"], requester_display, body.reason or ''),
        )
        return {"ok": True}
    finally:
        conn.close()


@router.post("/dev-cases/{case_id}/cancel-delete", status_code=200)
def cancel_dev_case_delete(case_id: int, authorization: str = Header("")):
    """管理員取消自己發出的刪除申請。"""
    user = _require_dev(authorization)
    if not _is_admin(user):
        raise HTTPException(403, "僅管理員可取消刪除申請")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not row["pending_delete"]:
            raise HTTPException(409, "此案件無待審核的刪除申請")
        requester_display = user.get("display_name") or user["username"]
        if user["role"] != "superadmin" and row["delete_requested_by"] != requester_display:
            raise HTTPException(403, "只能取消自己發出的刪除申請")
        conn.execute(
            "UPDATE dev_cases SET pending_delete=0, delete_requested_by='',"
            " delete_requested_at='', delete_reason='' WHERE id=?",
            (case_id,),
        )
        conn.commit()
        _audit(_tok(authorization), "dev_case.delete_cancel", "dev_case",
               str(case_id), row["case_name"])
        notify_module_activity("業務開發", "取消刪除申請", requester_display,
                                row["case_name"], "dev-crm.html")
        return {"ok": True}
    finally:
        conn.close()


@router.post("/dev-cases/{case_id}/approve-delete", status_code=200)
def approve_dev_case_delete(case_id: int, body: DevCaseDeleteApproveIn,
                             authorization: str = Header("")):
    """最高管理者審核刪除申請 — approve=True 執行軟刪除；False 退回。"""
    user = _require_dev(authorization)
    if user["role"] != "superadmin":
        raise HTTPException(403, "僅最高管理者可審核刪除申請")
    now = _TW_NOW()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not row["pending_delete"]:
            raise HTTPException(409, "此案件無待審核的刪除申請")
        if body.approve:
            snapshot = json.dumps(dict(row), ensure_ascii=False)
            approver_display = user.get("display_name") or user["username"]
            conn.execute(
                "UPDATE dev_cases SET is_deleted=1, deleted_at=?, deleted_by=?,"
                " deleted_snapshot=?, pending_delete=0 WHERE id=?",
                (now, approver_display, snapshot, case_id),
            )
            conn.commit()
            _purge_notifications(str(case_id), ['dev_case_stale'])
            _audit(_tok(authorization), "dev_case.delete", "dev_case",
                   str(case_id), row["case_name"])
            notify_module_activity("業務開發", "核准刪除", user.get("display_name") or user["username"],
                                    row["case_name"], "dev-crm.html")
            return {"ok": True, "deleted": True}
        else:
            conn.execute(
                "UPDATE dev_cases SET pending_delete=0, delete_requested_by='',"
                " delete_requested_at='', delete_reason='' WHERE id=?",
                (case_id,),
            )
            conn.commit()
            _audit(_tok(authorization), "dev_case.delete_reject", "dev_case",
                   str(case_id), row["case_name"])
            notify_module_activity("業務開發", "退回刪除申請", user.get("display_name") or user["username"],
                                    row["case_name"], "dev-crm.html")
            return {"ok": True, "deleted": False}
    finally:
        conn.close()


@router.patch("/dev-cases/{case_id}/status")
def update_dev_case_status(
    case_id: int, body: DevCaseStatusIn, authorization: str = Header("")
):
    user = _require_dev(authorization)
    if body.status not in _STATUS_OPTIONS:
        raise HTTPException(400, f"無效狀態：{body.status}")
    now = _TW_NOW()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not _can_access_case(user, row):
            raise HTTPException(403, "無權限修改此案件")
        conn.execute(
            "UPDATE dev_cases SET status=?, updated_at=? WHERE id=?",
            (body.status, now, case_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
        _audit(_tok(authorization), "dev_case.status", "dev_case",
               str(case_id), f"{row['case_name']} → {body.status}")
        notify_module_activity("業務開發", f"狀態變更為「{body.status}」", user.get("display_name") or user["username"],
                                row["case_name"], "dev-crm.html")
        return _case_row(updated, _user_map(conn))
    finally:
        conn.close()


@router.patch("/dev-cases/{case_id}/convert")
def mark_converted(
    case_id: int, body: DevCaseConvertIn, authorization: str = Header("")
):
    user = _require_dev(authorization)
    now = _TW_NOW()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not _can_access_case(user, row):
            raise HTTPException(403, "無權限修改此案件")
        if row["converted_quote_no"]:
            # 已有連結的報價單號，異動／清空一律走審核流程（見 request-relink-quote），
            # 避免繞過核准直接覆蓋掉已成立的連結。
            raise HTTPException(409, "此案件已連結報價單，如需異動或解除請透過「修改連結」送審")
        quote_no = body.quote_no.strip()
        # quotations 跟 dev_cases 之間沒有 FK 約束，寫入前先確認單號真的存在——
        # 否則之後這張報價單被刪掉（或單號打錯字從沒對應過任何單），
        # converted_quote_no 就是一個從一開始就沒有意義的懸空參照。
        if not conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (quote_no,)).fetchone():
            raise HTTPException(400, f"報價單 {quote_no} 不存在，無法連結")
        conn.execute(
            "UPDATE dev_cases SET converted_quote_no=?, status='成案', updated_at=? WHERE id=?",
            (quote_no, now, case_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
        _audit(_tok(authorization), "dev_case.convert", "dev_case",
               str(case_id), f"{row['case_name']} → {quote_no}")
        notify_module_activity("業務開發", "轉建報價單", user.get("display_name") or user["username"],
                                f"{row['case_name']} → {quote_no}", "dev-crm.html")
        spawn_bg_thread(push_event_for_dev_case_converted, args=(case_id,))
        return _case_row(updated, _user_map(conn))
    finally:
        conn.close()


@router.post("/dev-cases/{case_id}/request-relink-quote", status_code=200)
def request_dev_case_relink(case_id: int, body: DevCaseRelinkRequestIn,
                            authorization: str = Header("")):
    """Admin+ 申請異動（或清空）已連結的報價單號 → 送交最高管理者審核。
    quote_no 留空即申請「解除連結」——業務案件因報價單被取消等原因需要斷開關聯時使用。"""
    user = _require_dev(authorization)
    if not _is_admin(user):
        raise HTTPException(403, "僅管理員可申請異動報價單連結")
    now = _TW_NOW()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not row["converted_quote_no"]:
            raise HTTPException(400, "此案件尚未連結報價單，請使用「轉建報價單」建立連結")
        if row["pending_relink"]:
            raise HTTPException(409, "此案件已有待審核的連結異動申請")
        target = (body.quote_no or '').strip()
        if target == row["converted_quote_no"]:
            raise HTTPException(400, "新單號與目前連結相同")
        if target and not conn.execute(
            "SELECT 1 FROM quotations WHERE quote_no=?", (target,)
        ).fetchone():
            raise HTTPException(400, f"報價單 {target} 不存在，無法連結")
        requester_display = user.get("display_name") or user["username"]
        conn.execute(
            "UPDATE dev_cases SET pending_relink=1, relink_requested_by=?,"
            " relink_requested_at=?, relink_reason=?, relink_target_quote_no=? WHERE id=?",
            (requester_display, now, body.reason or '', target, case_id),
        )
        conn.commit()
        _audit(_tok(authorization), "dev_case.relink_request", "dev_case",
               str(case_id), f"{row['case_name']} → {target or '（解除連結）'}")
        spawn_bg_thread(
            notify_dev_case_relink_request,
            args=(case_id, row["case_name"], requester_display, target, body.reason or ''),
        )
        return {"ok": True}
    finally:
        conn.close()


@router.post("/dev-cases/{case_id}/cancel-relink-quote", status_code=200)
def cancel_dev_case_relink(case_id: int, authorization: str = Header("")):
    """管理員取消自己發出的連結異動申請。"""
    user = _require_dev(authorization)
    if not _is_admin(user):
        raise HTTPException(403, "僅管理員可取消連結異動申請")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not row["pending_relink"]:
            raise HTTPException(409, "此案件無待審核的連結異動申請")
        requester_display = user.get("display_name") or user["username"]
        if user["role"] != "superadmin" and row["relink_requested_by"] != requester_display:
            raise HTTPException(403, "只能取消自己發出的連結異動申請")
        conn.execute(
            "UPDATE dev_cases SET pending_relink=0, relink_requested_by='',"
            " relink_requested_at='', relink_reason='', relink_target_quote_no='' WHERE id=?",
            (case_id,),
        )
        conn.commit()
        _audit(_tok(authorization), "dev_case.relink_cancel", "dev_case",
               str(case_id), row["case_name"])
        notify_module_activity("業務開發", "取消連結異動申請", requester_display,
                                row["case_name"], "dev-crm.html")
        return {"ok": True}
    finally:
        conn.close()


@router.post("/dev-cases/{case_id}/approve-relink-quote", status_code=200)
def approve_dev_case_relink(case_id: int, body: DevCaseRelinkApproveIn,
                             authorization: str = Header("")):
    """最高管理者審核連結異動申請 — approve=True 套用新單號（或清空）；False 退回。
    清空（解除連結）核准後，案件狀態一併退回「洽談中」——報價單已不存在對應關係，
    「成案」狀態繼續掛著會誤導其他人以為案件仍有成立中的報價單。"""
    user = _require_dev(authorization)
    if user["role"] != "superadmin":
        raise HTTPException(403, "僅最高管理者可審核連結異動申請")
    now = _TW_NOW()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not row["pending_relink"]:
            raise HTTPException(409, "此案件無待審核的連結異動申請")
        if body.approve:
            target = row["relink_target_quote_no"] or ''
            if target and not conn.execute(
                "SELECT 1 FROM quotations WHERE quote_no=?", (target,)
            ).fetchone():
                raise HTTPException(400, f"報價單 {target} 已不存在，無法核准，請申請人取消或重新申請")
            new_status = "洽談中" if not target else row["status"]
            conn.execute(
                "UPDATE dev_cases SET converted_quote_no=?, status=?, pending_relink=0,"
                " relink_requested_by='', relink_requested_at='', relink_reason='',"
                " relink_target_quote_no='', updated_at=? WHERE id=?",
                (target, new_status, now, case_id),
            )
            conn.commit()
            updated = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
            _audit(_tok(authorization), "dev_case.relink_approve", "dev_case",
                   str(case_id), f"{row['case_name']} → {target or '（解除連結）'}")
            notify_module_activity("業務開發", "核准連結異動", user.get("display_name") or user["username"],
                                    row["case_name"], "dev-crm.html")
            return _case_row(updated, _user_map(conn))
        else:
            conn.execute(
                "UPDATE dev_cases SET pending_relink=0, relink_requested_by='',"
                " relink_requested_at='', relink_reason='', relink_target_quote_no='' WHERE id=?",
                (case_id,),
            )
            conn.commit()
            updated = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
            _audit(_tok(authorization), "dev_case.relink_reject", "dev_case",
                   str(case_id), row["case_name"])
            notify_module_activity("業務開發", "退回連結異動申請", user.get("display_name") or user["username"],
                                    row["case_name"], "dev-crm.html")
            return _case_row(updated, _user_map(conn))
    finally:
        conn.close()


# ── Dev Logs ─────────────────────────────────────────────────────────────────

@router.get("/dev-logs/pending")
def list_pending_logs(authorization: str = Header("")):
    user = _require_dev(authorization)
    if not _is_admin(user):
        raise HTTPException(403, "僅管理員可查看待審清單")
    conn = get_db()
    try:
        umap = _user_map(conn)
        rows = conn.execute(
            "SELECT * FROM dev_logs WHERE needs_approval=1 ORDER BY created_at DESC"
        ).fetchall()
        return [_log_row(r, umap) for r in rows]
    finally:
        conn.close()


@router.get("/dev-crm/activity-stats")
def dev_crm_activity_stats(authorization: str = Header("")):
    """跨案件每週／每日接洽成效統計：近 60 天每日筆數、近 8 週週彙總、近 30 天依廠商／
    通路拆解。僅計入已核准（needs_approval=0）的開發記錄；權限比照 _can_access_case
    （非 admin 僅計入自己建立或被列為業務/規劃人員的案件）。"""
    user = _require_dev(authorization)
    conn = get_db()
    try:
        case_rows = conn.execute(
            "SELECT id, sales_persons, planners, created_by, case_name, customer_name FROM dev_cases WHERE is_deleted=0"
        ).fetchall()
        visible_ids = [r["id"] for r in case_rows if _can_access_case(user, r)]
        if not visible_ids:
            return {"daily": [], "weekly": [], "byVendor": [], "byChannel": []}
        case_label = {r["id"]: (r["customer_name"] or r["case_name"] or "未命名案件") for r in case_rows}

        today = date.today()
        window_start = today - timedelta(days=59)  # 近 60 天（含今天）
        ph = ",".join("?" * len(visible_ids))
        rows = conn.execute(
            f"SELECT log_date, log_by, channel, case_id FROM dev_logs "
            f"WHERE needs_approval=0 AND case_id IN ({ph}) AND log_date >= ?",
            visible_ids + [window_start.isoformat()],
        ).fetchall()

        # 每日筆數（近 60 天，缺資料補 0，避免前端要另外處理稀疏陣列）
        daily_counts = {}
        for r in rows:
            d = (r["log_date"] or "")[:10]
            daily_counts[d] = daily_counts.get(d, 0) + 1
        daily = []
        for i in range(59, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            daily.append({"date": d, "count": daily_counts.get(d, 0)})

        # 每週彙總（近 8 週，週一為週起始，補 0）
        this_week_start = today - timedelta(days=today.weekday())
        weekly_counts = {}
        for item in daily:
            ws = (date.fromisoformat(item["date"]) - timedelta(
                days=date.fromisoformat(item["date"]).weekday())).isoformat()
            weekly_counts[ws] = weekly_counts.get(ws, 0) + item["count"]
        weekly = []
        for i in range(7, -1, -1):
            ws = this_week_start - timedelta(days=7 * i)
            we = ws + timedelta(days=6)
            weekly.append({
                "weekStart": ws.isoformat(),
                "label": f"{ws.month}/{ws.day}~{we.month}/{we.day}",
                "count": weekly_counts.get(ws.isoformat(), 0),
            })

        # 依廠商／通路拆解（近 30 天）
        recent_start = (today - timedelta(days=29)).isoformat()
        vendor_counts, ch_counts = {}, {}
        for r in rows:
            d = (r["log_date"] or "")[:10]
            if d < recent_start:
                continue
            label = case_label.get(r["case_id"], "未命名案件")
            vendor_counts[label] = vendor_counts.get(label, 0) + 1
            ch = r["channel"] or "未分類"
            ch_counts[ch] = ch_counts.get(ch, 0) + 1

        by_vendor = sorted(
            [{"name": name, "count": c} for name, c in vendor_counts.items()],
            key=lambda x: x["count"], reverse=True,
        )
        by_channel = sorted(
            [{"channel": ch, "count": c} for ch, c in ch_counts.items()],
            key=lambda x: x["count"], reverse=True,
        )

        return {"daily": daily, "weekly": weekly, "byVendor": by_vendor, "byChannel": by_channel}
    finally:
        conn.close()


@router.get("/dev-cases/{case_id}/logs")
def list_dev_logs(case_id: int, authorization: str = Header("")):
    user = _require_dev(authorization)
    conn = get_db()
    try:
        case_row = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
        if not case_row:
            raise HTTPException(404, "案件不存在")
        if not _can_access_case(user, case_row):
            raise HTTPException(403, "無權限查看此案件")
        umap = _user_map(conn)
        rows = conn.execute(
            "SELECT * FROM dev_logs WHERE case_id=? ORDER BY log_date DESC, id DESC",
            (case_id,),
        ).fetchall()
        return [_log_row(r, umap) for r in rows]
    finally:
        conn.close()


@router.post("/dev-cases/{case_id}/logs", status_code=201)
def create_dev_log(case_id: int, body: DevLogIn, authorization: str = Header("")):
    user = _require_dev(authorization)
    now = _TW_NOW()
    conn = get_db()
    try:
        case_row_chk = conn.execute(
            "SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)
        ).fetchone()
        if not case_row_chk:
            raise HTTPException(404, "案件不存在")
        if not _can_access_case(user, case_row_chk):
            raise HTTPException(403, "無權限在此案件新增記錄")
        needs_approval = 1 if body.log_by != user["id"] else 0
        cur = conn.execute("""
            INSERT INTO dev_logs
              (case_id, log_date, log_by, channel, content, next_action,
               status_snapshot, needs_approval, created_by, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            case_id, body.log_date, body.log_by,
            body.channel or "", body.content or "",
            body.next_action or "", body.status_snapshot or "",
            needs_approval, user["id"], now,
        ))
        conn.execute("UPDATE dev_cases SET updated_at=? WHERE id=?", (now, case_id))
        conn.commit()
        row = conn.execute("SELECT * FROM dev_logs WHERE id=?", (cur.lastrowid,)).fetchone()
        case_row = conn.execute("SELECT case_name FROM dev_cases WHERE id=?", (case_id,)).fetchone()
        case_name_str = case_row["case_name"] if case_row else str(case_id)
        _audit(_tok(authorization), "dev_log.create", "dev_log",
               str(cur.lastrowid), case_name_str)
        _detail_lines = []
        if body.channel:
            _detail_lines.append(f"聯絡管道：{body.channel}")
        if body.content:
            _detail_lines.append(body.content)
        if body.next_action:
            _detail_lines.append(f"下一步：{body.next_action}")
        notify_module_activity(
            "業務開發", "新增拜訪記錄",
            user.get("display_name") or user["username"],
            case_name_str,
            "dev-crm.html",
            detail="\n".join(_detail_lines),
        )
        _sync_customer_visit(conn, case_id, cur.lastrowid, "upsert", body.dict())
        return _log_row(row, _user_map(conn))
    finally:
        conn.close()


@router.put("/dev-logs/{log_id}")
def update_dev_log(log_id: int, body: DevLogIn, authorization: str = Header("")):
    user = _require_dev(authorization)
    now = _TW_NOW()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dev_logs WHERE id=?", (log_id,)).fetchone()
        if not row:
            raise HTTPException(404, "記錄不存在")
        if row["created_by"] != user["id"] and not _is_admin(user):
            raise HTTPException(403, "僅能修改自己建立的記錄")
        needs_approval = 1 if body.log_by != user["id"] else 0
        conn.execute("""
            UPDATE dev_logs
               SET log_date=?, log_by=?, channel=?, content=?,
                   next_action=?, status_snapshot=?, needs_approval=?
             WHERE id=?
        """, (
            body.log_date, body.log_by, body.channel or "",
            body.content or "", body.next_action or "",
            body.status_snapshot or "", needs_approval, log_id,
        ))
        conn.execute("UPDATE dev_cases SET updated_at=? WHERE id=?", (now, row["case_id"]))
        conn.commit()
        updated = conn.execute("SELECT * FROM dev_logs WHERE id=?", (log_id,)).fetchone()
        _audit(_tok(authorization), "dev_log.update", "dev_log", str(log_id), "")
        _sync_customer_visit(conn, row["case_id"], log_id, "upsert", body.dict())
        return _log_row(updated, _user_map(conn))
    finally:
        conn.close()


@router.delete("/dev-logs/{log_id}", status_code=204)
def delete_dev_log(log_id: int, authorization: str = Header("")):
    user = _require_dev(authorization)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dev_logs WHERE id=?", (log_id,)).fetchone()
        if not row:
            raise HTTPException(404, "記錄不存在")
        if row["created_by"] != user["id"] and not _is_admin(user):
            raise HTTPException(403, "僅能刪除自己建立的記錄")
        conn.execute("DELETE FROM dev_logs WHERE id=?", (log_id,))
        conn.commit()
        _audit(_tok(authorization), "dev_log.delete", "dev_log", str(log_id), "")
        _sync_customer_visit(conn, row["case_id"], log_id, "delete")
        case_row = conn.execute("SELECT case_name FROM dev_cases WHERE id=?", (row["case_id"],)).fetchone()
        notify_module_activity("業務開發", "刪除開發記錄", user.get("display_name") or user["username"],
                                case_row["case_name"] if case_row else str(row["case_id"]), "dev-crm.html")
    finally:
        conn.close()


@router.patch("/dev-logs/{log_id}/approve")
def approve_dev_log(log_id: int, authorization: str = Header("")):
    user = _require_dev(authorization)
    if not _is_admin(user):
        raise HTTPException(403, "僅管理員可審核記錄")
    now = _TW_NOW()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dev_logs WHERE id=?", (log_id,)).fetchone()
        if not row:
            raise HTTPException(404, "記錄不存在")
        conn.execute(
            "UPDATE dev_logs SET needs_approval=0, approved_by=?, approved_at=? WHERE id=?",
            (user["id"], now, log_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM dev_logs WHERE id=?", (log_id,)).fetchone()
        _audit(_tok(authorization), "dev_log.approve", "dev_log", str(log_id), "")
        case_row = conn.execute("SELECT case_name FROM dev_cases WHERE id=?", (row["case_id"],)).fetchone()
        notify_module_activity("業務開發", "審核通過開發記錄", user.get("display_name") or user["username"],
                                case_row["case_name"] if case_row else str(row["case_id"]), "dev-crm.html")
        return _log_row(updated, _user_map(conn))
    finally:
        conn.close()


# ── Stale-case notification scheduler (洽談中 > 30 days untouched) ────────────

_STALE_DAYS = 30
_STALE_RENOTIFY_INTERVAL = 14
_HOLD_AUTO_CONVERT_DAYS = 180


def _check_dev_case_stale() -> None:
    """洽談中案件超過 30 天未更新 → 通知業務/規劃人員 + 所有 admin/superadmin，
    之後每 14 天重複提醒直到案件狀態改變或有新開發記錄（重置 updated_at）。"""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    try:
        conn = get_db()
        users = conn.execute(
            "SELECT id, username, role FROM users WHERE active=1"
        ).fetchall()
        uid_map = {u["id"]: u["username"] for u in users}
        admin_usernames = [u["username"] for u in users if u["role"] in ("admin", "superadmin")]
        rows = conn.execute(
            "SELECT id, case_name, customer_name, sales_persons, planners, created_by, updated_at "
            "FROM dev_cases WHERE is_deleted=0 AND status='洽談中'"
        ).fetchall()
        conn.close()

        for row in rows:
            try:
                updated = datetime.strptime(row["updated_at"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            days = (now - updated).days
            if days < _STALE_DAYS:
                continue
            bucket = (days - _STALE_DAYS) // _STALE_RENOTIFY_INTERVAL
            # updated_at 併入 guard key，讓案件重新更新後再次逾期時，
            # 能取得全新的 key 空間，不會因 bucket 數字重複而永久漏發通知
            guard_key = f"devcase_stale.{row['id']}.{row['updated_at']}.{bucket}"
            if _get_setting(guard_key):
                continue
            _set_setting(guard_key, today_str)

            try:
                sp = json.loads(row["sales_persons"] or "[]")
            except Exception:
                sp = []
            try:
                pl = json.loads(row["planners"] or "[]")
            except Exception:
                pl = []
            usernames = [uid_map[uid] for uid in (sp + pl) if uid in uid_map]
            if not usernames and row["created_by"] in uid_map:
                usernames = [uid_map[row["created_by"]]]
            all_usernames = list(dict.fromkeys(usernames + admin_usernames))

            for username in all_usernames:
                _notify(username, "dev_case_stale", str(row["id"]), row["case_name"],
                        f"案件「{row['case_name']}」洽談中已 {days} 天未更新，請確認跟進進度")

            threading.Thread(
                target=notify_dev_case_stale,
                args=(row["id"], row["case_name"], row["customer_name"] or "", days, all_usernames),
                daemon=True,
            ).start()

            # 行事曆推送用獨立於上面 email 的 guard key（不帶 bucket 編號）：
            # 只在這次停滯週期第一次跨過 30 天時建一次，跟 email 每 14 天重複的
            # 頻率脫鉤，避免同一案件在行事曆上疊出好幾個重複事件（2026-08-21g，
            # 使用者明確要求「只建一次」）。
            cal_guard_key = f"devcase_stale_cal.{row['id']}.{row['updated_at']}"
            if not _get_setting(cal_guard_key):
                _set_setting(cal_guard_key, today_str)
                threading.Thread(
                    target=push_event_for_dev_case_stale,
                    args=(row["id"], row["case_name"], row["customer_name"] or "", days),
                    daemon=True,
                ).start()
        _logger.info("Dev case stale check complete for %s", today_str)
    except Exception as exc:
        _logger.warning("_check_dev_case_stale failed: %s", exc)


def _check_dev_case_hold_expiry() -> None:
    """暫擱置案件超過 180 天未更新 → 自動轉為未成案，避免案件無限期卡在暫擱置、
    篩選與統計持續失真。系統排程動作，不發 email、不站內通知（跟人工手動變更
    狀態不同——這裡沒有一個負責的操作者可歸因，通知也不會有人回應跟進），
    僅寫入 audit_log 供事後追查。"""
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    cutoff = (now - timedelta(days=_HOLD_AUTO_CONVERT_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    conn = None
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT id, case_name FROM dev_cases "
            "WHERE is_deleted=0 AND status='暫擱置' AND updated_at <= ?",
            (cutoff,),
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE dev_cases SET status='未成案', updated_at=? WHERE id=?",
                (now_str, row["id"]),
            )
            conn.execute(
                "INSERT INTO audit_log "
                "(at,username,display_name,action,target_type,target_id,target_label,detail) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (now.isoformat(), "system", "系統自動", "dev_case.status", "dev_case",
                 str(row["id"]), f"{row['case_name']} → 未成案",
                 json.dumps(
                     {"reason": f"暫擱置逾{_HOLD_AUTO_CONVERT_DAYS}天未更新，自動轉為未成案"},
                     ensure_ascii=False,
                 )),
            )
        conn.commit()
        if rows:
            _logger.info("Dev case hold-expiry auto-converted %d case(s)", len(rows))
    except Exception as exc:
        _logger.warning("_check_dev_case_hold_expiry failed: %s", exc)
    finally:
        if conn is not None:
            conn.close()


def schedule_dev_case_stale_check() -> None:
    """啟動時呼叫一次。啟動立即補跑一次，之後每天 08:00 重跑，
    比照 daily_tasks.schedule_overdue_check() 的排程寫法。
    排程觸發、不掛在任何 request 上的背景工作，依 §3.5 例外規則直接用
    threading.Thread／get_db()，不使用 spawn_bg_thread()。"""

    def _next_08() -> float:
        cur = datetime.now()
        t08 = cur.replace(hour=8, minute=0, second=0, microsecond=0)
        if t08 <= cur:
            t08 += timedelta(days=1)
        return (t08 - cur).total_seconds()

    def _run_all():
        _check_dev_case_stale()
        _check_dev_case_hold_expiry()

    def _loop():
        _run_all()
        t = threading.Timer(_next_08(), _loop)
        t.daemon = True
        t.start()

    threading.Thread(target=_run_all, daemon=True).start()  # startup catch-up
    t = threading.Timer(_next_08(), _loop)
    t.daemon = True
    t.start()
