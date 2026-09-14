"""商用／工業網路交換器選型導覽 CRUD — 行業情境／產品分類／適配矩陣／產品連結。

檢視：任何登入者皆可讀取。
編輯：superadmin 或具 switch_guide_edit 模組者。
"""
import json
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, Header

from db import get_db
from helpers import _require_user, _tok, _audit, notify_module_activity, require_any_module

router = APIRouter()

_EDIT_MODULE = "switch_guide_edit"


@router.get("/api/switch-guide/scenarios")
def list_scenarios(authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('switch_guide', 'switch_guide_edit'), "交換器選型導覽")
    conn = get_db()
    rows = conn.execute("SELECT * FROM switch_scenarios ORDER BY sort_order, code").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/switch-guide/scenarios", status_code=201)
def create_scenario(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    code = (body.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "情境代碼不得為空")
    conn = get_db()
    if conn.execute("SELECT 1 FROM switch_scenarios WHERE code=?", (code,)).fetchone():
        conn.close()
        raise HTTPException(409, "情境代碼已存在")
    now = datetime.now().isoformat()
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM switch_scenarios").fetchone()["m"]
    conn.execute(
        "INSERT INTO switch_scenarios (code, name, description, sort_order, updated_at) VALUES (?,?,?,?,?)",
        (code, body.get("name", ""), body.get("description", ""), max_sort + 1, now),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'switch_guide.scenario.create', 'switch_scenario', code, body.get('name', ''))
    notify_module_activity("交換器選型導覽", "建立情境", actor.get("display_name") or actor["username"],
                            body.get('name', code), "switch-guide.html")
    return {"code": code, "ok": True}


@router.put("/api/switch-guide/scenarios/{code}")
def update_scenario(code: str, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    if not conn.execute("SELECT 1 FROM switch_scenarios WHERE code=?", (code,)).fetchone():
        conn.close()
        raise HTTPException(404, "情境不存在")
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE switch_scenarios SET name=?, description=?, updated_at=? WHERE code=?",
        (body.get("name", ""), body.get("description", ""), now, code),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'switch_guide.scenario.update', 'switch_scenario', code, body.get('name', ''))
    return {"ok": True}


@router.delete("/api/switch-guide/scenarios/{code}")
def delete_scenario(code: str, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT name FROM switch_scenarios WHERE code=?", (code,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "情境不存在")
    conn.execute("DELETE FROM switch_scenarios WHERE code=?", (code,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'switch_guide.scenario.delete', 'switch_scenario', code, row['name'])
    notify_module_activity("交換器選型導覽", "刪除情境", actor.get("display_name") or actor["username"],
                            row['name'], "switch-guide.html")
    return {"ok": True}


@router.get("/api/switch-guide/categories")
def list_categories(authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('switch_guide', 'switch_guide_edit'), "交換器選型導覽")
    conn = get_db()
    rows = conn.execute("SELECT * FROM switch_categories ORDER BY sort_order, code").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/switch-guide/categories", status_code=201)
def create_category(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    code = (body.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "分類代碼不得為空")
    conn = get_db()
    if conn.execute("SELECT 1 FROM switch_categories WHERE code=?", (code,)).fetchone():
        conn.close()
        raise HTTPException(409, "分類代碼已存在")
    now = datetime.now().isoformat()
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM switch_categories").fetchone()["m"]
    conn.execute("""
        INSERT INTO switch_categories (code, name, key_specs, tags, price_range, dependency_note, watch_note, sort_order, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        code, body.get("name", ""), body.get("keySpecs", ""), body.get("tags", ""),
        body.get("priceRange", ""), body.get("dependencyNote", ""), body.get("watchNote", ""),
        max_sort + 1, now,
    ))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'switch_guide.category.create', 'switch_category', code, body.get('name', ''))
    notify_module_activity("交換器選型導覽", "建立分類", actor.get("display_name") or actor["username"],
                            body.get('name', code), "switch-guide.html")
    return {"code": code, "ok": True}


@router.put("/api/switch-guide/categories/{code}")
def update_category(code: str, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    if not conn.execute("SELECT 1 FROM switch_categories WHERE code=?", (code,)).fetchone():
        conn.close()
        raise HTTPException(404, "分類不存在")
    now = datetime.now().isoformat()
    conn.execute("""
        UPDATE switch_categories
           SET name=?, key_specs=?, tags=?, price_range=?, dependency_note=?, watch_note=?, updated_at=?
         WHERE code=?
    """, (
        body.get("name", ""), body.get("keySpecs", ""), body.get("tags", ""),
        body.get("priceRange", ""), body.get("dependencyNote", ""), body.get("watchNote", ""),
        now, code,
    ))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'switch_guide.category.update', 'switch_category', code, body.get('name', ''))
    return {"ok": True}


@router.delete("/api/switch-guide/categories/{code}")
def delete_category(code: str, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT name FROM switch_categories WHERE code=?", (code,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "分類不存在")
    conn.execute("DELETE FROM switch_categories WHERE code=?", (code,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'switch_guide.category.delete', 'switch_category', code, row['name'])
    notify_module_activity("交換器選型導覽", "刪除分類", actor.get("display_name") or actor["username"],
                            row['name'], "switch-guide.html")
    return {"ok": True}


@router.get("/api/switch-guide/fit")
def list_fit(authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('switch_guide', 'switch_guide_edit'), "交換器選型導覽")
    conn = get_db()
    rows = conn.execute("SELECT * FROM switch_fit ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/switch-guide/fit", status_code=201)
def create_fit(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    scenario_code = (body.get("scenarioCode") or "").strip()
    category_code = (body.get("categoryCode") or "").strip()
    if not scenario_code or not category_code:
        raise HTTPException(400, "情境與分類皆不得為空")
    conn = get_db()
    if not conn.execute("SELECT 1 FROM switch_scenarios WHERE code=?", (scenario_code,)).fetchone():
        conn.close()
        raise HTTPException(400, "情境代碼不存在")
    if not conn.execute("SELECT 1 FROM switch_categories WHERE code=?", (category_code,)).fetchone():
        conn.close()
        raise HTTPException(400, "分類代碼不存在")
    now = datetime.now().isoformat()
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM switch_fit").fetchone()["m"]
    cur = conn.execute("""
        INSERT INTO switch_fit (scenario_code, category_code, fit_level, fit_note, sort_order, updated_at)
        VALUES (?,?,?,?,?,?)
    """, (
        scenario_code, category_code, body.get("fitLevel", "可用"), body.get("fitNote", ""),
        max_sort + 1, now,
    ))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'switch_guide.fit.create', 'switch_fit', str(new_id), f"{scenario_code} x {category_code}")
    notify_module_activity("交換器選型導覽", "建立適配矩陣", actor.get("display_name") or actor["username"],
                            f"{scenario_code} x {category_code}", "switch-guide.html")
    return {"id": new_id, "ok": True}


@router.put("/api/switch-guide/fit/{fit_id}")
def update_fit(fit_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT scenario_code, category_code FROM switch_fit WHERE id=?", (fit_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "適配資料不存在")
    now = datetime.now().isoformat()
    conn.execute("""
        UPDATE switch_fit SET fit_level=?, fit_note=?, updated_at=? WHERE id=?
    """, (body.get("fitLevel", "可用"), body.get("fitNote", ""), now, fit_id))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'switch_guide.fit.update', 'switch_fit', str(fit_id), f"{row['scenario_code']} x {row['category_code']}")
    return {"ok": True}


@router.delete("/api/switch-guide/fit/{fit_id}")
def delete_fit(fit_id: int, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT scenario_code, category_code FROM switch_fit WHERE id=?", (fit_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "適配資料不存在")
    conn.execute("DELETE FROM switch_fit WHERE id=?", (fit_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'switch_guide.fit.delete', 'switch_fit', str(fit_id), f"{row['scenario_code']} x {row['category_code']}")
    notify_module_activity("交換器選型導覽", "刪除適配矩陣", actor.get("display_name") or actor["username"],
                            f"{row['scenario_code']} x {row['category_code']}", "switch-guide.html")
    return {"ok": True}


@router.get("/api/switch-guide/products")
def list_products(authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('switch_guide', 'switch_guide_edit'), "交換器選型導覽")
    conn = get_db()
    rows = conn.execute("SELECT * FROM switch_products ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/switch-guide/products", status_code=201)
def create_product(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    category_code = (body.get("categoryCode") or "").strip()
    if not category_code:
        raise HTTPException(400, "所屬分類不得為空")
    conn = get_db()
    if not conn.execute("SELECT 1 FROM switch_categories WHERE code=?", (category_code,)).fetchone():
        conn.close()
        raise HTTPException(400, "所屬分類不存在")
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM switch_products").fetchone()["m"]
    cur = conn.execute(
        "INSERT INTO switch_products (category_code, brand, model, url, label, price_note, specs_json, sort_order) VALUES (?,?,?,?,?,?,?,?)",
        (category_code, body.get("brand", ""), body.get("model", ""), body.get("url", ""),
         body.get("label", ""), body.get("priceNote", ""), json.dumps(body.get("specs", []), ensure_ascii=False), max_sort + 1),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'switch_guide.product.create', 'switch_product', str(new_id), f"{body.get('brand','')} {body.get('model','')}".strip())
    notify_module_activity("交換器選型導覽", "建立產品連結", actor.get("display_name") or actor["username"],
                            f"{body.get('brand','')} {body.get('model','')}".strip(), "switch-guide.html")
    return {"id": new_id, "ok": True}


@router.put("/api/switch-guide/products/{prod_id}")
def update_product(prod_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    if not conn.execute("SELECT 1 FROM switch_products WHERE id=?", (prod_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "產品不存在")
    conn.execute(
        "UPDATE switch_products SET brand=?, model=?, url=?, label=?, price_note=?, specs_json=? WHERE id=?",
        (body.get("brand", ""), body.get("model", ""), body.get("url", ""),
         body.get("label", ""), body.get("priceNote", ""), json.dumps(body.get("specs", []), ensure_ascii=False), prod_id),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'switch_guide.product.update', 'switch_product', str(prod_id), f"{body.get('brand','')} {body.get('model','')}".strip())
    return {"ok": True}


@router.delete("/api/switch-guide/products/{prod_id}")
def delete_product(prod_id: int, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT brand, model FROM switch_products WHERE id=?", (prod_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "產品不存在")
    conn.execute("DELETE FROM switch_products WHERE id=?", (prod_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'switch_guide.product.delete', 'switch_product', str(prod_id), f"{row['brand']} {row['model']}".strip())
    notify_module_activity("交換器選型導覽", "刪除產品連結", actor.get("display_name") or actor["username"],
                            f"{row['brand']} {row['model']}".strip(), "switch-guide.html")
    return {"ok": True}
