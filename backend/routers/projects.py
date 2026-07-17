"""Projects, project logs, action item approvals, photo upload/serving."""
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header, Body, UploadFile, File, Query
from fastapi.responses import FileResponse

from db import get_db
from helpers import _require_user, _tok, _audit
from photos import _process_project_photo, _PHOTO_UPLOAD_BASE

# Per-process secret — short-lived photo tokens; regenerates on restart which is acceptable.
_PHOTO_SECRET = secrets.token_bytes(32)
_PHOTO_TOKEN_TTL = 3600  # seconds


def _make_photo_token(path: str, ttl: int = _PHOTO_TOKEN_TTL) -> str:
    expires = int(time.time()) + ttl
    msg = f"{path}:{expires}".encode()
    sig = hmac.new(_PHOTO_SECRET, msg, hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def _verify_photo_token(path: str, token: str) -> bool:
    try:
        expires_str, sig = token.split(".", 1)
        expires = int(expires_str)
    except (ValueError, AttributeError):
        return False
    if time.time() > expires:
        return False
    msg = f"{path}:{expires}".encode()
    expected = hmac.new(_PHOTO_SECRET, msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)

router = APIRouter()


def _parse_log(r: dict) -> dict:
    r['attendees']      = json.loads(r.get('attendees')      or '[]')
    r['action_items']   = json.loads(r.get('action_items')   or '[]')
    r['materials_used'] = json.loads(r.get('materials_used') or '[]')
    r['photos']         = json.loads(r.get('photos')         or '[]')
    return r


# ── Projects CRUD ─────────────────────────────────────────────────────────────

@router.get("/api/projects")
def list_projects(
    status:  Optional[str] = None,
    q:       Optional[str] = None,
    case_no: Optional[str] = None,
    authorization: str = Header(None),
):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    conn.close()
    result = []
    for r in rows:
        d      = dict(r)
        linked = json.loads(d.get('linked_cases') or '[]')
        extra  = json.loads(d.get('data_json')    or '{}')
        if status  and d['status'] != status:               continue
        if case_no and case_no not in linked:               continue
        if q:
            ql = q.lower()
            if not (ql in d.get('name','').lower() or ql in d.get('code','').lower()):
                continue
        d['linked_cases'] = linked
        d['data_json']    = extra
        result.append(d)
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
        INSERT INTO projects (code, name, status, description, linked_cases, created_at, created_by, data_json)
        VALUES ('', ?, ?, ?, ?, ?, ?, ?)
    """, (
        name,
        body.get('status', '規劃中'),
        body.get('description', ''),
        json.dumps(body.get('linked_cases', []), ensure_ascii=False),
        now, user['display_name'],
        json.dumps(body.get('data_json', {}), ensure_ascii=False),
    ))
    new_id = cur.lastrowid
    code   = f"PR-{new_id:04d}"
    conn.execute("UPDATE projects SET code=? WHERE id=?", (code, new_id))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'project.create', 'project', code, name)
    return {"id": new_id, "code": code, "ok": True}


@router.get("/api/projects/{project_id}")
def get_project(project_id: int, authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row  = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "專案不存在")
    d = dict(row)
    d['linked_cases'] = json.loads(d.get('linked_cases') or '[]')
    d['data_json']    = json.loads(d.get('data_json')    or '{}')
    return d


@router.put("/api/projects/{project_id}")
def update_project(project_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    row  = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "專案不存在")
    updates = {}
    if 'name'         in body: updates['name']         = body['name']
    if 'description'  in body: updates['description']  = body['description']
    if 'linked_cases' in body: updates['linked_cases'] = json.dumps(body['linked_cases'], ensure_ascii=False)
    if 'data_json'    in body: updates['data_json']    = json.dumps(body['data_json'], ensure_ascii=False)
    if updates:
        sql = "UPDATE projects SET " + ', '.join(f"{k}=?" for k in updates) + " WHERE id=?"
        conn.execute(sql, list(updates.values()) + [project_id])
        conn.commit()
    conn.close()
    _audit(_tok(authorization), 'project.update', 'project', row['code'], row['name'])
    return {"ok": True}


@router.patch("/api/projects/{project_id}/status")
def update_project_status(project_id: int, body: dict = Body(...), authorization: str = Header(None)):
    _require_user(authorization)
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
    conn.execute("DELETE FROM project_logs WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'project.delete', 'project', row['code'], row['name'])
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
    if not conn.execute(
        "SELECT id FROM project_logs WHERE id=? AND project_id=?", (log_id, project_id)
    ).fetchone():
        conn.close(); raise HTTPException(404, "日誌不存在")
    conn.execute("DELETE FROM project_logs WHERE id=?", (log_id,))
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

    if stage == 1:
        if 'project_approve_eng' not in modules and user['role'] != 'superadmin':
            raise HTTPException(403, "需要工程主管確認（project_approve_eng）權限")
    elif stage == 2:
        if 'project_approve_biz' not in modules and user['role'] != 'superadmin':
            raise HTTPException(403, "需要業務確認（project_approve_biz）權限")
    else:
        raise HTTPException(400, "stage 必須為 1 或 2")

    conn = get_db()
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
    save_dir = os.path.join(_PHOTO_UPLOAD_BASE, str(project_id), today)
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
            "path":        f"projects/{project_id}/{today}/{fname}",
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
    return {"ok": True, "added": len(new_photos), "photos": new_photos}


@router.delete("/api/projects/{project_id}/logs/{log_id}/photos/{photo_id}")
def delete_project_photo(
    project_id: int, log_id: int, photo_id: str,
    authorization: str = Header(None),
):
    _require_user(authorization)
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
    return {"ok": True}


@router.get("/api/photo-token")
def get_photo_token(path: str = Query(...), authorization: str = Header(None)):
    """Return a short-lived signed token for accessing a specific upload path via ?pt=."""
    _require_user(authorization)
    safe = os.path.normpath(path).lstrip('/\\')
    return {"token": _make_photo_token(safe), "ttl": _PHOTO_TOKEN_TTL}


@router.get("/api/uploads/{file_path:path}")
def serve_upload(
    file_path: str,
    authorization: str = Header(None),
    token: str = Query(None),
    pt: str = Query(None),
):
    safe = os.path.normpath(file_path).lstrip('/\\')
    if pt:
        if not _verify_photo_token(safe, pt):
            raise HTTPException(403, "照片連結已過期或無效，請重新載入")
    else:
        if not authorization and token:
            authorization = f"Bearer {token}"
        _require_user(authorization)
    full = os.path.join(os.path.dirname(__file__), '..', '..', 'uploads', safe)
    if not os.path.isfile(full):
        raise HTTPException(404, "檔案不存在")
    return FileResponse(full)
