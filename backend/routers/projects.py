"""Projects, project logs, action item approvals, photo upload (2026-08-26:
専案管理業務端點已從 main.py 拔除掛載，見 db.py::_m062_case_project_merge()
docstring——此檔保留當歷史/備用程式碼，不再對外服務；通用上傳簽名 URL 服務
已搬到 routers/uploads.py 獨立維護，不隨此模組一起下線）。"""
import json
import os
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header, Body, UploadFile, File

from db import get_db
from helpers import (
    _require_user, _tok, _audit, _purge_notifications, notify_module_activity,
    resolve_department_manager, resolve_division_manager,
)
from photos import _process_project_photo, _PHOTO_UPLOAD_BASE, _photo_root

router = APIRouter()


def _parse_log(r: dict) -> dict:
    r['attendees']      = json.loads(r.get('attendees')      or '[]')
    r['action_items']   = json.loads(r.get('action_items')   or '[]')
    r['materials_used'] = json.loads(r.get('materials_used') or '[]')
    r['photos']         = json.loads(r.get('photos')         or '[]')
    return r


def _project_approver_ids(conn, department_id):
    """回傳 (部門主管 user_id, 處主管 user_id)，department_id 空值或查無資料時回傳
    (None, None)。專案確認事項簽核的額外路徑用（2026-08-23）——純附加，不影響既有
    project_approve_eng/project_approve_biz 模組權限判斷；department_id 未設定或
    部門/處未設主管時就是沒有新增任何人，行為完全比照現況。"""
    if not department_id:
        return None, None
    dept_mgr = resolve_department_manager(conn, department_id)
    row = conn.execute("SELECT division_id FROM departments WHERE id=?", (department_id,)).fetchone()
    div_mgr = resolve_division_manager(conn, row["division_id"]) if row else None
    return (
        dept_mgr["userId"] if dept_mgr else None,
        div_mgr["userId"] if div_mgr else None,
    )


# ── Projects CRUD ─────────────────────────────────────────────────────────────

@router.get("/api/projects")
def list_projects(
    status:        Optional[str] = None,
    q:             Optional[str] = None,
    case_no:       Optional[str] = None,
    department_id: Optional[int] = None,
    authorization: str = Header(None),
):
    user     = _require_user(authorization)
    is_admin = user['role'] in ('superadmin', 'admin')
    is_super = user['role'] == 'superadmin'
    modules  = json.loads(user.get('modules') or '[]')
    uid      = user['id']
    conn = get_db()
    rows = conn.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    result = []
    for r in rows:
        d        = dict(r)
        linked   = json.loads(d.get('linked_cases')      or '[]')
        extra    = json.loads(d.get('data_json')         or '{}')
        assigned = json.loads(d.get('assigned_user_ids') or '[]')
        # 非 admin：只看到已被分配到的專案
        if not is_admin and uid not in assigned:
            continue
        if status        and d['status'] != status:               continue
        if case_no        and case_no not in linked:               continue
        if department_id and d.get('department_id') != department_id: continue
        if q:
            ql = q.lower()
            if not (ql in d.get('name','').lower() or ql in d.get('code','').lower()):
                continue
        d['linked_cases']      = linked
        d['data_json']         = extra
        d['assigned_user_ids'] = assigned
        dept_manager_id, division_manager_id = _project_approver_ids(conn, d.get('department_id'))
        d['canApproveEng'] = is_super or 'project_approve_eng' in modules or uid == dept_manager_id
        d['canApproveBiz'] = is_super or 'project_approve_biz' in modules or uid == division_manager_id
        result.append(d)
    conn.close()
    return {"items": result}


