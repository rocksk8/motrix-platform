"""案件代辦事項（2026-08-26 專案管理併入案件管理）——工程主管→業務主管兩階段
簽核，邏輯整段比照原 routers/projects.py 的 _project_approver_ids()/
approve_action_item()，差異只在改用案件既有的
sales_person_id → users.department_id → departments/divisions.manager_user_id
查主管，不需要替 quotations 新增 department_id 欄位（比照 db.py
_m050_project_department() docstring 描述的既有 sales_person_id → department_id
查表模式）。"""
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Header, Body

from db import get_db
from helpers import (
    _require_user, _tok, _audit, notify_module_activity,
    resolve_department_manager, resolve_division_manager,
)

router = APIRouter()


def _case_approver_ids(conn, quote_no: str):
    """回傳 (工程/部門主管 user_id, 業務/處主管 user_id)，查不到案件、案件無
    業務員、業務員無部門、或部門/處未設主管時對應位置回傳 None，行為比照
    projects.py::_project_approver_ids()。"""
    row = conn.execute(
        "SELECT sales_person_id FROM quotations WHERE quote_no=?", (quote_no,)
    ).fetchone()
    if not row or not row["sales_person_id"]:
        return None, None
    urow = conn.execute(
        "SELECT department_id FROM users WHERE id=?", (row["sales_person_id"],)
    ).fetchone()
    department_id = urow["department_id"] if urow else None
    if not department_id:
        return None, None
    dept_mgr = resolve_department_manager(conn, department_id)
    drow = conn.execute(
        "SELECT division_id FROM departments WHERE id=?", (department_id,)
    ).fetchone()
    div_mgr = resolve_division_manager(conn, drow["division_id"]) if drow else None
    return (
        dept_mgr["userId"] if dept_mgr else None,
        div_mgr["userId"] if div_mgr else None,
    )


def _serialize(r, can_eng=False, can_biz=False) -> dict:
    return {
        "id":             r["id"],
        "quoteNo":        r["quote_no"],
        "text":           r["text"],
        "status":         r["status"],
        "stage1Approver": r["stage1_approver"],
        "stage1At":       r["stage1_at"],
        "stage2Approver": r["stage2_approver"],
        "stage2At":       r["stage2_at"],
        "sortOrder":      r["sort_order"],
        "createdAt":      r["created_at"],
        "createdBy":      r["created_by"],
        "updatedAt":      r["updated_at"],
        "canApproveEng":  can_eng,
        "canApproveBiz":  can_biz,
    }


@router.get("/api/quotations/{quote_no}/action-items")
def list_case_action_items(quote_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    modules = json.loads(user.get("modules") or "[]")
    is_super = user["role"] == "superadmin"
    conn = get_db()
    dept_mgr_id, div_mgr_id = _case_approver_ids(conn, quote_no)
    can_eng = is_super or "project_approve_eng" in modules or user["id"] == dept_mgr_id
    can_biz = is_super or "project_approve_biz" in modules or user["id"] == div_mgr_id
    rows = conn.execute(
        "SELECT * FROM case_action_items WHERE quote_no=? ORDER BY sort_order, id",
        (quote_no,)
    ).fetchall()
    conn.close()
    return {"items": [_serialize(r, can_eng, can_biz) for r in rows]}


@router.post("/api/quotations/{quote_no}/action-items", status_code=201)
def create_case_action_item(quote_no: str, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "代辦事項內容不得為空")
    conn = get_db()
    if not conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (quote_no,)).fetchone():
        conn.close(); raise HTTPException(404, "案件不存在")
    max_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) m FROM case_action_items WHERE quote_no=?", (quote_no,)
    ).fetchone()["m"]
    now = datetime.now().isoformat()
    cur = conn.execute("""
        INSERT INTO case_action_items
            (quote_no, text, status, sort_order, created_at, created_by, updated_at)
        VALUES (?,?,'pending',?,?,?,?)
    """, (quote_no, text, max_order + 1, now, user.get("display_name") or user["username"], now))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'case.action_item.create', 'case_action_item', quote_no, text)
    notify_module_activity("案件管理", "新增代辦事項", user.get("display_name") or user["username"],
                            f"{quote_no}：{text}", "case-management.html")
    return {"id": new_id, "ok": True}


@router.put("/api/quotations/{quote_no}/action-items/{item_id}")
def update_case_action_item(quote_no: str, item_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM case_action_items WHERE id=? AND quote_no=?", (item_id, quote_no)
    ).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "代辦事項不存在")
    if "text" not in body or not (body.get("text") or "").strip():
        conn.close(); raise HTTPException(400, "代辦事項內容不得為空")
    conn.execute(
        "UPDATE case_action_items SET text=?, updated_at=? WHERE id=?",
        (body["text"].strip(), datetime.now().isoformat(), item_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


@router.delete("/api/quotations/{quote_no}/action-items/{item_id}")
def delete_case_action_item(quote_no: str, item_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    if user["role"] not in ("superadmin", "admin"):
        raise HTTPException(403, "僅管理員可刪除代辦事項")
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM case_action_items WHERE id=? AND quote_no=?", (item_id, quote_no)
    ).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "代辦事項不存在")
    conn.execute("DELETE FROM case_action_items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    notify_module_activity("案件管理", "刪除代辦事項", user.get("display_name") or user["username"],
                            quote_no, "case-management.html")
    return {"ok": True}


@router.patch("/api/quotations/{quote_no}/action-items/{item_id}/approve")
def approve_case_action_item(quote_no: str, item_id: int, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    stage = body.get("stage")
    modules = json.loads(user.get("modules") or "[]")
    if stage not in (1, 2):
        raise HTTPException(400, "stage 必須為 1 或 2")

    conn = get_db()
    dept_mgr_id, div_mgr_id = _case_approver_ids(conn, quote_no)

    if stage == 1:
        if ('project_approve_eng' not in modules and user['role'] != 'superadmin'
                and user['id'] != dept_mgr_id):
            conn.close()
            raise HTTPException(403, "需要工程主管確認（project_approve_eng 權限，或為該案件業務員所屬部門主管）")
    else:
        if ('project_approve_biz' not in modules and user['role'] != 'superadmin'
                and user['id'] != div_mgr_id):
            conn.close()
            raise HTTPException(403, "需要業務確認（project_approve_biz 權限，或為該案件業務員所屬處主管）")

    row = conn.execute(
        "SELECT * FROM case_action_items WHERE id=? AND quote_no=?", (item_id, quote_no)
    ).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "代辦事項不存在")

    now_iso = datetime.now().isoformat()
    if stage == 1:
        conn.execute(
            "UPDATE case_action_items SET stage1_approver=?, stage1_at=?, status='stage1_done', updated_at=? WHERE id=?",
            (user['display_name'], now_iso, now_iso, item_id)
        )
    else:
        if not row['stage1_at']:
            conn.close(); raise HTTPException(400, "需先完成工程主管確認（第一階段）")
        conn.execute(
            "UPDATE case_action_items SET stage2_approver=?, stage2_at=?, status='done', updated_at=? WHERE id=?",
            (user['display_name'], now_iso, now_iso, item_id)
        )
    conn.commit()
    row = conn.execute("SELECT * FROM case_action_items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    _audit(_tok(authorization), 'case.action_item.approve', 'case_action_item', quote_no,
           f"#{item_id} 第{stage}階段：{user['display_name']}")
    notify_module_activity("案件管理", f"代辦事項第 {stage} 階段完成",
                            user.get("display_name") or user["username"],
                            f"{quote_no} #{item_id}", "case-management.html")
    return {"ok": True, "item": _serialize(row)}
