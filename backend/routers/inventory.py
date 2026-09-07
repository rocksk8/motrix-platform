"""序號級庫存（stock_items）：進貨批次、序號清單、料號彙總、人工調整。

粒度為序號級（比照設備登載 SN/MAC 結構），一列 = 一台實體設備。狀態機：
in_stock -> shipped（出貨單核准自動扣庫存，見 shipping_notes.py）
in_stock -> installed（設備登載自動扣庫存，見 quotations.py update_case_record）
in_stock -> void（人工報廢/遺失/盤點差異）
shipped/installed -> in_stock（人工 return_to_stock 更正，見 §出貨單回滾設計）
"""
import json
import math
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
    parts_rows = conn.execute("SELECT part_no, name, brand, unit, category, safety_stock FROM parts WHERE active=1").fetchall()
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

    _STOCK_LEVEL_YELLOW_MULTIPLIER = 1.5  # 在庫 < 安全庫存 * 此倍數時顯示黃燈（接近安全庫存）

    def _stock_level(in_cnt: int, safety_stock: int) -> str:
        """庫存水位燈號（2026-08-28）：safety_stock<=0 代表未設定門檻，一律綠燈，
        不強迫每個料號都要設定；有設定時 <門檻=紅、<門檻*_STOCK_LEVEL_YELLOW_MULTIPLIER=黃、其餘綠。"""
        if safety_stock <= 0:
            return "green"
        if in_cnt < safety_stock:
            return "red"
        if in_cnt < safety_stock * _STOCK_LEVEL_YELLOW_MULTIPLIER:
            return "yellow"
        return "green"

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
        safety_stock = d.get("safety_stock") or 0
        d.update({
            "inStockCount":   in_cnt,
            "inStockValue":   in_value,
            "shippedCount":   shipped_cnt,
            "installedCount": installed_cnt,
            "voidCount":      void_cnt,
            "lastInAt":       st.get("in_stock", {}).get("last_in", ""),
            "safetyStock":    safety_stock,
            "stockLevel":     _stock_level(in_cnt, safety_stock),
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
            "safetyStock":    0,
            "stockLevel":     _stock_level(in_cnt, 0),
        })
    return {"items": result}


# ── 採購建議（2026-09-07，架構地圖 §6.6） ───────────────────────────────────────

@router.get("/api/inventory/purchase-suggestions")
def purchase_suggestions(authorization: str = Header(None)):
    """依安全庫存缺口自動生成採購建議清單。

    **跟架構地圖 §6.6 原始建議的落差**：該條建議寫「資料已齊備、開發成本不高」，
    但實際查證後系統完全沒有追蹤「供應商前置時間」這個概念（`suppliers`/`parts`
    表都沒有對應欄位）——這裡刻意不做 ETA 預估，只回答「這個料號該補多少、上次
    是跟哪個供應商用多少單價買的」，不猜前置時間；缺料急迫程度用既有的
    `stockLevel`（紅/黃燈，`parts_summary()` 同一套邏輯）表示，不是用天數。

    建議採購量 = 補到「黃燈門檻」（安全庫存 * 1.5，跟既有水位燈號定義一致，
    見 `_stock_level()`）所需的數量，不是只補到剛好等於安全庫存——否則採購
    完成後燈號會立刻從紅燈變黃燈，還是會被同一張建議清單再抓出來一次。

    供應商/單價來源：`stock_batches` 該料號最近一筆進貨批次（依 created_at
    排序），查無進貨紀錄則供應商留空、單價退回 `parts.cost`（料件標準成本）。
    只回傳目前在紅燈或黃燈區間、且已設定安全庫存（>0）的料號。
    """
    _require_user(authorization)
    conn = get_db()
    parts_rows = conn.execute(
        "SELECT part_no, name, brand, unit, category, cost, safety_stock "
        "FROM parts WHERE active=1 AND safety_stock > 0"
    ).fetchall()
    in_stock_by_part = {
        r["part_no"]: r["cnt"] for r in conn.execute(
            "SELECT part_no, COUNT(*) AS cnt FROM stock_items WHERE status='in_stock' GROUP BY part_no"
        ).fetchall()
    }
    # SQLite 特性：GROUP BY 搭配單一 MAX() 聚合時，其餘裸欄位保證來自產生該
    # MAX 值的那一列（本專案既有 migration 已依賴同一特性，見 _m070_stock_batches()）
    last_batch_by_part = {
        r["part_no"]: {"supplierId": r["supplier_id"], "supplierName": r["supplier_name"],
                        "lastPurchaseAt": r["last_at"]}
        for r in conn.execute(
            "SELECT part_no, supplier_id, supplier_name, MAX(created_at) AS last_at "
            "FROM stock_batches WHERE part_no != '' GROUP BY part_no"
        ).fetchall()
    }
    conn.close()

    yellow_multiplier = 1.5  # 跟 parts_summary()::_stock_level() 的黃燈門檻定義一致
    result = []
    for p in parts_rows:
        d = dict(p)
        safety_stock = d["safety_stock"] or 0
        in_stock = in_stock_by_part.get(d["part_no"], 0)
        target = math.ceil(safety_stock * yellow_multiplier)  # 補到黃燈門檻，避免浮點小數採購量
        suggested_qty = max(0, target - in_stock)
        if suggested_qty <= 0:
            continue
        level = "red" if in_stock < safety_stock else "yellow"
        last_batch = last_batch_by_part.get(d["part_no"], {})
        unit_cost = d.get("cost") or 0
        result.append({
            "part_no": d["part_no"], "name": d["name"], "brand": d["brand"],
            "unit": d["unit"], "category": d["category"],
            "safetyStock": safety_stock, "inStockCount": in_stock,
            "stockLevel": level, "suggestedQty": suggested_qty,
            "unitCost": unit_cost, "estimatedCost": round(unit_cost * suggested_qty, 2),
            "lastSupplierId": last_batch.get("supplierId"),
            "lastSupplierName": last_batch.get("supplierName") or "",
            "lastPurchaseAt": last_batch.get("lastPurchaseAt") or "",
        })
    result.sort(key=lambda r: (r["stockLevel"] != "red", -r["estimatedCost"]))
    total_estimated_cost = round(sum(r["estimatedCost"] for r in result), 2)
    return {"items": result, "count": len(result), "totalEstimatedCost": total_estimated_cost}


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

