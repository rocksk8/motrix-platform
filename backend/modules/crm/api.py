"""M02 業務開發 CRM — 前期案件追蹤 + 開發記錄 (pre-quotation)。

2026-09-26 自 `routers/dev_crm.py` 搬入（PLAYBOOK §B）。只 import core／helpers／db（L1）。
"""
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, date
from typing import Any, Optional, List

from fastapi import APIRouter, File, Form, HTTPException, Header, Path, UploadFile
from pydantic import BaseModel, Field, ConfigDict

from db import get_db, spawn_bg_thread
from helpers import row_access
from helpers import perm as _perm
from helpers import email_notify as _en            # LINE 專屬事件（僅 LINE／細項）走 `_en._line_event`
import threading
from helpers import (
    _require_user, _tok, _audit, notify_module_activity, notify_dev_case_delete_request,
    notify_dev_case_relink_request, notify_dev_case_assigned, notify_dev_case_reply_overdue, notify_dev_log_directive,
    _notify, _get_setting, _set_setting, notify_dev_case_stale, _purge_notifications,
    push_event_for_dev_case_converted, push_event_for_dev_case_stale, push_event_for_module,
)

router = APIRouter(prefix="/api")          # 原本由 main.py 以 prefix="/api" 掛載
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
    # 介紹人（2026-09-30；自由文字、選填）。型別用 Any 由 `_clean_referrer` 自己驗：型別不對／太長回 400（不是 422）
    referrer: Optional[Any] = ''
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


class DevCaseAssignIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    assigned_to: Optional[int] = Field(None, alias="assignedTo")
    reply_deadline: Optional[str] = Field(None, alias="replyDeadline")


class DevCaseProgressIn(BaseModel):
    content: str = ""


class DirectiveTargetIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: int = Field(..., alias="userId", ge=1, le=2**31 - 1)
    must_reply: bool = Field(True, alias="mustReply")


class DevLogDirectiveIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    log_id: int = Field(..., alias="logId", ge=1, le=2**31 - 1)
    content: str = ""
    targets: List[DirectiveTargetIn] = []


class DevLogDirectiveReplyIn(BaseModel):
    content: str = ""


class DevLogIn(BaseModel):
    log_date: str
    log_by: int
    channel: Optional[str] = ''
    content: Optional[str] = ''
    next_action: Optional[str] = ''
    status_snapshot: Optional[str] = ''



import helpers.uploads as _uploads_mod
from helpers.uploads import save_document_files, files_txn, remove_json_item, purge_document_files
from core.txn import begin_write


# ── Permission helpers ────────────────────────────────────────────────────────

def _require_dev(authorization: str) -> dict:
    user = _require_user(authorization)
    mods = json.loads(user.get("modules") or "[]")
    if user["role"] not in ("superadmin", "admin") and "dev_crm" not in mods:
        raise HTTPException(403, "無業務開發模組權限")
    return user


def _is_admin(user: dict) -> bool:
    return user["role"] in ("superadmin", "admin")


# ── M02 業務開發案可見性：登錄到 L1 row_access（DEPENDENCY-MAP §0-5）─────────────
# 取代原 `_can_access_case()`：admin+ 直通，否則須為建立者、sales_persons／planners 之一、
# 或被指派人（assigned_to，crm v2 2026-11-03）。使用者裁示：被指派人取得與業務／企劃
# 同等完整權限，不是只讀＋回報進度——故用 owner_id_col（單值相等）而非另開一條窄權限路徑，
# 這樣 list/get/update/status/convert/relink/logs 全部既有的 row_access 呼叫點自動套用，不用逐一改。
# 成員欄位壞 JSON 視為空（沿用原行為）；dashboard／search／item_reads 經 row_access 查詢，
# 不再 import 本檔。沒登錄時 row_access 一律 fail closed。
DEV_CASE_ACCESS = row_access.OwnerRule(
    owner_id_col="assigned_to",
    creator_col="created_by",
    id_list_cols=("sales_persons", "planners"),
    lenient_json=True,
    deny_message="無權限存取此業務開發案",
)
row_access.register("dev_case", DEV_CASE_ACCESS)


class _DevLogPathAccess:
    """`uploads.path_access`（IP-104，2026-09-30 P0）：`dev_logs/<業務開發案 id>/<檔名>`（開發記錄附件）
    ⇒ 同 `GET /dev-cases/{case_id}/logs`：`_require_dev` 的模組規則（admin+ 或 dev_crm）＋ row_access `dev_case`。"""
    FOLDERS = ("dev_logs",)

    @staticmethod
    def readable(conn, folder, rest, user):
        if len(rest) != 2 or not rest[0].isdigit():
            return False
        mods = json.loads(user.get("modules") or "[]")
        if user.get("role") not in ("superadmin", "admin") and "dev_crm" not in mods:
            return False
        row = conn.execute("SELECT * FROM dev_cases WHERE id=?", (int(rest[0]),)).fetchone()
        return bool(row) and row_access.visible("dev_case", user, row)


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


def _case_people_usernames(conn, row) -> list:
    """案件相關人的帳號（LINE 細項事件的預設收件人）＝業務＋企劃＋被指派人＋建立者（只取啟用中的帳號）。
    與停滯提醒、`row_access` 的「這個案件誰有權限」同一組人；管理員不在內（要收的話在設定頁「另加指定人員」）。"""
    ids = []
    for col in ("sales_persons", "planners"):
        try:
            ids += [int(i) for i in json.loads(row[col] or "[]")]
        except Exception:
            pass
    keys = row.keys()
    for col in ("assigned_to", "created_by"):
        if col in keys and row[col]:
            ids.append(row[col])
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    rs = conn.execute("SELECT username FROM users WHERE active=1 AND id IN (%s)" % ",".join("?" * len(ids)), ids).fetchall()
    return [r["username"] for r in rs]


REFERRER_MAX = 60


def _clean_referrer(v) -> str:
    """介紹人：None／缺 ⇒ 空字串；必須是字串（否則 400）；去頭尾空白後最多 60 字（超過 400，不截斷：使用者要知道沒存進去）。"""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise HTTPException(400, "介紹人必須是文字")
    v = v.strip()
    if len(v) > REFERRER_MAX:
        raise HTTPException(400, "介紹人最多 %d 個字（目前 %d 字）" % (REFERRER_MAX, len(v)))
    return v


def _like_esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _case_row(row, umap: dict, extras: dict = None) -> dict:
    extras = extras or {}
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
        "referrer": (row["referrer"] if "referrer" in row.keys() else "") or "",
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
        "assignedToId": row["assigned_to"] if "assigned_to" in row.keys() else None,
        "assignedToName": (umap.get(row["assigned_to"], str(row["assigned_to"]))
                            if ("assigned_to" in row.keys() and row["assigned_to"]) else None),
        "replyDeadline": (row["reply_deadline"] if "reply_deadline" in row.keys() else None) or None,
        # crm v3（2026-11-04）：進度回報改成歷史表 dev_case_progress，不再回傳舊的單欄 progressReport
        "assignedAt": (row["assigned_at"] if "assigned_at" in row.keys() else None) or None,
        "assignedById": (row["assigned_by"] if "assigned_by" in row.keys() else None) or None,
        "assignedByName": (umap.get(row["assigned_by"], str(row["assigned_by"]))
                           if ("assigned_by" in row.keys() and row["assigned_by"]) else None),
        "currentProgress": extras.get("currentProgress"),        # 目前被指派人自指派後寫的最新一筆；沒有＝None（新負責人尚未回報）
        "progressCount": extras.get("progressCount", 0),         # 歷史總筆數（含前任）
        "overdueDays": extras.get("overdueDays"),                # 洽談中、期限已過、被指派人自指派後沒回報 ⇒ 逾期天數；否則 None
    }


