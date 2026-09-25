"""Supplier CRUD and visit log endpoints."""
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from db import get_db, next_entity_code, spawn_bg_thread
from helpers import _require_user, _tok, _audit, notify_module_activity, require_any_module
from helpers.procurement import clean_lead_time
from helpers.errors import trace_id
from archive import _backup_suppliers

router = APIRouter()
logger = logging.getLogger(__name__)


class SupplierIn(BaseModel):
    name:   str
    tax_id: Optional[str] = ''
    phone:  Optional[str] = ''
    data:   Optional[dict] = {}
    # 前置時間（天）。**None ＝ 未知，不是 0。** 0 是「現貨、當天可出」，
    # 未知是「我們從來沒追蹤過這家」——兩者在採購排程上是完全不同的事。
    # ⚠️ PUT 時「沒有送這個欄位」與「送了 null」必須分得開，否則舊的前端
    # （不知道有這欄位）每更新一次供應商就會把它清成 NULL，而且沒有任何訊息。
    # 判斷靠 `model_fields_set`，見 update_supplier()。
    lead_time_days: Optional[int] = None


@router.get("/api/suppliers")
def list_suppliers(authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'procurement', 'inventory'), "供應商管理")
    if user["role"] not in ("superadmin", "admin"):
        return []
    conn = get_db()
    rows = conn.execute(
        "SELECT id, code, name, tax_id, phone, lead_time_days, data_json, created_at, updated_at "
        "FROM suppliers ORDER BY name"
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
            **d,
            # 放在 **d 之後是刻意的：真欄位要贏過 data_json 裡可能同名的殘留值。
            "leadTimeDays": row["lead_time_days"],
        })
    return result


@router.post("/api/suppliers")
def create_supplier(body: SupplierIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'procurement', 'inventory'), "供應商管理")
    now = datetime.now().isoformat()
    # ⚠️ 驗證要在下面那個 `except Exception` **之外**做。
    # 那段是用來把 INSERT 的 IntegrityError 轉成乾淨 409 的，但它會一併吞掉
    # clean_lead_time() 丟的 422——負數前置時間會回「建立失敗」而不是說明原因。
    lead_time_days = clean_lead_time(body.lead_time_days)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO suppliers (name, tax_id, phone, lead_time_days, data_json, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (body.name.strip(), body.tax_id or '', body.phone or '',
             lead_time_days,
             json.dumps(body.data or {}, ensure_ascii=False), now, now)
        )
        conn.commit()
        sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        code = next_entity_code(conn, 'suppliers', 'S')
        conn.execute("UPDATE suppliers SET code=? WHERE id=?", (code, sid))
        conn.commit()
    except Exception as e:
        conn.close()
        tid = trace_id()
        logger.exception("supplier create failed trace=%s", tid)
        raise HTTPException(409, f"建立失敗（代碼 {tid}）")
    conn.close()
    spawn_bg_thread(_backup_suppliers)
    _audit(_tok(authorization), 'supplier.create', 'supplier', body.name, body.name)
    notify_module_activity("供應商管理", "建立", user.get("display_name") or user["username"],
                            body.name, "suppliers.html")
    return {"id": sid, "name": body.name, "code": code}


@router.put("/api/suppliers/{sid}")
def update_supplier(sid: int, body: SupplierIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'procurement', 'inventory'), "供應商管理")
    now = datetime.now().isoformat()
    conn = get_db()
    if not conn.execute("SELECT id FROM suppliers WHERE id=?", (sid,)).fetchone():
        conn.close()
        raise HTTPException(404, "供應商不存在")
    # 只有「這次真的送了 lead_time_days」才動它。沒送就保持原值——
    # 不知道有這個欄位的舊前端，不應該因為存了一次供應商就把它清掉。
    sets   = ["name=?", "tax_id=?", "phone=?", "data_json=?", "updated_at=?"]
    params = [body.name.strip(), body.tax_id or '', body.phone or '',
              json.dumps(body.data or {}, ensure_ascii=False), now]
    if "lead_time_days" in body.model_fields_set:
        sets.append("lead_time_days=?")
        params.append(clean_lead_time(body.lead_time_days))
    params.append(sid)
    conn.execute(f"UPDATE suppliers SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    conn.close()
    spawn_bg_thread(_backup_suppliers)
    _audit(_tok(authorization), 'supplier.update', 'supplier', str(sid), body.name)
    return {"ok": True}


@router.delete("/api/suppliers/{sid}")
def delete_supplier(sid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'procurement', 'inventory'), "供應商管理")
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
    require_any_module(user, ('customer', 'procurement', 'inventory'), "供應商管理")
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



# ── 個資蒐集告知（CUSTOMIZATION-SPEC §9.3，2026-09-26 擴大到聯絡人）──────────────────────
# 告知的對象是每一位聯絡人（自然人），不是供應商本身；紀錄存在 L1 設定鍵 `privacy_notice_acks`
# （`supplier_contact:<供應商id>:<聯絡人id>`），由伺服器蓋時間與人員，已記錄的不覆蓋。沒有紀錄不擋存檔。

def _privacy_contacts(conn, sid: int):
    row = conn.execute("SELECT name, data_json FROM suppliers WHERE id=?", (sid,)).fetchone()
    if not row:
        return None, []
    try:
        d = json.loads(row["data_json"] or "{}")
    except ValueError:
        d = {}
    contacts = d.get("contacts") if isinstance(d, dict) else None
    return row["name"], (contacts if isinstance(contacts, list) else [])


@router.get("/api/suppliers/{sid}/privacy-notice")
def get_supplier_contact_privacy_acks(sid: int, authorization: str = Header(None)):
    """每一位聯絡人的「已告知」紀錄：{"acks": {聯絡人id: 紀錄}}（沒有紀錄的不列）。"""
    from helpers import privacy_notice as _pn
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'procurement', 'inventory'), "供應商管理")
    conn = get_db()
    name, _ = _privacy_contacts(conn, sid)
    conn.close()
    if name is None:
        raise HTTPException(404, "供應商不存在")
    return {"acks": _pn.acks_with_prefix("supplier_contact", sid)}


@router.post("/api/suppliers/{sid}/contacts/{ctid}/privacy-notice/ack")
def ack_supplier_contact_privacy_notice(sid: int, ctid: str, authorization: str = Header(None)):
    """記錄「已告知這位聯絡人」：時間與人員由伺服器決定；已記錄的不覆蓋。聯絡人要先存進供應商資料。"""
    from helpers import privacy_notice as _pn
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'procurement', 'inventory'), "供應商管理")
    conn = get_db()
    name, contacts = _privacy_contacts(conn, sid)
    conn.close()
    if name is None:
        raise HTTPException(404, "供應商不存在")
    ct = next((c for c in contacts if isinstance(c, dict) and str(c.get("id")) == str(ctid)), None)
    if ct is None:
        raise HTTPException(404, "找不到這位聯絡人（請先儲存供應商資料）")
    rec, created = _pn.record_purpose_ack("supplier_contact", f"{sid}:{ctid}", user, "contact")
    if created:
        _audit(_tok(authorization), 'supplier.privacy_notice_ack', 'supplier', f"{sid}:{ctid}",
               f"{name}／{ct.get('name') or ''}", {"noticeHash": rec.get("noticeHash")})
    return {"ack": rec, "created": created}
