"""出貨單（Shipping/Delivery Note）：CRUD + 獨立簽核流程 + PDF + 回簽歷程。

案件管理的子項目，一個報價單（quote_no）可對應多張出貨單（分批出貨）。
簽核流程獨立於報價單（system_settings key: shipping_approval_flow），
機制比照報價單簽核（tiers 依序簽核）但故意簡化：無改版號的退回機制。
"""
import json
import threading
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote as urlquote

from fastapi import APIRouter, Body, HTTPException, Header
from fastapi.responses import Response
from pydantic import BaseModel

from db import get_db, next_entity_code, spawn_bg_thread
from helpers import _require_user, _tok, _audit, _notify, _get_setting, _set_setting
from pdf_gen import generate_shipping_pdf_bytes, _generate_shipping_pdf

router = APIRouter()


# ── Models ────────────────────────────────────────────────────────────────────

class ShippingNoteIn(BaseModel):
    quote_no:         str
    ship_date:        Optional[str]  = ''
    customer_name:    Optional[str]  = ''
    project_name:     Optional[str]  = ''
    recipient:        Optional[str]  = ''
    delivery_address: Optional[str]  = ''
    items:            Optional[list] = []
    notes:            Optional[str]  = ''


class ApprovalFlowApprover(BaseModel):
    userId:      int
    username:    str
    displayName: str

class ApprovalFlowTier(BaseModel):
    order:     int = 0
    approvers: List[ApprovalFlowApprover] = []

class ApprovalFlowSettings(BaseModel):
    tiers: List[ApprovalFlowTier] = []


# ── Approval tier helpers（獨立於報價單，不共用 quotations.py 邏輯）───────────

def _setting_to_active_tiers(setting: dict) -> list:
    tiers = setting.get("tiers") or []
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
    return appr.get("tiers") or []


def _current_tier_idx(appr: dict) -> int:
    return appr.get("currentTier") or 0


def _require_admin(user: dict):
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")


