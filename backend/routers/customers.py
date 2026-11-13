"""Customer CRUD and visit log endpoints."""
import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from core.txn import write_txn
from db import get_db, next_entity_code, spawn_bg_thread
from helpers import _require_user, _tok, _audit, notify_module_activity, require_any_module
from helpers.audit import _DETAIL_MAX, _derive_fields
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
# 規則：①空白＝不更新、更新是「合併進既有 data_json」（備註是追加、不是覆蓋）；
#       ②統編相同才算同一家；統編相同但公司名稱不同＝「需確認」（預設不寫，畫面上勾選才寫）；只有名稱相同＝可能重複（不合併、不匯入）；
#       ③預覽（dryRun 不是 False 一律當預覽）回每列「舊→新」差異與 planHash；確認時要帶回 planHash，資料在預覽後有變動 ⇒ 409 請重新預覽；
#       ④整批一個交易、備份與通知各一次。
_IMPORT_MAX_ROWS = 5000
_IMPORT_MAX_CONTACTS = 50                      # 每列聯絡人上限
_IMPORT_MAX_TEXT = 2000                        # 每個文字欄位上限（超過截斷）
_IMPORT_MAX_DIFF_ROWS = 200                    # 預覽回傳差異的列數上限
_IMPORT_DATA_KEYS = ("nameEn", "email", "fax", "website", "invoiceAddress", "deliveryAddress", "industry", "type",
                     "ownerName", "paymentMethod", "notes", "tags", "contacts")      # 白名單：visits／alias 等不接受由匯入寫入
_IMPORT_CONTACT_KEYS = ("id", "name", "title", "phone", "email")                      # 聯絡人只收這幾個鍵，其餘丟掉
_IMPORT_FIELD_LABELS = {"phone": "電話", "nameEn": "英文名稱", "email": "Email", "fax": "傳真", "website": "網站",
                        "invoiceAddress": "地址", "deliveryAddress": "送貨地址", "industry": "產業別", "type": "客戶類型",
                        "ownerName": "負責業務", "paymentMethod": "付款條件", "notes": "備註", "tags": "內部標籤", "contacts": "聯絡人"}


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and not v)


def _digits(v):
    return re.sub(r"\D", "", str(v or ""))


def _name_key(s):
    """公司名稱比對用：全形半形、大小寫、空白標點、「臺／台」、結尾的公司別都不當成差異。"""
    s = unicodedata.normalize("NFKC", str(s or "")).casefold().replace("臺", "台")
    s = re.sub(r"[\s\-_·・.,。()（）]", "", s)
    return re.sub(r"(股份有限公司|有限公司|股份公司|公司)$", "", s)


def _txt(v):
    return (str(v).strip() if v is not None else "")[:_IMPORT_MAX_TEXT]


def _norm_incoming(r: dict) -> dict:
    data = r.get("data") if isinstance(r.get("data"), dict) else {}
    clean = {}
    for k in _IMPORT_DATA_KEYS:
        v = data.get(k)
        if k == "tags":
            v = [_txt(t)[:50] for t in (v if isinstance(v, list) else [])[:50] if _txt(t)]
        elif k == "contacts":
            cs = [c for c in (v if isinstance(v, list) else []) if isinstance(c, dict) and _txt(c.get("name"))][:_IMPORT_MAX_CONTACTS]
            v = [{kk: (_txt(c[kk]) if isinstance(c[kk], (str, int, float)) else "") for kk in _IMPORT_CONTACT_KEYS if kk in c} for c in cs]
        else:
            v = _txt(v)
        if not _blank(v):
            clean[k] = v
    return {"row": r.get("row"), "name": _txt(r.get("name")), "tax": _digits(r.get("taxId"))[:20],
            "phone": _txt(r.get("phone"))[:100], "data": clean, "confirm": r.get("confirm") is True}


def _merge_customer_data(old: dict, inc: dict) -> dict:
    """合併：檔案有給（非空）的欄位才動；其餘原樣保留。標籤取聯集；聯絡人同名補空白欄位、不同名附加；
    備註＝追加（換行＋〔Excel 匯入 日期〕＋新內容），內容已經在裡面就不重複加。"""
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
        elif k == "notes":
            have = str(out.get("notes") or "")
            if _blank(have):
                out["notes"] = v
            elif v.strip() not in have:
                out["notes"] = have.rstrip() + "\n〔Excel 匯入 %s〕%s" % (datetime.now().strftime("%Y-%m-%d"), v)
        else:
            out[k] = v
    return out