def _progress_out(r, umap: dict) -> dict:
    aid = r["author_id"]
    return {
        "id": r["id"],
        "caseId": r["case_id"],
        "authorId": aid,
        "authorName": (umap.get(aid, str(aid)) if aid else ""),
        "legacy": aid is None,                                   # 舊資料搬來、當時沒有被指派人：畫面顯示「（舊資料）」
        "content": r["content"],
        "createdAt": r["created_at"],
    }


def _progress_extras(conn, rows, umap: dict) -> dict:
    """{case_id: {currentProgress, progressCount, overdueDays}}。一次查完整份清單，不逐案查（列表頁有幾百筆）。
    「目前進度」＝目前被指派人、`created_at >= assigned_at` 的最新一筆（與逾期判斷同一個條件：換人後新負責人沒寫過 ⇒ None）。
    進度表讀不到（舊庫、migration 未完成）⇒ 回空，案件清單不能因此 500。"""
    ids = [r["id"] for r in rows]
    cnt, cur = {}, {}
    try:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(f"SELECT case_id, COUNT(*) AS n FROM dev_case_progress WHERE case_id IN ({ph}) GROUP BY case_id", chunk).fetchall():
                cnt[r["case_id"]] = r["n"]
            for r in conn.execute(
                f"SELECT p.* FROM dev_case_progress p JOIN dev_cases d ON d.id = p.case_id AND p.author_id = d.assigned_to "
                f"WHERE p.case_id IN ({ph}) AND p.created_at >= COALESCE(d.assigned_at, '') "
                f"AND p.id = (SELECT MAX(p2.id) FROM dev_case_progress p2 WHERE p2.case_id = p.case_id "
                f"AND p2.author_id = d.assigned_to AND p2.created_at >= COALESCE(d.assigned_at, ''))", chunk).fetchall():
                cur[r["case_id"]] = r
    except Exception as exc:                                     # noqa: BLE001
        _logger.warning("_progress_extras failed: %s", exc)
        return {}
    today = date.today()
    out = {}
    for r in rows:
        keys = r.keys()
        c = cur.get(r["id"])
        overdue = None
        dl = (r["reply_deadline"] if "reply_deadline" in keys else None) or None
        if c is None and dl and r["status"] == "洽談中" and ("assigned_to" in keys and r["assigned_to"]):
            try:
                d = date.fromisoformat(dl)
            except ValueError:
                d = None
            if d is not None and d < today:
                overdue = (today - d).days
        out[r["id"]] = {"currentProgress": _progress_out(c, umap) if c is not None else None,
                        "progressCount": cnt.get(r["id"], 0), "overdueDays": overdue}
    return out


def _case_out(conn, row, umap: dict = None) -> dict:
    """單筆案件回傳（含目前進度與逾期天數）。"""
    umap = umap if umap is not None else _user_map(conn)
    return _case_row(row, umap, _progress_extras(conn, [row], umap).get(row["id"]))


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
        "files": _log_files(row),
    }


def _log_files(row) -> list:
    """dev_logs.files_json（DB v82）。舊列沒有這個欄位值時回空陣列——
    sqlite3.Row 對不存在的欄位會 raise IndexError，所以用 keys() 先判斷，
    這樣 migration 還沒跑到的環境也不會整支端點噴錯。"""
    try:
        if "files_json" not in row.keys():
            return []
        return json.loads(row["files_json"] or "[]")
    except Exception:
        return []


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
            clauses.append("(case_name LIKE ? ESCAPE '\\' OR customer_name LIKE ? ESCAPE '\\' OR referrer LIKE ? ESCAPE '\\')")
            like = f"%{_like_esc(q)}%"
            params += [like, like, like]
        where = "WHERE " + " AND ".join(clauses)
        rows = conn.execute(
            f"SELECT * FROM dev_cases {where} ORDER BY updated_at DESC",
            params,
        ).fetchall()
        if not _is_admin(user):
            rows = [r for r in rows if row_access.visible("dev_case", user, r)]
        extras = _progress_extras(conn, rows, umap)
        return [_case_row(r, umap, extras.get(r["id"])) for r in rows]
    finally:
        conn.close()


