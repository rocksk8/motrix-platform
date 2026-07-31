"""Module version records — per-module changelog stored in DB, synced via daily backup."""
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from db import get_db
from helpers import _require_user, _audit, _tok

router = APIRouter()

_ROLE_RANK = {"viewer": 0, "engineer": 1, "sales": 1, "admin": 2, "superadmin": 3}


def _require_admin(authorization: str) -> dict:
    u = _require_user(authorization)
    if _ROLE_RANK.get(u["role"], 0) < 2:
        raise HTTPException(403, "需要管理員以上權限")
    return u


# ── Models ────────────────────────────────────────────────────────────────────

class ModuleVersionBody(BaseModel):
    module:  str
    version: str
    content: str = ""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/module-versions")
def list_module_versions(authorization: str = Header(None)):
    """Return all version entries grouped by module, newest-first within each group."""
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, module, version, updated_at, content, updated_by "
        "FROM module_versions ORDER BY module, updated_at DESC"
    ).fetchall()
    conn.close()

    grouped: dict = {}
    for r in rows:
        m = r["module"]
        if m not in grouped:
            grouped[m] = {"module": m, "history": []}
        grouped[m]["history"].append(dict(r))

    result = []
    for m, g in sorted(grouped.items()):
        latest = g["history"][0] if g["history"] else {}
        result.append({
            "module":            m,
            "latest_version":    latest.get("version", ""),
            "latest_updated_at": latest.get("updated_at", ""),
            "latest_content":    latest.get("content", ""),
            "history":           g["history"],
        })
    return result


@router.post("/api/module-versions", status_code=201)
def create_module_version(body: ModuleVersionBody, authorization: str = Header(None)):
    """Create a new version entry for a module. Requires admin+."""
    u = _require_admin(authorization)
    if not body.module.strip():
        raise HTTPException(422, "模組名稱不可為空")
    if not body.version.strip():
        raise HTTPException(422, "版本號不可為空")

    now = datetime.now().isoformat(timespec="seconds")
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO module_versions (module, version, updated_at, content, updated_by) "
        "VALUES (?, ?, ?, ?, ?)",
        (body.module.strip(), body.version.strip(), now,
         body.content.strip(), u["display_name"] or u["username"]),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()

    _audit(
        _tok(authorization), "module_version.create",
        target_type="module_version", target_id=str(new_id),
        target_label=f"{body.module} {body.version}",
        detail={"module": body.module, "version": body.version},
    )
    return {"id": new_id, "module": body.module, "version": body.version,
            "updated_at": now, "content": body.content, "updated_by": u["display_name"] or u["username"]}


@router.delete("/api/module-versions/{mvid}", status_code=204)
def delete_module_version(mvid: int, authorization: str = Header(None)):
    """Delete a version entry. Requires superadmin."""
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    row = conn.execute("SELECT * FROM module_versions WHERE id=?", (mvid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到此版本記錄")
    conn.execute("DELETE FROM module_versions WHERE id=?", (mvid,))
    conn.commit()
    conn.close()

    _audit(
        _tok(authorization), "module_version.delete",
        target_type="module_version", target_id=str(mvid),
        target_label=f"{row['module']} {row['version']}",
    )