def _show(v):
    if isinstance(v, list):
        v = "、".join(str(x.get("name") or "") if isinstance(x, dict) else str(x) for x in v)
    return str(v if v is not None else "")[:120]


def _customer_diff(t: dict, old: dict, r: dict) -> list:
    """這一列若寫入，會改哪些欄位：[{field, label, old, new}]（只列真的有變的）。"""
    out = []
    if r["phone"] and r["phone"] != (t["phone"] or ""):
        out.append({"field": "phone", "label": _IMPORT_FIELD_LABELS["phone"], "old": _show(t["phone"]), "new": _show(r["phone"])})
    for k, v in r["data"].items():
        new = _merge_customer_data(old, {k: v}).get(k)
        if new != old.get(k):
            out.append({"field": k, "label": _IMPORT_FIELD_LABELS.get(k, k), "old": _show(old.get(k)), "new": _show(new)})
    return out


def _plan_customer_import(conn, rows: list) -> list:
    """每列 ⇒ {row, name, action: create|update|confirm|duplicate|error, ...}。唯讀；預覽與正式匯入用同一份。"""
    existing = [dict(r) for r in conn.execute("SELECT id, name, tax_id, phone, data_json, updated_at FROM customers").fetchall()]
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
            item.update(action="error", reason="同一個檔案裡統一編號 %s 出現多次，這一列未匯入" % r["tax"])
        elif r["tax"]:
            hits = by_tax.get(r["tax"], [])
            if len(hits) > 1:
                item.update(action="duplicate", reason="統一編號 %s 在系統裡對到 %d 家客戶，無法判斷是哪一家，未匯入" % (r["tax"], len(hits)))
            elif hits:
                if _name_key(hits[0]["name"]) == _name_key(r["name"]):
                    item.update(action="update", target=hits[0])
                else:
                    item.update(action="confirm", target=hits[0],
                                reason="統一編號 %s 在系統裡是「%s」，檔案寫的是「%s」，名稱不同——可能是統一編號打錯" % (r["tax"], hits[0]["name"], r["name"]))
            elif by_name.get(r["name"]) or r["name"] in seen_name:
                item.update(action="duplicate", reason="系統裡已有同名客戶「%s」但統一編號不同或沒有統一編號，可能是同一家，未匯入（請人工確認）" % r["name"])
            else:
                item.update(action="create")
            seen_tax.add(r["tax"])
        else:
            if by_name.get(r["name"]) or r["name"] in seen_name:
                item.update(action="duplicate", reason="只有名稱相同（檔案沒有統一編號），可能與既有客戶重複，未匯入（請補統一編號或人工確認）")
            else:
                item.update(action="create")
        if item.get("action") in ("update", "confirm"):
            try:
                old = json.loads(item["target"]["data_json"] or "{}")
                if not isinstance(old, dict):
                    raise ValueError("not a dict")
                item["old"] = old
                item["diff"] = _customer_diff(item["target"], old, r)
            except Exception:                                    # noqa: BLE001 — 單一客戶資料損毀只影響這一列
                item.update(action="error", reason="系統裡這家客戶的資料格式損毀，這一列未匯入（請通知管理員）")
        if item.get("action") == "create":
            seen_name.add(r["name"])
        plan.append(item)
    return plan


def _code_allocator(conn):
    """批次取客戶代號：與 `db.next_entity_code(conn,'customers','C')` 相同的規則（本月最大三碼序號＋1、跳過已存在與暫存區保留的號），
    但只掃一次資料表、用集合判斷（逐筆呼叫＝每筆重掃、1500 筆新增在寫入鎖裡跑十幾秒）。⇒ 每次呼叫回傳下一個號。"""
    month = datetime.now().strftime("%Y%m")
    try:
        from helpers import recycle_bin as _rb
        used = set(_rb.reserved_ids(conn, "") or ())
    except Exception:                                      # noqa: BLE001 — 暫存區讀不到不可讓匯入失敗（與 next_entity_code 一樣）
        used = set()
    prefix = "C-%s-" % month
    mx = 0
    for r in conn.execute("SELECT code FROM customers WHERE code LIKE ?", (prefix + "%",)).fetchall():
        c = r["code"] or ""
        used.add(c)
        if len(c) == len(prefix) + 3 and c[len(prefix):].isdigit():
            mx = max(mx, int(c[len(prefix):]))
    state = {"seq": mx}

    def nxt():
        state["seq"] += 1
        while "%s%03d" % (prefix, state["seq"]) in used:
            state["seq"] += 1
        code = "%s%03d" % (prefix, state["seq"])
        used.add(code)
        return code
    return nxt