def _note_public(row, include_items: bool = True) -> dict:
    """Map DB row → camelCase API shape (mirrors vendor_contractors.py's _dispatch_row,
    the closest precedent consumed by this same case-management.js file)."""
    d = dict(row)
    items = json.loads(d.get("items_json") or "[]")
    approval = (json.loads(d.get("data_json") or "{}") or {}).get("approval") or {}
    out = {
        "id":              d["id"],
        "noteNo":          d["note_no"],
        "quoteNo":         d["quote_no"],
        "status":          d["status"] or "草稿",
        "shipDate":        d.get("ship_date") or "",
        "customerName":    d.get("customer_name") or "",
        "projectName":     d.get("project_name") or "",
        "recipient":       d.get("recipient") or "",
        "deliveryAddress": d.get("delivery_address") or "",
        "notes":           d.get("notes") or "",
        "itemCount":       len(items),
        "isSigned":        bool(d.get("is_signed")),
        "signedBy":        d.get("signed_by") or "",
        "signedAt":        d.get("signed_at") or "",
        "signedLog":       json.loads(d.get("signed_log") or "[]"),
        "exportCount":     d.get("export_count") or 0,
        "exportLog":       json.loads(d.get("export_log") or "[]"),
        "approval":        approval,
        "createdBy":       d.get("created_by") or "",
        "createdAt":       d.get("created_at") or "",
        "updatedAt":       d.get("updated_at") or "",
    }
    if include_items:
        out["items"] = items
    return out


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/api/shipping-notes")
def list_shipping_notes(quote_no: Optional[str] = None, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    if quote_no:
        rows = conn.execute(
            "SELECT * FROM shipping_notes WHERE quote_no=? ORDER BY created_at DESC",
            (quote_no,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM shipping_notes ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    conn.close()
    return [_note_public(r, include_items=False) for r in rows]


@router.get("/api/shipping-notes/{note_no}")
def get_shipping_note(note_no: str, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM shipping_notes WHERE note_no=?", (note_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"出貨單 {note_no} 不存在")
    return _note_public(row, include_items=True)


@router.post("/api/shipping-notes", status_code=201)
def create_shipping_note(body: ShippingNoteIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    now  = datetime.now().isoformat()
    conn = get_db()
    q = conn.execute(
        "SELECT customer_name, project_name FROM quotations WHERE quote_no=?", (body.quote_no,)
    ).fetchone()
    if not q:
        conn.close()
        raise HTTPException(404, "找不到關聯的報價單")
    customer_name = (body.customer_name or '').strip() or (q["customer_name"] or "")
    project_name  = (body.project_name or '').strip() or (q["project_name"] or "")
    note_no = next_entity_code(conn, "shipping_notes", "DN", code_col="note_no")
    conn.execute(
        "INSERT INTO shipping_notes "
        "(note_no, quote_no, status, ship_date, customer_name, project_name, recipient, "
        "delivery_address, items_json, notes, data_json, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (note_no, body.quote_no, "草稿", body.ship_date or "", customer_name, project_name,
         body.recipient or "", body.delivery_address or "",
         json.dumps(body.items or [], ensure_ascii=False), body.notes or "", "{}",
         user["username"], now, now)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "shipping.create", "shipping_note", note_no, f"{note_no}（{customer_name}）")
    return {"note_no": note_no, "created_at": now}


@router.put("/api/shipping-notes/{note_no}")
def update_shipping_note(note_no: str, body: ShippingNoteIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute("SELECT status FROM shipping_notes WHERE note_no=?", (note_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "出貨單不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可編輯")
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE shipping_notes SET ship_date=?, customer_name=?, project_name=?, recipient=?, "
        "delivery_address=?, items_json=?, notes=?, updated_at=? WHERE note_no=?",
        (body.ship_date or "", body.customer_name or "", body.project_name or "", body.recipient or "",
         body.delivery_address or "", json.dumps(body.items or [], ensure_ascii=False),
         body.notes or "", now, note_no)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "shipping.update", "shipping_note", note_no, note_no)
    return {"ok": True, "updated_at": now}


@router.delete("/api/shipping-notes/{note_no}")
def delete_shipping_note(note_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute("SELECT status FROM shipping_notes WHERE note_no=?", (note_no,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "出貨單不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可刪除")
    conn.execute("DELETE FROM shipping_notes WHERE note_no=?", (note_no,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "shipping.delete", "shipping_note", note_no, note_no)
    return {"ok": True}


# ── 簽核流程 ──────────────────────────────────────────────────────────────────

@router.post("/api/shipping-notes/{note_no}/submit")
def submit_shipping_note(note_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute(
        "SELECT status, data_json, customer_name, items_json FROM shipping_notes WHERE note_no=?",
        (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "出貨單不存在")
    if row["status"] != "草稿":
        conn.close()
        raise HTTPException(409, "僅草稿狀態可送出審核")
    items = json.loads(row["items_json"] or "[]")
    if not any((it.get("description") or "").strip() for it in items if it.get("type") != "header"):
        conn.close()
        raise HTTPException(400, "至少需要一項品項說明")

    cname = row["customer_name"] or ""
    d     = json.loads(row["data_json"] or "{}")
    now   = datetime.now().isoformat()

    flow_setting = _get_setting("shipping_approval_flow", {"tiers": []}) or {}
    active_tiers = _setting_to_active_tiers(flow_setting)
    d["approval"] = {
        "requestedBy":        user["username"],
        "requestedByDisplay": user.get("display_name") or user["username"],
        "requestedAt":        now,
        "tiers":              active_tiers,
        "currentTier":        0,
    }

    if active_tiers:
        for a in active_tiers[0].get("approvers") or []:
            _notify(a["username"], "shipping_approval_request", note_no, note_no,
                    f"出貨單 {note_no}（{cname}）需要您簽核")

    conn.execute(
        "UPDATE shipping_notes SET status='待審核', data_json=?, updated_at=? WHERE note_no=?",
        (json.dumps(d, ensure_ascii=False), now, note_no)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "shipping.submit", "shipping_note", note_no, f"{note_no}（{cname}）",
           {"tierCount": len(active_tiers)})
    return {"ok": True, "status": "待審核"}


@router.post("/api/shipping-notes/{note_no}/approve")
def approve_shipping_note(note_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM shipping_notes WHERE note_no=? AND status IN ('待審核','簽核中')",
        (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"出貨單 {note_no} 不存在或不在待審核狀態")
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

        is_in_tier = any(a["username"] == user["username"] for a in approvers)
        if not is_in_tier:
            conn.close()
            raise HTTPException(403, "此層無您的簽核權限")

        first_pending = next((a for a in approvers if a.get("status") != "approved"), None)
        if not first_pending:
            conn.close()
            raise HTTPException(400, "此層所有簽核人員已完成")
        if first_pending["username"] != user["username"]:
            next_name = first_pending.get("displayName") or first_pending["username"]
            conn.close()
            raise HTTPException(403, f"請等待 {next_name} 先完成簽核（簽核順序固定）")

        first_pending["status"]     = "approved"
        first_pending["approvedAt"] = now

        tier_done = all(a.get("status") == "approved" for a in approvers)
        if tier_done:
            appr["currentTier"] = ct_idx + 1
            all_done = (ct_idx + 1) >= len(tiers)
            if not all_done:
                for na in tiers[ct_idx + 1].get("approvers") or []:
                    _notify(na["username"], "shipping_approval_request", note_no, note_no,
                            f"出貨單 {note_no}（{cname}）輪到您簽核（第 {ct_idx + 2} 層 / 共 {len(tiers)} 層）")
        else:
            all_done = False

        appr["tiers"] = tiers
        detail_status = f"第 {ct_idx + 1} 層 {first_pending.get('displayName', user['username'])} 已簽核"
    else:
        if user["role"] != "superadmin":
            conn.close()
            raise HTTPException(403, "僅超級管理員可執行此操作")
        _global_flow  = _get_setting("shipping_approval_flow", {"tiers": []}) or {}
        _global_tiers = _setting_to_active_tiers(_global_flow)
        if _global_tiers:
            conn.close()
            raise HTTPException(403, "系統已設定簽核流程，此出貨單缺少簽核層資料，請重新送審")
        all_done      = True
        detail_status = "超級管理員簽核"

    if all_done:
        appr["approvedBy"]        = user["username"]
        appr["approvedByDisplay"] = user.get("display_name") or user["username"]
        appr["approvedAt"]        = now
        appr["status"]            = "approved"
        d["approval"] = appr
        conn.execute(
            "UPDATE shipping_notes SET status='已核准', data_json=?, updated_at=? WHERE note_no=?",
            (json.dumps(d, ensure_ascii=False), now, note_no)
        )
        conn.commit()
        approver_name = appr.get("approvedByDisplay") or user["username"]
        spawn_bg_thread(_generate_shipping_pdf, args=(note_no, approver_name, '簽核'))
        requester = appr.get("requestedBy")
        if requester:
            _notify(requester, "shipping_approved", note_no, note_no, f"出貨單 {note_no}（{cname}）已核准")
        detail_status = "已核准"
    else:
        d["approval"] = appr
        new_status = "簽核中" if (appr.get("currentTier") or 0) > 0 else "待審核"
        conn.execute(
            "UPDATE shipping_notes SET status=?, data_json=?, updated_at=? WHERE note_no=?",
            (new_status, json.dumps(d, ensure_ascii=False), now, note_no)
        )
        conn.commit()

    conn.close()
    _audit(_tok(authorization), "shipping.approve", "shipping_note", note_no, f"{note_no}（{cname}）",
           {"allDone": all_done, "status": detail_status})
    return {"ok": True, "allDone": all_done}


@router.post("/api/shipping-notes/{note_no}/reject")
def reject_shipping_note(note_no: str, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    note = (body or {}).get("note", "")
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, customer_name FROM shipping_notes WHERE note_no=? AND status IN ('待審核','簽核中')",
        (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"出貨單 {note_no} 不存在或不在待審核狀態")
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

    now       = datetime.now().isoformat()
    requester = appr.get("requestedBy")
    d.pop("approval", None)
    conn.execute(
        "UPDATE shipping_notes SET status='草稿', data_json=?, updated_at=? WHERE note_no=?",
        (json.dumps(d, ensure_ascii=False), now, note_no)
    )
    conn.commit()
    conn.close()
    if requester:
        msg = f"出貨單 {note_no}（{cname}）已退回，請確認後重新送審" + (f"：{note}" if note else "")
        _notify(requester, "shipping_returned", note_no, note_no, msg)
    _audit(_tok(authorization), "shipping.reject", "shipping_note", note_no, f"{note_no}（{cname}）", {"note": note})
    return {"ok": True}


# ── PDF / 匯出紀錄 ────────────────────────────────────────────────────────────

@router.get("/api/shipping-notes/{note_no}/pdf-download")
def download_shipping_pdf(note_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute("SELECT note_no FROM shipping_notes WHERE note_no=?", (note_no,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "出貨單不存在")
    try:
        pdf_bytes = generate_shipping_pdf_bytes(note_no)
    except ValueError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"PDF 產生失敗：{e}")
    encoded = urlquote(f"{note_no}.pdf")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"}
    )


@router.post("/api/shipping-notes/{note_no}/export")
def record_shipping_export(note_no: str, mode: str = "external", authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute(
        "SELECT export_count, export_log FROM shipping_notes WHERE note_no=?", (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, f"出貨單 {note_no} 不存在")
    log   = json.loads(row["export_log"] or "[]")
    count = (row["export_count"] or 0) + 1
    log.append({
        "at": datetime.now().isoformat(),
        "mode": mode,
        "user": user["username"],
        "userDisplay": user.get("display_name") or user["username"],
        "count": count,
    })
    conn.execute("UPDATE shipping_notes SET export_count=?, export_log=? WHERE note_no=?",
                 (count, json.dumps(log, ensure_ascii=False), note_no))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "shipping.export_pdf", "shipping_note", note_no,
           f"{note_no} PDF 匯出（{mode}）by {user['username']}")
    return {"export_count": count, "log": log}


# ── 已回簽 toggle ─────────────────────────────────────────────────────────────

@router.post("/api/shipping-notes/{note_no}/signed-toggle")
def toggle_signed(note_no: str, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    action = (body or {}).get("action", "")
    note   = (body or {}).get("note", "")
    if action not in ("sign", "unsign"):
        raise HTTPException(400, "action 必須為 sign 或 unsign")
    conn = get_db()
    row = conn.execute(
        "SELECT status, is_signed, signed_log FROM shipping_notes WHERE note_no=?", (note_no,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "出貨單不存在")
    if row["status"] != "已核准":
        conn.close()
        raise HTTPException(409, "僅已核准狀態可標記回簽")
    is_signed = bool(row["is_signed"])
    if action == "sign" and is_signed:
        conn.close()
        raise HTTPException(409, "已回簽，無需重複標記")
    if action == "unsign" and not is_signed:
        conn.close()
        raise HTTPException(409, "尚未回簽")

    now = datetime.now().isoformat()
    log = json.loads(row["signed_log"] or "[]")
    log.append({
        "at":          now,
        "user":        user["username"],
        "username":    user["username"],
        "userDisplay": user.get("display_name") or user["username"],
        "action":      "signed" if action == "sign" else "unsigned",
        "note":        note,
    })
    if action == "sign":
        conn.execute(
            "UPDATE shipping_notes SET is_signed=1, signed_by=?, signed_at=?, signed_log=?, updated_at=? "
            "WHERE note_no=?",
            (user.get("display_name") or user["username"], now, json.dumps(log, ensure_ascii=False), now, note_no)
        )
    else:
        conn.execute(
            "UPDATE shipping_notes SET is_signed=0, signed_by='', signed_at='', signed_log=?, updated_at=? "
            "WHERE note_no=?",
            (json.dumps(log, ensure_ascii=False), now, note_no)
        )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), f"shipping.{action}", "shipping_note", note_no, note_no, {"note": note})
    return {"ok": True, "is_signed": action == "sign", "signed_log": log}


# ── 出貨單專屬簽核流程設定（獨立於報價單 approval_flow）───────────────────────

@router.get("/api/shipping-notes/settings/approval-flow")
def get_shipping_approval_flow(authorization: str = Header(None)):
    _require_user(authorization)
    return _get_setting("shipping_approval_flow", {"tiers": []}) or {"tiers": []}


@router.put("/api/shipping-notes/settings/approval-flow")
def set_shipping_approval_flow(body: ApprovalFlowSettings, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    total_approvers = sum(len(t.approvers) for t in body.tiers)
    value = {"tiers": [t.model_dump() for t in body.tiers]}
    _set_setting("shipping_approval_flow", value)
    _audit(_tok(authorization), "settings.shipping_approval_flow.update", "settings", "shipping_approval_flow",
           "出貨單簽核流程設定", {"tierCount": len(body.tiers), "approverCount": total_approvers})
    return {"ok": True}
