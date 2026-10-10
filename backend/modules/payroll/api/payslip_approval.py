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
    active_delegators_for, check_reject_permission, register_doc_type, setting_to_active_tiers,
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
    user = _require_user(authorization, require_superadmin=True)
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
        if tiers or user.get("role") != "superadmin":                 # 有簽核層，或送審人不是最高管理者 ⇒ 待審核（沒設層時由最高管理者走無層簽核路徑，不自核）
            status, extra = S_REVIEW, ""
        else:                                                         # 沒設簽核層、且送審人是最高管理者 ⇒ 送審即核准
            status = S_APPROVED
            appr["approvedBy"], appr["approvedAt"] = _name(user), now
            appr["history"].append({"at": now, "by": user["username"], "byDisplay": _name(user), "action": "auto_approve", "comment": ""})
            sets += ["approved_at=?", "approved_by=?"]
            args += [now, _name(user)]
        conn.execute("UPDATE payslips SET status=?, approval_json=?, updated_at=?" + "".join(", " + s for s in sets) + " WHERE slip_no=? AND status=?",
                     [status, json.dumps(appr, ensure_ascii=False), now] + args + [slip_no, S_DRAFT])
        recipients = current_approvers(conn, appr) if status == S_REVIEW else []
        if status == S_REVIEW and not tiers:                          # 無簽核層的待審核：通知其他在職最高管理者
            recipients = [r["username"] for r in conn.execute("SELECT username FROM users WHERE active=1 AND role='superadmin' ORDER BY id")]
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


#: 代核原因的最短有意義長度（正規化後：去掉零寬字元與多餘空白再算字數）。登錄式常數；README／SPEC／CHANGELOG 都引用這個名字，日後要調整只改這一處。
BYPASS_REASON_MIN_LEN = 4
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063\u2064\ufeff\u00ad\u180e"))   # 零寬／格式字元（原始碼用跳脫寫法，不放不可見字元）


def normalize_reason(text) -> str:
    """原因正規化：去零寬／格式字元、全形空白換半形、連續空白收成一個、頭尾去空白。非字串 ⇒ 空字串。"""
    if not isinstance(text, str):
        return ""
    t = text.translate(_ZERO_WIDTH).replace("\u3000", " ")
    return " ".join(t.split())


def _deadlock_bypass(conn, appr, tiers, ct, user, reason, code, msg):
    """第 54 班（使用者回報：勞報單送審後卡死）：送審人不得自核（Q-S6），若當層**排序最前的未簽核人就是送審人**，其他人不是簽不了
    （不在層內／要等送審人先簽）⇒ 單據卡死。比照獎金分潤（第 52 班）：**另一位最高管理者**可帶原因代核。
    回 `{"approver": 被代的簽核人帳號, "reason": 原因}`；條件不符 ⇒ 丟原本的 403／錯誤（`code`／`msg`）。
    條件：①原本被擋的是權限（403）②操作者不是送審人（送審人永遠不可自核）
    ③卡點成立：當層排序最前的未簽核人是送審人；或整條鏈只有一位簽核人、而他**已停用／帳號不存在**（有錢有扣繳的單據，不給覆寫一位在職的單一簽核人——
      他自己能簽，缺席走轉簽）④操作者**還沒在這張單簽過任何一格**（避免同一個人簽出兩個人的簽名）⑤必填原因（強制稽核、簽核紀錄、通知其他最高管理者）。
    操作者本身必須是真正的最高管理者（端點已要求）。"""
    requester = appr.get("requestedBy") or ""
    names = [(a.get("username") or "") for t in tiers for a in (t.get("approvers") or [])]
    cur = (tiers[ct].get("approvers") or []) if ct < len(tiers) else []
    first = next((a.get("username") or "" for a in cur if a.get("status") != "approved"), "")
    blocker = ""
    if first and first == requester:
        blocker = first
    elif len(names) == 1 and names[0]:
        r = conn.execute("SELECT active FROM users WHERE username=?", (names[0],)).fetchone()
        if r is None or not r["active"]:
            blocker = names[0]
    signed = {h.get("by") for h in (appr.get("history") or []) if h.get("action") in ("approve", "approve_bypass")}
    # 1d 稽核：代核人不得是這條簽核鏈上的任何簽核人，也不得是鏈上任何人目前有效的代理人——否則同層 [送審人 S, A] 時 A 代 S 簽一格、再簽自己那一格
    # ＝一個人填滿兩格（雙人控管失效）。鏈外的另一位最高管理者才能代核。
    in_chain = user["username"] in set(names) or bool(active_delegators_for(conn, user["username"]) & set(names))
    if code != 403 or not blocker or user["username"] == requester or user["username"] == blocker or user["username"] in signed or in_chain:
        raise HTTPException(code, msg)
    reason = normalize_reason(reason)
    if len(reason) < BYPASS_REASON_MIN_LEN:
        raise HTTPException(403, "這張勞報單目前輪到的簽核人（%s）無法簽核（送審人不能自行核准，或該帳號已停用），單據會卡住。若要以最高管理者身分代為核准，請填寫原因"
                                 "（至少 %d 個字；會寫入稽核紀錄，並通知其他最高管理者）。" % (blocker, BYPASS_REASON_MIN_LEN))
    return {"approver": blocker, "reason": reason[:500]}