def _audit_rows(token: str, entries: list) -> None:
    """匯入的逐列稽核：同一條連線、一次 commit（逐列呼叫 `_audit` ＝每列各開連線各 commit，1500 列要十幾秒）。每列內容與 `_audit` 相同。
    entries＝[(action, target_type, target_id, target_label, detail)]；永不丟例外。呼叫前資料交易必須已 commit。"""
    if not entries:
        return
    try:
        conn = get_db()
        try:
            user_id, username, display_name = None, "", ""
            row = conn.execute("SELECT u.id, u.username, u.display_name FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token=?", (token,)).fetchone() if token else None
            if row:
                user_id, username, display_name = row["id"], row["username"], row["display_name"]
            now = datetime.now().isoformat()
            for action, ttype, tid, tlabel, detail in entries:
                d = _derive_fields(action, ttype, tid, tlabel, detail)
                payload = json.dumps(detail or {}, ensure_ascii=False)
                if len(payload) > _DETAIL_MAX:
                    payload = json.dumps({"_truncated": True, "originalLength": len(payload), "preview": payload[:_DETAIL_MAX - 200]}, ensure_ascii=False)
                conn.execute("INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail,module,case_no,ref_no,result,reason_code,status_code) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'ok','',0)",
                             (now, user_id, username, display_name, action, ttype, tid, tlabel, payload, d["module"], d["case_no"], d["ref_no"]))
            conn.commit()
        finally:
            conn.close()
    except Exception:                                      # noqa: BLE001
        logger.warning("customer import audit rows failed", exc_info=True)


