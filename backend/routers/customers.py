"""Customer CRUD and visit log endpoints."""
import json
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from core.txn import write_txn
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


# ── Excel 匯入（票 fix/excel-import-dataloss）────────────────────────────────
# 舊行為：前端逐列 PUT 整包覆蓋 data_json（拜訪紀錄、別名、聯絡人消失）、名稱相同就併成一家、每列各觸發一次整表備份。
# 新規則：①空白＝不更新、更新是「合併進既有 data_json」；②統編相同才算同一家，只有名稱相同＝可能重複（列出、不合併、不匯入）；
#         ③先 dryRun 回計畫讓畫面確認，確認後整批一個交易、備份與通知各一次。
_IMPORT_MAX_ROWS = 5000
_IMPORT_DATA_KEYS = ("nameEn", "email", "fax", "website", "invoiceAddress", "deliveryAddress", "industry", "type",
                     "ownerName", "paymentMethod", "notes", "tags", "contacts")      # 白名單：visits／alias 等不接受由匯入寫入


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and not v)


def _digits(v):
    return re.sub(r"\D", "", str(v or ""))


def _norm_incoming(r: dict) -> dict:
    data = r.get("data") if isinstance(r.get("data"), dict) else {}
    clean = {}
    for k in _IMPORT_DATA_KEYS:
        v = data.get(k)
        if k == "tags":
            v = [str(t).strip() for t in (v if isinstance(v, list) else []) if str(t).strip()]
        elif k == "contacts":
            v = [{kk: str(vv).strip() if isinstance(vv, str) else vv for kk, vv in c.items()} for c in (v if isinstance(v, list) else [])
                 if isinstance(c, dict) and str(c.get("name") or "").strip()]
        else:
            v = str(v).strip() if v is not None else ""
        if not _blank(v):
            clean[k] = v
    return {"row": r.get("row"), "name": str(r.get("name") or "").strip(), "tax": _digits(r.get("taxId")),
            "phone": str(r.get("phone") or "").strip(), "data": clean}


def _merge_customer_data(old: dict, inc: dict) -> dict:
    """合併：檔案有給（非空）的欄位才動；其餘原樣保留。標籤取聯集；聯絡人同名補空白欄位、不同名附加。"""
    out = dict(old)
    for k, v in inc.items():
        if k == "tags":
            have = list(out.get("tags") or [])
            out["tags"] = have + [t for t in v if t not in have]
        elif k == "contacts":
            have = [dict(c) for c in (out.get("contacts") or []) if isinstance(c, dict)]
            for c in v:
                same = next((h for h in have if (h.get("name") or "") == c["name"]), None)
                if same is None:
                    have.append(c)
                else:
                    for kk, vv in c.items():
                        if not _blank(vv) and _blank(same.get(kk)):
                            same[kk] = vv
            out["contacts"] = have
        else:
            out[k] = v
    return out


def _plan_customer_import(conn, rows: list) -> list:
    """每列 ⇒ {row, name, action: create|update|duplicate|error, ...}。唯讀；dryRun 與正式匯入用同一份。"""
    existing = [dict(r) for r in conn.execute("SELECT id, name, tax_id, phone, data_json FROM customers").fetchall()]
    by_tax, by_name = {}, {}
    for e in existing:
        t = _digits(e["tax_id"])
        if t:
            by_tax.setdefault(t, []).append(e)
        by_name.setdefault((e["name"] or "").strip(), []).append(e)
    seen_tax, seen_name, plan = set(), set(), []
    for raw in rows:
        r = _norm_incoming(raw if isinstance(raw, dict) else {})
        item = {"row": r["row"], "name": r["name"], "in": r}
        if not r["name"]:
            item.update(action="error", reason="公司名稱不可空白")
        elif r["tax"] and r["tax"] in seen_tax:
            item.update(action="error", reason="同一個檔案裡統編 %s 出現多次，這一列未匯入" % r["tax"])
        elif r["tax"]:
            hits = by_tax.get(r["tax"], [])
            if len(hits) > 1:
                item.update(action="duplicate", reason="統編 %s 在系統裡對到 %d 家客戶，無法判斷是哪一家，未匯入" % (r["tax"], len(hits)))
            elif hits:
                item.update(action="update", target=hits[0])
            elif by_name.get(r["name"]) or r["name"] in seen_name:
                item.update(action="duplicate", reason="系統裡已有同名客戶「%s」但統編不同或沒有統編，可能是同一家，未匯入（請人工確認）" % r["name"])
            else:
                item.update(action="create")
            seen_tax.add(r["tax"])
        else:
            if by_name.get(r["name"]) or r["name"] in seen_name:
                item.update(action="duplicate", reason="只有名稱相同（檔案沒有統編），可能與既有客戶重複，未匯入（請補統編或人工確認）")
            else:
                item.update(action="create")
        if item.get("action") == "create":
            seen_name.add(r["name"])
        plan.append(item)
    return plan


def _plan_summary(plan: list) -> dict:
    count = lambda a: sum(1 for p in plan if p["action"] == a)               # noqa: E731
    return {"created": count("create"), "updated": count("update"), "failed": count("error"),
            "duplicates": [{"row": p["row"], "name": p["name"], "reason": p["reason"]} for p in plan if p["action"] == "duplicate"],
            "errors": ["第 %s 行：%s" % (p["row"], p["reason"]) for p in plan if p["action"] == "error"]}