@router.post("/dev-cases", status_code=201)
def create_dev_case(body: DevCaseIn, authorization: str = Header("")):
    user = _require_dev(authorization)
    referrer = _clean_referrer(body.referrer)
    now = _TW_NOW()
    conn = get_db()
    try:
        cur = conn.execute("""
            INSERT INTO dev_cases
              (case_name, customer_name, customer_id, status,
               sales_persons, planners, converted_quote_no, created_by, created_at, updated_at, referrer)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
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
            referrer,
        ))
        conn.commit()
        row = conn.execute("SELECT * FROM dev_cases WHERE id=?", (cur.lastrowid,)).fetchone()
        umap = _user_map(conn)
        _audit(_tok(authorization), "dev_case.create", "dev_case",
               str(cur.lastrowid), body.case_name.strip(), {"referrer": referrer} if referrer else None)
        notify_module_activity(
            "業務開發", "新增案件",
            user.get("display_name") or user["username"],
            body.case_name.strip(), "dev-crm.html",
            line_event="crm_case_created", line_usernames=_case_people_usernames(conn, row), line_exclude=[user["username"]],
        )
        return _case_out(conn, row, umap)
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
        if not row_access.visible("dev_case", user, row):
            raise HTTPException(403, "無權限查看此案件")
        return _case_out(conn, row)
    finally:
        conn.close()


@router.put("/dev-cases/{case_id}")
def update_dev_case(case_id: int, body: DevCaseIn, authorization: str = Header("")):
    user = _require_dev(authorization)
    referrer = _clean_referrer(body.referrer)
    now = _TW_NOW()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not row_access.visible("dev_case", user, row):
            raise HTTPException(403, "無權限修改此案件")
        # 樂觀鎖：業務開發案件可能有多位業務/企劃同時有編輯權（見 §3.4 sales_persons/
        # planners），沒有鎖的話兩人同時存檔會後寫覆蓋前寫且完全沒有提示
        if body.expected_updated_at and row["updated_at"] and body.expected_updated_at != row["updated_at"]:
            raise HTTPException(409, "案件資料已被其他人更新，請重新載入後再存")
        conn.execute("""
            UPDATE dev_cases
               SET case_name=?, customer_name=?, customer_id=?,
                   status=?, sales_persons=?, planners=?, updated_at=?, referrer=?
             WHERE id=?
        """, (
            body.case_name.strip(),
            (body.customer_name or "").strip(),
            body.customer_id,
            body.status or row["status"],
            json.dumps(body.sales_persons or []),
            json.dumps(body.planners or []),
            now,
            referrer,
            case_id,
        ))
        conn.commit()
        updated = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
        old_ref = (row["referrer"] if "referrer" in row.keys() else "") or ""
        _audit(_tok(authorization), "dev_case.update", "dev_case",
               str(case_id), body.case_name.strip(),
               {"referrer": {"from": old_ref, "to": referrer}} if old_ref != referrer else None)
        return _case_out(conn, updated)
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
        if not row_access.visible("dev_case", user, row):
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
                                row["case_name"], "dev-crm.html",
                                line_event="crm_case_status", line_usernames=_case_people_usernames(conn, updated), line_exclude=[user["username"]])
        return _case_out(conn, updated)
    finally:
        conn.close()


@router.patch("/dev-cases/{case_id}/assign")
def assign_dev_case(case_id: int, body: DevCaseAssignIn, authorization: str = Header("")):
    """管理員指派業務開發案件給成員，並可設定回覆期限（crm v2，2026-11-03）。
    被指派人經 DEV_CASE_ACCESS 的 owner_id_col="assigned_to" 取得與業務／企劃同等的完整權限
    （使用者裁示；見本檔 DEV_CASE_ACCESS 旁的說明），不是另一條窄權限路徑。

    crm v3（2026-11-04）：存檔前先跟舊值比對，**只有真的變才動作**——
    - 對象與期限都沒變 ⇒ 不寫 DB、不稽核、不通知、updated_at 不動（重按一次儲存鍵沒有任何副作用）；
    - 換人（含首次指派、取消指派）⇒ 更新 assigned_at／assigned_by；新負責人站內＋信，前任站內「不再負責」；
    - 只改期限（對象不變）⇒ 只發站內通知給被指派人，不寄信；
    - 期限早於今天 ⇒ 400（不能一指派就逾期）：期限這次有被改動，或這次換了人（即使沿用原期限）都檢查；同人同期限原封不動重存＝no-op，不擋；
    - 取消指派 ⇒ 回覆期限一併清空。"""
    user = _require_dev(authorization)
    if not _is_admin(user):
        raise HTTPException(403, "僅管理員可指派業務開發案件")
    now = _TW_NOW()
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        keys = row.keys()
        old_to = row["assigned_to"] if "assigned_to" in keys else None
        old_dl = (row["reply_deadline"] if "reply_deadline" in keys else None) or None
        new_to = body.assigned_to
        new_dl = (body.reply_deadline or "").strip() or None
        if new_to is None:
            new_dl = None                                                 # 取消指派（或本來就沒人）⇒ 期限一併清空：沒有負責人就沒有回覆期限
        if new_to == old_to and new_dl == old_dl:
            return _case_out(conn, row)                                   # 沒有任何變動
        if new_dl is not None and (new_dl != old_dl or new_to != old_to):      # 期限有改，或換人（含首次指派）沿用過期期限：都不能一指派就逾期
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", new_dl):        # fromisoformat 在 3.11+ 也收 20261201：存進去會讓字串比較的逾期判斷錯位
                    raise ValueError(new_dl)
                d = date.fromisoformat(new_dl)
            except ValueError:
                raise HTTPException(400, "回覆期限格式錯誤（須為 YYYY-MM-DD）")
            if d < date.today():
                raise HTTPException(400, "回覆期限不可早於今天")
        assignee_changed = new_to != old_to
        assignee = None
        if new_to is not None:
            assignee = conn.execute(
                "SELECT id, username, display_name, role, modules, active FROM users WHERE id=?", (new_to,)
            ).fetchone()
            if assignee_changed:                                          # 對象沒換就不重驗（對象之後被停用，只改期限仍可存）
                if not assignee or not assignee["active"]:
                    raise HTTPException(400, "指派對象不存在或已停用")
                if assignee["role"] not in ("superadmin", "admin") and "dev_crm" not in json.loads(assignee["modules"] or "[]"):
                    raise HTTPException(400, "指派對象沒有業務開發模組權限")
        old_user = None
        if assignee_changed and old_to is not None:
            old_user = conn.execute("SELECT username, display_name FROM users WHERE id=?", (old_to,)).fetchone()
        if assignee_changed:
            conn.execute(
                "UPDATE dev_cases SET assigned_to=?, reply_deadline=?, assigned_at=?, assigned_by=?, updated_at=? WHERE id=?",
                (new_to, new_dl, now if new_to is not None else None, user["id"] if new_to is not None else None, now, case_id),
            )
        else:
            conn.execute("UPDATE dev_cases SET reply_deadline=?, updated_at=? WHERE id=?", (new_dl, now, case_id))
        conn.commit()
        updated = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
        umap = _user_map(conn)
        actor_display = user.get("display_name") or user["username"]
        if assignee_changed:
            _audit(_tok(authorization), "dev_case.assign", "dev_case", str(case_id),
                   f"{row['case_name']} → {umap.get(new_to, '') if new_to else '（取消指派）'}",
                   {"from": old_to, "to": new_to, "replyDeadline": new_dl})
        else:
            _audit(_tok(authorization), "dev_case.assign", "dev_case", str(case_id),
                   f"{row['case_name']} 回覆期限 {old_dl or '未設定'} → {new_dl or '未設定'}",
                   {"from": old_dl, "to": new_dl})
        if assignee_changed and assignee:
            assignee_display = assignee["display_name"] or assignee["username"]
            _notify(assignee["username"], "dev_case_assigned", str(case_id), row["case_name"],
                    f"{actor_display} 將業務開發案件「{row['case_name']}」指派給您"
                    + (f"，回覆期限 {new_dl}" if new_dl else "") + "。",
                    link="dev-crm.html")
            spawn_bg_thread(
                notify_dev_case_assigned,
                args=(case_id, row["case_name"], new_dl, assignee["username"],
                      assignee_display, actor_display),
            )
        if assignee_changed and old_user:                                 # 前任失去存取卻不知情（T73 稽核 S5）：站內通知，不寄信（LINE：僅 LINE 事件 `dev_case_unassigned`）
            _notify(old_user["username"], "dev_case_unassigned", str(case_id), row["case_name"],
                    f"{actor_display} 已將業務開發案件「{row['case_name']}」"
                    + (f"改指派給 {umap.get(new_to, '他人')}" if new_to else "取消指派") + "，您不再負責此案件。",
                    link="dev-crm.html")
            _en._line_event("dev_case_unassigned", usernames=[old_user["username"]], exclude=[user["username"]],
                            title="業務開發案件已不由您負責", rows=[("案件名稱", row["case_name"]), ("操作人", actor_display)],
                            reason=("已改指派給 %s" % umap.get(new_to, "他人")) if new_to else "已取消指派")
        if not assignee_changed and assignee:                             # 只改期限：站內，不寄信（LINE：僅 LINE 事件 `dev_case_deadline_changed`）
            _notify(assignee["username"], "dev_case_deadline_changed", str(case_id), row["case_name"],
                    f"{actor_display} 將業務開發案件「{row['case_name']}」的回覆期限"
                    + (f"改為 {new_dl}" if new_dl else "清除（目前未設定）") + "。",
                    link="dev-crm.html")
            _en._line_event("dev_case_deadline_changed", usernames=[assignee["username"]], exclude=[user["username"]],
                            title="業務開發案件回覆期限已調整", rows=[("案件名稱", row["case_name"]), ("新的回覆期限", new_dl or "已清除"), ("操作人", actor_display)],
                            reason="請依新的期限回覆")
        # 指派／調整期限的 LINE 已由 dev_case_assigned／dev_case_unassigned／dev_case_deadline_changed 負責 ⇒ 泛用的 module_activity 不再重複推（line_skip）
        notify_module_activity("業務開發", "指派案件" if assignee_changed else "調整回覆期限", actor_display,
                               row["case_name"], "dev-crm.html", line_skip=True)
        return _case_out(conn, updated, umap)
    finally:
        conn.close()


PROGRESS_MAX = 4000


@router.get("/dev-cases/{case_id}/progress")
def list_dev_case_progress(case_id: int, authorization: str = Header("")):
    """進度回報歷史（新到舊）。看得到這個案件的人都看得到（含管理員）；每筆自帶作者與時間，換人後前任寫的也留著。"""
    user = _require_dev(authorization)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        if not row_access.visible("dev_case", user, row):
            raise HTTPException(403, "無權限查看此案件")
        umap = _user_map(conn)
        rows = conn.execute("SELECT * FROM dev_case_progress WHERE case_id=? ORDER BY id DESC", (case_id,)).fetchall()
        return [_progress_out(r, umap) for r in rows]
    finally:
        conn.close()


@router.post("/dev-cases/{case_id}/progress", status_code=201)
def add_dev_case_progress(case_id: int, body: DevCaseProgressIn, authorization: str = Header("")):
    """新增一筆進度回報（crm v3，2026-11-04；取代 v2 的 PATCH 整段覆寫）。**只有目前被指派人本人可以新增；不是被指派人的管理員（含 superadmin）403**
    （使用者已確認：管理員唯讀；管理員若「本人就是」被指派人，他是現任負責人，可以寫——主持裁示 2026-11-04）。只增不改不刪：寫錯就再新增一筆更正。比對 assigned_to 本人，不走 row_access（row_access 給的是完整存取，
    業務／企劃不等於被指派回報進度的人）。"""
    user = _require_dev(authorization)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)).fetchone()
        if not row:
            raise HTTPException(404, "案件不存在")
        assigned_to = row["assigned_to"] if "assigned_to" in row.keys() else None
        if assigned_to is None or user["id"] != assigned_to:
            raise HTTPException(403, "僅目前被指派人可新增進度回報")
        content = (body.content or "").strip()
        if not content:
            raise HTTPException(400, "進度內容不可空白")
        if len(content) > PROGRESS_MAX:
            raise HTTPException(400, "進度內容最多 %d 個字（目前 %d 字）" % (PROGRESS_MAX, len(content)))
        now = _TW_NOW()
        cur = conn.execute(
            "INSERT INTO dev_case_progress (case_id, author_id, content, created_at) VALUES (?,?,?,?)",      # 單位欄用預設值（寫入點屬 U1，同 dev_logs）
            (case_id, user["id"], content, now),
        )
        conn.execute("UPDATE dev_cases SET updated_at=? WHERE id=?", (now, case_id))        # 算真活動：重置 30 天停滯計時
        conn.commit()
        entry = conn.execute("SELECT * FROM dev_case_progress WHERE id=?", (cur.lastrowid,)).fetchone()
        updated = conn.execute("SELECT * FROM dev_cases WHERE id=?", (case_id,)).fetchone()
        umap = _user_map(conn)
        label = content[:40] + ("…" if len(content) > 40 else "")                          # 稽核標籤只放摘要，全文在進度表
        _audit(_tok(authorization), "dev_case.progress", "dev_case", str(case_id), label,
               {"progressId": cur.lastrowid, "length": len(content)})
        notify_module_activity("業務開發", "更新進度回報", user.get("display_name") or user["username"],
                                row["case_name"], "dev-crm.html", detail=content,
                                line_event="crm_case_progress", line_usernames=_case_people_usernames(conn, updated), line_exclude=[user["username"]])
        return {"entry": _progress_out(entry, umap), "case": _case_out(conn, updated, umap)}
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
        if not row_access.visible("dev_case", user, row):
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
                                f"{row['case_name']} → {quote_no}", "dev-crm.html",
                                line_event="crm_case_converted", line_usernames=_case_people_usernames(conn, updated), line_exclude=[user["username"]])
        spawn_bg_thread(push_event_for_dev_case_converted, args=(case_id,))
        return _case_out(conn, updated)
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
            return _case_out(conn, updated)
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
            return _case_out(conn, updated)
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
    通路拆解。僅計入已核准（needs_approval=0）的開發記錄；權限比照 row_access 的 dev_case
    （非 admin 僅計入自己建立或被列為業務/規劃人員的案件）。"""
    user = _require_dev(authorization)
    conn = get_db()
    try:
        case_rows = conn.execute(
            "SELECT id, sales_persons, planners, created_by, assigned_to, case_name, customer_name FROM dev_cases WHERE is_deleted=0"
        ).fetchall()
        visible_ids = [r["id"] for r in case_rows if row_access.visible("dev_case", user, r)]
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
        if not row_access.visible("dev_case", user, case_row):
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
async def create_dev_log(case_id: int,
                         log_date: str = Form(...),
                         log_by: int = Form(...),
                         channel: str = Form(""),
                         content: str = Form(""),
                         next_action: str = Form(""),
                         status_snapshot: str = Form(""),
                         files: list[UploadFile] = File(default=[]),
                         authorization: str = Header("")):
    """新增開發記錄（2026-09-14 起可附照片／檔案）。

    **改成 multipart 而不是另開補傳端點**（使用者裁示）：一次請求送出，不會出現
    「記錄存了、檔案失敗」的半完成狀態。原本的 DevLogIn pydantic model 仍留著
    給其他呼叫端用，這一支改讀 Form 欄位——欄位名與型別跟原本的 JSON body
    一字不差，前端只是改用 FormData 送。

    照片會壓上「上傳者 · 日期時間 · GPS」浮水印（使用者裁示），PDF 不動。
    """
    user = _require_dev(authorization)
    body = DevLogIn(log_date=log_date, log_by=log_by, channel=channel,
                    content=content, next_action=next_action,
                    status_snapshot=status_snapshot)
    now = _TW_NOW()
    conn = get_db()
    try:
        case_row_chk = conn.execute(
            "SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)
        ).fetchone()
        if not case_row_chk:
            raise HTTPException(404, "案件不存在")
        if not row_access.visible("dev_case", user, case_row_chk):
            raise HTTPException(403, "無權限在此案件新增記錄")
        needs_approval = 1 if body.log_by != user["id"] else 0
        saved_files = []
        if files:
            # 存檔在 INSERT 之前：格式/大小不合就整批擋下，不會留下一筆
            # 沒有附件的記錄讓使用者以為傳成功
            saved_files = await save_document_files(
                "dev_logs", str(case_id), files,
                user.get("display_name") or user["username"],
                watermark_by=user.get("display_name") or user["username"],
            )
        with files_txn(conn, saved_files):      # T84：寫庫失敗／案件在上傳途中被刪 ⇒ 回收剛存的檔
            if not conn.execute("SELECT 1 FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)).fetchone():
                raise HTTPException(404, "案件不存在")
            cur = conn.execute("""
                INSERT INTO dev_logs
                  (case_id, log_date, log_by, channel, content, next_action,
                   status_snapshot, needs_approval, created_by, created_at, files_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                case_id, body.log_date, body.log_by,
                body.channel or "", body.content or "",
                body.next_action or "", body.status_snapshot or "",
                needs_approval, user["id"], now,
                json.dumps(saved_files, ensure_ascii=False),
            ))
            conn.execute("UPDATE dev_cases SET updated_at=? WHERE id=?", (now, case_id))
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
            line_event="crm_visit_logged", line_usernames=_case_people_usernames(conn, case_row_chk), line_exclude=[user["username"]],
        )
        _sync_customer_visit(conn, case_id, cur.lastrowid, "upsert", body.dict())
        # 行事曆「業務開發案件更新」（2026-09-30，預設關；開關在 L1 判斷）：同一案件同一天合併成一個事件
        spawn_bg_thread(push_event_for_module, args=_dev_update_calendar_args(
            case_id, case_name_str, case_row_chk["customer_name"],
            user.get("display_name") or user["username"], body.log_date, _detail_lines, now))
        return _log_row(row, _user_map(conn))
    finally:
        conn.close()


def _dev_update_calendar_args(case_id, case_name, customer_name, author, log_date, detail_lines, at):
    """行事曆「業務開發案件更新」事件的內容（push_event_for_module 的參數）：標題「○○案件更新」，
    說明＝這一筆開發紀錄；merge_key＝案件 id ⇒ 同一天的紀錄累加在同一個事件的說明裡。"""
    head = f"[{(at or '')[11:16]}] {author}（紀錄日期 {log_date or ''}）"
    desc = head + ("\n" + "\n".join(detail_lines) if detail_lines else "")
    title = f"{case_name}案件更新" + (f"（{customer_name}）" if customer_name else "")
    return ("dev_case_update", title, desc, (at or "")[:10] or None, f"dev{case_id}")


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
        begin_write(conn)                               # T86：讀（含附件清單）與 DELETE 在同一把寫鎖裡——鎖外讀的清單可能漏掉剛補上的附件 ⇒ 留孤兒檔
        row = conn.execute("SELECT * FROM dev_logs WHERE id=?", (log_id,)).fetchone()
        if not row:
            raise HTTPException(404, "記錄不存在")
        if row["created_by"] != user["id"] and not _is_admin(user):
            raise HTTPException(403, "僅能刪除自己建立的記錄")
        # 已有批示的紀錄不可刪（crm v4，docs/platform/plans/DEV-LOG-DIRECTIVE-PLAN.md §5）：硬刪附件後批示會懸空。
        # 「沒有批示才刪」是單一陳述（SQLite 單寫者 ⇒ 與同時新增批示的 INSERT…WHERE EXISTS 不會交錯）。
        # 訊息刻意不提「批示」：批示限作者／對象／管理員可見，被擋的建立者可能看不到它。
        del_sql = "DELETE FROM dev_logs WHERE id=?"
        try:
            deleted = conn.execute(
                del_sql + " AND NOT EXISTS (SELECT 1 FROM dev_log_directive WHERE log_id=?)", (log_id, log_id)).rowcount
        except sqlite3.OperationalError as e:
            if not _no_such_table(e):                   # 鎖定等其他原因不能退回「沒有守門的 DELETE」（複核 M3）
                conn.rollback()
                raise HTTPException(503, "資料庫忙碌中，請稍後再試")
            deleted = conn.execute(del_sql, (log_id,)).rowcount      # 批示表不存在（舊庫、migration 未完成）⇒ 當作沒有批示
        if deleted == 0:
            conn.rollback()
            raise HTTPException(409, "此開發記錄已有後續處理紀錄，不可刪除")
        # 記錄刪掉，附件也要從磁碟清掉——否則 uploads/ 會留下沒人引用的孤兒檔案，
        # 而 archive.py::_mirror_uploads() 只增不減，會一路跟著進雲端備份
        # T86：**commit 之後**才刪實體檔（原本在 commit 之前刪：commit 失敗＝紀錄還在、檔案沒了）；路徑經 canonical_upload_path 驗證
        conn.commit()
        purge_document_files(_log_files(row))
        _audit(_tok(authorization), "dev_log.delete", "dev_log", str(log_id), "")
        _sync_customer_visit(conn, row["case_id"], log_id, "delete")
        case_row = conn.execute("SELECT case_name FROM dev_cases WHERE id=?", (row["case_id"],)).fetchone()
        notify_module_activity("業務開發", "刪除開發記錄", user.get("display_name") or user["username"],
                                case_row["case_name"] if case_row else str(row["case_id"]), "dev-crm.html")
    finally:
        conn.close()


@router.delete("/dev-logs/{log_id}/files/{file_id}")
def delete_dev_log_file(log_id: int, file_id: str, authorization: str = Header("")):
    """刪除開發記錄的單一附件——**限 admin 以上**（2026-09-14 使用者裁示）。

    跟「刪整筆記錄」的權限刻意不同：整筆記錄建立者自己就能刪（撤回自己寫的
    東西），但單獨抽掉一張附件是**只改證據、留下文字**。這在業務開發這一頁
    特別要緊——代填的記錄要經 admin 審核（needs_approval），審核過了還能讓
    原建立者悄悄換掉附件的話，那道審核就沒有意義了。
    """
    user = _require_dev(authorization)
    if not _is_admin(user):
        raise HTTPException(403, "僅管理員以上可刪除附件")
    conn = get_db()
    try:
        if not conn.execute("SELECT 1 FROM dev_logs WHERE id=?", (log_id,)).fetchone():
            raise HTTPException(404, "記錄不存在")
        # T86：寫鎖內重讀 files_json、濾掉、commit，commit 之後才刪實體檔（寫庫失敗＝紀錄與檔都還在；並發的補附件不會被整包覆寫）
        remaining = remove_json_item(conn, "dev_logs", "files_json", "id", log_id, file_id, not_found="記錄不存在")
        _audit(_tok(authorization), "dev_log.delete_file", "dev_log", str(log_id), "")
        return {"ok": True, "files": remaining}
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
        _case_full = conn.execute("SELECT * FROM dev_cases WHERE id=?", (row["case_id"],)).fetchone()
        notify_module_activity("業務開發", "審核通過開發記錄", user.get("display_name") or user["username"],
                                case_row["case_name"] if case_row else str(row["case_id"]), "dev-crm.html",
                                line_event="crm_log_approved", line_usernames=_case_people_usernames(conn, _case_full) if _case_full else [],
                                line_exclude=[user["username"]])
        return _log_row(updated, _user_map(conn))
    finally:
        conn.close()


# ── 開發記錄「批示」（crm v4，2026-11-04；docs/platform/plans/DEV-LOG-DIRECTIVE-PLAN.md） ──────────────
# 管理員（或被勾了 crm.dev_log_directive.comment 的人）對某筆開發記錄下批示，通知指定的成員、可指定誰要回覆。
# 與「進度回報」方向相反（進度＝被指派人自己回報；批示＝上對下指示）。批示與回覆只增不改不刪；
# 不碰 dev_logs（不連動客戶拜訪／行事曆／接洽統計）、不重置 dev_cases.updated_at（那是 30 天停滯警報的依據）、
# 不呼叫 notify_module_activity（它帶全文寄全體 admin，與限縮可見度矛盾）。

DIRECTIVE_CAP = "crm.dev_log_directive.comment"
DIRECTIVE_MAX = 4000
DIRECTIVE_TARGETS_MAX = 10


def _no_such_table(e: Exception) -> bool:
    """只有「表不存在」（舊庫、migration 未完成）才算可以退回舊行為；鎖定、I/O 錯誤等一律不算。"""
    return "no such table" in str(e).lower()


def _directive_names(conn, ids) -> dict:
    """{user_id: 顯示名}。含已停用帳號（歷史批示的作者／對象之後可能離職，不能顯示成數字）。"""
    ids = sorted({i for i in ids if i is not None})
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT id, display_name, username FROM users WHERE id IN (%s)" % ",".join("?" * len(ids)), ids
    ).fetchall()
    return {r["id"]: (r["display_name"] or r["username"]) for r in rows}


def _directive_items(conn, user: dict, case_id: int, only_root: Optional[int] = None) -> list:
    """這個人看得到的批示（連同回覆與對象）；前端依 log_id 分組。
    可見度（使用者裁示）：**管理員、批示作者、被列為對象的人**；其他人連「有這筆批示」都看不到（整列不回）。
    表不存在（舊庫、migration 未完成）⇒ 回空，不能讓案件頁 500。"""
    try:
        drows = conn.execute("SELECT * FROM dev_log_directive WHERE case_id=? ORDER BY id", (case_id,)).fetchall()
        trows = conn.execute(
            "SELECT t.* FROM dev_log_directive_target t JOIN dev_log_directive d ON d.id = t.directive_id "
            "WHERE d.case_id=? ORDER BY t.id", (case_id,)).fetchall()
    except sqlite3.OperationalError as e:
        if _no_such_table(e):
            return []
        raise HTTPException(503, "資料庫忙碌中，請稍後再試")          # 鎖定等其他原因：不能回空清單讓畫面誤以為沒有批示（複核 M3）
    uid, admin = user["id"], _is_admin(user)
    targets = {}
    for t in trows:
        targets.setdefault(t["directive_id"], []).append(t)
    replies = {}
    for r in drows:
        if r["parent_id"] is not None:
            replies.setdefault(r["parent_id"], []).append(r)
    roots = []
    for r in drows:
        if r["parent_id"] is not None or (only_root is not None and r["id"] != only_root):
            continue
        is_target = any(t["user_id"] == uid for t in targets.get(r["id"], []))
        if admin or r["author_id"] == uid or is_target:
            roots.append((r, is_target))
    ids = set()
    for r, _ in roots:
        ids.add(r["author_id"])
        ids.update(t["user_id"] for t in targets.get(r["id"], []))
        ids.update(x["author_id"] for x in replies.get(r["id"], []))
    names = _directive_names(conn, ids)
    out = []
    for r, is_target in roots:
        ts = targets.get(r["id"], [])
        reps = replies.get(r["id"], [])
        out.append({
            "id": r["id"], "caseId": r["case_id"], "logId": r["log_id"],
            "authorId": r["author_id"], "authorName": names.get(r["author_id"], str(r["author_id"])),
            "content": r["content"], "createdAt": r["created_at"],
            "targets": [{"userId": t["user_id"], "name": names.get(t["user_id"], str(t["user_id"])),
                         "mustReply": bool(t["must_reply"]), "repliedAt": t["replied_at"]} for t in ts],
            "pendingReplyNames": [names.get(t["user_id"], str(t["user_id"])) for t in ts
                                  if t["must_reply"] and not t["replied_at"]],
            "replies": [{"id": x["id"], "authorId": x["author_id"],
                         "authorName": names.get(x["author_id"], str(x["author_id"])),
                         "content": x["content"], "createdAt": x["created_at"]} for x in reps],
            "lastActivityAt": max([r["created_at"]] + [x["created_at"] for x in reps]),
            "canReply": r["author_id"] == uid or is_target,
        })
    return out


def _directive_case(conn, user: dict, case_id: int):
    row = conn.execute("SELECT * FROM dev_cases WHERE id=? AND is_deleted=0", (case_id,)).fetchone()
    if not row:
        raise HTTPException(404, "案件不存在")
    if not row_access.visible("dev_case", user, row):
        raise HTTPException(403, "無權限查看此案件")
    return row


def _directive_text(body_content: str) -> str:
    content = (body_content or "").strip()
    if not content:
        raise HTTPException(400, "內容不可空白")
    if len(content) > DIRECTIVE_MAX:
        raise HTTPException(400, "內容最多 %d 個字（目前 %d 字）" % (DIRECTIVE_MAX, len(content)))
    return content


def _snippet(text: str, n: int = 40) -> str:
    text = " ".join((text or "").split())
    return text[:n] + ("…" if len(text) > n else "")


@router.get("/dev-cases/{case_id}/directives")
def list_dev_log_directives(case_id: int = Path(..., ge=1, le=2**31 - 1), authorization: str = Header("")):
    """整案的批示（含回覆與對象），**只回這個人看得到的**（管理員／作者／對象）；`canDirect`＝這個人能不能下批示（前端據此顯示「批示」鈕）。"""
    user = _require_dev(authorization)
    conn = get_db()
    try:
        _directive_case(conn, user, case_id)
        return {"canDirect": _perm.can(user, DIRECTIVE_CAP), "items": _directive_items(conn, user, case_id)}
    finally:
        conn.close()


@router.post("/dev-cases/{case_id}/directives", status_code=201)
def add_dev_log_directive(body: DevLogDirectiveIn, case_id: int = Path(..., ge=1, le=2**31 - 1), authorization: str = Header("")):
    """對某筆開發記錄下批示。閘：業務開發模組 ＋ 能力 `crm.dev_log_directive.comment` ＋ 看得到此案件。
    對象 1～10 人，不含自己；每人須在職、具業務開發權限（或管理員）、看得到此案件，否則 400 並列出名字。"""
    user = _require_dev(authorization)
    _perm.require(user, DIRECTIVE_CAP)
    conn = get_db()
    try:
        case_row = _directive_case(conn, user, case_id)
        log = conn.execute("SELECT id, case_id FROM dev_logs WHERE id=?", (body.log_id,)).fetchone()
        if not log or log["case_id"] != case_id:
            raise HTTPException(400, "開發記錄不存在或不屬於此案件")
        content = _directive_text(body.content)
        want = {}
        for t in body.targets:                       # 去重；同一人重複出現時，任一筆要回覆就算要回覆
            want[t.user_id] = want.get(t.user_id, False) or bool(t.must_reply)
        if not want:
            raise HTTPException(400, "請至少指定一位通知對象")
        if len(want) > DIRECTIVE_TARGETS_MAX:
            raise HTTPException(400, "通知對象最多 %d 人" % DIRECTIVE_TARGETS_MAX)
        if user["id"] in want:
            raise HTTPException(400, "通知對象不可包含自己")
        urows = {r["id"]: r for r in conn.execute(
            "SELECT id, username, display_name, role, modules, active FROM users WHERE id IN (%s)" % ",".join("?" * len(want)),
            list(want)).fetchall()}
        bad = []
        for uid in want:
            u = urows.get(uid)
            if not u:
                bad.append("使用者#%s（不存在）" % uid)
                continue
            name = u["display_name"] or u["username"]
            if not u["active"]:
                bad.append("%s（已停用）" % name)
            elif u["role"] not in ("superadmin", "admin") and "dev_crm" not in json.loads(u["modules"] or "[]"):
                bad.append("%s（沒有業務開發模組權限）" % name)
            elif not row_access.visible("dev_case", {"id": u["id"], "role": u["role"], "modules": u["modules"],
                                                     "username": u["username"], "display_name": u["display_name"]}, case_row):
                bad.append("%s（看不到此案件）" % name)
        if bad:
            raise HTTPException(400, "以下對象無法指定：" + "、".join(bad))
        now = _TW_NOW()
        cur = conn.execute(                           # 「紀錄還在」與寫入是同一個陳述：與同時刪紀錄的 DELETE 不會交錯
            "INSERT INTO dev_log_directive (log_id, case_id, author_id, content, parent_id, created_at) "
            "SELECT ?,?,?,?,NULL,? WHERE EXISTS (SELECT 1 FROM dev_logs WHERE id=? AND case_id=?)",
            (body.log_id, case_id, user["id"], content, now, body.log_id, case_id))
        if cur.rowcount == 0:
            conn.rollback()
            raise HTTPException(400, "開發記錄不存在或不屬於此案件")
        did = cur.lastrowid
        for uid, must in want.items():
            conn.execute("INSERT INTO dev_log_directive_target (directive_id, user_id, must_reply) VALUES (?,?,?)",
                         (did, uid, 1 if must else 0))
        conn.commit()
        actor = user.get("display_name") or user["username"]
        # 稽核任何有 audit_log 模組勾選的人都讀得到：標籤與明細不放批示內容、也不放對象（複核 S1，與 §3 一致）
        _audit(_tok(authorization), "dev_log.directive", "dev_log", str(body.log_id), "批示#%d" % did,
               {"directiveId": did})
        mail_to = []
        for uid, must in want.items():
            u = urows[uid]
            _notify(u["username"], "dev_log_directive", str(did), case_row["case_name"],
                    "%s 對業務開發案件「%s」的開發記錄下了批示%s：%s"
                    % (actor, case_row["case_name"], "，請回覆" if must else "（僅知會）", _snippet(content)),
                    link="dev-crm.html")
            if must:
                mail_to.append(u["username"])
        if mail_to:                                   # 信件只寄「要回覆」的人，本文不放批示全文
            spawn_bg_thread(notify_dev_log_directive, args=(case_id, case_row["case_name"], mail_to, actor))
        info_only = [urows[uid]["username"] for uid, must in want.items() if not must]
        if info_only:                                 # LINE 也要通知「僅知會」的人（信件不寄；要回覆的人由 notify_dev_log_directive 內的 LINE 負責）；不放批示全文
            _en._line_event("dev_log_directive", usernames=info_only, title="業務開發記錄批示（僅知會）",
                            rows=[("案件名稱", case_row["case_name"]), ("批示人", actor)], reason="請登入系統查看")
        items = _directive_items(conn, user, case_id, only_root=did)
        return items[0]
    finally:
        conn.close()


@router.post("/dev-cases/{case_id}/directives/{directive_id}/replies", status_code=201)
def reply_dev_log_directive(body: DevLogDirectiveReplyIn, case_id: int = Path(..., ge=1, le=2**31 - 1),
                            directive_id: int = Path(..., ge=1, le=2**31 - 1), authorization: str = Header("")):
    """回覆批示。**只有批示作者與被列為對象的人可回**（不需要下批示的能力）；只一層，不能回覆回覆。
    對象回覆 ⇒ 記該對象首次回覆時間、通知作者；作者回覆 ⇒ 通知所有對象（皆站內通知，不寄信）。
    看不到這筆批示的人（不是管理員／作者／對象）得到 404，不洩漏它存在；管理員但不是作者／對象 ⇒ 403。"""
    user = _require_dev(authorization)
    conn = get_db()
    try:
        case_row = _directive_case(conn, user, case_id)
        root = conn.execute("SELECT * FROM dev_log_directive WHERE id=? AND case_id=?", (directive_id, case_id)).fetchone()
        if not root:
            raise HTTPException(404, "批示不存在")
        # 可見度一律以「根批示」判斷：呼叫端給的 id 是根、是回覆、還是不存在，對看不到的人都回同一個 404（複核 M2）
        head = root if root["parent_id"] is None else conn.execute(
            "SELECT id, author_id FROM dev_log_directive WHERE id=?", (root["parent_id"],)).fetchone()
        if head is None:
            raise HTTPException(404, "批示不存在")
        tgt = conn.execute("SELECT * FROM dev_log_directive_target WHERE directive_id=? AND user_id=?",
                           (head["id"], user["id"])).fetchone()
        is_author = head["author_id"] == user["id"]
        if not (is_author or tgt or _is_admin(user)):
            raise HTTPException(404, "批示不存在")
        if root["parent_id"] is not None:
            raise HTTPException(400, "不能回覆回覆（請回覆原批示）")
        if not (is_author or tgt):
            raise HTTPException(403, "僅批示作者或被指定的對象可回覆")
        content = _directive_text(body.content)
        now = _TW_NOW()
        cur = conn.execute(
            "INSERT INTO dev_log_directive (log_id, case_id, author_id, content, parent_id, created_at) VALUES (?,?,?,?,?,?)",
            (root["log_id"], case_id, user["id"], content, directive_id, now))
        if tgt and not tgt["replied_at"]:
            conn.execute("UPDATE dev_log_directive_target SET replied_at=? WHERE id=? AND replied_at IS NULL", (now, tgt["id"]))
        conn.commit()
        actor = user.get("display_name") or user["username"]
        _audit(_tok(authorization), "dev_log.directive_reply", "dev_log", str(root["log_id"]), "批示#%d 回覆" % directive_id,
               {"directiveId": directive_id, "replyId": cur.lastrowid})
        if is_author:
            to_ids = [t["user_id"] for t in conn.execute(
                "SELECT user_id FROM dev_log_directive_target WHERE directive_id=? ORDER BY id", (directive_id,)).fetchall()]
        else:
            to_ids = [root["author_id"]]
        recips = conn.execute("SELECT id, username FROM users WHERE active=1 AND id IN (%s)" % ",".join("?" * len(to_ids)),
                              to_ids).fetchall() if to_ids else []
        for u in recips:
            _notify(u["username"], "dev_log_directive_reply", str(directive_id), case_row["case_name"],
                    "%s 回覆了業務開發案件「%s」的批示：%s" % (actor, case_row["case_name"], _snippet(content)),
                    link="dev-crm.html")
        if recips:                                    # LINE：僅 LINE 事件 `dev_log_directive_reply`（信件沒有）；不放回覆內容
            _en._line_event("dev_log_directive_reply", usernames=[u["username"] for u in recips],
                            title="業務開發記錄批示有新回覆", rows=[("案件名稱", case_row["case_name"]), ("回覆人", actor)], reason="請登入系統查看回覆內容")
        return _directive_items(conn, user, case_id, only_root=directive_id)[0]
    finally:
        conn.close()


# ── Stale-case notification scheduler (洽談中 > 30 days untouched) ────────────

_STALE_DAYS = 30
_STALE_RENOTIFY_INTERVAL = 14
_HOLD_AUTO_CONVERT_DAYS = 180


def _check_dev_case_stale() -> None:
    """洽談中案件超過 30 天未更新 → 通知業務/規劃人員/被指派人 + 所有 admin/superadmin，
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
            "SELECT id, case_name, customer_name, sales_persons, planners, created_by, assigned_to, updated_at "
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
            if row["assigned_to"] in uid_map:                     # 被指派人與業務／企劃同等，一律收提醒（不只是沒人時的備援）
                usernames.append(uid_map[row["assigned_to"]])
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


def _check_dev_case_reply_overdue() -> None:
    """回覆期限已過、被指派人自指派後一筆進度都沒寫的洽談中案件 ⇒ 提醒一次（站內＋信），不重複催（crm v3，2026-11-04）。
    防重入 guard key＝案件＋期限＋被指派人：換人或改期限會重新武裝，同一組合只提醒一次。
    收件人＝被指派人＋指派人（assigned_by）；任一方停用或沒有紀錄（舊資料）⇒ 另外加上全體 admin（跟 `_check_dev_case_stale` 的退路一致）。
    期限當天不算逾期（< 今天）。"""
    today_str = date.today().strftime("%Y-%m-%d")
    conn = None
    try:
        conn = get_db()
        users = {u["id"]: u for u in conn.execute(
            "SELECT id, username, display_name, role FROM users WHERE active=1").fetchall()}
        rows = conn.execute(
            "SELECT d.id, d.case_name, d.assigned_to, d.assigned_by, d.reply_deadline FROM dev_cases d "
            "WHERE d.is_deleted=0 AND d.status='洽談中' AND d.assigned_to IS NOT NULL "
            "AND d.reply_deadline IS NOT NULL AND d.reply_deadline <> '' AND d.reply_deadline < ? "
            "AND NOT EXISTS (SELECT 1 FROM dev_case_progress p WHERE p.case_id = d.id AND p.author_id = d.assigned_to "
            "AND p.created_at >= COALESCE(d.assigned_at, ''))",
            (today_str,),
        ).fetchall()
        conn.close()
        conn = None
        admins = [u["username"] for u in users.values() if u["role"] in ("admin", "superadmin")]
        for row in rows:
            try:
                days = (date.today() - date.fromisoformat(row["reply_deadline"])).days
            except ValueError:
                continue
            guard_key = f"devcase_reply_overdue.{row['id']}.{row['reply_deadline']}.{row['assigned_to']}"
            if _get_setting(guard_key):
                continue
            _set_setting(guard_key, today_str)
            a, b = users.get(row["assigned_to"]), (users.get(row["assigned_by"]) if row["assigned_by"] else None)
            names = [u["username"] for u in (a, b) if u]
            if a is None or b is None:
                names += admins
            names = list(dict.fromkeys(names))
            if not names:
                continue
            assignee_display = (a["display_name"] or a["username"]) if a else ""
            for username in names:
                _notify(username, "dev_case_reply_overdue", str(row["id"]), row["case_name"],
                        f"案件「{row['case_name']}」的回覆期限（{row['reply_deadline']}）已過 {days} 天，被指派人尚未回報進度",
                        link="dev-crm.html")
            threading.Thread(
                target=notify_dev_case_reply_overdue,
                args=(row["id"], row["case_name"], row["reply_deadline"], days, assignee_display, names),
                daemon=True,
            ).start()
        _logger.info("Dev case reply-overdue check complete for %s (%d case(s))", today_str, len(rows))
    except Exception as exc:
        _logger.warning("_check_dev_case_reply_overdue failed: %s", exc)
    finally:
        if conn is not None:
            conn.close()


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


def unlink_deleted_quote(conn, quote_no: str) -> list:
    """IP-13 `crm.quote_deleted`（M02 → M01）：報價單被刪除 ⇒ 轉建連結指到它的業務開發案件解除連結、退回「洽談中」。

    在**呼叫方的交易內**執行、不 commit（與刪報價單同一筆交易：要嘛都成、要嘛都不成）。
    dev_cases 與 quotations 之間沒有 FK，不解除就會留下指向不存在報價單的連結。
    回傳被解除的案件 `[{"id", "case_name"}]`，稽核紀錄由呼叫方寫（它有操作者的身分）。"""
    rows = conn.execute(
        "SELECT id, case_name FROM dev_cases WHERE converted_quote_no=?", (quote_no,)
    ).fetchall()
    if rows:
        conn.execute(
            "UPDATE dev_cases SET converted_quote_no='', status='洽談中', updated_at=? "
            "WHERE converted_quote_no=?",
            (datetime.now().isoformat(), quote_no),
        )
    return [{"id": r["id"], "case_name": r["case_name"]} for r in rows]


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
        _check_dev_case_reply_overdue()
        _check_dev_case_hold_expiry()

    def _loop():
        try:
            _run_all()
        except Exception:                     # noqa: BLE001
            _logger.exception("dev_crm scheduled checks failed")
        finally:
        # 🔴 重排放在 `finally` —— 形狀照 `helpers/geo.py::schedule_geocode_warm()`。
        # ☠️ 放在工作之後而沒包 `try` 的話，**一次未捕捉的例外就讓這支排程
        #    從此不再跑，直到重開機** —— 而「排程死了」與「今天沒事做」
        #    長得一模一樣，沒有任何訊號。
            t = threading.Timer(_next_08(), _loop)
            t.daemon = True
            t.start()

    threading.Thread(target=_run_all, daemon=True).start()  # startup catch-up
    t = threading.Timer(_next_08(), _loop)
    t.daemon = True
    t.start()