@router.post("/api/projects", status_code=201)
def create_project(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    name = (body.get('name') or '').strip()
    if not name:
        raise HTTPException(400, "專案名稱不得為空")
    now  = datetime.now().isoformat()
    conn = get_db()
    cur  = conn.execute("""
        INSERT INTO projects (code, name, status, description, linked_cases, created_at, created_by, data_json, department_id)
        VALUES ('', ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name,
        body.get('status', '規劃中'),
        body.get('description', ''),
        json.dumps(body.get('linked_cases', []), ensure_ascii=False),
        now, user['display_name'],
        json.dumps(body.get('data_json', {}), ensure_ascii=False),
        body.get('department_id') or None,
    ))
    new_id = cur.lastrowid
    code   = f"PR-{new_id:04d}"
    conn.execute("UPDATE projects SET code=? WHERE id=?", (code, new_id))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'project.create', 'project', code, name)
    notify_module_activity("專案管理", "建立", user.get("display_name") or user["username"],
                            f"{code} {name}", "projects.html")
    return {"id": new_id, "code": code, "ok": True}


@router.get("/api/projects/{project_id}")
def get_project(project_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    row  = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "專案不存在")
    d = dict(row)
    d['linked_cases']      = json.loads(d.get('linked_cases')      or '[]')
    d['data_json']         = json.loads(d.get('data_json')         or '{}')
    d['assigned_user_ids'] = json.loads(d.get('assigned_user_ids') or '[]')
    dept_manager_id, division_manager_id = _project_approver_ids(conn, d.get('department_id'))
    conn.close()
    modules = json.loads(user.get('modules') or '[]')
    is_super = user['role'] == 'superadmin'
    d['canApproveEng'] = is_super or 'project_approve_eng' in modules or user['id'] == dept_manager_id
    d['canApproveBiz'] = is_super or 'project_approve_biz' in modules or user['id'] == division_manager_id
    return d


@router.put("/api/projects/{project_id}")
def update_project(project_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row  = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "專案不存在")
    updates = {}
    if 'name'          in body: updates['name']          = body['name']
    if 'description'   in body: updates['description']   = body['description']
    if 'linked_cases'  in body: updates['linked_cases']  = json.dumps(body['linked_cases'], ensure_ascii=False)
    if 'data_json'     in body: updates['data_json']     = json.dumps(body['data_json'], ensure_ascii=False)
    if 'department_id' in body: updates['department_id'] = body['department_id'] or None
    if updates:
        sql = "UPDATE projects SET " + ', '.join(f"{k}=?" for k in updates) + " WHERE id=?"
        conn.execute(sql, list(updates.values()) + [project_id])
        conn.commit()
    conn.close()
    _audit(_tok(authorization), 'project.update', 'project', row['code'], row['name'])
    return {"ok": True}


@router.patch("/api/projects/{project_id}/status")
def update_project_status(project_id: int, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    new_status = body.get('status', '')
    valid = ['規劃中', '進行中', '暫停', '驗收中', '完工', '結案', '取消']
    if new_status not in valid:
        raise HTTPException(400, f"無效狀態，有效值: {valid}")
    conn = get_db()
    row  = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "專案不存在")
    conn.execute("UPDATE projects SET status=? WHERE id=?", (new_status, project_id))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'project.status', 'project', row['code'], f"{row['name']} → {new_status}")
    notify_module_activity("專案管理", f"狀態變更為「{new_status}」", user.get("display_name") or user["username"],
                            f"{row['code']} {row['name']}", "projects.html")
    return {"ok": True}


@router.patch("/api/projects/{project_id}/assigned-users")
def update_project_assigned_users(project_id: int, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    if user['role'] not in ('superadmin', 'admin'):
        raise HTTPException(403, "僅管理員可設定成員分配")
    user_ids = [int(uid) for uid in (body.get('user_ids') or []) if uid]
    conn = get_db()
    row = conn.execute("SELECT code, name FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "專案不存在")
    conn.execute("UPDATE projects SET assigned_user_ids=? WHERE id=?",
                 (json.dumps(user_ids, ensure_ascii=False), project_id))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'project.assign', 'project', row['code'],
           f"{row['name']} 分配 {len(user_ids)} 位成員")
    notify_module_activity("專案管理", "設定成員分配", user.get("display_name") or user["username"],
                            f"{row['code']} {row['name']}（{len(user_ids)} 位成員）", "projects.html")
    return {"ok": True}


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    if user['role'] not in ('superadmin', 'admin'):
        raise HTTPException(403, "僅管理員可刪除專案")
    conn = get_db()
    row  = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "專案不存在")
    if row['status'] not in ('規劃中', '取消'):
        conn.close(); raise HTTPException(400, "只有規劃中或取消狀態才可刪除")
    linked = json.loads(row['linked_cases'] or '[]')
    if linked:
        conn.close(); raise HTTPException(400, f"此專案仍關聯 {len(linked)} 筆案件，請先在專案詳情頁解除案件關聯後再刪除")
    conn.execute("DELETE FROM project_logs WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    conn.commit()
    conn.close()
    _purge_notifications(row['code'], ['project_deadline'])
    _audit(_tok(authorization), 'project.delete', 'project', row['code'], row['name'])
    notify_module_activity("專案管理", "刪除", user.get("display_name") or user["username"],
                            f"{row['code']} {row['name']}", "projects.html")
    return {"ok": True}


# ── Project Logs ──────────────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/logs")
def list_project_logs(project_id: int, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM project_logs WHERE project_id=? ORDER BY log_date DESC, id DESC",
        (project_id,)
    ).fetchall()
    conn.close()
    return {"items": [_parse_log(dict(r)) for r in rows]}


@router.post("/api/projects/{project_id}/logs", status_code=201)
def create_project_log(project_id: int, body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    if not conn.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone():
        conn.close(); raise HTTPException(404, "專案不存在")
    now      = datetime.now().isoformat()
    log_date = body.get('log_date') or datetime.now().strftime('%Y-%m-%d')
    items    = body.get('action_items', [])
    for item in items:
        if not item.get('id'):
            item['id'] = uuid.uuid4().hex[:8]
    cur = conn.execute("""
        INSERT INTO project_logs
          (project_id, log_date, work_content, attendees, action_items, materials_used, photos, log_status, created_at, created_by, updated_at)
        VALUES (?,?,?,?,?,?,?,'draft',?,?,?)
    """, (
        project_id, log_date,
        body.get('work_content', ''),
        json.dumps(body.get('attendees', []), ensure_ascii=False),
        json.dumps(items, ensure_ascii=False),
        json.dumps(body.get('materials_used', []), ensure_ascii=False),
        '[]', now, user['display_name'], now,
    ))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'project.log.create', 'project_log', str(project_id), f"PR-{project_id:04d} 日誌 {log_date}")
    notify_module_activity("專案管理", "新增工作日誌", user.get("display_name") or user["username"],
                            f"PR-{project_id:04d} 日誌 {log_date}", "projects.html",
                            detail=body.get('work_content', ''))
    return {"id": new_id, "ok": True}


@router.put("/api/projects/{project_id}/logs/{log_id}")
def update_project_log(project_id: int, log_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM project_logs WHERE id=? AND project_id=?", (log_id, project_id)
    ).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "日誌不存在")
    now   = datetime.now().isoformat()
    items = body.get('action_items', json.loads(row['action_items'] or '[]'))
    conn.execute("""
        UPDATE project_logs SET log_date=?, work_content=?, attendees=?, action_items=?,
               materials_used=?, updated_at=?
        WHERE id=? AND project_id=?
    """, (
        body.get('log_date', row['log_date']),
        body.get('work_content', row['work_content'] or ''),
        json.dumps(body.get('attendees', json.loads(row['attendees'] or '[]')), ensure_ascii=False),
        json.dumps(items, ensure_ascii=False),
        json.dumps(body.get('materials_used', json.loads(row['materials_used'] or '[]')), ensure_ascii=False),
        now, log_id, project_id,
    ))
    conn.commit()
    conn.close()
    return {"ok": True}


@router.delete("/api/projects/{project_id}/logs/{log_id}")
def delete_project_log(project_id: int, log_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    if user['role'] not in ('superadmin', 'admin'):
        raise HTTPException(403, "僅管理員可刪除日誌")
    conn = get_db()
    row = conn.execute(
        "SELECT log_date FROM project_logs WHERE id=? AND project_id=?", (log_id, project_id)
    ).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "日誌不存在")
    conn.execute("DELETE FROM project_logs WHERE id=?", (log_id,))
    conn.commit()
    conn.close()
    notify_module_activity("專案管理", "刪除工作日誌", user.get("display_name") or user["username"],
                            f"PR-{project_id:04d} 日誌 {row['log_date']}", "projects.html")
    return {"ok": True}


# ── Project Stages（執行階段，2026-08-24：多階段清單＋可手動設起訖日期，比照
#    案件管理 case_stages 的風格，但專案這邊沒有負責人/前置依賴/前往記錄的需求，
#    刻意只做「具名階段＋完成狀態＋起訖日期」這個子集，不照搬整套）──────────────

def _serialize_project_stage(r) -> dict:
    return {
        "id":        r["id"],
        "label":     r["label"],
        "sortOrder": r["sort_order"],
        "done":      bool(r["done"]),
        "doneAt":    r["done_at"],
        "startDate": r["start_date"],
        "dueDate":   r["due_date"],
    }


@router.get("/api/projects/{project_id}/stages")
def list_project_stages(project_id: int, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM project_stages WHERE project_id=? ORDER BY sort_order, id", (project_id,)
    ).fetchall()
    conn.close()
    return {"items": [_serialize_project_stage(r) for r in rows]}


@router.post("/api/projects/{project_id}/stages", status_code=201)
def create_project_stage(project_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    if not conn.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone():
        conn.close(); raise HTTPException(404, "專案不存在")
    max_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) m FROM project_stages WHERE project_id=?", (project_id,)
    ).fetchone()["m"]
    now = datetime.now().isoformat()
    cur = conn.execute("""
        INSERT INTO project_stages
            (project_id, label, sort_order, done, done_at, start_date, due_date, created_at, updated_at)
        VALUES (?,?,?,0,'','','',?,?)
    """, (project_id, body.get("label") or "", max_order + 1, now, now))
    new_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM project_stages WHERE id=?", (new_id,)).fetchone()
    conn.close()
    return _serialize_project_stage(row)


@router.put("/api/projects/{project_id}/stages/{stage_id}")
def update_project_stage(project_id: int, stage_id: int, body: dict = Body(...), authorization: str = Header(None)):
    """局部更新階段欄位（label/done/doneAt/startDate/dueDate），比照
    quotations.py::update_case_stage() 的作法：不加任何自動邏輯（done=true 不
    自動填 doneAt），各欄位互相獨立，維持跟前端 x-model 直接綁定的行為一致。"""
    _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM project_stages WHERE id=? AND project_id=?", (stage_id, project_id)
    ).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "階段不存在")
    updates = {}
    if "label" in body:     updates["label"]      = body.get("label") or ""
    if "done" in body:      updates["done"]       = 1 if body.get("done") else 0
    if "doneAt" in body:    updates["done_at"]    = body.get("doneAt") or ""
    if "startDate" in body: updates["start_date"] = body.get("startDate") or ""
    if "dueDate" in body:   updates["due_date"]   = body.get("dueDate") or ""
    if updates:
        updates["updated_at"] = datetime.now().isoformat()
        sql = "UPDATE project_stages SET " + ", ".join(f"{k}=?" for k in updates) + " WHERE id=?"
        conn.execute(sql, list(updates.values()) + [stage_id])
        conn.commit()
    row = conn.execute("SELECT * FROM project_stages WHERE id=?", (stage_id,)).fetchone()
    conn.close()
    return _serialize_project_stage(row)


@router.delete("/api/projects/{project_id}/stages/{stage_id}")
def delete_project_stage(project_id: int, stage_id: int, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM project_stages WHERE id=? AND project_id=?", (stage_id, project_id)
    ).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "階段不存在")
    conn.execute("DELETE FROM project_stages WHERE id=?", (stage_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@router.patch("/api/projects/{project_id}/stages/reorder")
def reorder_project_stages(project_id: int, body: dict = Body(...), authorization: str = Header(None)):
    """依 orderedIds 陣列順序重寫 sort_order，對應拖曳重排的最終結果。"""
    _require_user(authorization)
    ordered_ids = body.get("orderedIds") or []
    conn = get_db()
    valid_ids = {r["id"] for r in conn.execute(
        "SELECT id FROM project_stages WHERE project_id=?", (project_id,)
    ).fetchall()}
    now = datetime.now().isoformat()
    for idx, sid in enumerate(ordered_ids):
        if sid in valid_ids:
            conn.execute("UPDATE project_stages SET sort_order=?, updated_at=? WHERE id=? AND project_id=?",
                         (idx, now, sid, project_id))
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Action Item Approval ──────────────────────────────────────────────────────

@router.patch("/api/projects/{project_id}/logs/{log_id}/items/{item_id}/approve")
def approve_action_item(
    project_id: int, log_id: int, item_id: str,
    body: dict = Body(...),
    authorization: str = Header(None),
):
    user    = _require_user(authorization)
    stage   = body.get('stage')
    modules = json.loads(user.get('modules') or '[]')
    if stage not in (1, 2):
        raise HTTPException(400, "stage 必須為 1 或 2")

    conn = get_db()
    proj = conn.execute("SELECT department_id FROM projects WHERE id=?", (project_id,)).fetchone()
    dept_manager_id, division_manager_id = _project_approver_ids(
        conn, proj["department_id"] if proj else None
    )

    if stage == 1:
        if ('project_approve_eng' not in modules and user['role'] != 'superadmin'
                and user['id'] != dept_manager_id):
            conn.close()
            raise HTTPException(403, "需要工程主管確認（project_approve_eng 權限，或為該專案所屬部門主管）")
    else:
        if ('project_approve_biz' not in modules and user['role'] != 'superadmin'
                and user['id'] != division_manager_id):
            conn.close()
            raise HTTPException(403, "需要業務確認（project_approve_biz 權限，或為該專案所屬處主管）")

    row  = conn.execute(
        "SELECT * FROM project_logs WHERE id=? AND project_id=?", (log_id, project_id)
    ).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "日誌不存在")

    items   = json.loads(row['action_items'] or '[]')
    now_iso = datetime.now().isoformat()
    found   = False

    for item in items:
        if item.get('id') == item_id:
            found = True
            if stage == 1:
                item['stage1_approver'] = user['display_name']
                item['stage1_at']       = now_iso
                item['status']          = 'stage1_done'
            else:
                if not item.get('stage1_at'):
                    conn.close(); raise HTTPException(400, "需先完成工程主管確認（第一階段）")
                item['stage2_approver'] = user['display_name']
                item['stage2_at']       = now_iso
                item['status']          = 'done'
            break

    if not found:
        conn.close(); raise HTTPException(404, "確認事項不存在")

    conn.execute(
        "UPDATE project_logs SET action_items=?, updated_at=? WHERE id=?",
        (json.dumps(items, ensure_ascii=False), now_iso, log_id)
    )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'project.log.approve', 'project_log', str(project_id),
           f"PR-{project_id:04d} 日誌 #{log_id} 第{stage}階段：{user['display_name']}")
    notify_module_activity("專案管理", f"確認事項第 {stage} 階段完成",
                            user.get("display_name") or user["username"],
                            f"PR-{project_id:04d} 日誌 #{log_id}", "projects.html")
    return {"ok": True, "items": items}


# ── Photo Upload & Serving ────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/logs/{log_id}/photos", status_code=201)
async def upload_project_photos(
    project_id: int,
    log_id:     int,
    files:      List[UploadFile] = File(...),
    authorization: str = Header(None),
):
    user = _require_user(authorization)
    conn = get_db()
    row  = conn.execute(
        "SELECT * FROM project_logs WHERE id=? AND project_id=?", (log_id, project_id)
    ).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "日誌不存在")

    existing = json.loads(row['photos'] or '[]')
    today    = datetime.now().strftime('%Y-%m-%d')
    base_dir, url_prefix = _photo_root()
    save_dir = os.path.join(base_dir, str(project_id), today)
    os.makedirs(save_dir, exist_ok=True)

    new_photos = []
    for upload in files:
        raw_bytes = await upload.read()
        processed, gps_str, wm_str = _process_project_photo(raw_bytes, user['display_name'])
        ext   = os.path.splitext(upload.filename or 'photo.jpg')[1] or '.jpg'
        fname = uuid.uuid4().hex[:14] + ext.lower()
        with open(os.path.join(save_dir, fname), 'wb') as f:
            f.write(processed)
        new_photos.append({
            "id":          uuid.uuid4().hex[:8],
            "filename":    fname,
            "path":        f"{url_prefix}/{project_id}/{today}/{fname}",
            "gps":         gps_str,
            "watermark":   wm_str,
            "uploaded_by": user['display_name'],
            "uploaded_at": datetime.now().isoformat(),
        })

    all_photos = existing + new_photos
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE project_logs SET photos=?, updated_at=? WHERE id=?",
        (json.dumps(all_photos, ensure_ascii=False), now, log_id)
    )
    conn.commit()
    conn.close()
    notify_module_activity("專案管理", "上傳照片", user['display_name'],
                            f"PR-{project_id:04d} 日誌 #{log_id}（{len(new_photos)} 張）", "projects.html")
    return {"ok": True, "added": len(new_photos), "photos": new_photos}


@router.delete("/api/projects/{project_id}/logs/{log_id}/photos/{photo_id}")
def delete_project_photo(
    project_id: int, log_id: int, photo_id: str,
    authorization: str = Header(None),
):
    user = _require_user(authorization)
    conn   = get_db()
    row    = conn.execute(
        "SELECT * FROM project_logs WHERE id=? AND project_id=?", (log_id, project_id)
    ).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "日誌不存在")
    photos = json.loads(row['photos'] or '[]')
    photo  = next((p for p in photos if p.get('id') == photo_id), None)
    if not photo:
        conn.close(); raise HTTPException(404, "照片不存在")
    try:
        fp = os.path.join(_PHOTO_UPLOAD_BASE, '..', photo['path'])
        if os.path.isfile(fp):
            os.remove(fp)
    except Exception:
        pass
    photos = [p for p in photos if p.get('id') != photo_id]
    conn.execute("UPDATE project_logs SET photos=? WHERE id=?",
                 (json.dumps(photos, ensure_ascii=False), log_id))
    conn.commit()
    conn.close()
    notify_module_activity("專案管理", "刪除照片", user.get("display_name") or user["username"],
                            f"PR-{project_id:04d} 日誌 #{log_id}", "projects.html")
    return {"ok": True}
