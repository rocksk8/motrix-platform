"""Quotation CRUD, approval workflow, deal-tag, export endpoints."""
import json
import sqlite3
import threading
from collections import defaultdict
from datetime import datetime
from typing import Optional
from urllib.parse import quote as urlquote

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel

from db import get_db
from helpers import (
    _require_user, _tok, _audit, _notify, _get_setting,
    quote_hot_fields, save_quotation_json, SQL_DEAL_TAG, SQL_SETTLE_STATUS,
)
from archive import _backup_quotation
from pdf_gen import _generate_quotation_pdf, generate_pdf_bytes

router = APIRouter()


# ── Approval tier helpers ─────────────────────────────────────────────────────

import re as _re

def _next_revision_no(quote_no: str) -> str:
    """MQ-202501-001 → MQ-202501-001-R1; MQ-202501-001-R2 → MQ-202501-001-R3"""
    m = _re.match(r'^(MQ-\d{6}-\d{3})(?:-R(\d+))?$', quote_no)
    if not m:
        return quote_no + '-R1'
    base = m.group(1)
    rev  = int(m.group(2) or '0') + 1
    return f'{base}-R{rev}'


def _setting_to_active_tiers(setting: dict) -> list:
    """Convert settings format (tiers or old steps) → list of active tier dicts with status fields."""
    tiers = setting.get("tiers") or []
    if not tiers:
        steps = setting.get("steps") or []
        tiers = [{"order": i, "approvers": [s]} for i, s in enumerate(steps)]
    return [
        {
            "order": t.get("order", i),
            "approvers": [
                {
                    "userId":      a.get("userId"),
                    "username":    a["username"],
                    "displayName": a.get("displayName", a["username"]),
                    "status":      "pending",
                    "approvedAt":  None,
                }
                for a in (t.get("approvers") or [])
            ],
        }
        for i, t in enumerate(tiers)
        if (t.get("approvers") or [])
    ]


def _active_tiers(appr: dict) -> list:
    """Read tiers from active approval object (backward-compat: old steps → single-approver tiers)."""
    tiers = appr.get("tiers") or []
    if tiers:
        return tiers
    steps = appr.get("steps") or []
    return [
        {
            "order": i,
            "approvers": [{
                "userId":      s.get("userId"),
                "username":    s["username"],
                "displayName": s.get("displayName", s["username"]),
                "status":      s.get("status", "pending"),
                "approvedAt":  s.get("approvedAt"),
            }],
        }
        for i, s in enumerate(steps)
    ]


def _current_tier_idx(appr: dict) -> int:
    ct = appr.get("currentTier")
    if ct is None:
        ct = appr.get("currentStep", 0)
    return ct


# ── Models ────────────────────────────────────────────────────────────────────

class QuotationIn(BaseModel):
    quote_no:   Optional[str] = None
    status:     Optional[str] = "草稿"
    data:       dict
    created_by: Optional[str] = None


class QuotationStatusUpdate(BaseModel):
    status: str


class QuotationDealTagUpdate(BaseModel):
    deal_tag:  Optional[str]  = ''
    log_entry: Optional[dict] = None


class CaseRecordUpdate(BaseModel):
    case_record: dict = {}


class ApprovalActionBody(BaseModel):
    approvedByDisplay: Optional[str] = None
    note:              Optional[str]  = None


# ── Quotation sequence ────────────────────────────────────────────────────────

def _peek_next_no(conn, month: str) -> str:
    """Compute next available quote number without reserving it in quote_seq.
    Reservation only happens on actual INSERT (create_quotation)."""
    row_max = conn.execute(
        "SELECT COALESCE(MAX(CAST(SUBSTR(quote_no, 11, 3) AS INTEGER)), 0) AS mx "
        "FROM quotations WHERE quote_no GLOB ? AND LENGTH(quote_no) = 13",
        (f"MQ-{month}-???",)
    ).fetchone()
    db_max = row_max["mx"] if row_max else 0

    row = conn.execute("SELECT seq FROM quote_seq WHERE month=?", (month,)).fetchone()
    next_seq = max(row["seq"] if row else 0, db_max) + 1

    while conn.execute(
        "SELECT 1 FROM quotations WHERE quote_no=?", (f"MQ-{month}-{next_seq:03d}",)
    ).fetchone():
        next_seq += 1

    return f"MQ-{month}-{next_seq:03d}"