@router.post("/api/customers/import-rows")
def import_customer_rows(body: dict, authorization: str = Header(None)):
    """Excel 匯入（已在瀏覽器解析成列）。`dryRun:true` ⇒ 只回計畫（新增／更新／可能重複幾筆），不寫入。"""
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'case_manage', 'dev_crm', 'procurement'), "客戶管理")
    rows = body.get("rows")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "沒有可匯入的資料列")
    if len(rows) > _IMPORT_MAX_ROWS:
        raise HTTPException(400, "一次最多匯入 %d 列，請分檔" % _IMPORT_MAX_ROWS)
    dry = body.get("dryRun") is True
    conn = get_db()
    written = []
    try:
        if dry:
            return _plan_summary(_plan_customer_import(conn, rows))
        now = datetime.now().isoformat()
        with write_txn(conn):                    # 整批一個交易：中途失敗不留半批
            plan = _plan_customer_import(conn, rows)      # 拿鎖之後重算：預覽到確認之間資料可能已被別人改
            for p in plan:
                r = p["in"]
                if p["action"] == "create":
                    data = dict(r["data"])
                    data.setdefault("type", "一般")
                    data["active"] = True
                    cur = conn.execute("INSERT INTO customers (name, tax_id, phone, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                                       (r["name"], r["tax"], r["phone"], json.dumps(data, ensure_ascii=False), now, now))
                    conn.execute("UPDATE customers SET code=? WHERE id=?", (next_entity_code(conn, 'customers', 'C'), cur.lastrowid))
                    written.append(("customer.create", cur.lastrowid, r["name"]))
                elif p["action"] == "update":
                    t = p["target"]
                    old = json.loads(t["data_json"] or "{}")
                    conn.execute("UPDATE customers SET name=?, tax_id=?, phone=?, data_json=?, updated_at=? WHERE id=?",
                                 (t["name"], t["tax_id"], r["phone"] or t["phone"],
                                  json.dumps(_merge_customer_data(old, r["data"]), ensure_ascii=False), now, t["id"]))
                    written.append(("customer.update", t["id"], t["name"]))
            conn.commit()
    except HTTPException:
        raise
    except Exception:
        tid = trace_id()
        logger.exception("customer import failed trace=%s", tid)
        raise HTTPException(409, f"匯入失敗，沒有任何資料被寫入（代碼 {tid}）")
    finally:
        conn.close()
    result = _plan_summary(plan)
    if written:
        spawn_bg_thread(_backup_customers)                       # 整批只備份一次（舊行為：每列一次）
        tok = _tok(authorization)
        for action, cid, name in written:
            _audit(tok, action, 'customer', str(cid), name, {"via": "excel_import"})
        notify_module_activity("客戶管理", "匯入", user.get("display_name") or user["username"],
                               "Excel 匯入：新增 %d 筆、更新 %d 筆" % (result["created"], result["updated"]), "customers.html")
    return result


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



# ── 個資蒐集告知（CUSTOMIZATION-SPEC §9.3，2026-09-26 擴大到聯絡人）──────────────────────
# 告知的對象是每一位聯絡人（自然人），不是客戶本身；紀錄存在 L1 設定鍵 `privacy_notice_acks`
# （`customer_contact:<客戶id>:<聯絡人id>`），由伺服器蓋時間與人員，已記錄的不覆蓋。沒有紀錄不擋存檔。

def _privacy_contacts(conn, cid: int):
    row = conn.execute("SELECT name, data_json FROM customers WHERE id=?", (cid,)).fetchone()
    if not row:
        return None, []
    try:
        d = json.loads(row["data_json"] or "{}")
    except ValueError:
        d = {}
    contacts = d.get("contacts") if isinstance(d, dict) else None
    return row["name"], (contacts if isinstance(contacts, list) else [])


@router.get("/api/customers/{cid}/privacy-notice")
def get_customer_contact_privacy_acks(cid: int, authorization: str = Header(None)):
    """每一位聯絡人的「已告知」紀錄：{"acks": {聯絡人id: 紀錄}}（沒有紀錄的不列）。"""
    from helpers import privacy_notice as _pn
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'case_manage', 'dev_crm', 'procurement'), "客戶管理")
    conn = get_db()
    name, _ = _privacy_contacts(conn, cid)
    conn.close()
    if name is None:
        raise HTTPException(404, "客戶不存在")
    return {"acks": _pn.acks_with_prefix("customer_contact", cid)}


@router.post("/api/customers/{cid}/contacts/{ctid}/privacy-notice/ack")
def ack_customer_contact_privacy_notice(cid: int, ctid: str, authorization: str = Header(None)):
    """記錄「已告知這位聯絡人」：時間與人員由伺服器決定；已記錄的不覆蓋。聯絡人要先存進客戶資料。"""
    from helpers import privacy_notice as _pn
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'case_manage', 'dev_crm', 'procurement'), "客戶管理")
    conn = get_db()
    name, contacts = _privacy_contacts(conn, cid)
    conn.close()
    if name is None:
        raise HTTPException(404, "客戶不存在")
    ct = next((c for c in contacts if isinstance(c, dict) and str(c.get("id")) == str(ctid)), None)
    if ct is None:
        raise HTTPException(404, "找不到這位聯絡人（請先儲存客戶資料）")
    rec, created = _pn.record_purpose_ack("customer_contact", f"{cid}:{ctid}", user, "contact")
    if created:
        _audit(_tok(authorization), 'customer.privacy_notice_ack', 'customer', f"{cid}:{ctid}",
               f"{name}／{ct.get('name') or ''}", {"noticeHash": rec.get("noticeHash")})
    return {"ack": rec, "created": created}
