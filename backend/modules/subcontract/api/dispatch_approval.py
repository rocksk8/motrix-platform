# -*- coding: utf-8 -*-
"""派發審核（31-A）：第一段「派發審核」的送審／核准／退回／撤回。分層簽核重用 `helpers/tiered_approval.py`（與額外支出同一套）。

引擎以 `Stage` 描述欄位名，第二段（完工審核）用同一套邏輯，只換欄位與狀態副作用。
簽核狀態（approval_status）與作業狀態（status）分開；本檔只動前者，作業狀態仍只由 `dispatch_flow.set_status` 寫。"""
import json
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from core.txn import begin_write
from helpers import (_require_user, _tok, _audit, _notify, require_any_module,
                     active_tiers as _active_tiers, current_tier_idx as _current_tier_idx,
                     setting_to_active_tiers as _setting_to_active_tiers,
                     check_approve_permission, check_reject_permission, check_no_tier_self_approval,
                     UnresolvedManagerError, resolve_active_flow_setting,
                     APPROVAL_DOC_TYPES, register_doc_type)
from helpers.tiered_approval import cascade_self_tiers, sign_first_pending
from modules.subcontract import dispatch_flow as _flow

DOC_TYPE = "contractor_dispatch"
if DOC_TYPE not in APPROVAL_DOC_TYPES:                     # 重複 import（測試重載）不重登
    register_doc_type(DOC_TYPE, "承攬商派發", unified=True)

router = APIRouter()


class Stage:
    """一段審核用到的欄位與文字。"""
    def __init__(self, *, key, status_col, json_col, by_col, at_col, done_col, label, audit_prefix, notify_type):
        self.key, self.status_col, self.json_col = key, status_col, json_col
        self.by_col, self.at_col, self.done_col = by_col, at_col, done_col
        self.label, self.audit_prefix, self.notify_type = label, audit_prefix, notify_type


STAGE1 = Stage(key="dispatch", status_col="approval_status", json_col="approval_json", by_col="submitted_by",
               at_col="submitted_at", done_col="approved_at", label="派發", audit_prefix="vendor.dispatch",
               notify_type="dispatch_approval_request")


