"""場域選型導覽 CRUD — 無人自動化載具部署場域／設備選型參考資料。

檢視：任何登入者皆可讀取（比照 parts.py）。
編輯：superadmin 或具 env_guide_edit 模組者（比照 contractors.py）。
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Header

from db import get_db
from helpers import _require_user, _tok, _audit

router = APIRouter()

_EDIT_MODULE = "env_guide_edit"


@router.get("/api/env-guide/environments")
def list_environments(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM env_guide_environments ORDER BY sort_order, code"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/env-guide/environments", status_code=201)
def create_environment(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    code = (body.get("code") or "").strip()
    if not code:
        conn.close()
        raise HTTPException(400, "場域代碼不得為空")
    if conn.execute("SELECT 1 FROM env_guide_environments WHERE code=?", (code,)).fetchone():
        conn.close()
        raise HTTPException(409, "場域代碼已存在")
    now = datetime.now().isoformat()
    max_sort = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) AS m FROM env_guide_environments"
    ).fetchone()["m"]
    conn.execute("""
        INSERT INTO env_guide_environments
          (code, name, group_name, temp_gate, ip_gate, cert_gate, trap_note, sort_order, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        code, body.get("name", ""), body.get("groupName", ""),
        body.get("tempGate", ""), body.get("ipGate", ""), body.get("certGate", ""),
        body.get("trapNote", ""), max_sort + 1, now,
    ))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'env_guide.environment.create', 'env_guide_environment', code, f"{code} {body.get('name','')}".strip())
    return {"code": code, "ok": True}


@router.put("/api/env-guide/environments/{code}")
def update_environment(code: str, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT code FROM env_guide_environments WHERE code=?", (code,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "場域不存在")
    now = datetime.now().isoformat()
    conn.execute("""
        UPDATE env_guide_environments
           SET name=?, group_name=?, temp_gate=?, ip_gate=?, cert_gate=?, trap_note=?, updated_at=?
         WHERE code=?
    """, (
        body.get("name", ""), body.get("groupName", ""),
        body.get("tempGate", ""), body.get("ipGate", ""), body.get("certGate", ""),
        body.get("trapNote", ""), now, code,
    ))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'env_guide.environment.update', 'env_guide_environment', code, f"{code} {body.get('name','')}".strip())
    return {"ok": True}


@router.delete("/api/env-guide/environments/{code}")
def delete_environment(code: str, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT name FROM env_guide_environments WHERE code=?", (code,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "場域不存在")
    conn.execute("DELETE FROM env_guide_environments WHERE code=?", (code,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'env_guide.environment.delete', 'env_guide_environment', code, f"{code} {row['name']}".strip())
    return {"ok": True}


@router.get("/api/env-guide/recommendations")
def list_recommendations(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM env_guide_recommendations ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/env-guide/recommendations", status_code=201)
def create_recommendation(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    env_code = (body.get("envCode") or "").strip()
    if not env_code:
        conn.close()
        raise HTTPException(400, "場域代碼不得為空")
    if not conn.execute("SELECT 1 FROM env_guide_environments WHERE code=?", (env_code,)).fetchone():
        conn.close()
        raise HTTPException(400, "場域代碼不存在")
    now = datetime.now().isoformat()
    max_sort = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) AS m FROM env_guide_recommendations"
    ).fetchone()["m"]
    cur = conn.execute("""
        INSERT INTO env_guide_recommendations
          (env_code, layer, position, tier1, tier2, tier3, custom_note, trap_note, sort_order, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        env_code, body.get("layer", ""), body.get("position", ""),
        body.get("tier1", ""), body.get("tier2", ""), body.get("tier3", ""),
        body.get("customNote", ""), body.get("trapNote", ""), max_sort + 1, now,
    ))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'env_guide.recommendation.create', 'env_guide_recommendation', str(new_id), f"{env_code} {body.get('layer','')}".strip())
    return {"id": new_id, "ok": True}


@router.put("/api/env-guide/recommendations/{rec_id}")
def update_recommendation(rec_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT env_code FROM env_guide_recommendations WHERE id=?", (rec_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "建議項目不存在")
    now = datetime.now().isoformat()
    conn.execute("""
        UPDATE env_guide_recommendations
           SET layer=?, position=?, tier1=?, tier2=?, tier3=?, custom_note=?, trap_note=?, updated_at=?
         WHERE id=?
    """, (
        body.get("layer", ""), body.get("position", ""),
        body.get("tier1", ""), body.get("tier2", ""), body.get("tier3", ""),
        body.get("customNote", ""), body.get("trapNote", ""), now, rec_id,
    ))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'env_guide.recommendation.update', 'env_guide_recommendation', str(rec_id), f"{row['env_code']} {body.get('layer','')}".strip())
    return {"ok": True}


@router.delete("/api/env-guide/recommendations/{rec_id}")
def delete_recommendation(rec_id: int, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT env_code, layer FROM env_guide_recommendations WHERE id=?", (rec_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "建議項目不存在")
    conn.execute("DELETE FROM env_guide_recommendations WHERE id=?", (rec_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'env_guide.recommendation.delete', 'env_guide_recommendation', str(rec_id), f"{row['env_code']} {row['layer']}".strip())
    return {"ok": True}


@router.get("/api/env-guide/links")
def list_links(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("SELECT * FROM env_guide_links ORDER BY sort_order, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/api/env-guide/links", status_code=201)
def create_link(body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    keyword = (body.get("keyword") or "").strip()
    url = (body.get("url") or "").strip()
    if not keyword or not url:
        raise HTTPException(400, "關鍵字與連結不得為空")
    conn = get_db()
    max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), -1) AS m FROM env_guide_links").fetchone()["m"]
    cur = conn.execute(
        "INSERT INTO env_guide_links (keyword, url, label, sort_order) VALUES (?,?,?,?)",
        (keyword, url, body.get("label", ""), max_sort + 1),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'env_guide.link.create', 'env_guide_link', str(new_id), keyword)
    return {"id": new_id, "ok": True}


@router.put("/api/env-guide/links/{link_id}")
def update_link(link_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    keyword = (body.get("keyword") or "").strip()
    url = (body.get("url") or "").strip()
    if not keyword or not url:
        raise HTTPException(400, "關鍵字與連結不得為空")
    conn = get_db()
    row = conn.execute("SELECT id FROM env_guide_links WHERE id=?", (link_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "連結不存在")
    conn.execute(
        "UPDATE env_guide_links SET keyword=?, url=?, label=? WHERE id=?",
        (keyword, url, body.get("label", ""), link_id),
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'env_guide.link.update', 'env_guide_link', str(link_id), keyword)
    return {"ok": True}


@router.delete("/api/env-guide/links/{link_id}")
def delete_link(link_id: int, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True, module=_EDIT_MODULE)
    conn = get_db()
    row = conn.execute("SELECT keyword FROM env_guide_links WHERE id=?", (link_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "連結不存在")
    conn.execute("DELETE FROM env_guide_links WHERE id=?", (link_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'env_guide.link.delete', 'env_guide_link', str(link_id), row['keyword'])
    return {"ok": True}