@router.post("/api/payslips/{slip_no}/approve")
def approve_payslip(slip_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """當層簽核人（或代理人）簽；同層全數簽完才換層；最後一層簽完 ⇒ 已核准。沒有簽核鏈（設定被移除）⇒ superadmin 且不可自核（唯一最高管理者例外）。"""
    user = _require_user(authorization, require_superadmin=True, module="payslip")
    if user.get("role") != "superadmin":                              # 簽核當下再確認一次（簽核人被降級、代理人不是最高管理者 ⇒ 拒絕；W1）
        raise HTTPException(403, _ONLY_SUPERADMIN_MSG)
    comment = str((body or {}).get("comment") or "").strip()[:200]
    bypass = None
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
            err = check_no_tier_self_approval(conn, appr, user)          # 第47班 Q-S6（使用者裁示 A）：有簽核層時送審人也不得自核；全公司只有這一位在職最高管理者時例外
            if err:
                raise HTTPException(403, err)
            ct = int(appr.get("currentTier") or 0)
            ok, code, msg = check_approve_permission(tiers, ct, user["username"], conn)
            if not ok:
                bypass = _deadlock_bypass(conn, appr, tiers, ct, user, (body or {}).get("reason"), code, msg)      # 條件不符 ⇒ 丟原本的錯
            approvers = tiers[ct].get("approvers") or []
            fp = next(a for a in approvers if a.get("status") != "approved")
            fp["status"], fp["approvedAt"], fp["approvedBy"] = "approved", now, _name(user)
            if bypass:                                                # 代核：把『誰、代誰、為什麼』留在簽核紀錄本身
                fp["bypass"] = {"by": user["username"], "reason": bypass["reason"], "at": now}
                appr["bypass"] = {"by": user["username"], "forApprover": bypass["approver"], "reason": bypass["reason"], "at": now}
            if all(a.get("status") == "approved" for a in approvers):
                appr["currentTier"] = ct + 1
            done = int(appr.get("currentTier") or 0) >= len(tiers)
        else:
            err = check_no_tier_self_approval(conn, appr, user)
            if err:
                raise HTTPException(403, err)
            done = True
        appr.setdefault("history", []).append({"at": now, "by": user["username"], "byDisplay": _name(user), "action": "approve_bypass" if bypass else "approve",
                                               "comment": ("【代 %s 核准】%s" % (bypass["approver"], bypass["reason"])) if bypass else comment})
        if bypass:
            _audit_in_txn(conn, user, "payslip.approve_bypass", "payslip", slip_no, "%s 層外代核（代 %s）" % (slip_no, bypass["approver"]),
                          {"by": user["username"], "forApprover": bypass["approver"], "reason": bypass["reason"], "requestedBy": appr.get("requestedBy") or ""})
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
    if bypass:
        _notify_bypass(slip_no, row["slip_date"], user, bypass)
    if done:
        _pn.fire_approved(slip_no, row["slip_date"], requester, fin, approver=user["username"])
    else:
        _pn.fire_submitted(slip_no, row["slip_date"], recipients, next_tier=True, actor=user["username"])
    return {"ok": True, "status": S_APPROVED if done else S_REVIEW}


@router.post("/api/payslips/{slip_no}/reject")
def reject_payslip(slip_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """簽核人退回（待審核）⇒ 回草稿；原因必填；歷史保留在 approval_json.history（送審重來會重新解析簽核鏈）。"""
    user = _require_user(authorization, require_superadmin=True, module="payslip")
    if user.get("role") != "superadmin":                              # 注意：_require_user 的 module 參數會放行「持有勞報單模組的非最高管理者」；簽核／退回一律要真正的最高管理者（W1）
        raise HTTPException(403, _ONLY_SUPERADMIN_MSG)
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


def _audit_in_txn(conn, user, action, target_type, target_id, label, detail):
    """**強制**稽核：寫在核准同一個交易裡（寫不進去 ⇒ 例外 ⇒ 整個核准回滾），不像 `_audit` 失敗只吞掉。
    module／case_no／ref_no 與 `_audit` 同一個推導函式（單號歷史搜尋靠 ref_no）。"""
    from helpers.audit import _derive_fields
    d = _derive_fields(action, target_type, target_id, label, detail)
    conn.execute(
        "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,module,case_no,ref_no,result,reason_code,status_code)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'ok','',0)",
        (datetime.now().isoformat(), user.get("id"), user.get("username") or "", user.get("display_name") or "", action, target_type, target_id, label,
         json.dumps(detail, ensure_ascii=False), d["module"], d["case_no"], d["ref_no"]))


def _notify_bypass(slip_no, slip_date, user, bypass):
    """代核後知會其他在職最高管理者（含被代的簽核人，不含操作者）。附帶動作：失敗只記 log。"""
    try:
        conn = get_db()
        try:
            who = [r["username"] for r in conn.execute("SELECT username FROM users WHERE active=1 AND role='superadmin' ORDER BY id")]
        finally:
            conn.close()
        _pn.fire_bypass(slip_no, slip_date, user["username"], bypass["approver"], bypass["reason"], who)
    except Exception:                                            # noqa: BLE001 — 附帶動作
        logger.exception("勞報單層外代核通知失敗（%s）", slip_no)


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
            typeLabel=DOC_LABEL, projectName=DOC_LABEL, customer="", caseless=True,                 # 不掛案件：詳情只有簽核鏈上的人、送審人與最高管理者能開（L1 `_access_step`）
            openUrl="payslips.html?q=%s" % r["slip_no"],
            approveUrl="/api/payslips/%s/approve" % r["slip_no"], rejectUrl="/api/payslips/%s/reject" % r["slip_no"], rejectField="reason"))
    return out


