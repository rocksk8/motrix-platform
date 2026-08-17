"""Supplier CRUD and visit log endpoints."""
import json
import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from db import get_db, next_entity_code, spawn_bg_thread
from helpers import _require_user, _tok, _audit, notify_module_activity
from archive import _backup_suppliers

router = APIRouter()


class SupplierIn(BaseModel):
    name:   str
    tax_id: Optional[str] = ''
    phone:  Optional[str] = ''
    data:   Optional[dict] = {}


@router.get("/api/suppliers")
def list_suppliers(authorization: str = Header(None)):
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        return []
    conn = get_db()
    rows = conn.execute(
        "SELECT id, code, name, tax_id, phone, data_json, created_at, updated_at FROM suppliers ORDER BY name"
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = json.loads(row["data_json"] or "{}")
        result.append({
            "id": row["id"], "code": row["code"] or "",
            "name": row["name"],
            "taxId": row["tax_id"], "phone": row["phone"],
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
            **d
        })
    return result


@router.post("/api/suppliers")
def create_supplier(body: SupplierIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO suppliers (name, tax_id, phone, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (body.name.strip(), body.tax_id or '', body.phone or '',
             json.dumps(body.data or {}, ensure_ascii=False), now, now)
        )
        conn.commit()
        sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        code = next_entity_code(conn, 'suppliers', 'S')
        conn.execute("UPDATE suppliers SET code=? WHERE id=?", (code, sid))
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(409, f"建立失敗：{e}")
    conn.close()
    spawn_bg_thread(_backup_suppliers)
    _audit(_tok(authorization), 'supplier.create', 'supplier', body.name, body.name)
    notify_module_activity("供應商管理", "建立", user.get("display_name") or user["username"],
                            body.name, "suppliers.html")
    return {"id": sid, "name": body.name, "code": code}


@router.put("/api/suppliers/{sid}")
def update_supplier(sid: int, body: SupplierIn, authorization: str = Header(None)):
    _require_user(authorization)
    now = datetime.now().isoformat()
    conn = get_db()
    if not conn.execute("SELECT id FROM suppliers WHERE id=?", (sid,)).fetchone():
        conn.close()
        raise HTTPException(404, "供應商不存在")
    conn.execute(
        "UPDATE suppliers SET name=?, tax_id=?, phone=?, data_json=?, updated_at=? WHERE id=?",
        (body.name.strip(), body.tax_id or '', body.phone or '',
         json.dumps(body.data or {}, ensure_ascii=False), now, sid)
    )
    conn.commit()
    conn.close()
    spawn_bg_thread(_backup_suppliers)
    _audit(_tok(authorization), 'supplier.update', 'supplier', str(sid), body.name)
    return {"ok": True}


@router.delete("/api/suppliers/{sid}")
def delete_supplier(sid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute("SELECT name FROM suppliers WHERE id=?", (sid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "供應商不存在")
    sname = row['name']
    conn.execute("DELETE FROM suppliers WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    spawn_bg_thread(_backup_suppliers)
    _audit(_tok(authorization), 'supplier.delete', 'supplier', str(sid), sname)
    notify_module_activity("供應商管理", "刪除", user.get("display_name") or user["username"],
                            sname, "suppliers.html")
    return {"ok": True}


@router.patch("/api/suppliers/{sid}/visits")
def update_supplier_visits(sid: int, body: dict, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT name, data_json, updated_at FROM suppliers WHERE id=?", (sid,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "供應商不存在")
    expected = body.get("expectedUpdatedAt")
    if expected and row["updated_at"] and expected != row["updated_at"]:
        conn.close()
        raise HTTPException(409, "供應商資料已被其他人更新，請重新載入後再存")
    sname = row["name"]
    d = json.loads(row["data_json"] or "{}")
    d["visits"] = body.get("visits", [])
    visit_count = len(d["visits"])
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE suppliers SET data_json=?, updated_at=? WHERE id=?",
        (json.dumps(d, ensure_ascii=False), now, sid)
    )
    conn.commit()
    conn.close()
    spawn_bg_thread(_backup_suppliers)
    _audit(_tok(authorization), 'supplier.visit.update', 'supplier', str(sid),
           f"{sname}（{visit_count} 筆往來紀錄）")
    _latest_visit = d["visits"][-1] if d["visits"] else {}
    notify_module_activity("供應商管理", "新增往來紀錄", user.get("display_name") or user["username"],
                            f"{sname}{('（' + _latest_visit['date'] + '）') if _latest_visit.get('date') else ''}",
                            "suppliers.html", detail=_latest_visit.get("note", ""))
    return {"ok": True, "count": visit_count, "updated_at": now}
