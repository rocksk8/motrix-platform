"""處/部門組織架構（2026-08-22）。純組織分類用途，division.manager_user_id／
department.manager_user_id 先預留給未來「處/部門主管自動列入簽核」使用，這輪
不接 helpers/tiered_approval.py。

⚠️ 未來開發保留：目前簽核設定（quotations.py／shipping_notes.py／
contractor_vouchers.py／invoice_vouchers.py 的 approval-settings 頁面）
仍是逐一手動挑選簽核人員，完全沒有依處/部門結構自動帶入的能力。日後如果要
支援「依部門/處自動列入主管簽核」，這裡的 manager_user_id 欄位就是專門
為此保留的資料來源，設計時務必沿用、不要另起爐灶。"""
import sqlite3
from datetime import datetime

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from db import get_db
from helpers import _require_user, _audit, _tok

router = APIRouter()


# ── Models ────────────────────────────────────────────────────────────────────

class DivisionIn(BaseModel):
    name: str
    sort_order: int = 0
    manager_user_id: Optional[int] = None


class DepartmentIn(BaseModel):
    division_id: int
    name: str
    sort_order: int = 0
    manager_user_id: Optional[int] = None


# ── Tree (read) ───────────────────────────────────────────────────────────────

@router.get("/api/org/tree")
def get_org_tree(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    divisions = conn.execute("""
        SELECT dv.id, dv.name, dv.sort_order, dv.manager_user_id,
               u.display_name AS manager_name
        FROM divisions dv
        LEFT JOIN users u ON u.id = dv.manager_user_id
        ORDER BY dv.sort_order, dv.name
    """).fetchall()
    departments = conn.execute("""
        SELECT d.id, d.division_id, d.name, d.sort_order, d.manager_user_id,
               u.display_name AS manager_name,
               (SELECT COUNT(*) FROM users WHERE department_id=d.id AND active=1) AS member_count
        FROM departments d
        LEFT JOIN users u ON u.id = d.manager_user_id
        ORDER BY d.sort_order, d.name
    """).fetchall()
    conn.close()

    depts_by_division: dict = {}
    for d in departments:
        depts_by_division.setdefault(d["division_id"], []).append({
            "id": d["id"],
            "name": d["name"],
            "sortOrder": d["sort_order"],
            "managerUserId": d["manager_user_id"],
            "managerName": d["manager_name"],
            "memberCount": d["member_count"],
        })

    return [
        {
            "id": v["id"],
            "name": v["name"],
            "sortOrder": v["sort_order"],
            "managerUserId": v["manager_user_id"],
            "managerName": v["manager_name"],
            "departments": depts_by_division.get(v["id"], []),
        }
        for v in divisions
    ]


# ── Divisions (處) ────────────────────────────────────────────────────────────

@router.post("/api/org/divisions", status_code=201)
def create_division(body: DivisionIn, authorization: str = Header(None)):
    u = _require_user(authorization, require_superadmin=True)
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "處名稱不可為空")
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_db()
    if body.manager_user_id is not None and not conn.execute(
        "SELECT id FROM users WHERE id=?", (body.manager_user_id,)
    ).fetchone():
        conn.close()
        raise HTTPException(404, "找不到指定的主管")
    try:
        cur = conn.execute(
            "INSERT INTO divisions (name, sort_order, manager_user_id, created_at) VALUES (?,?,?,?)",
            (name, body.sort_order, body.manager_user_id, now),
        )
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, "已有相同名稱的處")
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "division.create", "division", str(new_id), name)
    return {"id": new_id, "name": name, "sortOrder": body.sort_order}


@router.put("/api/org/divisions/{division_id}")
def update_division(division_id: int, body: DivisionIn, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "處名稱不可為空")
    conn = get_db()
    if not conn.execute("SELECT id FROM divisions WHERE id=?", (division_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "找不到此處")
    if body.manager_user_id is not None and not conn.execute(
        "SELECT id FROM users WHERE id=?", (body.manager_user_id,)
    ).fetchone():
        conn.close()
        raise HTTPException(404, "找不到指定的主管")
    try:
        conn.execute(
            "UPDATE divisions SET name=?, sort_order=?, manager_user_id=? WHERE id=?",
            (name, body.sort_order, body.manager_user_id, division_id),
        )
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, "已有相同名稱的處")
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "division.update", "division", str(division_id), name)
    return {"ok": True}


@router.delete("/api/org/divisions/{division_id}")
def delete_division(division_id: int, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    row = conn.execute("SELECT name FROM divisions WHERE id=?", (division_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到此處")
    if conn.execute("SELECT 1 FROM departments WHERE division_id=? LIMIT 1", (division_id,)).fetchone():
        conn.close()
        raise HTTPException(400, "此處底下還有部門，請先刪除或移動部門")
    conn.execute("DELETE FROM divisions WHERE id=?", (division_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "division.delete", "division", str(division_id), row["name"])
    return {"ok": True}


# ── Departments (部門) ────────────────────────────────────────────────────────

@router.post("/api/org/departments", status_code=201)
def create_department(body: DepartmentIn, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "部門名稱不可為空")
    conn = get_db()
    if not conn.execute("SELECT id FROM divisions WHERE id=?", (body.division_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "找不到所屬的處")
    if body.manager_user_id is not None and not conn.execute(
        "SELECT id FROM users WHERE id=?", (body.manager_user_id,)
    ).fetchone():
        conn.close()
        raise HTTPException(404, "找不到指定的主管")
    now = datetime.now().isoformat(timespec="seconds")
    try:
        cur = conn.execute(
            "INSERT INTO departments (division_id, name, sort_order, manager_user_id, created_at) "
            "VALUES (?,?,?,?,?)",
            (body.division_id, name, body.sort_order, body.manager_user_id, now),
        )
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, "此處底下已有相同名稱的部門")
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "department.create", "department", str(new_id), name)
    return {"id": new_id, "name": name, "divisionId": body.division_id, "sortOrder": body.sort_order}


@router.put("/api/org/departments/{department_id}")
def update_department(department_id: int, body: DepartmentIn, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "部門名稱不可為空")
    conn = get_db()
    if not conn.execute("SELECT id FROM departments WHERE id=?", (department_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "找不到此部門")
    if not conn.execute("SELECT id FROM divisions WHERE id=?", (body.division_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "找不到所屬的處")
    if body.manager_user_id is not None and not conn.execute(
        "SELECT id FROM users WHERE id=?", (body.manager_user_id,)
    ).fetchone():
        conn.close()
        raise HTTPException(404, "找不到指定的主管")
    try:
        conn.execute(
            "UPDATE departments SET division_id=?, name=?, sort_order=?, manager_user_id=? WHERE id=?",
            (body.division_id, name, body.sort_order, body.manager_user_id, department_id),
        )
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, "此處底下已有相同名稱的部門")
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "department.update", "department", str(department_id), name)
    return {"ok": True}


@router.delete("/api/org/departments/{department_id}")
def delete_department(department_id: int, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    row = conn.execute("SELECT name FROM departments WHERE id=?", (department_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "找不到此部門")
    if conn.execute("SELECT 1 FROM users WHERE department_id=? LIMIT 1", (department_id,)).fetchone():
        conn.close()
        raise HTTPException(400, "此部門仍有使用者，請先將人員轉移到其他部門或設為未分類")
    conn.execute("DELETE FROM departments WHERE id=?", (department_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "department.delete", "department", str(department_id), row["name"])
    return {"ok": True}