def _plan_hash(plan: list) -> str:
    """預覽與寫入之間「這份計畫」有沒有變：檔案內容（不含勾選）＋每列動作＋對到的客戶 id 與其 updated_at。"""
    sig = [{"in": {k: v for k, v in p["in"].items() if k != "confirm"}, "a": p["action"],
            "t": (p.get("target") or {}).get("id"), "u": (p.get("target") or {}).get("updated_at")} for p in plan]
    return hashlib.sha256(json.dumps(sig, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def _plan_summary(plan: list) -> dict:
    def applied(p):
        return p["action"] == "update" or (p["action"] == "confirm" and p["in"]["confirm"])
    count = lambda a: sum(1 for p in plan if p["action"] == a)               # noqa: E731
    changes = [{"row": p["row"], "name": p["name"], "action": p["action"], "fields": p["diff"]}
               for p in plan if p["action"] in ("update", "confirm") and p.get("diff")]
    return {"created": count("create"), "updated": sum(1 for p in plan if applied(p)), "failed": count("error"),
            "duplicates": [{"row": p["row"], "name": p["name"], "reason": p["reason"]} for p in plan if p["action"] == "duplicate"],
            "confirms": [{"row": p["row"], "name": p["name"], "oldName": p["target"]["name"], "taxId": p["in"]["tax"], "reason": p["reason"],
                          "applied": p["in"]["confirm"]} for p in plan if p["action"] == "confirm"],
            "errors": ["第 %s 行：%s" % (p["row"], p["reason"]) for p in plan if p["action"] == "error"],
            "changes": changes[:_IMPORT_MAX_DIFF_ROWS], "changesTruncated": len(changes) > _IMPORT_MAX_DIFF_ROWS,
            "planHash": _plan_hash(plan)}


@router.post("/api/customers/import-rows")
def import_customer_rows(body: dict, authorization: str = Header(None)):
    """Excel 匯入（已在瀏覽器解析成列）。**只有 `dryRun` 明確是 false 才會寫入**，其他（沒帶、true、"false"、0…）一律只回預覽。
    正式寫入要帶預覽時拿到的 `planHash`；資料在預覽後有變 ⇒ 409。"""
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'case_manage', 'dev_crm', 'procurement'), "客戶管理")
    rows = body.get("rows")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "沒有可匯入的資料列")
    if len(rows) > _IMPORT_MAX_ROWS:
        raise HTTPException(400, "一次最多匯入 %d 列，請分檔" % _IMPORT_MAX_ROWS)
    real = body.get("dryRun") is False
    conn = get_db()
    written = []
    try:
        if not real:
            return _plan_summary(_plan_customer_import(conn, rows))
        if not isinstance(body.get("planHash"), str) or not body["planHash"]:
            raise HTTPException(400, "請先預覽再確認匯入")
        now = datetime.now().isoformat()
        with write_txn(conn):                    # 整批一個交易：中途失敗不留半批
            plan = _plan_customer_import(conn, rows)      # 拿鎖之後重算：預覽到確認之間資料可能已被別人改
            if _plan_hash(plan) != body["planHash"]:
                raise HTTPException(409, {"code": "plan_changed", "message": "資料在您預覽之後有變動，請重新預覽再確認"})
            next_code = _code_allocator(conn)
            for p in plan:
                r = p["in"]
                if p["action"] == "create":
                    data = dict(r["data"])
                    data.setdefault("type", "一般")
                    data["active"] = True
                    cur = conn.execute("INSERT INTO customers (name, tax_id, phone, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                                       (r["name"], r["tax"], r["phone"], json.dumps(data, ensure_ascii=False), now, now))
                    conn.execute("UPDATE customers SET code=? WHERE id=?", (next_code(), cur.lastrowid))
                    written.append(("customer.create", cur.lastrowid, r["name"]))
                elif p["action"] == "update" or (p["action"] == "confirm" and r["confirm"]):
                    t = p["target"]
                    conn.execute("UPDATE customers SET name=?, tax_id=?, phone=?, data_json=?, updated_at=? WHERE id=?",
                                 (t["name"], t["tax_id"], r["phone"] or t["phone"],
                                  json.dumps(_merge_customer_data(p["old"], r["data"]), ensure_ascii=False), now, t["id"]))
                    written.append(("customer.update", t["id"], t["name"]))
            conn.commit()
    except HTTPException:
        raise
    except Exception:
        tid = trace_id()
        logger.exception("customer import failed trace=%s", tid)
        raise HTTPException(500, {"code": "import_failed", "message": f"匯入失敗，沒有任何資料被寫入（代碼 {tid}）"})
    finally:
        conn.close()
    result = _plan_summary(plan)
    try:                                         # 資料已經寫入：後續備份／稽核／通知失敗只記錄，不能讓畫面誤以為失敗而重匯
        if written:
            spawn_bg_thread(_backup_customers)                       # 整批只備份一次（舊：每列一次）
            tok = _tok(authorization)
            _audit(tok, 'customer.import', 'customer', '', "Excel 匯入客戶", {         # 批次一列（總數）；逐客戶的稽核另列
                "created": result["created"], "updated": result["updated"], "failed": result["failed"], "skipped_duplicates": len(result["duplicates"])})
            _audit_rows(tok, [(action, 'customer', str(cid), name, {"via": "excel_import"}) for action, cid, name in written])
            notify_module_activity("客戶管理", "匯入", user.get("display_name") or user["username"],
                                   "Excel 匯入：新增 %d 筆、更新 %d 筆" % (result["created"], result["updated"]), "customers.html")
    except Exception:                            # noqa: BLE001
        logger.exception("customer import post-commit steps failed (data already written)")
    return result


@router.put("/api/customers/{cid}")
def update_customer(cid: int, body: CustomerIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('customer', 'case_manage', 'dev_crm', 'procurement'), "客戶管理")
    now = datetime.now().isoformat()
    conn = get_db()
    cur_row = conn.execute("SELECT data_json FROM customers WHERE id=?", (cid,)).fetchone()
    if not cur_row:
        conn.close()
        raise HTTPException(404, "客戶不存在")
    new_data = dict(body.data or {})
    # 「伺服器端持有」的鍵（拜訪紀錄、別名、啟用狀態）：請求的 data 沒有帶這個鍵 ⇒ 沿用現值，不是清掉。
    # 一般編輯表單永遠整包送回這些鍵，行為不變；只送部分欄位的呼叫路徑（舊的逐列匯入等）才不會洗掉它們。
    try:
        old_data = json.loads(cur_row["data_json"] or "{}")
        old_data = old_data if isinstance(old_data, dict) else {}
    except Exception:                                                  # noqa: BLE001
        old_data = {}
    for k in ("visits", "alias", "active"):
        if k not in new_data and k in old_data:
            new_data[k] = old_data[k]
    conn.execute(
        "UPDATE customers SET name=?, tax_id=?, phone=?, data_json=?, updated_at=? WHERE id=?",
        (body.name.strip(), body.tax_id or '', body.phone or '',
         json.dumps(new_data, ensure_ascii=False), now, cid)
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
