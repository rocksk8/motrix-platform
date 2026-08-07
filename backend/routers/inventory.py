"""序號級庫存（stock_items）：進貨批次、序號清單、料號彙總、人工調整。

粒度為序號級（比照設備登載 SN/MAC 結構），一列 = 一台實體設備。狀態機：
in_stock -> shipped（出貨單核准自動扣庫存，見 shipping_notes.py）
in_stock -> installed（設備登載自動扣庫存，見 quotations.py update_case_record）
in_stock -> void（人工報廢/遺失/盤點差異）
shipped/installed -> in_stock（人工 return_to_stock 更正，見 §出貨單回滾設計）
"""
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Body

from db import get_db, next_entity_code
from helpers import _require_user, _tok, _audit, notify_module_activity

router = APIRouter()


def _require_admin(user: dict):
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "需要管理員權限")


# ── 料號彙總 ─────────────────────────────────────────────────────────────────

@router.get("/api/inventory/parts-summary")
def parts_summary(q: Optional[str] = None, category: Optional[str] = None, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    parts_rows = conn.execute("SELECT part_no, name, brand, unit, category FROM parts WHERE active=1").fetchall()
    counts = conn.execute(
        "SELECT part_no, status, COUNT(*) AS cnt, SUM(cost) AS cost_sum, MAX(created_at) AS last_in "
        "FROM stock_items GROUP BY part_no, status"
    ).fetchall()
    conn.close()

    by_part: dict = {}
    for c in counts:
        by_part.setdefault(c["part_no"], {})[c["status"]] = {
            "cnt": c["cnt"], "cost_sum": c["cost_sum"] or 0, "last_in": c["last_in"] or ""
        }

    def _stats(st, status):
        s = st.get(status, {})
        return s.get("cnt", 0), s.get("cost_sum", 0)

    result = []
    for p in parts_rows:
        d = dict(p)
        if q and q.lower() not in (d.get("part_no", "") + d.get("name", "") + d.get("brand", "")).lower():
            continue
        if category and d.get("category", "") != category:
            continue
        st = by_part.get(d["part_no"], {})
        in_cnt, in_value = _stats(st, "in_stock")
        shipped_cnt, _ = _stats(st, "shipped")
        installed_cnt, _ = _stats(st, "installed")
        void_cnt, _ = _stats(st, "void")
        d.update({
            "inStockCount":   in_cnt,
            "inStockValue":   in_value,
            "shippedCount":   shipped_cnt,
            "installedCount": installed_cnt,
            "voidCount":      void_cnt,
            "lastInAt":       st.get("in_stock", {}).get("last_in", ""),
        })
        result.append(d)
    # 也列出僅存在庫存、目前不在 parts 目錄的料號（避免資料孤兒不可見）
    known = {p["part_no"] for p in parts_rows}
    orphan_parts = {c["part_no"] for c in counts if c["part_no"] not in known}
    for pn in orphan_parts:
        st = by_part.get(pn, {})
        in_cnt, in_value = _stats(st, "in_stock")
        shipped_cnt, _ = _stats(st, "shipped")
        installed_cnt, _ = _stats(st, "installed")
        void_cnt, _ = _stats(st, "void")
        result.append({
            "part_no": pn, "name": "", "brand": "", "unit": "", "category": "",
            "inStockCount":   in_cnt,
            "inStockValue":   in_value,
            "shippedCount":   shipped_cnt,
            "installedCount": installed_cnt,
            "voidCount":      void_cnt,
            "lastInAt":       st.get("in_stock", {}).get("last_in", ""),
        })
    return {"items": result}


# ── 序號清單 ─────────────────────────────────────────────────────────────────

@router.get("/api/inventory/stock-items")
def list_stock_items(
    part_no:       Optional[str] = None,
    status:        Optional[str] = None,
    batch_no:      Optional[str] = None,
    q:             Optional[str] = None,
    authorization: str           = Header(None),
):
    _require_user(authorization)
    conn = get_db()
    sql = "SELECT * FROM stock_items WHERE 1=1"
    params = []
    if part_no:
        sql += " AND part_no=?"
        params.append(part_no)
    if status:
        sql += " AND status=?"
        params.append(status)
    if batch_no:
        sql += " AND batch_no=?"
        params.append(batch_no)
    sql += " ORDER BY id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    items = [dict(r) for r in rows]
    if q:
        sq = q.lower()
        items = [d for d in items if sq in (d.get("serial_no", "") + d.get("mac", "")).lower()]
    return {"items": items, "total": len(items)}


# ── 進貨批次 ─────────────────────────────────────────────────────────────────

@router.post("/api/inventory/batches", status_code=201)
def create_batch(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)

    part_no = (body.get("part_no") or body.get("partNo") or "").strip()
    if not part_no:
        raise HTTPException(400, "料號不得為空")
    serials = body.get("serials") or []
    if not serials:
        raise HTTPException(400, "至少需輸入一筆序號")

    clean = []
    seen = set()
    for s in serials:
        sn = (s.get("serial_no") or s.get("serialNo") or "").strip()
        if not sn:
            raise HTTPException(400, "序號不得為空白（每一台實體設備都需要實際序號才能建立庫存）")
        if sn in seen:
            raise HTTPException(400, f"序號重複：{sn}")
        seen.add(sn)
        clean.append({"serial_no": sn, "mac": (s.get("mac") or "").strip(), "note": s.get("note") or ""})

    conn = get_db()
    part = conn.execute("SELECT part_no, cost FROM parts WHERE part_no=? AND active=1", (part_no,)).fetchone()
    if not part:
        conn.close()
        raise HTTPException(404, "料號不存在")

    dup = conn.execute(
        f"SELECT serial_no FROM stock_items WHERE part_no=? AND serial_no IN ({','.join('?' * len(clean))})",
        [part_no] + [c["serial_no"] for c in clean],
    ).fetchall()
    if dup:
        conn.close()
        raise HTTPException(409, f"序號已存在於庫存：{', '.join(d['serial_no'] for d in dup)}")

    batch_no = next_entity_code(conn, "stock_items", "PO", code_col="batch_no")
    cost = body.get("cost")
    if cost is None:
        cost = part["cost"] or 0
    note = body.get("note") or ""
    now = datetime.now().isoformat()
    actor = user.get("display_name") or user["username"]

    for c in clean:
        conn.execute("""
            INSERT INTO stock_items (part_no, serial_no, mac, status, batch_no, cost, note,
                                      created_by, created_at, updated_at)
            VALUES (?,?,?,'in_stock',?,?,?,?,?,?)
        """, (part_no, c["serial_no"], c["mac"], batch_no, cost, c["note"] or note, actor, now, now))
    conn.commit()
    conn.close()

    label = f"{batch_no}（{part_no}，{len(clean)} 台）"
    _audit(_tok(authorization), "inventory.batch_create", "stock_batch", batch_no, label,
           {"partNo": part_no, "qty": len(clean)})
    notify_module_activity("庫存管理", "進貨", actor, label, "inventory.html")
    return {"batchNo": batch_no, "count": len(clean), "ok": True}


@router.get("/api/inventory/batches")
def list_batches(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("""
        SELECT batch_no, part_no, COUNT(*) AS qty, SUM(cost) AS total_cost,
               MIN(created_at) AS created_at, MIN(created_by) AS created_by
        FROM stock_items
        WHERE batch_no != ''
        GROUP BY batch_no
        ORDER BY created_at DESC
    """).fetchall()
    conn.close()
    return {"items": [dict(r) for r in rows]}


@router.get("/api/inventory/batches/{batch_no}")
def get_batch(batch_no: str, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("SELECT * FROM stock_items WHERE batch_no=? ORDER BY id", (batch_no,)).fetchall()
    conn.close()
    if not rows:
        raise HTTPException(404, "批次不存在")
    return {"batchNo": batch_no, "items": [dict(r) for r in rows]}


# ── 人工調整 ─────────────────────────────────────────────────────────────────

@router.post("/api/inventory/stock-items/{item_id}/adjust")
def adjust_stock_item(item_id: int, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    action = (body.get("action") or "").strip()
    if action not in ("void", "return_to_stock", "edit_note"):
        raise HTTPException(400, "action 需為 void / return_to_stock / edit_note")

    conn = get_db()
    row = conn.execute("SELECT * FROM stock_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "庫存項目不存在")
    now = datetime.now().isoformat()
    note = body.get("note") or ""

    if action == "void":
        if row["status"] == "void":
            conn.close()
            raise HTTPException(409, "此序號已經是報廢狀態")
        # 報廢是終態，不會再回到任何案件/出貨單/報價單——一併清掉關聯欄位，
        # 否則報廢後的序號仍掛在原案件的設備清單上，造成兩邊資料分岔卻無人發現
        # （return_to_stock 分支本來就有清這幾欄，這裡原本沒有，是不一致的地方）
        conn.execute("""
            UPDATE stock_items
            SET status='void', shipping_note_no='', quote_no='', case_device_id='',
                consumed_at='', consumed_by='', note=?, updated_at=?
            WHERE id=?
        """, (note or row["note"], now, item_id))
    elif action == "return_to_stock":
        if row["status"] == "in_stock":
            conn.close()
            raise HTTPException(409, "此序號已經在庫，不需要歸還")
        if row["status"] == "void":
            conn.close()
            raise HTTPException(409, "此序號已報廢，報廢是終態，無法直接歸還庫存")
        conn.execute("""
            UPDATE stock_items
            SET status='in_stock', shipping_note_no='', quote_no='', case_device_id='',
                consumed_at='', consumed_by='', note=?, updated_at=?
            WHERE id=?
        """, (note or row["note"], now, item_id))
    else:  # edit_note
        conn.execute("UPDATE stock_items SET note=?, updated_at=? WHERE id=?", (note, now, item_id))
    conn.commit()
    conn.close()

    label = f"{row['part_no']} / {row['serial_no']}"
    _audit(_tok(authorization), "inventory.adjust", "stock_item", str(item_id), label,
           {"action": action, "fromStatus": row["status"]})
    return {"ok": True}


@router.delete("/api/inventory/stock-items/{item_id}")
def delete_stock_item(item_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    row = conn.execute("SELECT * FROM stock_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "庫存項目不存在")
    if row["status"] != "in_stock":
        conn.close()
        raise HTTPException(409, "僅在庫（未出貨/未登載）狀態可直接刪除，其餘狀態請用「退回庫存」調整")
    conn.execute("DELETE FROM stock_items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "inventory.delete", "stock_item", str(item_id),
           f"{row['part_no']} / {row['serial_no']}")
    return {"ok": True}
