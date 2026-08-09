"""監控系統選型導覽 CRUD — 場域情境／相機分類／適配矩陣／產品連結。

檢視：任何登入者皆可讀取。
編輯：superadmin 或具 monitor_guide_edit 模組者。
"""
import json
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, Header

from db import get_db
from helpers import _require_user, _tok, _audit, notify_module_activity

router = APIRouter()

_EDIT_MODULE = "monitor_guide_edit"


@router.get("/api/monitor-guide/scenarios")
def list_scenarios(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("SELECT * FROM monitor_scenarios ORDER BY sort_order, code").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/monitor-guide/scenarios", status_code=201)
def create_scenario(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    code = (body.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "情境代碼不得為空")
    conn = get_db()
    if conn.execute("SELECT 1 FROM monitor_scenarios WHERE code=?", (code,)).fetchone():
        conn.close()
        raise HTTPException(409, "情境代碼已存在")
    now = datetime.now().isoformat()
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM monitor_scenarios").fetchone()["m"]
    conn.execute(
        "INSERT INTO monitor_scenarios (code, name, description, sort_order, updated_at) VALUES (?,?,?,?,?)",
        (code, body.get("name", ""), body.get("description", ""), max_sort + 1, now),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'monitor_guide.scenario.create', 'monitor_scenario', code, body.get('name', ''))
    notify_module_activity("監控系統選型導覽", "建立情境", actor.get("display_name") or actor["username"],
                            body.get('name', code), "monitor-guide.html")
    return {"code": code, "ok": True}


@router.put("/api/monitor-guide/scenarios/{code}")
def update_scenario(code: str, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    if not conn.execute("SELECT 1 FROM monitor_scenarios WHERE code=?", (code,)).fetchone():
        conn.close()
        raise HTTPException(404, "情境不存在")
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE monitor_scenarios SET name=?, description=?, updated_at=? WHERE code=?",
        (body.get("name", ""), body.get("description", ""), now, code),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'monitor_guide.scenario.update', 'monitor_scenario', code, body.get('name', ''))
    return {"ok": True}


@router.delete("/api/monitor-guide/scenarios/{code}")
def delete_scenario(code: str, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT name FROM monitor_scenarios WHERE code=?", (code,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "情境不存在")
    conn.execute("DELETE FROM monitor_scenarios WHERE code=?", (code,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'monitor_guide.scenario.delete', 'monitor_scenario', code, row['name'])
    notify_module_activity("監控系統選型導覽", "刪除情境", actor.get("display_name") or actor["username"],
                            row['name'], "monitor-guide.html")
    return {"ok": True}


@router.get("/api/monitor-guide/categories")
def list_categories(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("SELECT * FROM monitor_categories ORDER BY sort_order, code").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/monitor-guide/categories", status_code=201)
def create_category(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    code = (body.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "分類代碼不得為空")
    conn = get_db()
    if conn.execute("SELECT 1 FROM monitor_categories WHERE code=?", (code,)).fetchone():
        conn.close()
        raise HTTPException(409, "分類代碼已存在")
    now = datetime.now().isoformat()
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM monitor_categories").fetchone()["m"]
    conn.execute("""
        INSERT INTO monitor_categories (code, name, key_specs, tags, price_range, dependency_note, watch_note, sort_order, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        code, body.get("name", ""), body.get("keySpecs", ""), body.get("tags", ""),
        body.get("priceRange", ""), body.get("dependencyNote", ""), body.get("watchNote", ""),
        max_sort + 1, now,
    ))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'monitor_guide.category.create', 'monitor_category', code, body.get('name', ''))
    notify_module_activity("監控系統選型導覽", "建立分類", actor.get("display_name") or actor["username"],
                            body.get('name', code), "monitor-guide.html")
    return {"code": code, "ok": True}


@router.put("/api/monitor-guide/categories/{code}")
def update_category(code: str, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    if not conn.execute("SELECT 1 FROM monitor_categories WHERE code=?", (code,)).fetchone():
        conn.close()
        raise HTTPException(404, "分類不存在")
    now = datetime.now().isoformat()
    conn.execute("""
        UPDATE monitor_categories
           SET name=?, key_specs=?, tags=?, price_range=?, dependency_note=?, watch_note=?, updated_at=?
         WHERE code=?
    """, (
        body.get("name", ""), body.get("keySpecs", ""), body.get("tags", ""),
        body.get("priceRange", ""), body.get("dependencyNote", ""), body.get("watchNote", ""),
        now, code,
    ))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'monitor_guide.category.update', 'monitor_category', code, body.get('name', ''))
    return {"ok": True}


@router.delete("/api/monitor-guide/categories/{code}")
def delete_category(code: str, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT name FROM monitor_categories WHERE code=?", (code,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "分類不存在")
    conn.execute("DELETE FROM monitor_categories WHERE code=?", (code,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'monitor_guide.category.delete', 'monitor_category', code, row['name'])
    notify_module_activity("監控系統選型導覽", "刪除分類", actor.get("display_name") or actor["username"],
                            row['name'], "monitor-guide.html")
    return {"ok": True}


@router.get("/api/monitor-guide/fit")
def list_fit(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("SELECT * FROM monitor_fit ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/monitor-guide/fit", status_code=201)
def create_fit(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    scenario_code = (body.get("scenarioCode") or "").strip()
    category_code = (body.get("categoryCode") or "").strip()
    if not scenario_code or not category_code:
        raise HTTPException(400, "情境與分類皆不得為空")
    conn = get_db()
    if not conn.execute("SELECT 1 FROM monitor_scenarios WHERE code=?", (scenario_code,)).fetchone():
        conn.close()
        raise HTTPException(400, "情境代碼不存在")
    if not conn.execute("SELECT 1 FROM monitor_categories WHERE code=?", (category_code,)).fetchone():
        conn.close()
        raise HTTPException(400, "分類代碼不存在")
    now = datetime.now().isoformat()
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM monitor_fit").fetchone()["m"]
    cur = conn.execute("""
        INSERT INTO monitor_fit (scenario_code, category_code, fit_level, fit_note, sort_order, updated_at)
        VALUES (?,?,?,?,?,?)
    """, (
        scenario_code, category_code, body.get("fitLevel", "可用"), body.get("fitNote", ""),
        max_sort + 1, now,
    ))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'monitor_guide.fit.create', 'monitor_fit', str(new_id), f"{scenario_code} x {category_code}")
    notify_module_activity("監控系統選型導覽", "建立適配矩陣", actor.get("display_name") or actor["username"],
                            f"{scenario_code} x {category_code}", "monitor-guide.html")
    return {"id": new_id, "ok": True}


@router.put("/api/monitor-guide/fit/{fit_id}")
def update_fit(fit_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT scenario_code, category_code FROM monitor_fit WHERE id=?", (fit_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "適配資料不存在")
    now = datetime.now().isoformat()
    conn.execute("""
        UPDATE monitor_fit SET fit_level=?, fit_note=?, updated_at=? WHERE id=?
    """, (body.get("fitLevel", "可用"), body.get("fitNote", ""), now, fit_id))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'monitor_guide.fit.update', 'monitor_fit', str(fit_id), f"{row['scenario_code']} x {row['category_code']}")
    return {"ok": True}


@router.delete("/api/monitor-guide/fit/{fit_id}")
def delete_fit(fit_id: int, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT scenario_code, category_code FROM monitor_fit WHERE id=?", (fit_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "適配資料不存在")
    conn.execute("DELETE FROM monitor_fit WHERE id=?", (fit_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'monitor_guide.fit.delete', 'monitor_fit', str(fit_id), f"{row['scenario_code']} x {row['category_code']}")
    notify_module_activity("監控系統選型導覽", "刪除適配矩陣", actor.get("display_name") or actor["username"],
                            f"{row['scenario_code']} x {row['category_code']}", "monitor-guide.html")
    return {"ok": True}


@router.get("/api/monitor-guide/products")
def list_products(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("SELECT * FROM monitor_products ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/monitor-guide/products", status_code=201)
def create_product(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    category_code = (body.get("categoryCode") or "").strip()
    if not category_code:
        raise HTTPException(400, "所屬分類不得為空")
    conn = get_db()
    if not conn.execute("SELECT 1 FROM monitor_categories WHERE code=?", (category_code,)).fetchone():
        conn.close()
        raise HTTPException(400, "所屬分類不存在")
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM monitor_products").fetchone()["m"]
    cur = conn.execute(
        "INSERT INTO monitor_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) VALUES (?,?,?,?,?,?,?,?)",
        (category_code, body.get("brand", ""), body.get("model", ""), body.get("url", ""),
         body.get("label", ""), body.get("priceNote", ""), json.dumps(body.get("specs", []), ensure_ascii=False), max_sort + 1),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'monitor_guide.product.create', 'monitor_product', str(new_id), f"{body.get('brand','')} {body.get('model','')}".strip())
    notify_module_activity("監控系統選型導覽", "建立產品連結", actor.get("display_name") or actor["username"],
                            f"{body.get('brand','')} {body.get('model','')}".strip(), "monitor-guide.html")
    return {"id": new_id, "ok": True}


@router.put("/api/monitor-guide/products/{prod_id}")
def update_product(prod_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    if not conn.execute("SELECT 1 FROM monitor_products WHERE id=?", (prod_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "產品不存在")
    conn.execute(
        "UPDATE monitor_products SET brand=?, model=?, url=?, label=?, price_note=?, specs_json=? WHERE id=?",
        (body.get("brand", ""), body.get("model", ""), body.get("url", ""),
         body.get("label", ""), body.get("priceNote", ""), json.dumps(body.get("specs", []), ensure_ascii=False), prod_id),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'monitor_guide.product.update', 'monitor_product', str(prod_id), f"{body.get('brand','')} {body.get('model','')}".strip())
    return {"ok": True}


@router.delete("/api/monitor-guide/products/{prod_id}")
def delete_product(prod_id: int, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT brand, model FROM monitor_products WHERE id=?", (prod_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "產品不存在")
    conn.execute("DELETE FROM monitor_products WHERE id=?", (prod_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'monitor_guide.product.delete', 'monitor_product', str(prod_id), f"{row['brand']} {row['model']}".strip())
    notify_module_activity("監控系統選型導覽", "刪除產品連結", actor.get("display_name") or actor["username"],
                            f"{row['brand']} {row['model']}".strip(), "monitor-guide.html")
    return {"ok": True}
