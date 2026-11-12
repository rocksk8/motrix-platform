"""Parts master data CRUD."""
import re
import sqlite3
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Body

from core.txn import write_txn
from db import get_db
from helpers import _require_user, _tok, _audit, notify_module_activity, require_any_module
from helpers.procurement import clean_lead_time

router = APIRouter()

# 分類代碼表在 L1（helpers/part_catalog.py；DEPENDENCY-MAP §3 #17）
from helpers.part_catalog import PART_CATEGORIES, PART_CATEGORY_PREFIX, categories as _part_categories, prefix_for as _prefix_for  # noqa: E402


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
def list_part_categories(authorization: str = Header(None)):
    # 2026-09-13：這兩支讀取端點原本連 `authorization` 參數都沒有（僅靠 main.py 的
    # auth_middleware 擋未登入），所以也就沒有任何模組檢查。補上參數才有 user 可判斷。
    require_any_module(_require_user(authorization), ('procurement', 'case_manage', 'inventory'),
                       "供應商／料號／採購")
    return {"items": _part_categories()}      # census #4：選項清單關著／沒發布 ⇒ 與 PART_CATEGORIES 逐項相同


@router.get("/api/parts")
def list_parts(q: Optional[str] = None, category: Optional[str] = None,
               authorization: str = Header(None)):
    require_any_module(_require_user(authorization), ('procurement', 'case_manage', 'inventory'),
                       "供應商／料號／採購")
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
    require_any_module(user, ('procurement', 'case_manage', 'inventory'), "供應商／料號／採購")
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        category = (body.get("category") or "").strip()
        part_no = (body.get("partNo") or body.get("part_no") or "").strip()
        if not part_no:
            prefix = _prefix_for(category)
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
                INSERT INTO parts (part_no, name, brand, unit, cost, list_price, category, note, safety_stock, lead_time_days, active, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)
            """, (
                part_no, name,
                body.get("brand",""),
                body.get("unit","台"),
                body.get("cost",0),
                body.get("listPrice") or body.get("list_price") or 0,
                category,
                body.get("note",""),
                body.get("safetyStock") or body.get("safety_stock") or 0,
                clean_lead_time(body.get("leadTimeDays", body.get("lead_time_days"))),
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


# ── Excel 匯入（票 fix/excel-import-dataloss）────────────────────────────────
# 舊行為：逐列 PUT，空白儲存格被預設值覆蓋（成本 0、單位「台」）、只給廠牌會洗掉既有型號、亂碼成本變 0、安全庫存／前置天數無法匯入。
# 新規則：空白儲存格＝不更新（新增時才用預設）；廠牌與型號各自獨立（brand 欄的格式仍是「廠牌 / 型號」）；數字不合法＝這一列報錯；
#         先 dryRun 回計畫讓畫面確認，確認後整批一個交易。
_IMPORT_MAX_ROWS = 5000


def _imp_text(v):
    return "" if v is None else str(v).strip()


def _imp_number(v, label, integer=False):
    """⇒ (數字, None)；空白 ⇒ (None, None)；不合法／負數 ⇒ (None, 白話原因)。去掉 NT$、$、逗號、空白。"""
    s = re.sub(r"(?i)nt\$|\$|,|，|\s", "", _imp_text(v))
    if not s:
        return None, None
    try:
        n = float(s)
    except ValueError:
        return None, "「%s」不是數字（%s）" % (label, _imp_text(v))
    if n != n or n in (float("inf"), float("-inf")) or n < 0:
        return None, "「%s」不可為負數或無效數字（%s）" % (label, _imp_text(v))
    if integer:
        if n != int(n):
            return None, "「%s」必須是整數（%s）" % (label, _imp_text(v))
        return int(n), None
    return n, None


def _split_brand(brand):
    bn, *rest = (brand or "").split("/")
    return (bn or "").strip(), "/".join(rest).strip()


def _plan_part_import(conn, rows: list) -> list:
    """每列 ⇒ {row, partNo, name, action: create|update|error, fields:{欄位: 值}（只含檔案有給的欄位）, ...}。唯讀。"""
    existing = {r["part_no"]: dict(r) for r in conn.execute("SELECT * FROM parts").fetchall()}
    seen, plan = set(), []
    for raw in rows:
        raw = raw if isinstance(raw, dict) else {}
        item = {"row": raw.get("row"), "partNo": _imp_text(raw.get("partNo")), "name": _imp_text(raw.get("name"))}
        errs, f = [], {}
        for key, label, integer in (("cost", "成本", False), ("listPrice", "定價", False), ("safetyStock", "安全庫存", True), ("leadTimeDays", "前置天數", True)):
            n, e = _imp_number(raw.get(key), label, integer)
            if e:
                errs.append(e)
            elif n is not None:
                f[key] = n
        for key in ("unit", "category", "note"):
            if _imp_text(raw.get(key)):
                f[key] = _imp_text(raw.get(key))
        item.update(brandName=_imp_text(raw.get("brand")), brandModel=_imp_text(raw.get("model")))
        if item["name"]:
            f["name"] = item["name"]
        item["fields"] = f
        old = existing.get(item["partNo"]) if item["partNo"] else None
        if errs:
            item.update(action="error", reason="；".join(errs))
        elif item["partNo"] and item["partNo"] in seen:
            item.update(action="error", reason="同一個檔案裡料號 %s 出現多次，這一列未匯入" % item["partNo"])
        elif old:
            item.update(action="update", target=old)
        elif not item["name"]:
            item.update(action="error", reason="品名不可空白" if item["partNo"] else "品名不可空白（新增料號必填）")
        elif not item["partNo"] and not _prefix_for(f.get("category", "")):
            item.update(action="error", reason="請填料號，或填有對應前綴的類別以自動產生")
        else:
            item.update(action="create")
        if item["partNo"]:
            seen.add(item["partNo"])
        plan.append(item)
    return plan


def _part_plan_summary(plan: list) -> dict:
    count = lambda a: sum(1 for p in plan if p["action"] == a)               # noqa: E731
    return {"created": count("create"), "updated": count("update"), "failed": count("error"), "duplicates": [],
            "errors": ["第 %s 行：%s" % (p["row"], p["reason"]) for p in plan if p["action"] == "error"]}


@router.post("/api/parts/import-rows")
def import_part_rows(body: dict = Body(...), authorization: str = Header(None)):
    """Excel 匯入（已在瀏覽器解析成列）。`dryRun:true` ⇒ 只回計畫（新增／更新幾筆），不寫入。"""
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'inventory'), "供應商／料號／採購")
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
            return _part_plan_summary(_plan_part_import(conn, rows))
        now = datetime.now().isoformat()
        with write_txn(conn):                    # 整批一個交易；拿鎖之後重算計畫
            plan = _plan_part_import(conn, rows)
            for p in plan:
                f = p["fields"]
                if p["action"] == "create":
                    category = f.get("category", "")
                    part_no = p["partNo"] or _next_part_no(conn, _prefix_for(category))    # 交易內依序取號：同一批不會重號
                    brand = " / ".join(x for x in (p["brandName"], p["brandModel"]) if x)
                    lead = clean_lead_time(f.get("leadTimeDays"))        # 空白＝未知（NULL），不是 0
                    conn.execute("""
                        INSERT INTO parts (part_no, name, brand, unit, cost, list_price, category, note, safety_stock, lead_time_days, active, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)
                    """, (part_no, f["name"], brand, f.get("unit", "台"), f.get("cost", 0), f.get("listPrice", 0), category,
                          f.get("note", ""), f.get("safetyStock", 0), lead, now, now))
                    written.append(("part.create", part_no, f["name"]))
                elif p["action"] == "update":
                    t = p["target"]
                    sets, params = [], []
                    for key, col in (("name", "name"), ("unit", "unit"), ("cost", "cost"), ("listPrice", "list_price"), ("category", "category"),
                                     ("note", "note"), ("safetyStock", "safety_stock"), ("leadTimeDays", "lead_time_days")):
                        if key in f:
                            sets.append(col + "=?")
                            params.append(f[key])
                    if p["brandName"] or p["brandModel"]:               # 廠牌、型號各自獨立：沒給的那一半沿用既有值
                        bn, model = _split_brand(t["brand"])
                        brand = " / ".join(x for x in (p["brandName"] or bn, p["brandModel"] or model) if x)
                        sets.append("brand=?")
                        params.append(brand)
                    if sets:
                        sets.append("updated_at=?")
                        conn.execute("UPDATE parts SET " + ", ".join(sets) + " WHERE id=?", params + [now, t["id"]])
                    written.append(("part.update", t["part_no"], "%s %s" % (t["part_no"], f.get("name", t["name"]))))
            conn.commit()
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.getLogger(__name__).exception("part import failed")
        raise HTTPException(409, "匯入失敗，沒有任何資料被寫入")
    finally:
        conn.close()
    result = _part_plan_summary(plan)
    if written:
        tok = _tok(authorization)
        for action, part_no, label in written:
            _audit(tok, action, 'part', part_no, label, {"via": "excel_import"})
        notify_module_activity("供應商／料號／採購", "匯入", user.get("display_name") or user["username"],
                               "Excel 匯入料號：新增 %d 筆、更新 %d 筆" % (result["created"], result["updated"]), "parts.html")
    return result


@router.put("/api/parts/{part_id}")
def update_part(part_id: int, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('procurement', 'case_manage', 'inventory'), "供應商／料號／採購")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT part_no, name, safety_stock, lead_time_days FROM parts WHERE id=?",
            (part_id,)).fetchone()
        if not row:
            raise HTTPException(404, "料號不存在")
        now = datetime.now().isoformat()
        new_name = body.get("name", "")
        # safety_stock 只有請求明確帶了 safetyStock/safety_stock 鍵才更新，否則沿用
        # 現值——沒有這個保護的話，brand 批次改名／Excel 匯入等不知道這個新欄位的
        # 既有呼叫路徑會因為沒帶這個鍵而把每個料號的安全庫存悄悄清零
        if "safetyStock" in body or "safety_stock" in body:
            safety_stock = body.get("safetyStock", body.get("safety_stock")) or 0
        else:
            safety_stock = row["safety_stock"]
        # 前置時間照 safety_stock 同一個慣用法：沒帶這個鍵就沿用現值。
        # 不知道有這個欄位的既有呼叫路徑（批次改名／Excel 匯入／舊前端）
        # 不應該因為存了一次料號，就把前置時間悄悄清成 NULL。
        # ⚠️ 這裡分的是「有沒有送這個鍵」，不是「送的值是不是空的」——
        # 明確送 null 是「改成未知」，那是使用者的意思，要照做。
        if "leadTimeDays" in body or "lead_time_days" in body:
            lead_time_days = clean_lead_time(
                body.get("leadTimeDays", body.get("lead_time_days")))
        else:
            lead_time_days = row["lead_time_days"]
        conn.execute("""
            UPDATE parts SET name=?, brand=?, unit=?, cost=?, list_price=?, category=?, note=?, safety_stock=?, lead_time_days=?, updated_at=?
            WHERE id=?
        """, (
            new_name,
            body.get("brand",""),
            body.get("unit","台"),
            body.get("cost",0),
            body.get("listPrice") or body.get("list_price") or 0,
            body.get("category",""),
            body.get("note",""),
            safety_stock,
            lead_time_days,
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
    require_any_module(user, ('procurement', 'case_manage', 'inventory'), "供應商／料號／採購")
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
