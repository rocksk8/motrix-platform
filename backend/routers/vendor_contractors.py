"""承攬商管理 (vendor contractors) + 案件派發 CRUD + 回推報價單品項."""
import json
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from db import get_db, next_entity_code
from helpers import _require_user, _tok, _audit
from helpers.quotations import save_quotation_json

router = APIRouter()

_STATUS_LABELS = {
    "draft": "草稿",
    "sent": "已送出",
    "confirmed": "已確認",
    "pending_acceptance": "待驗收",
    "accepted": "已驗收",
    "completed": "完工",
    "cancelled": "已取消",
}


# ── Pydantic models ──────────────────────────────────────────────────────────

class VendorContractorIn(BaseModel):
    name: str
    tax_id: Optional[str] = ''
    contact_name: Optional[str] = ''
    phone: Optional[str] = ''
    email: Optional[str] = ''
    address: Optional[str] = ''
    data: Optional[dict] = {}


class DispatchIn(BaseModel):
    quote_no: str
    vendor_id: int
    dispatch_date: Optional[str] = ''
    scope: Optional[str] = ''
    items_json: Optional[list] = []
    tax_rate: Optional[float] = 0.05
    status: Optional[str] = 'draft'
    notes: Optional[str] = ''


# ── Helpers ──────────────────────────────────────────────────────────────────

def _vendor_row(row) -> dict:
    d = {}
    try:
        d = json.loads(row["data_json"] or "{}")
    except Exception:
        pass
    keys = row.keys() if hasattr(row, 'keys') else []
    return {
        "id": row["id"],
        "code": (row["code"] if "code" in keys else "") or "",
        "name": row["name"],
        "taxId": row["tax_id"] or "",
        "contactName": row["contact_name"] or "",
        "phone": row["phone"] or "",
        "email": row["email"] or "",
        "address": row["address"] or "",
        "active": bool(row["active"]),
        "createdAt": row["created_at"] or "",
        "updatedAt": row["updated_at"] or "",
        **d
    }


def _dispatch_row(row) -> dict:
    items = []
    try:
        items = json.loads(row["items_json"] or "[]")
    except Exception:
        pass
    total = float(row["total_amount"] or 0)
    if not total and items:
        total = sum(float(it.get("amount", 0) or 0) for it in items)
    keys = row.keys()
    tax_rate = float(row["tax_rate"]) if "tax_rate" in keys and row["tax_rate"] is not None else 0.05
    tax_amount = round(total * tax_rate)
    return {
        "id": row["id"],
        "quoteNo": row["quote_no"],
        "vendorId": row["vendor_id"],
        "vendorName": row["vendor_name"] if "vendor_name" in keys else "",
        "dispatchDate": row["dispatch_date"] or "",
        "scope": row["scope"] or "",
        "items": items,
        "totalAmount": total,
        "taxRate": tax_rate,
        "taxAmount": tax_amount,
        "totalWithTax": total + tax_amount,
        "status": row["status"] or "draft",
        "statusLabel": _STATUS_LABELS.get(row["status"] or "draft", row["status"] or ""),
        "notes": row["notes"] or "",
        "createdBy": row["created_by"] or "",
        "createdAt": row["created_at"] or "",
        "updatedAt": row["updated_at"] or "",
        "acceptedAt": (row["accepted_at"] if "accepted_at" in keys else "") or "",
        "acceptedBy": (row["accepted_by"] if "accepted_by" in keys else "") or "",
    }


# ── 承攬商 CRUD ───────────────────────────────────────────────────────────────

@router.get("/api/vendor-contractors")
def list_vendor_contractors(
    q: Optional[str] = None,
    active_only: bool = True,
    authorization: str = Header(None)
):
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        return []
    conn = get_db()
    sql = ("SELECT id, code, name, tax_id, contact_name, phone, email, address, "
           "data_json, active, created_at, updated_at FROM vendor_contractors")
    params = []
    clauses = []
    if active_only:
        clauses.append("active=1")
    if q:
        clauses.append("(name LIKE ? OR tax_id LIKE ? OR phone LIKE ? OR contact_name LIKE ? OR code LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY name"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_vendor_row(r) for r in rows]


@router.get("/api/vendor-contractors/selectable")
def list_vendors_selectable(authorization: str = Header(None)):
    """輕量列表供案件管理下拉選單使用（所有登入者皆可讀）。"""
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, contact_name, phone FROM vendor_contractors WHERE active=1 ORDER BY name"
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "name": r["name"],
             "contactName": r["contact_name"] or "", "phone": r["phone"] or ""} for r in rows]