# ── 簽核佇列詳情（`approval.detail`，名稱 payslip；使用者 2026-10-07 裁示：詳情顯示完整內容，**含身分證字號與收款帳號**）─────────
# 守門與稽核：
#   ① 佇列詳情的存取＝簽核鏈上的人、送審人、最高管理者（提供者宣告 `caseless`，L1 `_access_step`）；
#   ② **身分證字號與收款帳號不放在提供者回傳的內容裡**（L1 詳情端點沒有「每次檢視留稽核」的鉤子）——詳情只放遮蔽占位與 `revealUrl`，
#      頁面開詳情時打 `GET /api/payslips/{no}/approval-reveal`：最高管理者專用、只限待審核、**每次檢視寫一筆稽核（不含值）**；
#   ③ 佇列清單、角標、信件、站內通知、記錄檔一律不含這兩項（只有這支端點回值）。

def detail(conn, doc_no):
    r = conn.execute("SELECT * FROM payslips WHERE slip_no=?", (doc_no,)).fetchone()
    if r is None:
        return None
    try:
        d = json.loads(r["data_json"] or "{}") or {}
    except (TypeError, ValueError):
        d = {}
    reveal = "/api/payslips/%s/approval-reveal" % r["slip_no"]
    mask = "（點「顯示」才取值，每次留稽核）"
    fields = [{"label": "單號", "value": r["slip_no"]}, {"label": "開單日期", "value": (r["slip_date"] or "")[:10] or "—"},
              {"label": "受領人", "value": r["contractor_name"] or "—"}, {"label": "所得類別", "value": r["income_type"] or "—"},
              {"label": "勞務內容", "value": str(d.get("serviceContent") or "—")},
              {"label": "應付總額", "value": format(int(r["gross_amount"] or 0), ",")}, {"label": "代扣所得稅", "value": format(int(r["tax_withheld"] or 0), ",")},
              {"label": "代扣二代健保", "value": format(int(r["nhi_supplement"] or 0), ",")}, {"label": "實發金額", "value": format(int(r["net_amount"] or 0), ",")},
              {"label": "預定付款日", "value": (r["planned_pay_date"] or "")[:10] or "—"},
              {"label": "身分證字號", "value": mask, "revealUrl": reveal, "revealKey": "idNumber"},
              {"label": "收款銀行", "value": mask, "revealUrl": reveal, "revealKey": "bank"},
              {"label": "收款帳號", "value": mask, "revealUrl": reveal, "revealKey": "bankAccountNumber"}]
    return {"quoteNo": "", "caseless": True, "approvalRaw": r["approval_json"], "title": "勞報單 %s" % r["slip_no"], "fields": fields, "items": [], "files": []}


