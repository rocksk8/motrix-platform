# -*- coding: utf-8 -*-
"""勞報單送審／簽核（第 46 班；設計 docs/platform/plans/PAYSLIP-APPROVAL-T45.md §2、§3）。

狀態：草稿 ─送審→ 待審核 ─逐層簽核→ 已核准；退回（必填原因）＝回草稿。**沒設簽核層 ⇒ 送審即核准**。
簽核層進度放 `approval_json.currentTier`（同獎金分潤；不另開「簽核中」值）。簽核人只能是最高管理者（勞報單所有端點本來就是 superadmin；W1 同獎金分潤）。
重用 `helpers/tiered_approval` 原語（鏈解析、當層權限、自核規則、退回權限、退回原因）；單據類型 `payslip`（不併統一流程，預設自己一條流程）。
本檔不碰匯出／簽回／付款（仍在 `payslips.py`）。
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _audit, _get_setting, _require_user, _tok
from helpers.dates import normalize_date
from helpers.tiered_approval import (
    UnresolvedManagerError, approval_flow_setting_key, check_approve_permission, check_no_tier_self_approval,
    check_reject_permission, register_doc_type, setting_to_active_tiers,
)
from modules.payroll import payslip_notify as _pn

router = APIRouter()
logger = logging.getLogger(__name__)

DOC_TYPE = "payslip"
DOC_LABEL = "勞報單"
try:                                                                  # 單據類型登記（出現在簽核設定頁；不併統一流程）
    register_doc_type(DOC_TYPE, DOC_LABEL, unified=False)
except ValueError:                                                    # 重複載入（測試重入）時忽略
    pass

#: 簽核中（待審核）與核准後的狀態
S_DRAFT, S_REVIEW, S_APPROVED = "草稿", "待審核", "已核准"
_ONLY_SUPERADMIN_MSG = "勞報單的簽核人只能是最高管理者，請調整簽核設定。"


def _name(user) -> str:
    return user.get("display_name") or user["username"]


def _appr_of(raw) -> dict:
    try:
        d = json.loads(raw or "{}")
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError):
        return {}


def _non_superadmin_in_chain(conn, tiers):
    """鏈上的簽核人，以及他們今天有效的代理人，是否有人不是 superadmin。回違規的帳號清單（同獎金分潤 W1）。"""
    from datetime import date
    today = date.today().isoformat()
    bad = []
    for t in tiers or []:
        for a in (t or {}).get("approvers") or []:
            uname = a.get("username") or ""
            names = [uname] + [r["delegate_username"] for r in conn.execute(
                "SELECT delegate_username FROM approval_delegates WHERE delegator_username=? AND active=1"
                " AND start_date<=? AND end_date>=?", (uname, today, today))]
            for n in names:
                r = conn.execute("SELECT role FROM users WHERE username=?", (n,)).fetchone()
                if r is None or r["role"] != "superadmin":
                    bad.append(n)
    return bad


def resolve_tiers(conn, requester_username):
    """依現行設定解析勞報單簽核鏈。鏈上出現非最高管理者（含代理人解析）⇒ 400；沒設 ⇒ []（送審即核准）。"""
    scope = _get_setting("approval_flow_scope", {}) or {}
    flow = _get_setting(approval_flow_setting_key(DOC_TYPE, scope), None)
    tiers = []
    if flow is not None:
        try:
            tiers = setting_to_active_tiers(flow, conn, requester_username)
        except UnresolvedManagerError as exc:
            raise HTTPException(400, str(exc))
    bad = _non_superadmin_in_chain(conn, tiers)
    if bad:
        raise HTTPException(400, _ONLY_SUPERADMIN_MSG + "（非最高管理者：%s）" % "、".join(dict.fromkeys(bad)))
    return tiers


def current_approvers(conn, appr):
    """現在輪到誰簽：當層第一位未簽的人＋他今天有效的代理人（在職）。沒有簽核鏈 ⇒ []。"""
    tiers = appr.get("tiers") or []
    ct = int(appr.get("currentTier") or 0)
    if not tiers or ct >= len(tiers):
        return []
    nxt = next((a for a in (tiers[ct].get("approvers") or []) if a.get("status") != "approved"), None)
    if nxt is None:
        return []
    from datetime import date
    today = date.today().isoformat()
    uname = nxt.get("username") or ""
    who = [uname] + [r["delegate_username"] for r in conn.execute(
        "SELECT delegate_username FROM approval_delegates WHERE delegator_username=? AND active=1 AND start_date<=? AND end_date>=?",
        (uname, today, today))]
    out = []
    for w in dict.fromkeys(x for x in who if x):
        r = conn.execute("SELECT active FROM users WHERE username=?", (w,)).fetchone()
        if r is not None and r["active"]:
            out.append(w)
    return out


def _load(conn, slip_no):
    row = conn.execute("SELECT slip_no, status, approval_json, slip_date, contractor_id FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
    if not row:
        raise HTTPException(404, "找不到此勞報單")
    return row


def _finance_users(conn):
    from helpers.auth import finance_usernames
    return finance_usernames(conn)


@router.post("/api/payslips/{slip_no}/submit")
def submit_payslip(slip_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """草稿 → 待審核（沒設簽核層 ⇒ 直接已核准）。可選填預定付款日（`plannedPayDate`；核准後出納也能改）。"""
    user = _require_user(authorization, require_superadmin=True, module="payslip")
    planned = None
    if "plannedPayDate" in (body or {}):
        planned = normalize_date((body or {}).get("plannedPayDate"), "預定付款日")
    conn = get_db()
    now = datetime.now().isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _load(conn, slip_no)
        if row["status"] != S_DRAFT:
            raise HTTPException(409, "只有草稿可以送審，這一張現在是「%s」。" % row["status"])
        tiers = resolve_tiers(conn, user["username"])
        appr = {"tiers": tiers, "currentTier": 0, "requestedBy": user["username"], "requestedByDisplay": _name(user), "requestedAt": now,
                "history": [{"at": now, "by": user["username"], "byDisplay": _name(user), "action": "submit", "comment": ""}]}
        sets, args = [], []
        if planned is not None:
            sets.append("planned_pay_date=?")
            args.append(planned)
        if tiers:
            status, extra = S_REVIEW, ""
        else:                                                         # 沒設簽核層 ⇒ 送審即核准
            status = S_APPROVED
            appr["approvedBy"], appr["approvedAt"] = _name(user), now
            appr["history"].append({"at": now, "by": user["username"], "byDisplay": _name(user), "action": "auto_approve", "comment": ""})
            sets += ["approved_at=?", "approved_by=?"]
            args += [now, _name(user)]
        conn.execute("UPDATE payslips SET status=?, approval_json=?, updated_at=?" + "".join(", " + s for s in sets) + " WHERE slip_no=? AND status=?",
                     [status, json.dumps(appr, ensure_ascii=False), now] + args + [slip_no, S_DRAFT])
        recipients = current_approvers(conn, appr) if status == S_REVIEW else []
        fin = _finance_users(conn) if status == S_APPROVED else []
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "payslip.submit" if status == S_REVIEW else "payslip.auto_approve", "payslip", slip_no,
           "%s 送審%s" % (slip_no, "" if status == S_REVIEW else "（未設簽核層，直接核准）"), {"tierCount": len(tiers)})
    if status == S_REVIEW:
        _pn.fire_submitted(slip_no, row["slip_date"], recipients, actor=user["username"])
    else:
        _pn.fire_approved(slip_no, row["slip_date"], user["username"], fin, approver=user["username"])
    return {"ok": True, "status": status, "tierCount": len(tiers)}


@router.post("/api/payslips/{slip_no}/approve")
def approve_payslip(slip_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """當層簽核人（或代理人）簽；同層全數簽完才換層；最後一層簽完 ⇒ 已核准。沒有簽核鏈（設定被移除）⇒ superadmin 且不可自核（唯一最高管理者例外）。"""
    user = _require_user(authorization, require_superadmin=True, module="payslip")
    comment = str((body or {}).get("comment") or "").strip()[:200]
    conn = get_db()
    now = datetime.now().isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _load(conn, slip_no)
        if row["status"] != S_REVIEW:
            raise HTTPException(409, "這張勞報單不在簽核流程裡（目前「%s」）。" % row["status"])
        appr = _appr_of(row["approval_json"])
        tiers = appr.get("tiers") or []
        if tiers:
            ct = int(appr.get("currentTier") or 0)
            ok, code, msg = check_approve_permission(tiers, ct, user["username"], conn)
            if not ok:
                raise HTTPException(code, msg)
            approvers = tiers[ct].get("approvers") or []
            fp = next(a for a in approvers if a.get("status") != "approved")
            fp["status"], fp["approvedAt"], fp["approvedBy"] = "approved", now, _name(user)
            if all(a.get("status") == "approved" for a in approvers):
                appr["currentTier"] = ct + 1
            done = int(appr.get("currentTier") or 0) >= len(tiers)
        else:
            err = check_no_tier_self_approval(conn, appr, user)
            if err:
                raise HTTPException(403, err)
            done = True
        appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _name(user), "action": "approve", "comment": comment})
        if done:
            appr["approvedBy"], appr["approvedAt"] = _name(user), now
            conn.execute("UPDATE payslips SET status=?, approval_json=?, approved_at=?, approved_by=?, updated_at=? WHERE slip_no=? AND status=?",
                         (S_APPROVED, json.dumps(appr, ensure_ascii=False), now, _name(user), now, slip_no, S_REVIEW))
        else:
            conn.execute("UPDATE payslips SET approval_json=?, updated_at=? WHERE slip_no=? AND status=?",
                         (json.dumps(appr, ensure_ascii=False), now, slip_no, S_REVIEW))
        requester = appr.get("requestedBy") or ""
        recipients = [] if done else current_approvers(conn, appr)
        fin = _finance_users(conn) if done else []
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "payslip.approve", "payslip", slip_no, "%s 簽核 → %s" % (slip_no, S_APPROVED if done else S_REVIEW))
    if done:
        _pn.fire_approved(slip_no, row["slip_date"], requester, fin, approver=user["username"])
    else:
        _pn.fire_submitted(slip_no, row["slip_date"], recipients, next_tier=True, actor=user["username"])
    return {"ok": True, "status": S_APPROVED if done else S_REVIEW}


@router.post("/api/payslips/{slip_no}/reject")
def reject_payslip(slip_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """簽核人退回（待審核）⇒ 回草稿；原因必填；歷史保留在 approval_json.history（送審重來會重新解析簽核鏈）。"""
    user = _require_user(authorization, require_superadmin=True, module="payslip")
    reason = str((body or {}).get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "請填寫退回原因。")
    conn = get_db()
    now = datetime.now().isoformat()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = _load(conn, slip_no)
        if row["status"] != S_REVIEW:
            raise HTTPException(409, "這張勞報單不在簽核流程裡（目前「%s」）。" % row["status"])
        appr = _appr_of(row["approval_json"])
        ok, code, msg = check_reject_permission(appr.get("tiers") or [], int(appr.get("currentTier") or 0), user, conn)
        if not ok:
            raise HTTPException(code, msg)
        requester = appr.get("requestedBy") or ""
        back = {"history": (appr.get("history") or []) + [{"at": now, "by": user["username"], "byDisplay": _name(user), "action": "reject", "comment": reason}],
                "lastRejectedBy": _name(user), "lastRejectedAt": now, "lastRejectReason": reason}
        conn.execute("UPDATE payslips SET status=?, approval_json=?, updated_at=? WHERE slip_no=? AND status=?",
                     (S_DRAFT, json.dumps(back, ensure_ascii=False), now, slip_no, S_REVIEW))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "payslip.reject", "payslip", slip_no, "%s 退回：%s" % (slip_no, reason))
    _pn.fire_returned(slip_no, row["slip_date"], requester, approver=user["username"], reason=reason)
    return {"ok": True, "status": S_DRAFT}


# ── 「待我簽核」佇列提供者（IP-10 `approval.queue_items`，名稱 payroll_payslip）──────────────────────────────

def queue_items(conn) -> list:
    """待審核的勞報單。自帶 `typeLabel／openUrl／approveUrl／rejectUrl／rejectField`；**不放金額、受領人、身分資料**（只有單號、開單日期、送審人）。"""
    from helpers import approval_queue as _aq
    out = []
    for r in conn.execute("SELECT slip_no, slip_date, created_by, created_at, approval_json FROM payslips WHERE status=? ORDER BY id DESC", (S_REVIEW,)).fetchall():
        raw = _aq.approval_raw_of(r["approval_json"], DOC_TYPE, r["slip_no"])      # 壞一筆只跳過那一筆
        if raw is None:
            continue
        f = _aq.tier_fields(raw)
        req = (json.loads(raw) or {}).get("requestedBy") or r["created_by"] or ""
        out.append(_aq.base_item(
            "payslip", r["slip_no"], f, total=0,                  # type 用字面值：簽核佇列覆蓋守門靠提供者原始碼裡的 type 字面值判定
            quoteDate=(r["slip_date"] or "")[:10],
            requestedBy=req, requestedByDisplay=req, requestedAt=(r["created_at"] or ""),
            typeLabel=DOC_LABEL, projectName=DOC_LABEL, customer="",
            openUrl="payslips.html?q=%s" % r["slip_no"],
            approveUrl="/api/payslips/%s/approve" % r["slip_no"], rejectUrl="/api/payslips/%s/reject" % r["slip_no"], rejectField="reason"))
    return out
