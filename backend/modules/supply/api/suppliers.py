"""Supplier CRUD and visit log endpoints."""
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from db import get_db, next_entity_code, spawn_bg_thread
from helpers import _require_user, _tok, _audit, notify_module_activity
from helpers import perm
from helpers.procurement import clean_lead_time
from helpers.errors import trace_id
from helpers import list_catalog
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


def _gate_custom_fields(data, old_data):
    """T61 S5：供應商的自訂欄位閘門（旗標 builder_custom_fields.enabled 關閉 ⇒ 不介入：送來的 customFields 不存、舊值保留）。
    `data` 沒有 customFields 這個鍵＝沒有要改（舊頁面不知道這個欄位），帶回舊值；沒有值就不寫這個鍵。型別錯 ⇒ 400。回傳要存的 data。"""
    from helpers import builtin_fields as _bf
    data = dict(data or {})
    old = (old_data or {}).get("customFields")
    if "customFields" not in data:
        if old:
            data["customFields"] = old
        return data
    if data["customFields"] == old:
        if not old:
            data.pop("customFields", None)
        return data
    new, errors, _ignored = _bf.gate("supplier", data["customFields"], old)
    if errors:
        raise HTTPException(400, "自訂欄位有問題：" + "；".join(e["message"] for e in errors))
    if new:
        data["customFields"] = new
    else:
        data.pop("customFields", None)
    return data


# T66 L0：供應商清單登記到清單目錄（先導；沒有金額欄。排序／筆數目前由前端處理，個人偏好之後才接）。
list_catalog.register_list("supply:suppliers", "supply", {
    "label": "供應商清單",
    "modules": ["customer", "procurement", "inventory"],      # 與 /api/suppliers 的 legacy 閘相同（supply.supplier.* 的 legacy 宣告）
    "columns": [
        {"id": "name", "label": "公司名稱", "sortable": True, "required": True},
        {"id": "alias", "label": "內部簡稱", "sortable": True},
        {"id": "taxId", "label": "統一編號", "sortable": True},
        {"id": "category", "label": "類型", "sortable": True},
        {"id": "contact", "label": "主要聯絡人", "sortable": True},
        {"id": "phone", "label": "電話"},
        {"id": "currency", "label": "幣別", "sortable": True},
        {"id": "paymentTerms", "label": "付款條件"},
        {"id": "active", "label": "狀態", "sortable": True},
    ],
    "defaults": {"columns": ["name", "alias", "taxId", "category", "contact", "phone", "currency", "paymentTerms", "active"],
                 "sort": {"col": "name", "dir": "asc"}, "pageSize": 50},
    "pageSizeCeiling": 200, "pageSizeMenu": [20, 50, 100, 200],
})


#: 一條龍 P5a：非管理員（有採購模組權限）能看到的供應商欄位——**白名單**，一個函式；沒有列在這裡的鍵（銀行帳號、customFields、聯絡人明細、備註…）一律不回。
#: 欄位＝id／code／name／taxId／phone／leadTimeDays＋清單目錄（`supply:suppliers`）的欄位 alias／category／contact／currency／paymentTerms／active。
BUYER_SUPPLIER_FIELDS = ("id", "code", "name", "taxId", "phone", "leadTimeDays", "alias", "category", "contact", "currency", "paymentTerms", "active")


def _buyer_list_allowed(user) -> bool:
    from helpers.auth import user_has_module
    from helpers.onepipe_flags import flag_on
    return flag_on("buyer_access") and user_has_module(user, "procurement")


def _buyer_row(row, d) -> dict:
    """唯讀白名單列：只取 `BUYER_SUPPLIER_FIELDS`；`d`＝data_json（取不到的鍵給安全預設，不原樣倒出）。"""
    d = d if isinstance(d, dict) else {}
    src = {"id": row["id"], "code": row["code"] or "", "name": row["name"], "taxId": row["tax_id"], "phone": row["phone"],
           "leadTimeDays": row["lead_time_days"]}
    out = {k: src[k] for k in ("id", "code", "name", "taxId", "phone", "leadTimeDays")}
    for k in ("alias", "category", "currency", "paymentTerms"):
        v = d.get(k)
        out[k] = v if isinstance(v, str) else ""
    cs = d.get("contacts")                                   # 「主要聯絡人」＝第一位聯絡人的姓名（清單欄位 contact）；只取姓名，不帶職稱／電話／信箱／LINE
    first = cs[0] if isinstance(cs, list) and cs and isinstance(cs[0], dict) else {}
    out["contact"] = first.get("name") if isinstance(first.get("name"), str) else ""
    out["active"] = d.get("active") if isinstance(d.get("active"), bool) else True
    return out


def _buyer_list() -> list:
    conn = get_db()
    try:
        rows = conn.execute("SELECT id, code, name, tax_id, phone, lead_time_days, data_json FROM suppliers ORDER BY name").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            d = json.loads(r["data_json"] or "{}")
        except ValueError:
            d = {}
        out.append(_buyer_row(r, d))
    return out


