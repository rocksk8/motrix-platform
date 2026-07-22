"""業務開發 CRM — 前期案件追蹤 + 開發記錄 (pre-quotation)."""
import json
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from db import get_db
from helpers import _require_user, _tok, _audit, notify_module_activity

router = APIRouter()

_STATUS_OPTIONS = ["洽談中", "成案", "未成案"]
_TW_NOW = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Pydantic models ──────────────────────────────────────────────────────────

class DevCaseIn(BaseModel):
    case_name: str
    customer_name: Optional[str] = ''
    customer_id: Optional[int] = None
    status: Optional[str] = '洽談中'
    sales_persons: Optional[List[int]] = []
    planners: Optional[List[int]] = []


class DevCaseStatusIn(BaseModel):
    status: str


class DevCaseConvertIn(BaseModel):
    quote_no: str


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
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if q:
            clauses.append("(case_name LIKE ? OR customer_name LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
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
        row = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
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
        row = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not _can_access_case(user, row):
            raise HTTPException(403, "無權限修改此案件")
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


@router.delete("/dev-cases/{case_id}", status_code=204)
def delete_dev_case(case_id: int, authorization: str = Header("")):
    user = _require_dev(authorization)
    if not _is_admin(user):
        raise HTTPException(403, "僅管理員可刪除案件")
    conn = get_db()
    try:
        row = conn.execute("SELECT case_name FROM dev_cases WHERE id=?", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        conn.execute("DELETE FROM dev_cases WHERE id=?", (case_id,))
        conn.commit()
        _audit(_tok(authorization), "dev_case.delete", "dev_case",
               str(case_id), row["case_name"])
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
        row = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
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
        row = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not _can_access_case(user, row):
            raise HTTPException(403, "無權限修改此案件")
        conn.execute(
            "UPDATE dev_cases SET converted_quote_no=?, status='成案', updated_at=? WHERE id=?",
            (body.quote_no.strip(), now, case_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
        _audit(_tok(authorization), "dev_case.convert", "dev_case",
               str(case_id), f"{row['case_name']} → {body.quote_no}")
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
        case_row_chk = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
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
        notify_module_activity(
            "業務開發", "新增拜訪記錄",
            user.get("display_name") or user["username"],
            f"{case_name_str}：{(body.content or '')[:40]}",
            "dev-crm.html",
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
        return _log_row(updated, _user_map(conn))
    finally:
        conn.close()