def _jdict(s):
    try:
        v = json.loads(s or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def _load(conn, did):
    row = conn.execute("SELECT * FROM contractor_dispatches WHERE id=?", (did,)).fetchone()
    if not row:
        raise HTTPException(404, "派發紀錄不存在")
    return row


def _subject(conn, row):
    if row["vendor_id"]:
        v = conn.execute("SELECT name FROM vendor_contractors WHERE id=?", (row["vendor_id"],)).fetchone()
        if v and v["name"]:
            return v["name"]
    return "外包人員（點工）"


def _label(conn, row):
    return "%s %s" % (row["doc_code"] or ("#%s" % row["id"]), _subject(conn, row))      # 通知文字不放金額


def _audit_detail(row, **extra):
    return {"docCode": row["doc_code"] or "", **extra}


def _approvers(tier):
    return [a["username"] for a in (tier.get("approvers") or []) if a.get("username")]


def _require_dispatch_user(authorization):
    user = _require_user(authorization)
    require_any_module(user, ("procurement", "case_manage", "contractor_list"), "承攬商管理")
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    return user


def _now():
    return datetime.now().isoformat(timespec="seconds")


def do_submit(did, user, authorization, st: Stage, *, allowed_from, extra_check=None, on_auto_approved=None):
    """送審：解析流程 → 沒設層直接核准，否則進第一層。回傳 dict。"""
    conn = get_db()
    try:
        begin_write(conn)
        row = _load(conn, did)
        cur = row[st.status_col] or ""
        if cur not in allowed_from:
            raise HTTPException(409, "目前審核狀態「%s」不可送審" % (cur or "舊單"))
        if row["status"] == "cancelled":
            raise HTTPException(409, "已取消的派發不可送審")
        if extra_check:
            extra_check(row)
        if not row["vendor_id"] and not (row["personnel_json"] or "").strip("[] "):
            raise HTTPException(400, "請至少選擇承攬商或外包名單人員其中一項")
        try:
            tiers = _setting_to_active_tiers(resolve_active_flow_setting(DOC_TYPE), conn, user["username"])
        except UnresolvedManagerError as e:
            raise HTTPException(400, str(e))
        now = _now()
        h = _flow.substantive_hash(row["vendor_id"], row["items_json"], row["personnel_json"], row["tax_rate"])
        prev = _jdict(row[st.json_col])
        version = int(prev.get("version") or 0) + 1
        history = list(prev.get("history") or [])
        if not tiers:
            appr = {"autoApproved": True, "note": "未設定任何簽核層，送審即視為核准", "version": version,
                    "requestedBy": user["username"], "requestedAt": now, "history": history}
            conn.execute("UPDATE contractor_dispatches SET %s=?, %s=?, %s=?, %s=?, %s=?, updated_at=? WHERE id=?" % (
                st.status_col, st.json_col, st.by_col, st.at_col, st.done_col),
                (_flow.APPROVED, json.dumps(appr, ensure_ascii=False), user["username"], now, now, now, did))
            if st.key == "dispatch":
                conn.execute("UPDATE contractor_dispatches SET approved_hash=? WHERE id=?", (h, did))
            if on_auto_approved:
                on_auto_approved(conn, row, user)
            result = {"ok": True, "approvalStatus": _flow.APPROVED, "autoApproved": True}
            tier_count = 0
        else:
            appr = {"requestedBy": user["username"], "requestedByDisplay": user.get("display_name") or user["username"],
                    "requestedAt": now, "tiers": tiers, "currentTier": 0, "version": version, "history": history}
            conn.execute("UPDATE contractor_dispatches SET %s=?, %s=?, %s=?, %s=?, updated_at=? WHERE id=?" % (
                st.status_col, st.json_col, st.by_col, st.at_col),
                (_flow.PENDING, json.dumps(appr, ensure_ascii=False), user["username"], now, now, did))
            result = {"ok": True, "approvalStatus": _flow.PENDING, "tierCount": len(tiers)}
            tier_count = len(tiers)
        conn.commit()
        label = _label(conn, row)
        first = _approvers(tiers[0]) if tiers else []
    finally:
        conn.close()
    for u in first:
        _notify(u, st.notify_type, str(did), row["quote_no"], "%s %s 需要您簽核" % (st.label, label))
    _audit(_tok(authorization), "%s.submit" % st.audit_prefix, "contractor_dispatch", str(did), row["quote_no"],
           _audit_detail(row, tierCount=tier_count, autoApproved=bool(result.get("autoApproved")), version=version))
    return result


def do_approve(did, body, user, authorization, st: Stage, *, on_done=None):
    conn = get_db()
    try:
        begin_write(conn)
        row = _load(conn, did)
        if row[st.status_col] not in (_flow.PENDING, _flow.IN_PROGRESS):
            raise HTTPException(409, "「%s」狀態不在簽核中" % (row[st.status_col] or "舊單"))
        appr = _jdict(row[st.json_col])
        tiers = _active_tiers(appr)
        ct = _current_tier_idx(appr)
        if tiers:
            ok, code, msg = check_approve_permission(tiers, ct, user["username"], conn)
            if not ok:
                raise HTTPException(code, msg)
        else:
            err = check_no_tier_self_approval(conn, appr, user)
            if err:
                raise HTTPException(403, err)
        now = _now()
        display = user.get("display_name") or user["username"]
        tier_done = sign_first_pending(tiers[ct], user, now, conn=conn) if tiers else True
        cascaded = (cascade_self_tiers(tiers, ct, user["username"], now, conn=conn)
                    if (tiers and tier_done and (body or {}).get("cascade")) else [])
        appr["tiers"] = tiers
        appr["currentTier"] = (ct + 1 + len(cascaded)) if tier_done else ct
        done = appr["currentTier"] >= len(tiers)
        new_status = _flow.APPROVED if done else _flow.IN_PROGRESS
        appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": display,
                                               "action": "approve", "tier": ct,
                                               "comment": (body or {}).get("comment") or ""})
        conn.execute("UPDATE contractor_dispatches SET %s=?, %s=?, updated_at=? WHERE id=?" % (st.status_col, st.json_col),
                     (new_status, json.dumps(appr, ensure_ascii=False), now, did))
        if done:
            conn.execute("UPDATE contractor_dispatches SET %s=? WHERE id=?" % st.done_col, (now, did))
            if st.key == "dispatch":                       # 核准當下把實質欄位釘住：之後有變 ⇒ 要重新送審
                conn.execute("UPDATE contractor_dispatches SET approved_hash=? WHERE id=?",
                             (_flow.substantive_hash(row["vendor_id"], row["items_json"], row["personnel_json"],
                                                     row["tax_rate"]), did))
            if on_done:
                on_done(conn, row, user)
        conn.commit()
        label = _label(conn, row)
        nxt = _approvers(tiers[appr["currentTier"]]) if not done else []
        requester = appr.get("requestedBy")
    finally:
        conn.close()
    if not done:
        for u in nxt:
            _notify(u, st.notify_type, str(did), row["quote_no"], "%s %s 需要您簽核" % (st.label, label))
    elif requester:
        _notify(requester, "dispatch_approved", str(did), row["quote_no"], "%s %s 已核准" % (st.label, label))
    _audit(_tok(authorization), "%s.approve" % st.audit_prefix, "contractor_dispatch", str(did), row["quote_no"],
           _audit_detail(row, tier=ct + 1, status=new_status))
    return {"ok": True, "approvalStatus": new_status, "currentTier": appr["currentTier"]}


