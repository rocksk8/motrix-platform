# -*- coding: utf-8 -*-
"""獎金更正單 API（`/api/bonus/corrections`，2026-09-30 使用者核准）。規則與跨模組寫入落點見 `modules/payroll/bonus_correction.py`。

權限（與獎金分潤本體同一套，不另開權限 key）：
- 建立／修改／送審／作廢／駁回／核准：**最高管理者**（簽核鏈上只能是最高管理者＝`_resolve_bonus_tiers` 同一規則；最後由 superadmin 核准）。
- 標記補發：出納模組持有者或 superadmin（與原單 mark-paid 同）。
- 檢視：superadmin 全部；出納看「待補發／已完成」（為了照著發）；其他人一律 404（當作不存在）。金額不進信件、不進待簽核佇列。
"""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Body, Header, HTTPException

from core.txn import begin_write
from db import get_db
from helpers import _require_user, _audit, _tok
from helpers.auth import user_has_module
from helpers.tiered_approval import check_approve_permission, check_no_tier_self_approval, check_reject_permission
from modules.payroll import bonus_correction as bc
from modules.payroll import bonus_deductions, bonus_payouts, bonus_vouchers
from modules.payroll.api import bonus as bonus_api

router = APIRouter(prefix="/api/bonus/corrections", tags=["bonus-correction"])
logger = logging.getLogger(__name__)


def _now():
    return datetime.now().isoformat()


def _row(conn, corr_no):
    r = conn.execute("SELECT * FROM bonus_corrections WHERE corr_no = ?", (corr_no,)).fetchone()
    if r is None:
        raise HTTPException(404, "找不到這張更正單。")
    return dict(r)


def _paid_award(conn, quote_no):
    award, _lines = bonus_api._load_case_award(conn, quote_no)
    if award is None:
        raise HTTPException(404, "這個案件還沒有獎金分潤單。")
    if award["status"] != "已發放":
        raise HTTPException(409, "只有「已發放」的獎金分潤可以開更正單（這一張現在是「%s」；發放前請用退回）。" % award["status"])
    return award


def _view(conn, c, user, detail=False):
    """依身分決定回多少；不可見 ⇒ None。"""
    sup = user.get("role") == "superadmin"
    if not sup and not (c["status"] in ("待補發", "已完成") and user_has_module(user, "cashier")):
        return None
    lines = bc.parse_json(c["lines_json"], [])
    out = {k: c[k] for k in ("corr_no", "quote_no", "status", "reason", "old_total", "new_total", "supplement_total",
                              "clawback_total", "created_by", "created_at", "approved_by", "approved_at", "paid_by",
                              "paid_at", "voucher_notice")}
    out["lines"] = lines
    out["delta"] = out["new_total"] - out["old_total"]
    if detail:
        appr = bc.parse_json(c["approval_json"], {})
        out["approval"] = {"tiers": appr.get("tiers") or [], "currentTier": appr.get("currentTier") or 0,
                           "requestedBy": appr.get("requestedBy") or ""}
        out["vouchers"] = bc.linked_vouchers(conn, c)
        out["log"] = [dict(r) for r in conn.execute(
            "SELECT changed_by, changed_at, action, detail_json FROM bonus_correction_log WHERE corr_id = ? ORDER BY id",
            (c["id"],))]
        ded = bc.parse_json(c["deductions_json"], {})
        out["deductions"] = ded or None
        out["deductionNotice"] = ""
        if c["status"] == "待補發":
            d, why = _supplement_deductions(conn, c, datetime.now().date().isoformat())
            out["deductions"], out["deductionNotice"] = d, (why if d is None else
                                                            ("有人沒有設定投保金額，無法標記補發（請先設定投保金額）。" if d["missing"] else ""))
            out.update(bonus_api._payout_bank_choices({"status": "待發放"}))
    return out


def _supplement_lines(c):
    return [{"username": l["username"], "amount": int(l["delta"]), "display_name_snapshot": l.get("name") or l["username"]}
            for l in bc.parse_json(c["lines_json"], []) if int(l.get("delta") or 0) > 0]


