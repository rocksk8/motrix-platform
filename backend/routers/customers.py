"""Customer CRUD and visit log endpoints."""
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from db import get_db, next_entity_code, spawn_bg_thread
from helpers import _require_user, _tok, _audit, notify_module_activity, require_any_module
from helpers.errors import trace_id
from archive import _backup_customers

router = APIRouter()
logger = logging.getLogger(__name__)


class CustomerIn(BaseModel):
    name:   str
    tax_id: Optional[str] = ''
    phone:  Optional[str] = ''
    data:   Optional[dict] = {}


@router.get("/api/customers")
def list_customers(authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'case_manage', 'dev_crm', 'procurement'), "客戶管理")
    conn = get_db()
    rows = conn.execute(
        "SELECT id, code, name, tax_id, phone, data_json, created_at, updated_at FROM customers ORDER BY name"
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


@router.get("/api/customers/{cid}")
def get_customer(cid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'case_manage', 'dev_crm', 'procurement'), "客戶管理")
    conn = get_db()
    row  = conn.execute(
        "SELECT id, code, name, tax_id, phone, data_json, created_at, updated_at FROM customers WHERE id=?", (cid,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "客戶不存在")
    d = json.loads(row["data_json"] or "{}")
    return {"id": row["id"], "code": row["code"] or "",
            "name": row["name"],
            "taxId": row["tax_id"], "phone": row["phone"],
            "createdAt": row["created_at"], "updatedAt": row["updated_at"], **d}


@router.post("/api/customers")
def create_customer(body: CustomerIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'case_manage', 'dev_crm', 'procurement'), "客戶管理")
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO customers (name, tax_id, phone, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (body.name.strip(), body.tax_id or '', body.phone or '',
             json.dumps(body.data or {}, ensure_ascii=False), now, now)
        )
        conn.commit()
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        code = next_entity_code(conn, 'customers', 'C')
        conn.execute("UPDATE customers SET code=? WHERE id=?", (code, cid))
        conn.commit()
    except Exception as e:
        conn.close()
        tid = trace_id()
        logger.exception("customer create failed trace=%s", tid)
        raise HTTPException(409, f"建立失敗（代碼 {tid}）")
    conn.close()
    spawn_bg_thread(_backup_customers)
    _audit(_tok(authorization), 'customer.create', 'customer', body.name, body.name)
    notify_module_activity("客戶管理", "建立", user.get("display_name") or user["username"],
                            body.name, "customers.html")
    return {"id": cid, "name": body.name, "code": code}


@router.put("/api/customers/{cid}")
def update_customer(cid: int, body: CustomerIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'case_manage', 'dev_crm', 'procurement'), "客戶管理")
    now = datetime.now().isoformat()
    conn = get_db()
    if not conn.execute("SELECT id FROM customers WHERE id=?", (cid,)).fetchone():
        conn.close()
        raise HTTPException(404, "客戶不存在")
    conn.execute(
        "UPDATE customers SET name=?, tax_id=?, phone=?, data_json=?, updated_at=? WHERE id=?",
        (body.name.strip(), body.tax_id or '', body.phone or '',
         json.dumps(body.data or {}, ensure_ascii=False), now, cid)
    )
    conn.commit()
    conn.close()
    spawn_bg_thread(_backup_customers)
    _audit(_tok(authorization), 'customer.update', 'customer', str(cid), body.name)
    return {"ok": True}


@router.patch("/api/customers/{cid}/visits")
def update_customer_visits(cid: int, body: dict, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'case_manage', 'dev_crm', 'procurement'), "客戶管理")
    conn = get_db()
    row = conn.execute(
        "SELECT name, data_json, updated_at FROM customers WHERE id=?", (cid,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "客戶不存在")
    # Optimistic lock (optional): avoid last-write-wins on concurrent visit edits
    expected = body.get("expectedUpdatedAt")
    if expected and row["updated_at"] and expected != row["updated_at"]:
        conn.close()
        raise HTTPException(409, "客戶資料已被其他人更新，請重新載入後再存")
    cname = row["name"]
    d = json.loads(row["data_json"] or "{}")
    d["visits"] = body.get("visits", [])
    visit_count = len(d["visits"])
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE customers SET data_json=?, updated_at=? WHERE id=?",
        (json.dumps(d, ensure_ascii=False), now, cid)
    )
    conn.commit()
    conn.close()
    spawn_bg_thread(_backup_customers)
    _audit(_tok(authorization), 'customer.visit.update', 'customer', str(cid),
           f"{cname}（{visit_count} 筆拜訪紀錄）")
    _latest_visit = d["visits"][-1] if d["visits"] else {}
    notify_module_activity("客戶管理", "新增拜訪紀錄", user.get("display_name") or user["username"],
                            f"{cname}{('（' + _latest_visit['date'] + '）') if _latest_visit.get('date') else ''}",
                            "customers.html", detail=_latest_visit.get("note", ""))
    return {"ok": True, "updated_at": now}


@router.delete("/api/customers/{cid}")
def delete_customer(cid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'case_manage', 'dev_crm', 'procurement'), "客戶管理")
    conn = get_db()
    row = conn.execute("SELECT name FROM customers WHERE id=?", (cid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "客戶不存在")
    cname = row['name']
    conn.execute("DELETE FROM customers WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    spawn_bg_thread(_backup_customers)
    _audit(_tok(authorization), 'customer.delete', 'customer', str(cid), cname)
    notify_module_activity("客戶管理", "刪除", user.get("display_name") or user["username"],
                            cname, "customers.html")
    return {"ok": True}
