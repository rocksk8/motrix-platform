"""網路架構選型導覽 CRUD — 技術族系／世代規格／產品連結。

檢視：任何登入者皆可讀取。
編輯：superadmin 或具 netarch_guide_edit 模組者。
"""
import json
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, Header

from db import get_db
from helpers import _require_user, _tok, _audit, notify_module_activity

router = APIRouter()

_EDIT_MODULE = "netarch_guide_edit"


@router.get("/api/netarch-guide/families")
def list_families(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("SELECT * FROM netarch_families ORDER BY sort_order, code").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/netarch-guide/families", status_code=201)
def create_family(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    code = (body.get("code") or "").strip()
    if not code:
        raise HTTPException(400, "族系代碼不得為空")
    conn = get_db()
    if conn.execute("SELECT 1 FROM netarch_families WHERE code=?", (code,)).fetchone():
        conn.close()
        raise HTTPException(409, "族系代碼已存在")
    now = datetime.now().isoformat()
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM netarch_families").fetchone()["m"]
    conn.execute(
        "INSERT INTO netarch_families (code, name, description, sort_order, updated_at) VALUES (?,?,?,?,?)",
        (code, body.get("name", ""), body.get("description", ""), max_sort + 1, now),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'netarch_guide.family.create', 'netarch_family', code, body.get('name', ''))
    notify_module_activity("網路架構選型導覽", "建立技術族系", actor.get("display_name") or actor["username"],
                            body.get('name', code), "netarch-guide.html")
    return {"code": code, "ok": True}


@router.put("/api/netarch-guide/families/{code}")
def update_family(code: str, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    if not conn.execute("SELECT 1 FROM netarch_families WHERE code=?", (code,)).fetchone():
        conn.close()
        raise HTTPException(404, "族系不存在")
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE netarch_families SET name=?, description=?, updated_at=? WHERE code=?",
        (body.get("name", ""), body.get("description", ""), now, code),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'netarch_guide.family.update', 'netarch_family', code, body.get('name', ''))
    return {"ok": True}


@router.delete("/api/netarch-guide/families/{code}")
def delete_family(code: str, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT name FROM netarch_families WHERE code=?", (code,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "族系不存在")
    conn.execute("DELETE FROM netarch_families WHERE code=?", (code,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'netarch_guide.family.delete', 'netarch_family', code, row['name'])
    notify_module_activity("網路架構選型導覽", "刪除技術族系", actor.get("display_name") or actor["username"],
                            row['name'], "netarch-guide.html")
    return {"ok": True}


@router.get("/api/netarch-guide/generations")
def list_generations(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("SELECT * FROM netarch_generations ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/netarch-guide/generations", status_code=201)
def create_generation(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    family_code = (body.get("familyCode") or "").strip()
    if not family_code:
        raise HTTPException(400, "族系代碼不得為空")
    conn = get_db()
    if not conn.execute("SELECT 1 FROM netarch_families WHERE code=?", (family_code,)).fetchone():
        conn.close()
        raise HTTPException(400, "族系代碼不存在")
    now = datetime.now().isoformat()
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM netarch_generations").fetchone()["m"]
    cur = conn.execute("""
        INSERT INTO netarch_generations
          (family_code, gen_name, key_specs, upgrade_note, typical_scenario, tags, price_range, dependency_note, watch_note, sort_order, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        family_code, body.get("genName", ""), body.get("keySpecs", ""), body.get("upgradeNote", ""),
        body.get("typicalScenario", ""), body.get("tags", ""), body.get("priceRange", ""),
        body.get("dependencyNote", ""), body.get("watchNote", ""), max_sort + 1, now,
    ))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'netarch_guide.generation.create', 'netarch_generation', str(new_id), f"{family_code} {body.get('genName','')}".strip())
    notify_module_activity("網路架構選型導覽", "建立世代規格", actor.get("display_name") or actor["username"],
                            f"{family_code} {body.get('genName','')}".strip(), "netarch-guide.html")
    return {"id": new_id, "ok": True}


@router.put("/api/netarch-guide/generations/{gen_id}")
def update_generation(gen_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT family_code FROM netarch_generations WHERE id=?", (gen_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "世代不存在")
    now = datetime.now().isoformat()
    conn.execute("""
        UPDATE netarch_generations
           SET gen_name=?, key_specs=?, upgrade_note=?, typical_scenario=?, tags=?, price_range=?, dependency_note=?, watch_note=?, updated_at=?
         WHERE id=?
    """, (
        body.get("genName", ""), body.get("keySpecs", ""), body.get("upgradeNote", ""),
        body.get("typicalScenario", ""), body.get("tags", ""), body.get("priceRange", ""),
        body.get("dependencyNote", ""), body.get("watchNote", ""), now, gen_id,
    ))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'netarch_guide.generation.update', 'netarch_generation', str(gen_id), f"{row['family_code']} {body.get('genName','')}".strip())
    return {"ok": True}


@router.delete("/api/netarch-guide/generations/{gen_id}")
def delete_generation(gen_id: int, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT family_code, gen_name FROM netarch_generations WHERE id=?", (gen_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "世代不存在")
    conn.execute("DELETE FROM netarch_generations WHERE id=?", (gen_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'netarch_guide.generation.delete', 'netarch_generation', str(gen_id), f"{row['family_code']} {row['gen_name']}".strip())
    notify_module_activity("網路架構選型導覽", "刪除世代規格", actor.get("display_name") or actor["username"],
                            f"{row['family_code']} {row['gen_name']}".strip(), "netarch-guide.html")
    return {"ok": True}


@router.get("/api/netarch-guide/products")
def list_products(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("SELECT * FROM netarch_products ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/netarch-guide/products", status_code=201)
def create_product(body: dict = Body(...), authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    generation_id = body.get("generationId")
    if not generation_id:
        raise HTTPException(400, "所屬世代不得為空")
    conn = get_db()
    if not conn.execute("SELECT 1 FROM netarch_generations WHERE id=?", (generation_id,)).fetchone():
        conn.close()
        raise HTTPException(400, "所屬世代不存在")
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM netarch_products").fetchone()["m"]
    cur = conn.execute(
        "INSERT INTO netarch_products (generation_id, brand, model, url, label, price_note, sort_order) VALUES (?,?,?,?,?,?,?)",
        (generation_id, body.get("brand", ""), body.get("model", ""), body.get("url", ""),
         body.get("label", ""), body.get("priceNote", ""), max_sort + 1),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'netarch_guide.product.create', 'netarch_product', str(new_id), f"{body.get('brand','')} {body.get('model','')}".strip())
    notify_module_activity("網路架構選型導覽", "建立產品連結", actor.get("display_name") or actor["username"],
                            f"{body.get('brand','')} {body.get('model','')}".strip(), "netarch-guide.html")
    return {"id": new_id, "ok": True}


@router.put("/api/netarch-guide/products/{prod_id}")
def update_product(prod_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    if not conn.execute("SELECT 1 FROM netarch_products WHERE id=?", (prod_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "產品不存在")
    conn.execute(
        "UPDATE netarch_products SET brand=?, model=?, url=?, label=?, price_note=? WHERE id=?",
        (body.get("brand", ""), body.get("model", ""), body.get("url", ""),
         body.get("label", ""), body.get("priceNote", ""), prod_id),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'netarch_guide.product.update', 'netarch_product', str(prod_id), f"{body.get('brand','')} {body.get('model','')}".strip())
    return {"ok": True}


@router.delete("/api/netarch-guide/products/{prod_id}")
def delete_product(prod_id: int, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT brand, model FROM netarch_products WHERE id=?", (prod_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "產品不存在")
    conn.execute("DELETE FROM netarch_products WHERE id=?", (prod_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'netarch_guide.product.delete', 'netarch_product', str(prod_id), f"{row['brand']} {row['model']}".strip())
    notify_module_activity("網路架構選型導覽", "刪除產品連結", actor.get("display_name") or actor["username"],
                            f"{row['brand']} {row['model']}".strip(), "netarch-guide.html")
    return {"ok": True}