_REVEAL_KEYS = {"idNumber", "bank", "bankAccountNumber"}
_REVEAL_LIMIT, _REVEAL_WINDOW = 30, 60.0                 # 每人每分鐘最多 30 次
_REVEAL_LOG = {}                                          # username → [monotonic 時間戳]


def _reveal_rate_ok(username, now=None) -> bool:
    import time
    now = time.monotonic() if now is None else now
    xs = [t for t in _REVEAL_LOG.get(username, []) if now - t < _REVEAL_WINDOW]
    if len(xs) >= _REVEAL_LIMIT:
        _REVEAL_LOG[username] = xs
        return False
    xs.append(now)
    _REVEAL_LOG[username] = xs
    return True


def _audit_raising(user, action, target_id, label, detail=None):
    """稽核先寫、寫不進去就丟例外（⇒ 500，不回傳任何值）；一般 `_audit` 會吞例外，不適合「先稽核才給值」。"""
    conn = get_db()
    try:
        conn.execute("INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail) VALUES (?,?,?,?,?,?,?,?,?)",
                     (datetime.now().isoformat(), user.get("id"), user.get("username") or "", user.get("display_name") or "", action, "payslip", target_id, label,
                      json.dumps(detail or {}, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


@router.get("/api/payslips/{slip_no}/approval-reveal")
def approval_reveal(slip_no: str, field: str = "", authorization: str = Header(None)):
    """簽核佇列詳情要顯示的身分證字號／收款資料——**點一個欄位才取一個欄位**（`field`＝idNumber｜bank｜bankAccountNumber），每次點擊一筆稽核（不含值）。
    守門：**真正的最高管理者**（不用 `module=` 參數：它會放行持有勞報單模組的非最高管理者，等於繞過 F1 遮蔽）＋`can_see_full`＋能開這張詳情（L1 同一個判斷）＋只限待審核。
    稽核先寫（寫不進去 ⇒ 500、不回值）；每人每分鐘 30 次；回應 `Cache-Control: no-store`。"""
    from fastapi.responses import JSONResponse
    from modules.payroll import payslip_bank as _pb
    user = _require_user(authorization)
    if user.get("role") != "superadmin" or not _pb.can_see_full(user):
        raise HTTPException(403, "僅最高管理者可檢視身分證字號與收款帳號")
    if field not in _REVEAL_KEYS:
        raise HTTPException(400, "field 必須是 idNumber、bank 或 bankAccountNumber")
    conn = get_db()
    try:
        r = conn.execute("SELECT status, data_json, approval_json FROM payslips WHERE slip_no=?", (slip_no,)).fetchone()
        if r is None:
            raise HTTPException(404, "找不到此勞報單")
        if r["status"] != S_REVIEW:
            raise HTTPException(409, "只有待審核的勞報單可由簽核佇列檢視（目前「%s」）" % r["status"])
        try:                                                           # 與詳情同一個存取判斷（L1 `_access_step`；不掛案件 ⇒ 簽核鏈上的人、送審人、最高管理者）
            from routers import approval_queue as _aq
            if _aq._access_step(conn, user, "", r["approval_json"], False, caseless=True) == _aq.DENY:
                raise HTTPException(404, "找不到此勞報單")
        except ImportError:
            pass
        try:
            d = json.loads(r["data_json"] or "{}") or {}
        except (TypeError, ValueError):
            d = {}
    finally:
        conn.close()
    if not _reveal_rate_ok(user["username"]):
        raise HTTPException(429, "檢視太頻繁，請稍後再試")
    _audit_raising(user, "payslip.approval_reveal", slip_no, "%s 簽核佇列檢視（%s）" % (slip_no, field), {"field": field})     # 先稽核；失敗 ⇒ 500、不回值
    val = {"idNumber": str(d.get("contractorIdNumber") or d.get("idNumber") or ""),
           "bank": ("%s %s" % (d.get("bankCode") or "", d.get("bankName") or "")).strip(),
           "bankAccountNumber": str(d.get("bankAccountNumber") or "")}[field]
    return JSONResponse({"field": field, "value": val}, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