def do_reject(did, body, user, authorization, st: Stage):
    reason = str((body or {}).get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "退回必須填寫理由")
    conn = get_db()
    try:
        begin_write(conn)
        row = _load(conn, did)
        if row[st.status_col] not in (_flow.PENDING, _flow.IN_PROGRESS):
            raise HTTPException(409, "「%s」狀態不在簽核中" % (row[st.status_col] or "舊單"))
        appr = _jdict(row[st.json_col])
        tiers = _active_tiers(appr)
        ct = _current_tier_idx(appr)
        ok, code, msg = check_reject_permission(tiers, ct, user, conn)
        if not ok:
            raise HTTPException(code, msg)
        now = _now()
        display = user.get("display_name") or user["username"]
        appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": display,
                                               "action": "reject", "tier": ct, "comment": reason})
        appr.update({"rejectedAt": now, "rejectedByDisplay": display, "rejectReason": reason})
        conn.execute("UPDATE contractor_dispatches SET %s=?, %s=?, updated_at=? WHERE id=?" % (st.status_col, st.json_col),
                     (_flow.RETURNED, json.dumps(appr, ensure_ascii=False), now, did))
        conn.commit()
        label = _label(conn, row)
        requester = appr.get("requestedBy")
    finally:
        conn.close()
    if requester:
        _notify(requester, "dispatch_returned", str(did), row["quote_no"], "%s %s 被退回：%s" % (st.label, label, reason))
    _audit(_tok(authorization), "%s.reject" % st.audit_prefix, "contractor_dispatch", str(did), row["quote_no"],
           _audit_detail(row, tier=ct + 1, reason=reason))
    return {"ok": True, "approvalStatus": _flow.RETURNED}


def do_withdraw(did, user, authorization, st: Stage, *, back_to):
    """撤回：只有送審人本人或最高管理者；只有「待審核」（第一層還沒人簽）可撤回。"""
    conn = get_db()
    try:
        begin_write(conn)
        row = _load(conn, did)
        if row[st.status_col] != _flow.PENDING:
            raise HTTPException(409, "只有「待審核」的單據可以撤回（已有人簽核過請改用退回）")
        appr = _jdict(row[st.json_col])
        if user["role"] != "superadmin" and appr.get("requestedBy") != user["username"]:
            raise HTTPException(403, "只有送審人本人或最高管理者可以撤回")
        now = _now()
        appr.setdefault("history", []).append({"at": now, "by": user["username"],
                                               "byDisplay": user.get("display_name") or user["username"],
                                               "action": "withdraw", "tier": _current_tier_idx(appr), "comment": ""})
        for k in ("tiers", "currentTier"):
            appr.pop(k, None)
        conn.execute("UPDATE contractor_dispatches SET %s=?, %s=?, updated_at=? WHERE id=?" % (st.status_col, st.json_col),
                     (back_to, json.dumps(appr, ensure_ascii=False), now, did))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "%s.withdraw" % st.audit_prefix, "contractor_dispatch", str(did), row["quote_no"],
           _audit_detail(row))
    return {"ok": True, "approvalStatus": back_to}


# ── 第一段端點 ─────────────────────────────────────────────────────

@router.post("/api/contractor-dispatches/{did}/submit")
def submit_dispatch(did: int, authorization: str = Header(None)):
    user = _require_dispatch_user(authorization)
    return do_submit(did, user, authorization, STAGE1, allowed_from=(_flow.DRAFT, _flow.RETURNED))


@router.post("/api/contractor-dispatches/{did}/approve")
def approve_dispatch(did: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization)          # 簽核人不一定是 admin／有承攬商模組：能不能簽只看「是否當層簽核人」
    return do_approve(did, body, user, authorization, STAGE1)


@router.post("/api/contractor-dispatches/{did}/reject")
def reject_dispatch(did: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization)
    return do_reject(did, body, user, authorization, STAGE1)


@router.post("/api/contractor-dispatches/{did}/withdraw")
def withdraw_dispatch(did: int, authorization: str = Header(None)):
    user = _require_dispatch_user(authorization)
    return do_withdraw(did, user, authorization, STAGE1, back_to=_flow.DRAFT)