def _supplement_deductions(conn, c, on_date):
    """補發當日的扣繳試算：只算「補發的那一段」，全年累計含原單與已生效的更正（`ytd_in_motrix`）。"""
    return bonus_deductions.deductions_for_award(conn, {"id": 0}, _supplement_lines(c), on_date)


# ── 讀 ────────────────────────────────────────────────────────────────────────

@router.get("")
def list_corrections(quote_no: str = "", status: str = "", authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        sql, args = "SELECT * FROM bonus_corrections WHERE 1=1", []
        if quote_no:
            sql += " AND quote_no = ?"
            args.append(quote_no)
        if status:
            if status not in bc.STATUSES:
                raise HTTPException(400, "status 只能是：%s" % "、".join(bc.STATUSES))
            sql += " AND status = ?"
            args.append(status)
        rows = [dict(r) for r in conn.execute(sql + " ORDER BY id DESC LIMIT 200", args)]
        items = [v for v in (_view(conn, c, user) for c in rows) if v is not None]
    finally:
        conn.close()
    if not items and not (user.get("role") == "superadmin" or user_has_module(user, "cashier")):
        raise HTTPException(403, "沒有權限檢視獎金更正單。")
    return {"items": items}


@router.get("/current/{quote_no}")
def current_amounts(quote_no: str, authorization: str = Header(None)):
    """開更正單用：原單目前每人金額（原名單＋已完成更正）與可不可以開。最高管理者。"""
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        award, _lines = bonus_api._load_case_award(conn, quote_no)
        if award is None:
            raise HTTPException(404, "這個案件還沒有獎金分潤單。")
        open_row = conn.execute("SELECT corr_no, status FROM bonus_corrections WHERE award_id = ? AND status IN"
                                " ('草稿','待審核','待補發')", (award["id"],)).fetchone()
        cur = bc.effective_amounts(conn, award["id"])
    finally:
        conn.close()
    return {"quoteNo": quote_no, "awardStatus": award["status"], "canCreate": award["status"] == "已發放" and open_row is None,
            "open": dict(open_row) if open_row else None,
            "people": [{"username": u, "name": v["name"], "amount": v["amount"]} for u, v in cur.items()]}


@router.get("/{corr_no}")
def get_correction(corr_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        c = _row(conn, corr_no)
        v = _view(conn, c, user, detail=True)
    finally:
        conn.close()
    if v is None:
        raise HTTPException(404, "找不到這張更正單。")
    return v


# ── 寫：草稿 ──────────────────────────────────────────────────────────────────

@router.post("")
def create_correction(body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    quote_no = ((body or {}).get("quote_no") or "").strip()
    who, now = bonus_api._user_name(user), _now()
    conn = get_db()
    try:
        begin_write(conn)
        award = _paid_award(conn, quote_no)
        try:
            reason = bc.validate_reason((body or {}).get("reason"))
            lines, tot = bc.build_lines(conn, award["id"], (body or {}).get("lines"))
        except bc.CorrectionError as exc:
            raise HTTPException(400, str(exc))
        if conn.execute("SELECT 1 FROM bonus_corrections WHERE award_id = ? AND status IN ('草稿','待審核','待補發')",
                        (award["id"],)).fetchone():
            raise HTTPException(409, "這張獎金分潤已經有一張未結案的更正單，請先處理完。")
        seq = int(conn.execute("SELECT COALESCE(MAX(seq), 0) FROM bonus_corrections WHERE award_id = ?",
                               (award["id"],)).fetchone()[0]) + 1
        corr_no = bc.corr_no_for(quote_no, seq)
        cur = conn.execute(
            "INSERT INTO bonus_corrections (corr_no, quote_no, award_id, seq, status, reason, old_total, new_total,"
            " supplement_total, clawback_total, lines_json, created_by, created_at, updated_by, updated_at)"
            " VALUES (?,?,?,?, '草稿', ?,?,?,?,?,?,?,?,?,?)",
            (corr_no, quote_no, award["id"], seq, reason, tot["old_total"], tot["new_total"], tot["supplement_total"],
             tot["clawback_total"], json.dumps(lines, ensure_ascii=False), who, now, who, now))
        bc.log(conn, cur.lastrowid, who, "create", {"reason": reason, "lines": lines})
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.correction.create", "bonus_corrections", corr_no, "獎金更正單建立")
    return {"ok": True, "corr_no": corr_no, "status": "草稿"}


@router.put("/{corr_no}")
def update_correction(corr_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    who, now = bonus_api._user_name(user), _now()
    conn = get_db()
    try:
        begin_write(conn)
        c = _row(conn, corr_no)
        if c["status"] != "草稿":
            raise HTTPException(409, "只有草稿可以修改，這一張現在是「%s」。" % c["status"])
        try:
            reason = bc.validate_reason((body or {}).get("reason", c["reason"]))
            lines, tot = bc.build_lines(conn, c["award_id"], (body or {}).get("lines"))
        except bc.CorrectionError as exc:
            raise HTTPException(400, str(exc))
        conn.execute("UPDATE bonus_corrections SET reason=?, old_total=?, new_total=?, supplement_total=?, clawback_total=?,"
                     " lines_json=?, updated_by=?, updated_at=? WHERE id=?",
                     (reason, tot["old_total"], tot["new_total"], tot["supplement_total"], tot["clawback_total"],
                      json.dumps(lines, ensure_ascii=False), who, now, c["id"]))
        bc.log(conn, c["id"], who, "update", {"reason": reason, "lines": lines})
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.correction.update", "bonus_corrections", corr_no, "獎金更正單修改")
    return {"ok": True, "status": "草稿"}


@router.post("/{corr_no}/cancel")
def cancel_correction(corr_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    who = bonus_api._user_name(user)
    conn = get_db()
    try:
        begin_write(conn)
        c = _row(conn, corr_no)
        if c["status"] != "草稿":
            raise HTTPException(409, "只有草稿可以作廢，這一張現在是「%s」。" % c["status"])
        conn.execute("UPDATE bonus_corrections SET status='已作廢', updated_by=?, updated_at=? WHERE id=?", (who, _now(), c["id"]))
        bc.log(conn, c["id"], who, "cancel", {"reason": ((body or {}).get("reason") or "").strip()})
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.correction.cancel", "bonus_corrections", corr_no, "獎金更正單作廢")
    return {"ok": True, "status": "已作廢"}


# ── 寫：簽核 ──────────────────────────────────────────────────────────────────

def _notify(kind, corr_no, reason=""):
    """寄信（背景執行緒；失敗只記 log，不回滾狀態）。kind＝submitted／approved／returned。信裡不放金額、不放更正原因以外的資料。"""
    from helpers import email_notify
    conn = get_db()
    try:
        c = _row(conn, corr_no)
        appr = bc.parse_json(c["approval_json"], {})
        award = {"id": c["award_id"]}
        requester = appr.get("requestedBy") or c["created_by"]
        if kind == "submitted":
            who = bonus_payouts.approver_recipients(conn, award, appr, requester)
            fn, args = email_notify.notify_bonus_correction_submitted, (corr_no, c["quote_no"], who)
        elif kind == "approved":
            who = [requester] + (bonus_payouts.cashier_recipients(conn, award) if c["supplement_total"] > 0 else [])
            who = list(dict.fromkeys(w for w in who if w))
            fn, args = email_notify.notify_bonus_correction_approved, (corr_no, c["quote_no"], who, c["supplement_total"] > 0)
        else:
            who = [requester] if requester else []
            fn, args = email_notify.notify_bonus_correction_returned, (corr_no, c["quote_no"], who, reason)
    finally:
        conn.close()
    if not who:
        logger.warning("獎金更正單 %s（%s）沒有可通知的對象", corr_no, kind)
        return
    bonus_api._notify_safely(fn, *args)


@router.post("/{corr_no}/submit")
def submit_correction(corr_no: str, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    who, now = bonus_api._user_name(user), _now()
    conn = get_db()
    try:
        begin_write(conn)
        c = _row(conn, corr_no)
        if c["status"] != "草稿":
            raise HTTPException(409, "只有草稿可以送審，這一張現在是「%s」。" % c["status"])
        tiers = bonus_api._resolve_bonus_tiers(conn, user["username"])
        appr = {"tiers": tiers, "currentTier": 0, "requestedBy": user["username"], "requestedAt": now}
        conn.execute("UPDATE bonus_corrections SET status='待審核', approval_json=?, updated_by=?, updated_at=? WHERE id=?",
                     (json.dumps(appr, ensure_ascii=False), who, now, c["id"]))
        bc.log(conn, c["id"], who, "submit", {"tiers": len(tiers)})
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.correction.submit", "bonus_corrections", corr_no, "獎金更正單送審")
    _notify("submitted", corr_no)
    return {"ok": True, "status": "待審核"}


@router.post("/{corr_no}/approve")
def approve_correction(corr_no: str, authorization: str = Header(None)):
    """走共用簽核引擎（同原單）：有鏈 ⇒ 當層簽核人（或代理人）依序簽；沒鏈 ⇒ superadmin 且不可自簽（唯一最高管理者例外）。
    簽完最後一層 ⇒ 同一個交易內開沖轉＋重開應付傳票草稿（R1），有人要補發 ⇒ 待補發，否則 ⇒ 已完成。"""
    user = _require_user(authorization, require_superadmin=True)
    who, now = bonus_api._user_name(user), _now()
    conn = get_db()
    try:
        begin_write(conn)
        c = _row(conn, corr_no)
        if c["status"] != "待審核":
            raise HTTPException(409, "這張更正單不在簽核流程裡（現在是「%s」）。" % c["status"])
        appr = bc.parse_json(c["approval_json"], {})
        tiers = appr.get("tiers") or []
        done = True
        if tiers:
            ct = int(appr.get("currentTier") or 0)
            ok, code, msg = check_approve_permission(tiers, ct, user["username"], conn)
            if not ok:
                raise HTTPException(code, msg)
            approvers = tiers[ct].get("approvers") or []
            fp = next(a for a in approvers if a.get("status") != "approved")
            fp.update(status="approved", approvedAt=now, approvedBy=who)
            if all(a.get("status") == "approved" for a in approvers):
                appr["currentTier"] = ct + 1
            done = int(appr.get("currentTier") or 0) >= len(tiers)
        else:
            err = check_no_tier_self_approval(conn, appr, user)
            if err:
                raise HTTPException(403, err)
            appr["approvedBy"], appr["approvedAt"] = who, now
        if not done:
            conn.execute("UPDATE bonus_corrections SET approval_json=?, updated_by=?, updated_at=? WHERE id=?",
                         (json.dumps(appr, ensure_ascii=False), who, now, c["id"]))
            bc.log(conn, c["id"], who, "approve", {"status": "待審核"})
            conn.commit()
            nxt, notice = "待審核", ""
        else:
            nxt = "待補發" if c["supplement_total"] > 0 else "已完成"
            conn.execute("UPDATE bonus_corrections SET status=?, approval_json=?, approved_by=?, approved_at=?,"
                         " updated_by=?, updated_at=? WHERE id=?",
                         (nxt, json.dumps(appr, ensure_ascii=False), who, now, who, now, c["id"]))
            c.update(status=nxt, approved_at=now)
            award = _paid_award(conn, c["quote_no"])
            # R1：財務會計／總帳（沖轉＋重開應付傳票草稿）；營運報表的追回（負數支出）在狀態生效的同一刻起讀得到
            notice = bc.open_vouchers(conn, c, award, who, now)
            if notice:
                conn.execute("UPDATE bonus_corrections SET voucher_notice=? WHERE id=?", (notice, c["id"]))
            bc.log(conn, c["id"], who, "approve", {"status": nxt, "notice": notice})
            conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.correction.approve", "bonus_corrections", corr_no, "獎金更正單簽核：%s" % nxt)
    if nxt != "待審核":
        _notify("approved", corr_no)
    else:
        _notify("submitted", corr_no)
    return {"ok": True, "status": nxt, "notice": notice}


@router.post("/{corr_no}/reject")
def reject_correction(corr_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """駁回（待審核）⇒ 草稿。當層簽核人／代理人或 superadmin；必填原因。核准後不可退回（已開沖轉傳票；要再改請另開更正單）。"""
    user = _require_user(authorization, require_superadmin=True)
    reason = ((body or {}).get("reason") or "").strip()
    if not reason:
        raise HTTPException(400, "請填寫駁回原因。")
    who, now = bonus_api._user_name(user), _now()
    conn = get_db()
    try:
        begin_write(conn)
        c = _row(conn, corr_no)
        if c["status"] != "待審核":
            raise HTTPException(409, "只有「待審核」的更正單可以駁回（現在是「%s」）。" % c["status"])
        appr = bc.parse_json(c["approval_json"], {})
        ok, code, msg = check_reject_permission(appr.get("tiers") or [], int(appr.get("currentTier") or 0), user, conn)
        if not ok:
            raise HTTPException(code, msg)
        conn.execute("UPDATE bonus_corrections SET status='草稿', approval_json='{}', updated_by=?, updated_at=? WHERE id=?",
                     (who, now, c["id"]))
        bc.log(conn, c["id"], who, "reject", {"reason": reason, "approval_before": c["approval_json"]})
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.correction.reject", "bonus_corrections", corr_no, "獎金更正單駁回：%s" % reason)
    _notify("returned", corr_no, reason)
    return {"ok": True, "status": "草稿"}


# ── 寫：補發（出納）────────────────────────────────────────────────────────────

@router.post("/{corr_no}/mark-paid")
def mark_supplement_paid(corr_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    """出納標記補發（與原單 mark-paid 同一套：扣繳／補充保費算不出來或有人沒有投保金額 ⇒ **拒絕、狀態不變**）。
    R1：補發支出傳票草稿（財務會計／總帳）、營運報表（補發日列支出）、發放紀錄（出納）。"""
    user = _require_user(authorization)
    if user.get("role") != "superadmin" and not user_has_module(user, "cashier"):
        raise HTTPException(403, "只有出納可以標記補發。")
    bank = ((body or {}).get("bank_account_code") or "").strip()
    who, now = bonus_api._user_name(user), _now()
    conn = get_db()
    try:
        begin_write(conn)
        c = _row(conn, corr_no)
        if c["status"] != "待補發":
            raise HTTPException(409, "只有「待補發」的更正單可以標記補發（現在是「%s」）。" % c["status"])
        if bank and bonus_vouchers.accounting_available():
            err = bonus_vouchers.account_problem(conn, bank)
            if err:
                raise HTTPException(400, "銀行科目：%s" % err)
        ded, why = _supplement_deductions(conn, c, now[:10])
        if ded is None:
            raise HTTPException(409, why + "；未標記補發。")
        if ded["missing"]:
            names = {l["username"]: l.get("name") or l["username"] for l in bc.parse_json(c["lines_json"], [])}
            raise HTTPException(409, "無法計算補充保費：%s 沒有設定投保金額，請先到「獎金分潤 → 投保金額與全年累計」設定。"
                                % "、".join(names.get(u, u) for u in ded["missing"]))
        conn.execute("UPDATE bonus_corrections SET status='已完成', paid_by=?, paid_at=?, deductions_json=?,"
                     " updated_by=?, updated_at=? WHERE id=?",
                     (who, now, json.dumps(ded, ensure_ascii=False), who, now, c["id"]))
        c.update(status="已完成", paid_at=now)
        notice = bc.create_supplement_payment(conn, c, who, now, bank, ded["totals"])
        if notice:
            conn.execute("UPDATE bonus_corrections SET voucher_notice = voucher_notice || ? WHERE id=?",
                         ((" " if c["voucher_notice"] else "") + notice, c["id"]))
        bc.log(conn, c["id"], who, "mark_paid", {"paid_at": now, "deductions": ded["totals"], "notice": notice})
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "bonus.correction.mark_paid", "bonus_corrections", corr_no, "獎金更正單標記補發")
    return {"ok": True, "status": "已完成", "notice": notice, "deductions": ded}