# ⚠️ 這支必須在 GET /api/inventory/batches/{batch_no} 之前註冊，否則
# "last-paid-bank-account" 這個路徑會被當成 batch_no 吃掉（比照
# invoice_vouchers.py::/remaining 的既有慣例）。
@router.get("/api/inventory/batches/last-paid-bank-account")
def get_last_paid_bank_account(supplier_id: Optional[int] = None, authorization: str = Header(None)):
    """查這個供應商上一次「標記已付款」用的銀行帳戶，供標記 Modal 開啟時預帶值。
    見 accounting_export.py 檔頭「標記已付款/已收款時的銀行帳戶預設值」說明。"""
    _require_user(authorization)
    if not supplier_id:
        return {"name": "", "acctCode": ""}
    conn = get_db()
    row = conn.execute(
        "SELECT paid_bank_account_name, paid_bank_account_code FROM stock_batches "
        "WHERE supplier_id=? AND is_paid=1 AND paid_bank_account_code != '' "
        "ORDER BY paid_at DESC LIMIT 1",
        (supplier_id,),
    ).fetchone()
    conn.close()
    if not row:
        return {"name": "", "acctCode": ""}
    return {"name": row["paid_bank_account_name"], "acctCode": row["paid_bank_account_code"]}


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

    supplier_id = body.get("supplier_id") or body.get("supplierId")
    supplier_name = ""
    if supplier_id:
        srow = conn.execute("SELECT name FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
        supplier_name = srow["name"] if srow else ""
    invoice_no = (body.get("invoice_no") or body.get("invoiceNo") or "").strip()

    for c in clean:
        conn.execute("""
            INSERT INTO stock_items (part_no, serial_no, mac, status, batch_no, cost, note,
                                      created_by, created_at, updated_at)
            VALUES (?,?,?,'in_stock',?,?,?,?,?,?)
        """, (part_no, c["serial_no"], c["mac"], batch_no, cost, c["note"] or note, actor, now, now))
    conn.execute("""
        INSERT INTO stock_batches (batch_no, part_no, supplier_id, supplier_name, invoice_no,
                                    note, created_by, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (batch_no, part_no, supplier_id, supplier_name, invoice_no, note, actor, now, now))
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
    # qty/total_cost 刻意即時從 stock_items 群組加總，不信任 stock_batches 裡
    # 快取的值（表本身也沒存這兩欄）——避免跟人工調整（adjust_stock_item）脫鉤，
    # 見 db.py::_m070_stock_batches() docstring。供應商/發票號/付款狀態才是
    # stock_batches header 專屬的批次層級屬性。
    rows = conn.execute("""
        SELECT si.batch_no, si.part_no, COUNT(*) AS qty, SUM(si.cost) AS total_cost,
               MIN(si.created_at) AS created_at, MIN(si.created_by) AS created_by,
               sb.supplier_id, sb.supplier_name, sb.invoice_no,
               sb.is_paid, sb.paid_by, sb.paid_at, sb.note,
               sb.paid_bank_account_name, sb.paid_bank_account_code
        FROM stock_items si
        LEFT JOIN stock_batches sb ON sb.batch_no = si.batch_no
        WHERE si.batch_no != ''
        GROUP BY si.batch_no
        ORDER BY created_at DESC
    """).fetchall()
    conn.close()
    return {"items": [dict(r) for r in rows]}


@router.get("/api/inventory/batches/{batch_no}")
def get_batch(batch_no: str, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("SELECT * FROM stock_items WHERE batch_no=? ORDER BY id", (batch_no,)).fetchall()
    header = conn.execute("SELECT * FROM stock_batches WHERE batch_no=?", (batch_no,)).fetchone()
    conn.close()
    if not rows:
        raise HTTPException(404, "批次不存在")
    return {"batchNo": batch_no, "items": [dict(r) for r in rows],
            "header": dict(header) if header else None}


@router.put("/api/inventory/batches/{batch_no}")
def update_batch_header(batch_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """編輯批次層級屬性（供應商／發票號／備註），不動 stock_items 本身。
    已標記已付款的批次仍可編輯這些欄位（供應商/發票號屬於補登資料，不是
    財務金額，不比照憑證流「已核准鎖定」的邏輯）。"""
    user = _require_user(authorization)
    _require_admin(user)
    conn = get_db()
    header = conn.execute("SELECT * FROM stock_batches WHERE batch_no=?", (batch_no,)).fetchone()
    if not header:
        conn.close()
        raise HTTPException(404, "批次不存在")

    supplier_id = header["supplier_id"]
    supplier_name = header["supplier_name"]
    if "supplier_id" in body or "supplierId" in body:
        supplier_id = body.get("supplier_id", body.get("supplierId"))
        if supplier_id:
            srow = conn.execute("SELECT name FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
            supplier_name = srow["name"] if srow else ""
        else:
            supplier_id = None
            supplier_name = ""

    invoice_no = body.get("invoice_no", body.get("invoiceNo", header["invoice_no"])) or ""
    note = body.get("note", header["note"]) or ""
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE stock_batches SET supplier_id=?, supplier_name=?, invoice_no=?, note=?, updated_at=? "
        "WHERE batch_no=?",
        (supplier_id, supplier_name, invoice_no, note, now, batch_no),
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.post("/api/inventory/batches/{batch_no}/paid-toggle")
def toggle_batch_paid(batch_no: str, body: dict = Body(...), authorization: str = Header(None)):
    """標記/取消標記進貨批次已付款（比照 contractor_payment_vouchers 的
    paid-toggle 慣例），供 T100 傳票匯出（accounting_export.py）作為現金
    基礎的付款事件來源。"""
    user = _require_user(authorization)
    _require_admin(user)
    action = body.get("action")
    if action not in ("pay", "unpay"):
        raise HTTPException(400, "action 必須為 pay 或 unpay")
    conn = get_db()
    header = conn.execute("SELECT * FROM stock_batches WHERE batch_no=?", (batch_no,)).fetchone()
    if not header:
        conn.close()
        raise HTTPException(404, "批次不存在")
    now = datetime.now().isoformat()
    actor = user.get("display_name") or user["username"]
    if action == "pay":
        if header["is_paid"]:
            conn.close()
            raise HTTPException(409, "此批次已標記為已付款")
        paid_at = body.get("paid_at") or body.get("paidAt") or now[:10]
        bank_name = body.get("bank_account_name") or body.get("bankAccountName") or ""
        bank_code = body.get("bank_account_code") or body.get("bankAccountCode") or ""
        conn.execute(
            "UPDATE stock_batches SET is_paid=1, paid_by=?, paid_at=?, "
            "paid_bank_account_name=?, paid_bank_account_code=?, updated_at=? WHERE batch_no=?",
            (actor, paid_at, bank_name, bank_code, now, batch_no),
        )
    else:
        if not header["is_paid"]:
            conn.close()
            raise HTTPException(409, "此批次尚未標記為已付款")
        conn.execute(
            "UPDATE stock_batches SET is_paid=0, paid_by='', paid_at='', "
            "paid_bank_account_name='', paid_bank_account_code='', updated_at=? WHERE batch_no=?",
            (now, batch_no),
        )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), f"inventory.batch_{action}", "stock_batch", batch_no,
           f"{batch_no} 標記{'已付款' if action == 'pay' else '取消已付款'}")
    return {"ok": True}


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