@router.get("/api/vendor-contractors/{vid}")
def get_vendor_contractor(vid: int, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT * FROM vendor_contractors WHERE id=?", (vid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "找不到此承攬商")
    return _vendor_row(row)


@router.post("/api/vendor-contractors", status_code=201)
def create_vendor_contractor(body: VendorContractorIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    now = datetime.now().isoformat()
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO vendor_contractors "
        "(name, tax_id, contact_name, phone, email, address, data_json, active, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,1,?,?)",
        (body.name.strip(), body.tax_id or '', body.contact_name or '',
         body.phone or '', body.email or '', body.address or '',
         json.dumps(body.data or {}, ensure_ascii=False), now, now)
    )
    vid = cur.lastrowid
    conn.commit()
    code = next_entity_code(conn, 'vendor_contractors', 'V')
    conn.execute("UPDATE vendor_contractors SET code=? WHERE id=?", (code, vid))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.create', 'vendor_contractor', str(vid), body.name)
    return {"id": vid, "code": code, "created_at": now}


@router.put("/api/vendor-contractors/{vid}")
def update_vendor_contractor(vid: int, body: VendorContractorIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    now = datetime.now().isoformat()
    conn = get_db()
    existing = conn.execute("SELECT data_json FROM vendor_contractors WHERE id=?", (vid,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "承攬商不存在")
    # Merge: preserve existing visits unless caller explicitly provides them
    existing_data = {}
    try:
        existing_data = json.loads(existing["data_json"] or "{}")
    except Exception:
        pass
    new_data = body.data or {}
    if "visits" not in new_data:
        new_data = {**new_data, "visits": existing_data.get("visits", [])}
    conn.execute(
        "UPDATE vendor_contractors SET name=?, tax_id=?, contact_name=?, phone=?, email=?, address=?, data_json=?, updated_at=? WHERE id=?",
        (body.name.strip(), body.tax_id or '', body.contact_name or '',
         body.phone or '', body.email or '', body.address or '',
         json.dumps(new_data, ensure_ascii=False), now, vid)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.update', 'vendor_contractor', str(vid), body.name)
    return {"ok": True, "updated_at": now}


@router.patch("/api/vendor-contractors/{vid}/active")
def toggle_vendor_active(vid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    conn = get_db()
    row = conn.execute("SELECT active, name FROM vendor_contractors WHERE id=?", (vid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "承攬商不存在")
    new_active = 0 if row["active"] else 1
    conn.execute("UPDATE vendor_contractors SET active=?, updated_at=? WHERE id=?",
                 (new_active, datetime.now().isoformat(), vid))
    conn.commit()
    conn.close()
    action = 'vendor.activate' if new_active else 'vendor.deactivate'
    _audit(_tok(authorization), action, 'vendor_contractor', str(vid), row["name"])
    return {"active": bool(new_active)}


@router.delete("/api/vendor-contractors/{vid}")
def delete_vendor_contractor(vid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    conn = get_db()
    row = conn.execute("SELECT name FROM vendor_contractors WHERE id=?", (vid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "承攬商不存在")
    cnt = conn.execute(
        "SELECT COUNT(*) FROM contractor_dispatches WHERE vendor_id=?", (vid,)
    ).fetchone()[0]
    if cnt > 0:
        conn.close()
        raise HTTPException(409, f"此承攬商有 {cnt} 筆派發紀錄，無法刪除，請改為停用")
    vname = row["name"]
    conn.execute("DELETE FROM vendor_contractors WHERE id=?", (vid,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.delete', 'vendor_contractor', str(vid), vname)
    return {"ok": True}


@router.patch("/api/vendor-contractors/{vid}/visits")
def update_vendor_visits(vid: int, body: dict, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT name, data_json, updated_at FROM vendor_contractors WHERE id=?", (vid,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "承攬商不存在")
    expected = body.get("expectedUpdatedAt")
    if expected and row["updated_at"] and expected != row["updated_at"]:
        conn.close()
        raise HTTPException(409, "資料已被其他人更新，請重新載入後再存")
    d = json.loads(row["data_json"] or "{}")
    d["visits"] = body.get("visits", [])
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE vendor_contractors SET data_json=?, updated_at=? WHERE id=?",
        (json.dumps(d, ensure_ascii=False), now, vid)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.visit.update', 'vendor_contractor', str(vid),
           f"{row['name']}（{len(d['visits'])} 筆往來紀錄）")
    return {"ok": True, "count": len(d["visits"]), "updated_at": now}


# ── 派發 CRUD ─────────────────────────────────────────────────────────────────

@router.get("/api/contractor-dispatches")
def list_dispatches(quote_no: Optional[str] = None, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    if quote_no:
        rows = conn.execute(
            "SELECT d.*, v.name AS vendor_name FROM contractor_dispatches d "
            "LEFT JOIN vendor_contractors v ON v.id=d.vendor_id "
            "WHERE d.quote_no=? ORDER BY d.created_at DESC",
            (quote_no,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT d.*, v.name AS vendor_name FROM contractor_dispatches d "
            "LEFT JOIN vendor_contractors v ON v.id=d.vendor_id "
            "ORDER BY d.created_at DESC LIMIT 200"
        ).fetchall()
    conn.close()
    return [_dispatch_row(r) for r in rows]


@router.get("/api/contractor-dispatches/{did}")
def get_dispatch(did: int, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT d.*, v.name AS vendor_name FROM contractor_dispatches d "
        "LEFT JOIN vendor_contractors v ON v.id=d.vendor_id WHERE d.id=?",
        (did,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "派發紀錄不存在")
    return _dispatch_row(row)


@router.post("/api/contractor-dispatches", status_code=201)
def create_dispatch(body: DispatchIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    now = datetime.now().isoformat()
    items = body.items_json or []
    total = sum(float(it.get("amount", 0) or 0) for it in items)
    conn = get_db()
    if not conn.execute("SELECT id FROM vendor_contractors WHERE id=?", (body.vendor_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "承攬商不存在")
    cur = conn.execute(
        "INSERT INTO contractor_dispatches "
        "(quote_no, vendor_id, dispatch_date, scope, items_json, total_amount, tax_rate, status, notes, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (body.quote_no, body.vendor_id, body.dispatch_date or '',
         body.scope or '', json.dumps(items, ensure_ascii=False), total,
         body.tax_rate if body.tax_rate is not None else 0.05,
         body.status or 'draft', body.notes or '',
         user["username"], now, now)
    )
    did = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.dispatch.create', 'contractor_dispatch', str(did),
           f"{body.quote_no}")
    return {"id": did, "created_at": now, "total_amount": total}


@router.put("/api/contractor-dispatches/{did}")
def update_dispatch(did: int, body: DispatchIn, authorization: str = Header(None)):
    _require_user(authorization)
    now = datetime.now().isoformat()
    items = body.items_json or []
    total = sum(float(it.get("amount", 0) or 0) for it in items)
    conn = get_db()
    if not conn.execute("SELECT id FROM contractor_dispatches WHERE id=?", (did,)).fetchone():
        conn.close()
        raise HTTPException(404, "派發紀錄不存在")
    conn.execute(
        "UPDATE contractor_dispatches SET vendor_id=?, dispatch_date=?, scope=?, items_json=?, "
        "total_amount=?, tax_rate=?, status=?, notes=?, updated_at=? WHERE id=?",
        (body.vendor_id, body.dispatch_date or '', body.scope or '',
         json.dumps(items, ensure_ascii=False), total,
         body.tax_rate if body.tax_rate is not None else 0.05,
         body.status or 'draft', body.notes or '', now, did)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.dispatch.update', 'contractor_dispatch', str(did), body.quote_no)
    return {"ok": True, "updated_at": now, "total_amount": total}


@router.delete("/api/contractor-dispatches/{did}")
def delete_dispatch(did: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    conn = get_db()
    row = conn.execute("SELECT quote_no FROM contractor_dispatches WHERE id=?", (did,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "派發紀錄不存在")
    conn.execute("DELETE FROM contractor_dispatches WHERE id=?", (did,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'vendor.dispatch.delete', 'contractor_dispatch', str(did), row["quote_no"])
    return {"ok": True}


# ── 驗收流程節點 ──────────────────────────────────────────────────────────────

_ACCEPT_ALLOWED_FROM = {
    "pending_acceptance": ("draft", "sent", "confirmed"),
    "accepted": ("pending_acceptance",),
}

@router.patch("/api/contractor-dispatches/{did}/accept")
def accept_dispatch(did: int, body: dict, authorization: str = Header(None)):
    """驗收流程節點：
    action=pending_acceptance — 標記待驗收（admin+，來源：draft/sent/confirmed）
    action=accepted          — 確認驗收（admin+，來源：pending_acceptance），記錄驗收人與時間
    """
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")
    action = body.get("action", "")
    if action not in _ACCEPT_ALLOWED_FROM:
        raise HTTPException(400, "action 必須為 pending_acceptance 或 accepted")
    conn = get_db()
    row = conn.execute(
        "SELECT quote_no, status FROM contractor_dispatches WHERE id=?", (did,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "派發紀錄不存在")
    current = row["status"] or "draft"
    if current not in _ACCEPT_ALLOWED_FROM[action]:
        allowed_labels = "、".join(_STATUS_LABELS.get(s, s) for s in _ACCEPT_ALLOWED_FROM[action])
        conn.close()
        raise HTTPException(409, f"目前狀態「{_STATUS_LABELS.get(current, current)}」無法執行此操作（需為：{allowed_labels}）")
    now = datetime.now().isoformat()
    if action == "accepted":
        conn.execute(
            "UPDATE contractor_dispatches SET status='accepted', accepted_by=?, accepted_at=?, updated_at=? WHERE id=?",
            (user.get("display_name") or user["username"], now, now, did)
        )
    else:
        conn.execute(
            "UPDATE contractor_dispatches SET status=?, updated_at=? WHERE id=?",
            (action, now, did)
        )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), f'vendor.dispatch.{action}', 'contractor_dispatch', str(did), row["quote_no"])
    return {"ok": True, "status": action, "updated_at": now}


# ── 回推報價單品項 ────────────────────────────────────────────────────────────

@router.post("/api/contractor-dispatches/{did}/import-to-quote")
def import_dispatch_to_quote(did: int, authorization: str = Header(None)):
    """將派發報價品項以「外包成本」方式附加至報價單的品項清單。
    僅限報價單為草稿（status='草稿'）狀態；已送出需先在報價單頁面解鎖。"""
    user = _require_user(authorization)
    conn = get_db()
    # Load dispatch
    drow = conn.execute(
        "SELECT d.*, v.name AS vendor_name FROM contractor_dispatches d "
        "LEFT JOIN vendor_contractors v ON v.id=d.vendor_id WHERE d.id=?",
        (did,)
    ).fetchone()
    if not drow:
        conn.close()
        raise HTTPException(404, "派發紀錄不存在")
    # Load quotation
    qrow = conn.execute(
        "SELECT quote_no, status, data_json, updated_at FROM quotations WHERE quote_no=?",
        (drow["quote_no"],)
    ).fetchone()
    if not qrow:
        conn.close()
        raise HTTPException(404, "找不到對應報價單")
    if qrow["status"] != "草稿":
        conn.close()
        raise HTTPException(409, f"報價單目前為「{qrow['status']}」狀態，請先在報價單頁面解鎖後再匯入")

    vendor_name = drow["vendor_name"] or f"承攬商#{drow['vendor_id']}"
    dispatch_items = []
    try:
        dispatch_items = json.loads(drow["items_json"] or "[]")
    except Exception:
        pass

    qdata = {}
    try:
        qdata = json.loads(qrow["data_json"] or "{}")
    except Exception:
        pass

    if not isinstance(qdata.get("items"), list):
        qdata["items"] = []

    # Add section header
    qdata["items"].append({
        "id": str(uuid.uuid4()),
        "type": "header",
        "description": f"外包承攬 — {vendor_name}"
    })
    # Convert dispatch items to quotation items (cost = vendor unit_price)
    for it in dispatch_items:
        unit_price = float(it.get("unitPrice", 0) or 0)
        qty = float(it.get("qty", 1) or 1)
        qdata["items"].append({
            "id": str(uuid.uuid4()),
            "description": it.get("description", ""),
            "brand": "",
            "qty": qty,
            "unit": it.get("unit", "式"),
            "cost": unit_price,
            "margin": 0.30,
            "unitPrice": None,
            "unitPriceOverride": False,
            "amount": 0,
            "notes": it.get("note", "")
        })

    now = datetime.now().isoformat()
    save_quotation_json(conn, qrow["quote_no"], qdata, user["username"])
    conn.close()
    _audit(_tok(authorization), 'vendor.dispatch.import', 'contractor_dispatch', str(did),
           f"匯入 {len(dispatch_items)} 品項至 {qrow['quote_no']}")
    return {"ok": True, "imported": len(dispatch_items), "updated_at": now}
