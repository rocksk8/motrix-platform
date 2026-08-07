"""Parts master data CRUD."""
import json
import sqlite3
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Body

from db import get_db
from helpers import _require_user, _tok, _audit, notify_module_activity

router = APIRouter()

# 固定分類清單：新增分類時可在此增列（顯示順序＝清單順序）
PART_CATEGORIES = [
    {"name": "網通設備", "prefix": "NET"},
    {"name": "監控設備", "prefix": "CCTV"},
    {"name": "交換器",   "prefix": "SW"},
    {"name": "伺服器/工控", "prefix": "SVR"},
    {"name": "線材配件", "prefix": "CAB"},
    {"name": "其他",     "prefix": "OTH"},
]
PART_CATEGORY_PREFIX = {c["name"]: c["prefix"] for c in PART_CATEGORIES}


def _next_part_no(conn, prefix: str) -> str:
    """回傳下一個可用料號，如 NET-001。prefix 須為內部信任常數。"""
    rows = conn.execute(
        "SELECT part_no FROM parts WHERE part_no LIKE ?", (f"{prefix}-%",)
    ).fetchall()
    mx = 0
    for r in rows:
        suffix = r["part_no"][len(prefix) + 1:]
        if suffix.isdigit():
            mx = max(mx, int(suffix))
    n = mx + 1
    while conn.execute("SELECT 1 FROM parts WHERE part_no=?", (f"{prefix}-{n:03d}",)).fetchone():
        n += 1
    return f"{prefix}-{n:03d}"


@router.get("/api/parts/categories")
def list_part_categories():
    return {"items": PART_CATEGORIES}


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
    user = _require_user(authorization)
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        category = (body.get("category") or "").strip()
        part_no = (body.get("partNo") or body.get("part_no") or "").strip()
        if not part_no:
            prefix = PART_CATEGORY_PREFIX.get(category)
            if not prefix:
                raise HTTPException(400, "請輸入料號，或選擇有對應前綴的類別以自動產生")
            part_no = _next_part_no(conn, prefix)
        if conn.execute("SELECT id FROM parts WHERE part_no=?", (part_no,)).fetchone():
            raise HTTPException(409, "料號已存在")
        name = body.get("name", "")
        # _next_part_no() 算出候選號碼、上面這行再查一次確認未用，兩步之間沒有交易
        # 保護——兩個併發請求可能都通過檢查、都嘗試 INSERT。part_no 有 UNIQUE 約束
        # 擋住真的產生重複資料，但沒接這個 except 的話，輸家的 IntegrityError 會原樣
        # 拋成不友善的 500，而不是乾淨的 409。
        try:
            conn.execute("""
                INSERT INTO parts (part_no, name, brand, unit, cost, list_price, category, note, active, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,1,?,?)
            """, (
                part_no, name,
                body.get("brand",""),
                body.get("unit","台"),
                body.get("cost",0),
                body.get("listPrice") or body.get("list_price") or 0,
                category,
                body.get("note",""),
                now, now,
            ))
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(409, "料號已存在，請重新整理後再試")
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _audit(_tok(authorization), 'part.create', 'part', part_no, f"{part_no} {name}".strip())
        notify_module_activity("料號管理", "建立", user.get("display_name") or user["username"],
                                f"{part_no} {name}".strip(), "parts.html")
        return {"id": new_id, "ok": True}
    finally:
        conn.close()


@router.put("/api/parts/{part_id}")
def update_part(part_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    try:
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
        label = f"{row['part_no']} {new_name or row['name']}".strip()
        _audit(_tok(authorization), 'part.update', 'part', row['part_no'], label)
        return {"ok": True}
    finally:
        conn.close()


@router.delete("/api/parts/{part_id}")
def delete_part(part_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        row = conn.execute("SELECT part_no, name FROM parts WHERE id=?", (part_id,)).fetchone()
        if not row:
            raise HTTPException(404, "料號不存在")
        if conn.execute("SELECT 1 FROM stock_items WHERE part_no=? LIMIT 1", (row["part_no"],)).fetchone():
            raise HTTPException(409, "此料號仍有庫存紀錄，無法刪除")
        conn.execute("DELETE FROM parts WHERE id=?", (part_id,))
        conn.commit()
        _audit(_tok(authorization), 'part.delete', 'part', row['part_no'],
               f"{row['part_no']} {row['name']}".strip())
        notify_module_activity("料號管理", "刪除", user.get("display_name") or user["username"],
                                f"{row['part_no']} {row['name']}".strip(), "parts.html")
        return {"ok": True}
    finally:
        conn.close()
