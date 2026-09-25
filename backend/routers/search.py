"""全域搜尋 — 跨客戶/供應商/報價單/業務開發案/料號，供 topbar 快速查找使用。
橫跨多個模組、不屬於任何單一業務 router，故獨立成檔（沿用 dashboard.py 收納跨模組端點的慣例）。
每個分類的可見性一律復用該模組既有 router 已驗證過的角色規則，不重新發明權限邏輯。"""
import json

from fastapi import APIRouter, Header, Query

from db import get_db
from helpers import _require_user, user_has_module
from helpers import row_access

router = APIRouter()

_LIMIT = 6


@router.get("/api/search")
def global_search(q: str = Query(..., min_length=1), authorization: str = Header(None)):
    u = _require_user(authorization)
    role = u["role"]
    mods = json.loads(u.get("modules") or "[]") if isinstance(u.get("modules"), str) else (u.get("modules") or [])
    is_admin = role in ("superadmin", "admin")
    like = f"%{q}%"
    conn = get_db()

    # 2026-09-13（模組權限稽核）：各分類的可見性「復用該模組既有規則」是這支檔案
    # 的原則（見檔頭）。`/api/customers`／`/api/parts` 這輪起有了模組檢查，這裡跟著
    # 補上，否則全域搜尋會變成繞過模組檢查的側門。比照既有的 suppliers 寫法——
    # 沒權限就回空清單，不是 403：搜尋框是多分類的，其中一類沒權限不該讓整個框壞掉。
    customers = []
    if is_admin or any(user_has_module(u, k) for k in
                       ("customer", "case_manage", "dev_crm", "procurement")):
        customers = conn.execute(
            "SELECT id, code, name FROM customers WHERE name LIKE ? OR code LIKE ? "
            "ORDER BY name LIMIT ?", (like, like, _LIMIT)
        ).fetchall()

    suppliers = []
    if is_admin:  # 比照 /api/suppliers：非 admin+ 不回傳資料
        suppliers = conn.execute(
            "SELECT id, code, name FROM suppliers WHERE name LIKE ? OR code LIKE ? "
            "ORDER BY name LIMIT ?", (like, like, _LIMIT)
        ).fetchall()

    qsql = (
        "SELECT quote_no, customer_name, project_name, status FROM quotations "
        "WHERE (quote_no LIKE ? OR customer_name LIKE ? OR project_name LIKE ?)"
    )
    qparams = [like, like, like]
    # 與案件列表同一套規則（row_access 的 case，scope=read）。2026-09-25 主持裁示（使用者裁示）：
    # 原本只比業務歸屬與舊資料顯示名稱，少了 assigned_user_ids 與 cashier ⇒ 兩者現在也搜得到。
    frag, fparams = row_access.filter_sql("case", u, scope="read")
    qsql += frag
    qparams.extend(fparams)
    qsql += " ORDER BY id DESC LIMIT ?"
    qparams.append(_LIMIT)
    quotations = conn.execute(qsql, qparams).fetchall()

    dev_cases = []
    if is_admin or "dev_crm" in mods:
        rows = conn.execute(
            "SELECT * FROM dev_cases WHERE case_name LIKE ? OR customer_name LIKE ? "
            "ORDER BY id DESC LIMIT ?", (like, like, _LIMIT * 3)
        ).fetchall()
        dev_cases = [r for r in rows if row_access.visible("dev_case", u, r)][:_LIMIT]

    parts = []
    if is_admin or any(user_has_module(u, k) for k in ("procurement", "case_manage")):
        parts = conn.execute(
            "SELECT part_no, name, brand FROM parts WHERE active=1 "
            "AND (part_no LIKE ? OR name LIKE ? OR brand LIKE ?) "
            "ORDER BY id DESC LIMIT ?", (like, like, like, _LIMIT)
        ).fetchall()

    conn.close()

    return {
        "customers":  [{"id": r["id"], "code": r["code"] or "", "name": r["name"] or ""} for r in customers],
        "suppliers":  [{"id": r["id"], "code": r["code"] or "", "name": r["name"] or ""} for r in suppliers],
        "quotations": [{"quoteNo": r["quote_no"], "customerName": r["customer_name"] or "",
                         "projectName": r["project_name"] or "", "status": r["status"] or ""} for r in quotations],
        "devCases":   [{"id": r["id"], "caseName": r["case_name"] or "",
                         "customerName": r["customer_name"] or "", "status": r["status"] or ""} for r in dev_cases],
        "parts":      [{"partNo": r["part_no"] or "", "name": r["name"] or "", "brand": r["brand"] or ""} for r in parts],
    }