@router.get("/api/next-quote-no")
def next_quote_no():
    """Peek-only: returns the next available number without reserving it.
    The number is not guaranteed until the quotation is actually saved."""
    month = datetime.now().strftime("%Y%m")
    conn  = get_db()
    conn.execute(
        "INSERT INTO quote_seq (month, seq) VALUES (?, 0) ON CONFLICT(month) DO NOTHING",
        (month,)
    )
    conn.commit()
    result = _peek_next_no(conn, month)
    conn.close()
    return {"quote_no": result}


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/api/quotations")
def list_quotations(
    status:   Optional[str] = None,
    customer: Optional[str] = None,
    month:    Optional[str] = None,
    deal_tag: Optional[str] = None,
    limit:    int = 100,
    offset:   int = 0,
    authorization: str = Header(None),
):
    user   = _require_user(authorization)
    conn   = get_db()
    sql    = (
        "SELECT id, quote_no, status, customer_name, project_name, total, pretax, "
        "direct_margin_pct, net_margin_pct, sales_person, quote_date, valid_days, "
        f"{SQL_DEAL_TAG} as deal_tag, "
        "created_at, updated_at, "
        "COALESCE(json_array_length(json_extract(data_json, '$.editHistory')), 0) as edit_count, "
        "json_extract(data_json, '$.editHistory') as edit_history_json, "
        f"{SQL_SETTLE_STATUS} as settle_status "
        "FROM quotations WHERE 1=1"
    )
    params = []
    if user["role"] not in ("superadmin", "admin"):
        sql += " AND sales_person=?"; params.append(user["display_name"])
    if status:
        sql += " AND status=?"; params.append(status)
    if customer:
        sql += " AND customer_name LIKE ?"; params.append(f"%{customer}%")
    if month:
        sql += " AND quote_no LIKE ?"; params.append(f"MQ-{month}%")
    if deal_tag:
        tags = [t.strip() for t in deal_tag.split(",")]
        sql += f" AND {SQL_DEAL_TAG} IN (" + ",".join("?" * len(tags)) + ")"
        params.extend(tags)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows  = conn.execute(sql, params).fetchall()
    count = conn.execute(
        "SELECT COUNT(*) FROM quotations WHERE 1=1" + sql[sql.find(" AND"):sql.find(" ORDER")],
        params[:-2]
    ).fetchone()[0] if params[:-2] else conn.execute("SELECT COUNT(*) FROM quotations").fetchone()[0]
    conn.close()
    items = []
    for r in rows:
        row = dict(r)
        eh_json = row.pop("edit_history_json", None)
        edit_last = None
        if eh_json:
            try:
                history = json.loads(eh_json)
                if history and isinstance(history, list):
                    last = history[-1]
                    edit_last = {
                        "rev":       last.get("rev"),
                        "at":        last.get("at", ""),
                        "byDisplay": last.get("byDisplay") or last.get("by", ""),
                        "type":      last.get("type", ""),
                    }
            except Exception:
                pass
        row["edit_last"] = edit_last
        items.append(row)
    return {"total": count, "items": items}


