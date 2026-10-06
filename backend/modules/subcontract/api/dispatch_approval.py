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
from modules.subcontract import dispatch_notify as _dn

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


def dispatch_review_submit(did, user, authorization, st: Stage, *, allowed_from, extra_check=None, on_auto_approved=None):
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
        if not row["doc_code"]:
            # 舊單（第 31-A 之前建立）doc_code=''：簽核佇列／詳情／轉簽都以單號為鍵，沒有單號 ⇒ 這筆完工審核永遠不顯示（正式機回報）。
            # 送審當下（已持寫鎖）補號；只補這一欄，舊單的其他欄位與「舊單」身分（approval_status=''）不變。
            conn.execute("UPDATE contractor_dispatches SET doc_code=? WHERE id=? AND doc_code=''", (_flow.next_dispatch_code(conn), did))
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
        row = _load(conn, did)                                  # 重讀：剛補的單號要進通知／稽核文字
        label = _label(conn, row)
        first = _approvers(tiers[0]) if tiers else []
        subject = _subject(conn, row)
    finally:
        conn.close()
    for u in first:
        _notify(u, st.notify_type, str(did), row["quote_no"], "%s %s 需要您簽核" % (st.label, label))
    if first:
        _dn.fire(st.key, "submitted", row, subject, approvers=first)
    elif result.get("autoApproved"):
        _dn.fire(st.key, "approved", row, subject, requester=user["username"])
    _audit(_tok(authorization), "%s.submit" % st.audit_prefix, "contractor_dispatch", str(did), row["quote_no"],
           _audit_detail(row, tierCount=tier_count, autoApproved=bool(result.get("autoApproved")), version=version))
    return result


def dispatch_review_approve(did, body, user, authorization, st: Stage, *, on_done=None):
    conn = get_db()
    try:
        begin_write(conn)
        row = _load(conn, did)
        if row["status"] == "cancelled":
            raise HTTPException(409, "這筆派發已取消，不能再簽核")
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
        subject = _subject(conn, row)
    finally:
        conn.close()
    if not done:
        for u in nxt:
            _notify(u, st.notify_type, str(did), row["quote_no"], "%s %s 需要您簽核" % (st.label, label))
        _dn.fire(st.key, "next_tier", row, subject, approvers=nxt, tier_no=appr["currentTier"] + 1, total_tiers=len(tiers))
    elif requester:
        _notify(requester, "dispatch_approved", str(did), row["quote_no"], "%s %s 已核准" % (st.label, label), link="case-management.html?q=%s" % row["quote_no"])
        _dn.fire(st.key, "approved", row, subject, requester=requester)
    _audit(_tok(authorization), "%s.approve" % st.audit_prefix, "contractor_dispatch", str(did), row["quote_no"],
           _audit_detail(row, tier=ct + 1, status=new_status))
    return {"ok": True, "approvalStatus": new_status, "currentTier": appr["currentTier"]}


def dispatch_review_reject(did, body, user, authorization, st: Stage):
    reason = str((body or {}).get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "退回必須填寫理由")
    conn = get_db()
    try:
        begin_write(conn)
        row = _load(conn, did)
        if row["status"] == "cancelled":
            raise HTTPException(409, "這筆派發已取消，不能再簽核")
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
        subject = _subject(conn, row)
    finally:
        conn.close()
    if requester:
        _notify(requester, "dispatch_returned", str(did), row["quote_no"], "%s %s 被退回：%s" % (st.label, label, reason), link="case-management.html?q=%s" % row["quote_no"])
        _dn.fire(st.key, "returned", row, subject, requester=requester, reason=reason)
    _audit(_tok(authorization), "%s.reject" % st.audit_prefix, "contractor_dispatch", str(did), row["quote_no"],
           _audit_detail(row, tier=ct + 1, reason=reason))
    return {"ok": True, "approvalStatus": _flow.RETURNED}


def dispatch_review_withdraw(did, user, authorization, st: Stage, *, back_to):
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
    return dispatch_review_submit(did, user, authorization, STAGE1, allowed_from=(_flow.DRAFT, _flow.RETURNED))


@router.post("/api/contractor-dispatches/{did}/approve")
def approve_dispatch(did: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization)          # 簽核人不一定是 admin／有承攬商模組：能不能簽只看「是否當層簽核人」
    return dispatch_review_approve(did, body, user, authorization, STAGE1)


@router.post("/api/contractor-dispatches/{did}/reject")
def reject_dispatch(did: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization)
    return dispatch_review_reject(did, body, user, authorization, STAGE1)


@router.post("/api/contractor-dispatches/{did}/withdraw")
def withdraw_dispatch(did: int, authorization: str = Header(None)):
    user = _require_dispatch_user(authorization)
    return dispatch_review_withdraw(did, user, authorization, STAGE1, back_to=_flow.DRAFT)


# ── 第二段（完工審核）端點：作業狀態維持 accepted，全部簽完才由 set_status(via_completion=True) 設 completed ──

STAGE2 = Stage(key="completion", status_col="completion_status", json_col="completion_approval_json",
               by_col="completion_requested_by", at_col="completion_requested_at", done_col="completion_approved_at",
               label="派發完工", audit_prefix="vendor.dispatch.completion", notify_type="dispatch_completion_request")


def _need_accepted(row):
    if row["status"] != "accepted":
        raise HTTPException(409, "只有「已驗收」的派發可以申請完工（目前：%s）" % row["status"])
    if (row["approval_status"] or "") not in ("", _flow.APPROVED):
        raise HTTPException(409, "派發審核尚未核准")


def _complete(conn, row, user):
    """完工審核通過的唯一事件：把作業狀態推到 completed（寫入口仍是 dispatch_flow.set_status）。"""
    fresh = conn.execute("SELECT * FROM contractor_dispatches WHERE id=?", (row["id"],)).fetchone()
    try:
        _flow.set_status(conn, fresh, "completed", user, via_completion=True)
    except _flow.FlowError as e:
        raise HTTPException(e.status_code, str(e))


@router.post("/api/contractor-dispatches/{did}/completion/request")
def request_completion(did: int, authorization: str = Header(None)):
    user = _require_dispatch_user(authorization)
    return dispatch_review_submit(did, user, authorization, STAGE2, allowed_from=("", _flow.RETURNED),
                     extra_check=_need_accepted, on_auto_approved=_complete)


@router.post("/api/contractor-dispatches/{did}/completion/approve")
def approve_completion(did: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization)
    return dispatch_review_approve(did, body, user, authorization, STAGE2, on_done=_complete)


@router.post("/api/contractor-dispatches/{did}/completion/reject")
def reject_completion(did: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization)
    return dispatch_review_reject(did, body, user, authorization, STAGE2)


@router.post("/api/contractor-dispatches/{did}/completion/withdraw")
def withdraw_completion(did: int, authorization: str = Header(None)):
    user = _require_dispatch_user(authorization)
    return dispatch_review_withdraw(did, user, authorization, STAGE2, back_to="")


# ── 待我簽核佇列（IP-10）／詳情／轉簽：兩種 type，各讀自己那一段的欄位 ─────────────────────
from helpers import approval_queue as _aq  # noqa: E402

TYPE1, TYPE2 = "contractor_dispatch", "contractor_dispatch_completion"
_TYPE_STAGE = {TYPE1: (STAGE1, "承攬商派發", "dispatch"), TYPE2: (STAGE2, "承攬商派發完工", "completion")}


def _row_view(row) -> dict:
    """派工列的公開形狀：走 IP-1 `dispatch.row` 提供者（與其他模組同一條路，不 import 私有函式）。"""
    from core import registry
    return registry.single_provider("dispatch.row")(row)


def _grand_total(row) -> float:
    return _row_view(row).get("grandTotal", 0)


def _queue_for(conn, type_, rows):
    st, label, seg = _TYPE_STAGE[type_]
    out = []
    for r in rows:
        if r[st.status_col] not in (_flow.PENDING, _flow.IN_PROGRESS) or r["status"] == "cancelled":
            continue                                          # 已取消的派發不進佇列（歷史資料或取消後殘留也不列）
        raw = _aq.approval_raw_of(r[st.json_col], type_, r["doc_code"])
        if raw is None or not r["doc_code"]:                  # 壞資料只跳過那一筆
            continue
        f = _aq.tier_fields(raw)
        base = "/api/contractor-dispatches/%d" % r["id"] + ("/completion" if seg == "completion" else "")
        out.append(_aq.base_item(
            type_, r["doc_code"], f,
            customer=_subject(conn, r), projectName="關聯案件 %s" % r["quote_no"], total=_grand_total(r),
            quoteDate=(r[st.at_col] or r["created_at"] or "")[:10], linkedQuoteNo=r["quote_no"],
            typeLabel=label, docCode=r["doc_code"], dispatchId=r["id"],
            openUrl="case-management.html?q=%s&tab=dispatch" % r["quote_no"],
            approveUrl=base + "/approve", rejectUrl=base + "/reject", rejectField="reason",
            dispatchVersion=int(f["appr"].get("version") or 1)))
    return out


def queue_items(conn) -> list:
    """`approval.queue_items`（subcontract_dispatch）：派發審核＋完工審核兩種待簽項目。"""
    rows = conn.execute("SELECT * FROM contractor_dispatches WHERE approval_status IN ('待審核','簽核中') "
                        "OR completion_status IN ('待審核','簽核中') ORDER BY id DESC").fetchall()
    # 型別寫成字面值：覆蓋檢查（tools/check_approval_queue_coverage.py）是靜態讀提供者函式原始碼找 type 字面值
    return _queue_for(conn, "contractor_dispatch", rows) + _queue_for(conn, "contractor_dispatch_completion", rows)


def _detail(conn, doc_code, type_):
    st, label, seg = _TYPE_STAGE[type_]
    r = conn.execute("SELECT * FROM contractor_dispatches WHERE doc_code=?", (doc_code,)).fetchone()
    if not r:
        return None
    d = _row_view(r)
    fields = [{"label": "承攬商", "value": _subject(conn, r)},
              {"label": "派發單號", "value": r["doc_code"]},
              {"label": "派發日期", "value": r["dispatch_date"] or "—"},
              {"label": "範圍", "value": r["scope"] or "—"},
              {"label": "稅率", "value": "%g%%" % round(float(d.get("taxRate") or 0) * 100, 4)},
              {"label": "金額", "value": format(d.get("grandTotal") or 0, ",.0f")},
              {"label": "建立者", "value": r["created_by"] or "—"}]
    if seg == "completion":
        fields += [{"label": "驗收人", "value": r["accepted_by"] or "—"},
                   {"label": "驗收時間", "value": (r["accepted_at"] or "—")[:16].replace("T", " ")}]
    pers = [{"description": "外包人員：%s" % (p.get("name") or ""), "amount": p.get("amount") or 0}
            for p in (d.get("personnel") or []) if isinstance(p, dict)]
    return {"quoteNo": r["quote_no"], "title": "%s %s" % (label, r["doc_code"]),
            "approvalRaw": r[st.json_col] or "{}", "fields": fields,
            "items": [x for x in (d.get("items") or []) if isinstance(x, dict)] + pers, "files": []}


def detail_dispatch(conn, doc_code):
    return _detail(conn, doc_code, TYPE1)


def detail_completion(conn, doc_code):
    return _detail(conn, doc_code, TYPE2)


class _ColumnApproval:
    """`approval.reassign`：簽核鏈存在 contractor_dispatches 的獨立欄位（兩段各一欄），以 doc_code 為單號。"""

    def __init__(self, stage: Stage):
        self.st = stage

    def load(self, conn, doc_no):
        r = conn.execute("SELECT doc_code, quote_no, %s AS s, %s AS j FROM contractor_dispatches WHERE doc_code=?"
                         % (self.st.status_col, self.st.json_col), (doc_no,)).fetchone()
        if not r:
            return None
        try:
            a = json.loads(r["j"] or "{}")
        except (TypeError, ValueError):
            raise _aq.ApprovalUnreadable(doc_no)
        if not isinstance(a, dict):
            raise _aq.ApprovalUnreadable(doc_no)
        return {"docNo": r["doc_code"], "quoteNo": r["quote_no"], "status": r["s"], "approval": a}

    def save(self, conn, doc, approval, now):
        conn.execute("UPDATE contractor_dispatches SET %s=?, updated_at=? WHERE doc_code=?" % self.st.json_col,
                     (json.dumps(approval, ensure_ascii=False), now, doc["docNo"]))


REASSIGN_DISPATCH = _ColumnApproval(STAGE1)
REASSIGN_COMPLETION = _ColumnApproval(STAGE2)