@router.get("/api/suppliers")
def list_suppliers(authorization: str = Header(None)):
    user = _require_user(authorization)
    perm.require(user, "supply.supplier.view")
    if user["role"] not in ("superadmin", "admin"):
        # 一條龍 P5a（旗標 onepipe.buyer_access，預設關＝與今天相同回空）：擁有採購模組權限者看唯讀白名單欄位（見 `_buyer_row`）
        if _buyer_list_allowed(user):
            return _buyer_list()
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
    perm.require(user, "supply.supplier.create")
    now = datetime.now().isoformat()
    # ⚠️ 驗證要在下面那個 `except Exception` **之外**做。
    # 那段是用來把 INSERT 的 IntegrityError 轉成乾淨 409 的，但它會一併吞掉
    # clean_lead_time() 丟的 422——負數前置時間會回「建立失敗」而不是說明原因。
    lead_time_days = clean_lead_time(body.lead_time_days)
    new_data = _gate_custom_fields(body.data, None)          # 400 在 try 之外丟（不被下面的 except 吞成『建立失敗』）
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO suppliers (name, tax_id, phone, lead_time_days, data_json, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (body.name.strip(), body.tax_id or '', body.phone or '',
             lead_time_days,
             json.dumps(new_data, ensure_ascii=False), now, now)
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
    perm.require(user, "supply.supplier.edit")
    now = datetime.now().isoformat()
    conn = get_db()
    _row = conn.execute("SELECT id, data_json FROM suppliers WHERE id=?", (sid,)).fetchone()
    if not _row:
        conn.close()
        raise HTTPException(404, "供應商不存在")
    try:
        new_data = _gate_custom_fields(body.data, json.loads(_row["data_json"] or "{}"))
    except HTTPException:
        conn.close()
        raise
    # 只有「這次真的送了 lead_time_days」才動它。沒送就保持原值——
    # 不知道有這個欄位的舊前端，不應該因為存了一次供應商就把它清掉。
    sets   = ["name=?", "tax_id=?", "phone=?", "data_json=?", "updated_at=?"]
    params = [body.name.strip(), body.tax_id or '', body.phone or '',
              json.dumps(new_data, ensure_ascii=False), now]
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


def _supplier_references(conn, sid: int) -> dict:
    """一條龍 P5b：誰在用這個供應商——採購單（`case_extra_expenses.data_json.supplierId`）與材料申請（`quotations.data_json` 的 `materialOrders[].supplierId`）。
    只做『先用 LIKE 粗篩、再逐筆解析比對』（不用 json_extract）；案件模組沒裝（沒有那些表）⇒ 空。回 `{"po": [單號…], "orders": [案號…]}`。"""
    out = {"po": [], "orders": []}

    def _hit(v):
        try:
            return int(v) == int(sid)
        except (TypeError, ValueError):
            return False
    try:
        for r in conn.execute("SELECT doc_code, data_json FROM case_extra_expenses WHERE kind='purchase_order' AND data_json LIKE '%\"supplierId\"%'").fetchall():
            try:
                if _hit((json.loads(r["data_json"] or "{}") or {}).get("supplierId")):
                    out["po"].append(r["doc_code"] or "")
            except ValueError:
                continue
        for r in conn.execute("SELECT quote_no, data_json FROM quotations WHERE data_json LIKE '%\"supplierId\"%'").fetchall():
            try:
                d = json.loads(r["data_json"] or "{}") or {}
            except ValueError:
                continue
            orders = ((d.get("caseRecord") or {}).get("materialOrders") if isinstance(d.get("caseRecord"), dict) else None) or []
            if any(isinstance(o, dict) and _hit(o.get("supplierId")) for o in orders):
                out["orders"].append(r["quote_no"])
    except Exception:                                                          # noqa: BLE001  沒有那些表（案件模組未安裝）⇒ 沒有引用
        return {"po": [], "orders": []}
    return out


def _refs_message(name: str, refs: dict) -> str:
    parts = []
    if refs["po"]:
        parts.append("%d 張採購單（%s%s）" % (len(refs["po"]), "、".join(refs["po"][:3]), "…" if len(refs["po"]) > 3 else ""))
    if refs["orders"]:
        parts.append("%d 個案件的材料申請（%s%s）" % (len(refs["orders"]), "、".join(refs["orders"][:3]), "…" if len(refs["orders"]) > 3 else ""))
    return "供應商「%s」已被%s使用，無法刪除。請先更換這些單據的供應商，或將此供應商改為停用。" % (name, "與".join(parts))


@router.delete("/api/suppliers/{sid}")
def delete_supplier(sid: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    perm.require(user, "supply.supplier.delete")
    conn = get_db()
    row = conn.execute("SELECT name FROM suppliers WHERE id=?", (sid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "供應商不存在")
    sname = row['name']
    from helpers.onepipe_flags import flag_on
    if flag_on("supplier_master", conn=conn):                                             # 一條龍 P5b：被採購單／材料申請引用的供應商不能刪（旗標關＝與目前相同）
        refs = _supplier_references(conn, sid)
        if refs["po"] or refs["orders"]:
            conn.close()
            raise HTTPException(409, _refs_message(sname, refs))
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
    perm.require(user, "supply.supplier.edit")
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
    """每一位聯絡人的「已告知」紀錄：{"acks": {聯絡人id: 紀錄}}（沒有紀錄的不列）。管理員看完整紀錄；非管理員只看 `{at}`（已告知與日期）。"""
    from helpers import privacy_notice as _pn
    user = _require_user(authorization)
    perm.require(user, "supply.supplier.view")
    conn = get_db()
    name, _ = _privacy_contacts(conn, sid)
    conn.close()
    if name is None:
        raise HTTPException(404, "供應商不存在")
    acks = _pn.acks_with_prefix("supplier_contact", sid)
    return {"acks": _pn.acks_view(user, acks)}


@router.post("/api/suppliers/{sid}/contacts/{ctid}/privacy-notice/ack")
def ack_supplier_contact_privacy_notice(sid: int, ctid: str, authorization: str = Header(None)):
    """記錄「已告知這位聯絡人」：時間與人員由伺服器決定；已記錄的不覆蓋。聯絡人要先存進供應商資料。"""
    from helpers import privacy_notice as _pn
    user = _require_user(authorization)
    perm.require(user, "supply.supplier.edit")
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
    return {"ack": _pn.ack_view(user, rec), "created": created}