@router.get("/api/quotations/{quote_no}")
def get_quotation(quote_no: str):
    conn = get_db()
    row  = conn.execute("SELECT * FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    result = dict(row)
    result["data"] = json.loads(result.pop("data_json", "{}"))
    result["data"]["status"] = result["status"]   # DB column is authoritative
    return result


@router.post("/api/quotations", status_code=201)
def create_quotation(body: QuotationIn, authorization: str = Header(None)):
    q   = body.data
    now = datetime.now().isoformat()
    month = datetime.now().strftime("%Y%m")
    tot  = q.get("tot", {})
    deal_tag, settle_status = quote_hot_fields(q)
    conn = get_db()

    # Ensure quote_seq row exists for peek helper
    conn.execute(
        "INSERT INTO quote_seq (month, seq) VALUES (?, 0) ON CONFLICT(month) DO NOTHING",
        (month,)
    )

    # Use provisional number from client if provided; otherwise auto-assign
    qno = body.quote_no or q.get("quoteNo") or _peek_next_no(conn, month)

    def _do_insert(no: str):
        q["quoteNo"] = no
        conn.execute("""
            INSERT INTO quotations
              (quote_no, status, customer_name, project_name,
               total, pretax, direct_margin_pct, net_margin_pct,
               sales_person, quote_date, valid_days, data_json,
               created_at, updated_at, created_by, deal_tag, settle_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            no, body.status,
            q.get("customerName"), q.get("projectName"),
            tot.get("total", 0), tot.get("pretax", 0),
            tot.get("directMarginPct", 0), tot.get("netMarginPct", 0),
            q.get("salesPerson"), q.get("quoteDate"), q.get("validDays", 30),
            json.dumps(q, ensure_ascii=False),
            now, now, body.created_by, deal_tag, settle_status,
        ))

    try:
        _do_insert(qno)
    except sqlite3.IntegrityError:
        # Provisional number taken (concurrent save); auto-assign next available
        qno = _peek_next_no(conn, month)
        try:
            _do_insert(qno)
        except sqlite3.IntegrityError:
            conn.close()
            raise HTTPException(409, "報價單號衝突，請重試")

    # Reserve in quote_seq so future peeks don't repeat this number
    seq_no = int(qno.split("-")[-1]) if qno.count("-") == 2 else 0
    if seq_no:
        conn.execute(
            "INSERT INTO quote_seq (month, seq) VALUES (?, ?) "
            "ON CONFLICT(month) DO UPDATE SET seq=MAX(seq, excluded.seq)",
            (month, seq_no)
        )
    conn.commit()
    conn.close()
    threading.Thread(target=_backup_quotation, args=(qno,), daemon=True).start()
    _audit(_tok(authorization), 'quotation.create', 'quotation', qno, f"{qno}（{q.get('customerName','')}）")
    return {"quote_no": qno, "created_at": now}


@router.put("/api/quotations/{quote_no}")
def update_quotation(quote_no: str, body: QuotationIn, authorization: str = Header(None)):
    q   = body.data
    now = datetime.now().isoformat()

    # consume unlock-edit flag before any processing
    is_unlock_edit = bool(q.pop("_isUnlockEdit", False))

    new_status = body.status or q.get("status", "草稿")

    # ── Unlock-edit → append history + force approval flow ────────────────────
    edit_rev = None
    if is_unlock_edit:
        editor = _require_user(authorization)
        history = q.get("editHistory") or []
        if not isinstance(history, list):
            history = []
        edit_rev = len(history) + 1
        history.append({
            "rev":       edit_rev,
            "at":        now,
            "by":        editor["username"],
            "byDisplay": editor["display_name"] or editor["username"],
            "type":      "quote_edit",
        })
        q["editHistory"] = history
        # Force re-approval regardless of current status
        new_status = "待審核"
        q["approval"] = {
            "requestedBy":        editor["username"],
            "requestedByDisplay": editor["display_name"] or editor["username"],
            "requestedAt":        now,
            "isEditApproval":     True,
            "status":             "pending",
            "reasons":            [f"解鎖後修改（v{edit_rev}），需重新簽核"],
        }

    # ── 待審核：build approval tiers from settings ─────────────────────────────
    if new_status == "待審核":
        appr = q.get("approval") or {}
        is_new_submission = not appr.get("requestedAt") or is_unlock_edit
        if not appr.get("tiers") and not appr.get("steps"):
            flow_setting = _get_setting("approval_flow", {"tiers": []}) or {}
            active_tiers = _setting_to_active_tiers(flow_setting)
            if active_tiers:
                appr["tiers"]       = active_tiers
                appr["currentTier"] = 0
        q["approval"] = appr
        if is_new_submission:
            tiers = _active_tiers(appr)
            cname = q.get("customerName") or ""
            label = "（解鎖改版）" if appr.get("isEditApproval") else ""
            msg   = f"報價單 {quote_no}{label}（{cname}）需要您簽核"
            if tiers:
                for a in tiers[0].get("approvers", []):
                    _notify(a["username"], "approval_request", quote_no, quote_no, msg)
            else:
                _conn = get_db()
                admins = _conn.execute(
                    "SELECT username FROM users WHERE role='superadmin' AND active=1"
                ).fetchall()
                _conn.close()
                requester = appr.get("requestedBy") or ""
                for adm in admins:
                    if adm["username"] != requester:
                        _notify(adm["username"], "approval_request", quote_no, quote_no, msg)

    tot = q.get("tot", {})
    deal_tag, settle_status = quote_hot_fields(q)

    conn = get_db()
    existing = conn.execute("SELECT id, status FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    if existing["status"] == "已拒絕":
        conn.close()
        raise HTTPException(403, "已拒絕結案的報價單不可修改")
    conn.execute("""
        UPDATE quotations SET
          status=?, customer_name=?, project_name=?,
          total=?, pretax=?, direct_margin_pct=?, net_margin_pct=?,
          sales_person=?, quote_date=?, valid_days=?,
          data_json=?, updated_at=?, deal_tag=?, settle_status=?
        WHERE quote_no=?
    """, (
        new_status,
        q.get("customerName"), q.get("projectName"),
        tot.get("total", 0), tot.get("pretax", 0),
        tot.get("directMarginPct", 0), tot.get("netMarginPct", 0),
        q.get("salesPerson"), q.get("quoteDate"), q.get("validDays", 30),
        json.dumps(q, ensure_ascii=False), now, deal_tag, settle_status,
        quote_no,
    ))
    conn.commit()
    conn.close()
    threading.Thread(target=_backup_quotation, args=(quote_no,), daemon=True).start()
    if is_unlock_edit:
        _audit(_tok(authorization), 'quotation.unlock_edit', 'quotation', quote_no,
               f"{quote_no}（{q.get('customerName','')}）", {"rev": edit_rev, "pendingApproval": True})
        # save PDF snapshot of this revision (includes editor name in filename)
        editor_display = (q.get("editHistory") or [{}])[-1].get("byDisplay", "")
        threading.Thread(
            target=_generate_quotation_pdf,
            args=(quote_no, editor_display, '修改'),
            daemon=True
        ).start()
    else:
        _audit(_tok(authorization), 'quotation.update', 'quotation', quote_no,
               f"{quote_no}（{q.get('customerName','')}）")
    return {"quote_no": quote_no, "updated_at": now, "status": new_status}


@router.patch("/api/quotations/{quote_no}/status")
def update_status(quote_no: str, body: QuotationStatusUpdate, authorization: str = Header(None)):
    conn = get_db()
    row = conn.execute("SELECT customer_name FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    cname = row['customer_name'] or ''
    conn.execute("UPDATE quotations SET status=?, updated_at=? WHERE quote_no=?",
                 (body.status, datetime.now().isoformat(), quote_no))
    conn.commit()
    conn.close()
    action_map = {'待審核': 'quotation.submit', '已送出': 'quotation.approve'}
    action = action_map.get(body.status, 'quotation.status_change')
    _audit(_tok(authorization), action, 'quotation', quote_no, f"{quote_no}（{cname}）", {'status': body.status})
    if body.status == '已送出':
        try:
            actor_u = _require_user(authorization)
            actor_name = actor_u.get("display_name") or actor_u.get("username") or ""
        except Exception:
            actor_name = ""
        threading.Thread(target=_generate_quotation_pdf, args=(quote_no, actor_name, '已簽核'), daemon=True).start()
    return {"ok": True}


@router.patch("/api/quotations/{quote_no}/deal-tag")
def update_deal_tag(quote_no: str, body: QuotationDealTagUpdate, authorization: str = Header(None)):
    user = _require_user(authorization)
    # 未成案 / 已成案 限管理員以上
    if body.deal_tag in ("未成案", "已成案") and user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員以上可標記「未成案」或「已成案」")
    conn = get_db()
    row = conn.execute("SELECT data_json, customer_name FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    cname = row['customer_name'] or ''
    d = json.loads(row["data_json"] or "{}")
    old_tag = d.get("dealTag", "")
    d["dealTag"] = body.deal_tag or ''
    if body.log_entry:
        if "statusLog" not in d or not isinstance(d["statusLog"], list):
            d["statusLog"] = []
        d["statusLog"].append(body.log_entry)
    save_quotation_json(conn, quote_no, d)
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'deal_tag.change', 'quotation', quote_no,
           f"{quote_no}（{cname}）", {'from': old_tag, 'to': body.deal_tag})
    if body.deal_tag == '已結案':
        try:
            actor_u = _require_user(authorization)
            actor_name = actor_u.get("display_name") or actor_u.get("username") or ""
        except Exception:
            actor_name = ""
        threading.Thread(target=_generate_quotation_pdf, args=(quote_no, actor_name, '結案'), daemon=True).start()
    return {"ok": True}


@router.delete("/api/quotations/{quote_no}")
def delete_quotation(quote_no: str, authorization: str = Header(None)):
    conn = get_db()
    row = conn.execute("SELECT customer_name FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    cname = row['customer_name'] or ''
    conn.execute("DELETE FROM quotations WHERE quote_no=?", (quote_no,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'quotation.delete', 'quotation', quote_no, f"{quote_no}（{cname}）")
    return {"ok": True}


@router.patch("/api/quotations/{quote_no}/case-record")
def update_case_record(quote_no: str, body: CaseRecordUpdate, authorization: str = Header(None)):
    conn = get_db()
    row = conn.execute(
        "SELECT id, customer_name, project_name, data_json, updated_at FROM quotations WHERE quote_no=?",
        (quote_no,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    # Optimistic lock: client may send expectedUpdatedAt to avoid silent overwrite
    expected = (body.case_record or {}).pop("_expectedUpdatedAt", None) if isinstance(body.case_record, dict) else None
    if expected and row["updated_at"] and expected != row["updated_at"]:
        conn.close()
        raise HTTPException(409, "案件資料已被其他人更新，請重新載入後再存")
    label = f"{quote_no}（{row['customer_name'] or ''}{'／' if row['project_name'] else ''}{row['project_name'] or ''}）"
    data = json.loads(row["data_json"] or "{}")
    data["caseRecord"] = body.case_record or {}
    now = save_quotation_json(conn, quote_no, data)
    conn.commit()
    conn.close()
    threading.Thread(target=_backup_quotation, args=(quote_no,), daemon=True).start()
    _audit(_tok(authorization), 'case.update', 'quotation', quote_no, label)
    return {"ok": True, "updated_at": now}


@router.post("/api/quotations/{quote_no}/export")
def record_export(quote_no: str, mode: str = "external", authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row  = conn.execute("SELECT export_count, export_log FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    log   = json.loads(row["export_log"] or "[]")
    count = (row["export_count"] or 0) + 1
    log.append({
        "at": datetime.now().isoformat(),
        "mode": mode,
        "user": user["username"],
        "userDisplay": user.get("display_name") or user["username"],
        "count": count,
    })
    conn.execute("UPDATE quotations SET export_count=?, export_log=? WHERE quote_no=?",
                 (count, json.dumps(log, ensure_ascii=False), quote_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'quotation.export_pdf', 'quotation', quote_no,
           f"{quote_no} PDF 匯出（{mode}）by {user['username']}")
    return {"export_count": count, "log": log}


# ── Payment ───────────────────────────────────────────────────────────────────

@router.patch("/api/quotations/{no}/payment/{idx}")
def mark_payment(no: str, idx: int, body: dict, authorization: str = Header(None)):
    conn = get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()
        if not row:
            raise HTTPException(404, "報價單不存在")
        data = json.loads(row["data_json"] or "{}")
        cr   = data.setdefault("caseRecord", {})
        pay  = cr.setdefault("payment", {})
        pits = pay.setdefault("items", [])
        if idx < 0 or idx >= len(pits):
            raise HTTPException(400, "款項索引超出範圍")
        if "received" in body:
            is_rcv = bool(body["received"])
            pits[idx]["received"]   = is_rcv
            pits[idx]["receivedAt"] = body.get("receivedAt", "") if is_rcv else ""
            pits[idx]["receivedBy"] = body.get("receivedBy", "") if is_rcv else ""
            if is_rcv:
                pits[idx]["actualAmount"] = body.get("actualAmount")
                pits[idx]["feeAmount"]    = body.get("feeAmount") or 0
                pits[idx]["feeNote"]      = body.get("feeNote", "")
                pits[idx]["note"]         = body.get("note", "")
            else:
                for k in ("actualAmount", "feeAmount", "feeNote", "note"):
                    pits[idx].pop(k, None)
        if "invoiceNo" in body:
            pits[idx]["invoiceNo"] = body["invoiceNo"]
        now = save_quotation_json(conn, no, data)
        conn.commit()
    finally:
        conn.close()
    threading.Thread(target=_backup_quotation, args=(no,), daemon=True).start()
    label = pits[idx].get('label', f'第{idx+1}期')
    fee   = pits[idx].get("feeAmount") or 0
    action_detail = (
        f'標記收款（手續費 {fee:,}）' if body.get('received') and fee
        else ('標記收款' if body.get('received') else '取消收款')
    )
    _audit(_tok(authorization), 'payment.mark', 'quotation', no, f"{no} {label}（{action_detail}）")
    return {"ok": True, "updated_at": now}


# ── Settlement ────────────────────────────────────────────────────────────────

class SettlementIn(BaseModel):
    settlement: dict


@router.get("/api/quotations/{quote_no}/settlement")
def get_settlement(quote_no: str, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    data = json.loads(row["data_json"] or "{}")
    return {"settlement": data.get("settlement", None), "items": data.get("items", []),
            "tot": data.get("tot", {}), "customerName": data.get("customerName", ""),
            "projectName": data.get("projectName", "")}


@router.put("/api/quotations/{quote_no}/settlement")
def update_settlement(quote_no: str, body: SettlementIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    now  = datetime.now().isoformat()
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在")
    data = json.loads(row["data_json"] or "{}")
    data["settlement"] = body.settlement

    # append edit history entry for settlement saves
    is_finalized = body.settlement.get("status") == "finalized"
    history = data.get("editHistory") or []
    if not isinstance(history, list):
        history = []
    settle_rev = len(history) + 1
    history.append({
        "rev":       settle_rev,
        "at":        now,
        "by":        user["username"],
        "byDisplay": user["display_name"] or user["username"],
        "type":      "settlement_finalized" if is_finalized else "settlement_draft",
    })
    data["editHistory"] = history

    now = save_quotation_json(conn, quote_no, data, updated_at=now)
    conn.commit()
    conn.close()
    cname = row["customer_name"] or ""
    threading.Thread(target=_backup_quotation, args=(quote_no,), daemon=True).start()
    _audit(_tok(authorization), 'quotation.settlement', 'quotation', quote_no,
           f"{quote_no}（{cname}）成本精算{'完結' if is_finalized else '更新'}",
           {"rev": settle_rev})
    return {"ok": True, "updated_at": now}


# ── Approval queue ────────────────────────────────────────────────────────────

@router.get("/api/approval-queue")
def get_approval_queue(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("""
        SELECT quote_no, customer_name, project_name, total, quote_date, sales_person,
               json_extract(data_json,'$.approval') as approval_json
        FROM quotations
        WHERE status='待審核'
        ORDER BY id DESC
    """).fetchall()
    conn.close()

    items = []
    for r in rows:
        try:
            appr = json.loads(r["approval_json"] or "{}")
        except Exception:
            appr = {}
        tiers   = _active_tiers(appr)
        ct_idx  = _current_tier_idx(appr)
        cur_tier_approvers = []
        if tiers and ct_idx < len(tiers):
            cur_tier_approvers = tiers[ct_idx].get("approvers") or []
        items.append({
            "quoteNo":             r["quote_no"],
            "customer":            r["customer_name"] or "",
            "projectName":         r["project_name"] or "",
            "total":               r["total"] or 0,
            "quoteDate":           r["quote_date"] or "",
            "salesPerson":         r["sales_person"] or "",
            "requestedBy":         appr.get("requestedBy") or "",
            "requestedByDisplay":  appr.get("requestedByDisplay") or appr.get("requestedBy") or "",
            "requestedAt":         appr.get("requestedAt") or "",
            "isEditApproval":      appr.get("isEditApproval", False),
            "reasons":             appr.get("reasons") or [],
            "tiers":               tiers,
            "currentTier":         ct_idx,
            "tierCount":           len(tiers),
            "currentApprovers":    cur_tier_approvers,
        })

    groups: dict = defaultdict(list)
    for item in items:
        groups[item["requestedBy"]].append(item)

    queue = []
    for username, group_items in groups.items():
        group_items.sort(key=lambda x: x["requestedAt"])
        queue.append({
            "requestedBy":        username,
            "requestedByDisplay": group_items[0]["requestedByDisplay"] if group_items else username,
            "count":              len(group_items),
            "items":              group_items,
        })
    queue.sort(key=lambda g: g["items"][0]["requestedAt"] if g["items"] else "")

    return {"queue": queue, "total": len(items)}


@router.post("/api/quotations/{quote_no}/approve")
def approve_quotation(quote_no: str, body: ApprovalActionBody, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM quotations WHERE quote_no=? AND status IN ('待審核','簽核中')",
        (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在或不在待審核狀態")
    cname = row["customer_name"] or ""
    d     = json.loads(row["data_json"] or "{}")
    appr  = d.get("approval") or {}
    tiers = _active_tiers(appr)
    now   = datetime.now().isoformat()

    if tiers:
        ct_idx = _current_tier_idx(appr)
        if ct_idx >= len(tiers):
            conn.close()
            raise HTTPException(400, "所有層已完成")
        tier      = tiers[ct_idx]
        approvers = tier.get("approvers") or []

        # find this user in current tier
        my_entry = next(
            (a for a in approvers if a["username"] == user["username"] and a.get("status") != "approved"),
            None
        )
        if not my_entry:
            pending_names = "、".join(
                a.get("displayName") or a["username"] for a in approvers if a.get("status") != "approved"
            ) or "（無待簽核人員）"
            conn.close()
            raise HTTPException(403, f"此層需由以下人員簽核：{pending_names}")

        my_entry["status"]     = "approved"
        my_entry["approvedAt"] = now

        tier_done = all(a.get("status") == "approved" for a in approvers)
        if tier_done:
            appr["currentTier"] = ct_idx + 1
            all_done = (ct_idx + 1) >= len(tiers)
            if not all_done:
                next_tier = tiers[ct_idx + 1]
                for na in next_tier.get("approvers") or []:
                    _notify(na["username"], "approval_request", quote_no, quote_no,
                            f"報價單 {quote_no}（{cname}）輪到您簽核（第 {ct_idx + 2} 層 / 共 {len(tiers)} 層）")
        else:
            all_done = False

        # write back tiers
        appr["tiers"] = tiers
        appr.pop("steps", None)
        appr.pop("currentStep", None)
        detail_status = f"第 {ct_idx + 1} 層 {my_entry.get('displayName', user['username'])} 已簽核"
    else:
        # no configured tiers — fallback: any superadmin
        if user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "僅超級管理員可執行此操作")
        if appr.get("requestedBy") == user["username"]:
            conn.close()
            raise HTTPException(403, "申請人不得自行審核")
        all_done      = True
        detail_status = "超級管理員簽核"

    if all_done:
        appr["approvedBy"]        = user["username"]
        appr["approvedByDisplay"] = body.approvedByDisplay or user.get("display_name") or user["username"]
        appr["approvedAt"]        = now
        appr["status"]            = "approved"
        d["approval"] = appr
        save_quotation_json(conn, quote_no, d, status="已送出", updated_at=now)
        approver_name = appr.get("approvedByDisplay") or user.get("display_name") or user.get("username") or ""
        threading.Thread(target=_generate_quotation_pdf, args=(quote_no, approver_name, '簽核'), daemon=True).start()
        detail_status = "已送出"
    else:
        d["approval"] = appr
        # 若 tier 已推進（至少一層完成但未全部通過）→ 顯示「簽核中」
        new_status = "簽核中" if (appr.get("currentTier") or 0) > 0 else None
        save_quotation_json(conn, quote_no, d, status=new_status, updated_at=now)

    conn.commit()
    conn.close()
    _audit(_tok(authorization), "quotation.approve", "quotation", quote_no,
           f"{quote_no}（{cname}）", {"allDone": all_done, "status": detail_status})
    return {"ok": True, "allDone": all_done}


@router.post("/api/quotations/{quote_no}/reject")
def reject_quotation(quote_no: str, body: ApprovalActionBody, authorization: str = Header(None)):
    """退回修改：清除簽核、單號升版（-Rn）、狀態回草稿，申請人可重新編輯後再送審。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM quotations WHERE quote_no=? AND status IN ('待審核','簽核中')",
        (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在或不在待審核狀態")
    cname = row["customer_name"] or ""
    d     = json.loads(row["data_json"] or "{}")
    appr  = d.get("approval") or {}
    tiers = _active_tiers(appr)

    if tiers:
        ct_idx    = _current_tier_idx(appr)
        tier      = tiers[ct_idx] if ct_idx < len(tiers) else {}
        approvers = tier.get("approvers") or []
        is_in_tier = any(a["username"] == user["username"] for a in approvers)
        if not is_in_tier and user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "無退回權限（非當層簽核人員）")
    else:
        if user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "僅超級管理員可執行此操作")

    new_no = _next_revision_no(quote_no)
    note   = body.note or ""
    now    = datetime.now().isoformat()

    # Append to statusLog
    if not isinstance(d.get("statusLog"), list):
        d["statusLog"] = []
    d["statusLog"].append({
        "at":   now,
        "user": user.get("display_name") or user["username"],
        "from": "待審核",
        "to":   f"草稿（退回，改為 {new_no}）",
        "note": note,
    })
    # Update quoteNo and status in data_json too
    d["quoteNo"] = new_no
    d["status"]  = "草稿"
    d.pop("approval", None)

    conn.execute(
        "UPDATE quotations SET quote_no=?, status='草稿', data_json=?, updated_at=? WHERE quote_no=?",
        (new_no, json.dumps(d, ensure_ascii=False), now, quote_no)
    )
    conn.commit()

    requester = appr.get("requestedBy")
    if requester:
        _notify(requester, "approval_returned", new_no, new_no,
                f"報價單 {new_no}（原 {quote_no}，{cname}）已退回修改，請確認後重新送審")
    conn.close()
    _audit(_tok(authorization), "quotation.return", "quotation", new_no,
           f"{new_no}（原 {quote_no}，{cname}）", {"note": note, "previous_no": quote_no})
    return {"ok": True, "new_quote_no": new_no}


@router.post("/api/quotations/{quote_no}/reject-final")
def reject_final_quotation(quote_no: str, body: ApprovalActionBody, authorization: str = Header(None)):
    """拒絕結案：永久鎖定，不可再修改或送審。"""
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM quotations WHERE quote_no=? AND status IN ('待審核','簽核中')",
        (quote_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"報價單 {quote_no} 不存在或不在待審核狀態")
    cname = row["customer_name"] or ""
    d     = json.loads(row["data_json"] or "{}")
    appr  = d.get("approval") or {}
    tiers = _active_tiers(appr)

    if tiers:
        ct_idx    = _current_tier_idx(appr)
        tier      = tiers[ct_idx] if ct_idx < len(tiers) else {}
        approvers = tier.get("approvers") or []
        is_in_tier = any(a["username"] == user["username"] for a in approvers)
        if not is_in_tier and user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "無拒絕權限（非當層簽核人員）")
    else:
        if user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "僅超級管理員可執行此操作")

    note = body.note or ""
    now  = datetime.now().isoformat()
    d["rejection"] = {
        "rejectedBy":        user["username"],
        "rejectedByDisplay": user.get("display_name") or user["username"],
        "rejectedAt":        now,
        "note":              note,
    }
    if not isinstance(d.get("statusLog"), list):
        d["statusLog"] = []
    d["statusLog"].append({
        "at":   now,
        "user": user.get("display_name") or user["username"],
        "from": "待審核",
        "to":   "已拒絕",
        "note": note,
    })

    save_quotation_json(conn, quote_no, d, status="已拒絕", updated_at=now)
    conn.commit()

    requester = appr.get("requestedBy")
    if requester:
        suffix = f"：{note}" if note else ""
        _notify(requester, "approval_rejected", quote_no, quote_no,
                f"報價單 {quote_no}（{cname}）已被拒絕結案{suffix}")
    conn.close()
    _audit(_tok(authorization), "quotation.reject_final", "quotation", quote_no,
           f"{quote_no}（{cname}）", {"note": note})
    return {"ok": True}


@router.get("/api/quotations/{quote_no}/pdf-download")
def download_quotation_pdf(quote_no: str, internal: bool = False, authorization: str = Header(None)):
    """後端 Edge Headless 產生 PDF 並直接下載（internal=true 含成本），避免 macOS/瀏覽器列印頁首干擾。"""
    _require_user(authorization)
    conn = get_db()
    row  = conn.execute("SELECT quote_no FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "報價單不存在")
    try:
        pdf_bytes = generate_pdf_bytes(quote_no, internal=internal)
    except ValueError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"PDF 產生失敗：{e}")
    mode_label = "內部版" if internal else "對外版"
    _audit(_tok(authorization), "quotation.export_pdf", "quotation", quote_no,
           f"{quote_no} {mode_label} PDF 下載", {"mode": "internal" if internal else "external", "via": "server"})
    fname = f"{quote_no}_內部.pdf" if internal else f"{quote_no}.pdf"
    encoded = urlquote(fname)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )
