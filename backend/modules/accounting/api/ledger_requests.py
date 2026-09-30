# -*- coding: utf-8 -*-
"""總帳申請 API（會計規定 C 類）：結帳／重開期間／年度決算／期初批次建立，一般財務人員送申請、最高管理者核准後自動執行。

- 直接動作端點（`/periods/{id}/close` 等）：最高管理者 ⇒ 直接執行；其他人（cashier／finance）⇒ 產生申請並回 `pending`（HTTP 200）。
- 讀＝cashier／finance（一般人只看到自己的申請，最高管理者看全部）；核准／退回＝最高管理者；撤回＝申請人。
- 待我簽核（`approval.queue_items`，type＝`ledger_action`）由 `queue_items()` 提供；核准／退回端點與傳票同形狀（`/approve`、`/send-back`）。
- 通知信：送審 ⇒ 全部在職最高管理者；核准／退回 ⇒ 申請人。寄信失敗不影響動作。
"""
import logging

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _audit, _require_user, _tok, require_any_module
from modules.accounting import notify as _notify
from modules.accounting.ledger import requests as _req

router = APIRouter(prefix="/api/ledger/action-requests", tags=["ledger"])
_log = logging.getLogger(__name__)

_READ = ("cashier", "finance")
_SUPER = "superadmin"


def _is_super(user):
    return (user or {}).get("role") == _SUPER


def _require_read(authorization):
    user = _require_user(authorization)
    require_any_module(user, _READ, "總帳")
    return user


def _require_super(authorization, what):
    user = _require_user(authorization)
    if not _is_super(user):
        raise HTTPException(403, "只有最高管理者（會計主管）可以%s。" % what)
    return user


def _mail(fn, *args):
    try:
        fn(*args)
    except Exception:  # noqa: BLE001  附帶動作
        _log.exception("總帳申請通知信失敗（不影響動作）")


def _supers(conn):
    return [r["username"] for r in conn.execute("SELECT username FROM users WHERE role='superadmin' AND active=1")]


def _http(exc):
    return HTTPException(409 if isinstance(exc, _req.RequestConflict) else 400, str(exc))


def submit(user, action, params, authorization):
    """非最高管理者的直接動作端點呼叫：建立申請並回應（呼叫端直接 return 這個結果）。"""
    conn = get_db()
    try:
        try:
            row = _req.create(conn, user, action, params)
        except _req.RequestError as exc:
            conn.rollback()
            raise _http(exc)
        conn.commit()
        supers = _supers(conn)
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.request.create", "gl_action_requests", row["request_no"], "送出總帳申請：%s" % row["label"])
    _mail(_notify.notify_ledger_action_submitted, row["request_no"], row["label"], row["requested_by_display"], supers)
    return {"ok": True, "pending": True, "request_no": row["request_no"], "request_id": row["id"],
            "message": "已送出申請 %s（%s），待最高管理者（會計主管）核准後自動執行。" % (row["request_no"], row["label"])}


@router.get("")
def list_requests(status: str = None, authorization: str = Header(None)):
    user = _require_read(authorization)
    conn = get_db()
    try:
        return {"requests": _req.list_requests(conn, None if _is_super(user) else user["username"], status or None),
                "is_superadmin": _is_super(user)}
    finally:
        conn.close()


@router.get("/{request_id}")
def get_request(request_id: int, authorization: str = Header(None)):
    user = _require_read(authorization)
    conn = get_db()
    try:
        row = _req.get(conn, request_id)
    finally:
        conn.close()
    if not row or not (_is_super(user) or row["requested_by"] == user["username"]):
        raise HTTPException(404, "找不到這張申請。")
    return row


@router.post("/{request_id}/approve")
def approve(request_id: int, authorization: str = Header(None)):
    user = _require_super(authorization, "核准總帳申請")
    conn = get_db()
    try:
        try:
            row = _req.approve(conn, request_id, user)
        except _req.RequestError as exc:
            conn.rollback()
            raise _http(exc)
        except Exception as exc:  # noqa: BLE001  服務層的資料庫錯誤（例如觸發器）⇒ 說明原因，申請維持待核准
            conn.rollback()
            raise HTTPException(409, "執行失敗，申請仍待核准：%s" % exc)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.request.approve", "gl_action_requests", row["request_no"], "核准並執行總帳申請：%s" % row["label"])
    _mail(_notify.notify_ledger_action_approved, row["request_no"], row["label"], user["username"], row["requested_by"])
    return {"ok": True, "status": "已核准", "allDone": True, "request": row}


@router.post("/{request_id}/send-back")
def send_back(request_id: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_super(authorization, "退回總帳申請")
    note = str((body or {}).get("reason") or (body or {}).get("note") or "")
    conn = get_db()
    try:
        try:
            row = _req.send_back(conn, request_id, user, note)
        except _req.RequestError as exc:
            conn.rollback()
            raise _http(exc)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.request.return", "gl_action_requests", row["request_no"], "退回總帳申請：%s（%s）" % (row["label"], row["decision_note"]))
    _mail(_notify.notify_ledger_action_returned, row["request_no"], row["label"], row["decision_note"], row["requested_by"])
    return {"ok": True, "status": "已退回", "request": row}


@router.post("/{request_id}/withdraw")
def withdraw(request_id: int, authorization: str = Header(None)):
    user = _require_read(authorization)
    conn = get_db()
    try:
        try:
            row = _req.withdraw(conn, request_id, user)
        except _req.RequestError as exc:
            conn.rollback()
            raise _http(exc)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.request.withdraw", "gl_action_requests", row["request_no"], "撤回總帳申請：%s" % row["label"])
    return {"ok": True, "request": row}


def queue_items(conn) -> list:
    """`approval.queue_items`：待核准的總帳申請（`type`＝`ledger_action`）。簽核層＝單層、全部在職最高管理者。"""
    from helpers import approval_queue as _aq
    supers = [{"username": r["username"], "displayName": r["display_name"] or r["username"], "status": "pending"}
              for r in conn.execute("SELECT username, display_name FROM users WHERE role='superadmin' AND active=1 ORDER BY id")]
    out = []
    for r in conn.execute("SELECT id, request_no, label, approval_json FROM gl_action_requests WHERE status='待審核' ORDER BY id DESC LIMIT 500"):
        raw = _aq.approval_raw_of(r["approval_json"], "ledger_action", r["request_no"])       # 壞一筆只跳過那一筆（QJ-M1）
        if raw is None:
            continue
        f = _aq.tier_fields(raw)
        # 簽核層＝目前所有在職最高管理者（單層、系統規定）：新加入的最高管理者也看得到，不吃建立當下的名單
        f.update({"tiers": [{"order": 0, "approvers": supers, "system": True}], "currentTier": 0, "tierCount": 1, "currentApprovers": supers})
        out.append(_aq.base_item("ledger_action", r["request_no"], f, customer="", projectName=r["label"], requestId=r["id"]))
    return out
