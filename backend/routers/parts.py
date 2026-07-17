"""Parts master data CRUD."""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Body

from db import get_db
from helpers import _tok, _audit

router = APIRouter()


@router.get("/api/parts")
def list_parts(q: Optional[str] = None, category: Optional[str] = None):
    conn = get_db()
    rows = conn.execute("SELECT * FROM parts ORDER BY id DESC").fetchall()
    conn.close()
    result = []
    for r in rows:
        if not r["active"]:
            continue
        d = dict(r)
        if q and q.lower() not in (d.get("part_no","") + d.get("name","") + d.get("brand","")).lower():
            continue
        if category and d.get("category","") != category:
            continue
        result.append(d)
    return {"items": result}


@router.post("/api/parts", status_code=201)
def create_part(body: dict = Body(...), authorization: str = Header(None)):
    conn = get_db()
    now = datetime.now().isoformat()
    part_no = (body.get("partNo") or body.get("part_no") or "").strip()
    if not part_no:
        raise HTTPException(400, "料號不得為空")
    if conn.execute("SELECT id FROM parts WHERE part_no=?", (part_no,)).fetchone():
        raise HTTPException(409, "料號已存在")
    name = body.get("name", "")
    conn.execute("""
        INSERT INTO parts (part_no, name, brand, unit, cost, list_price, category, note, active, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,1,?,?)
    """, (
        part_no, name,
        body.get("brand",""),
        body.get("unit","台"),
        body.get("cost",0),
        body.get("listPrice") or body.get("list_price") or 0,
        body.get("category",""),
        body.get("note",""),
        now, now,
    ))
    conn.commit()
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    _audit(_tok(authorization), 'part.create', 'part', part_no, f"{part_no} {name}".strip())
    return {"id": new_id, "ok": True}


@router.put("/api/parts/{part_id}")
def update_part(part_id: int, body: dict = Body(...), authorization: str = Header(None)):
    conn = get_db()
    row = conn.execute("SELECT part_no, name FROM parts WHERE id=?", (part_id,)).fetchone()
    if not row:
        raise HTTPException(404, "料號不存在")
    now = datetime.now().isoformat()
    new_name = body.get("name", "")
    conn.execute("""
        UPDATE parts SET name=?, brand=?, unit=?, cost=?, list_price=?, category=?, note=?, updated_at=?
        WHERE id=?
    """, (
        new_name,
        body.get("brand",""),
        body.get("unit","台"),
        body.get("cost",0),
        body.get("listPrice") or body.get("list_price") or 0,
        body.get("category",""),
        body.get("note",""),
        now, part_id,
    ))
    conn.commit()
    conn.close()
    label = f"{row['part_no']} {new_name or row['name']}".strip()
    _audit(_tok(authorization), 'part.update', 'part', row['part_no'], label)
    return {"ok": True}


@router.delete("/api/parts/{part_id}")
def delete_part(part_id: int, authorization: str = Header(None)):
    conn = get_db()
    row = conn.execute("SELECT part_no, name FROM parts WHERE id=?", (part_id,)).fetchone()
    if not row:
        raise HTTPException(404, "料號不存在")
    conn.execute("DELETE FROM parts WHERE id=?", (part_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'part.delete', 'part', row['part_no'],
           f"{row['part_no']} {row['name']}".strip())
    return {"ok": True}
