"""Auth + User management endpoints."""
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel

from db import get_db, get_demo_db, reset_demo_db, demo_reset_lock
from helpers import (
    _hash_pw, _verify_pw, _require_user, _tok, _audit,
    _SUPERADMIN_MODULES, is_weak_password, MIN_PASSWORD_LEN, DEMO_TOKEN_PREFIX,
    notify_module_activity,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Login rate limiting (per source IP) ───────────────────────────────────────

_LOGIN_MAX_FAILS = 5       # consecutive failures before lockout
_LOGIN_LOCKOUT_S = 900     # 15 minutes

_rl_lock = threading.Lock()
# ip -> {"fails": int, "locked_until": float (monotonic epoch)}
_rl_state: dict = {}


def _client_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rl_db_write(ip: str, locked_until_mono: float) -> None:
    delta = locked_until_mono - time.monotonic()
    wall_until = datetime.now() + timedelta(seconds=max(delta, 0))
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO login_rate_limit (ip, locked_until) VALUES (?, ?) "
            "ON CONFLICT(ip) DO UPDATE SET locked_until=excluded.locked_until",
            (ip, wall_until.isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _rl_db_clear(ip: str) -> None:
    try:
        conn = get_db()
        conn.execute("DELETE FROM login_rate_limit WHERE ip=?", (ip,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def init_rate_limiting() -> None:
    """Reload persisted IP lockouts from DB into memory on startup."""
    try:
        conn = get_db()
        rows = conn.execute("SELECT ip, locked_until FROM login_rate_limit").fetchall()
        conn.close()
        now_wall = datetime.now()
        now_mono = time.monotonic()
        with _rl_lock:
            for row in rows:
                try:
                    wall_until = datetime.fromisoformat(row["locked_until"])
                    if wall_until > now_wall:
                        delta = (wall_until - now_wall).total_seconds()
                        _rl_state[row["ip"]] = {"fails": 0, "locked_until": now_mono + delta}
                except Exception:
                    pass
        try:
            conn2 = get_db()
            conn2.execute("DELETE FROM login_rate_limit WHERE locked_until <= ?", (now_wall.isoformat(),))
            conn2.commit()
            conn2.close()
        except Exception:
            pass
    except Exception:
        logger.warning("init_rate_limiting: could not load from DB")


def _rl_check(ip: str) -> None:
    """Raise 429 if IP is currently locked out."""
    now = time.monotonic()
    with _rl_lock:
        state = _rl_state.get(ip)
        if not state:
            return
        if now < state["locked_until"]:
            wait = int(state["locked_until"] - now)
            raise HTTPException(429, f"登入嘗試次數過多，請於 {wait} 秒後再試")
        if state["locked_until"] > 0:
            del _rl_state[ip]


def _rl_fail(ip: str, username: str) -> None:
    now = time.monotonic()
    lockout_until = 0.0
    with _rl_lock:
        state = _rl_state.setdefault(ip, {"fails": 0, "locked_until": 0.0})
        state["fails"] += 1
        if state["fails"] >= _LOGIN_MAX_FAILS:
            state["locked_until"] = now + _LOGIN_LOCKOUT_S
            lockout_until = state["locked_until"]
            state["fails"] = 0
            logger.warning("Login lockout: IP=%s username=%s locked for %ds", ip, username, _LOGIN_LOCKOUT_S)
    if lockout_until:
        _rl_db_write(ip, lockout_until)


def _rl_clear(ip: str) -> None:
    with _rl_lock:
        _rl_state.pop(ip, None)
    _rl_db_clear(ip)


# ── Models ────────────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class VerifyUnlockIn(BaseModel):
    password: str
    ref: str = ''


class SetUnlockPasswordIn(BaseModel):
    unlock_password: str


class VerifyDailyTaskUnlockIn(BaseModel):
    password: str


class SetDailyTaskPasswordIn(BaseModel):
    daily_task_password: str


class UserIn(BaseModel):
    username: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    modules: Optional[List[str]] = None
    notification_muted: Optional[List[str]] = None
    password: Optional[str] = None
    active: Optional[bool] = None
    department_id: Optional[int] = None


# ── Auth ──────────────────────────────────────────────────────────────────────

@router.get("/api/ping")
def ping():
    return {"ok": True, "time": datetime.now().isoformat()}


@router.get("/api/system/version")
def system_version():
    """Latest overall system version (newest entry in version_manifest.json).
    Public — used by the login page footer, which has no session token yet."""
    manifest_path = os.path.join(os.path.dirname(__file__), "..", "version_manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            entries = json.load(f)
        latest = entries[0] if entries else {}
    except Exception:
        latest = {}
    return {"version": latest.get("version", ""), "date": latest.get("date", "")}


@router.post("/api/auth/login")
def auth_login(body: LoginIn, request: Request):
    ip = _client_ip(request)
    _rl_check(ip)
    conn = get_db()
    row = conn.execute(
        "SELECT id, username, display_name, role, modules, password_hash, "
        "COALESCE(must_change_password, 0) AS must_change_password "
        "FROM users WHERE username=? AND active=1",
        (body.username.strip(),)
    ).fetchone()
    if not row or not _verify_pw(body.password, row["password_hash"]):
        conn.close()
        _rl_fail(ip, body.username.strip())
        raise HTTPException(401, "帳號或密碼錯誤")
    must_change = bool(row["must_change_password"])
    # Legacy weak password still works once, but forces rotation
    if is_weak_password(body.password):
        must_change = True
        conn.execute(
            "UPDATE users SET must_change_password=1 WHERE id=?",
            (row["id"],),
        )
    if ":" not in row["password_hash"]:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                     (_hash_pw(body.password), row["id"]))
    now = datetime.now().isoformat()

    if row["username"] == "demo":
        # Showcase account: never touches real data. Reset the isolated demo DB
        # to a fresh, fully-migrated, completely empty state and issue a
        # prefixed token whose session/user row lives ONLY in that demo DB —
        # auth_middleware detects the prefix and routes every subsequent
        # request (including _require_user()/_audit() lookups) there too.
        conn.commit()
        conn.close()
        token      = DEMO_TOKEN_PREFIX + secrets.token_hex(32)
        expires_at = (datetime.now() + timedelta(days=1)).isoformat()
        # Serialise reset+seed: two demo logins arriving at nearly the same
        # moment must not both wipe/re-seed the shared demo DB concurrently
        # (races on the fresh 'demo' user INSERT / VACUUM otherwise).
        with demo_reset_lock:
            reset_demo_db()
            dconn = get_demo_db()
            dconn.execute(
                "INSERT INTO users (username, password_hash, display_name, role, modules, "
                "active, created_at, must_change_password) VALUES ('demo',?,?,?,?,1,?,0)",
                (row["password_hash"], row["display_name"], row["role"], row["modules"], now),
            )
            demo_user_id = dconn.execute("SELECT last_insert_rowid()").fetchone()[0]
            dconn.execute(
                "INSERT INTO sessions (token, user_id, username, created_at, expires_at, last_active) "
                "VALUES (?,?,?,?,?,?)",
                (token, demo_user_id, "demo", now, expires_at, now),
            )
            dconn.execute(
                "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (now, demo_user_id, "demo", row["display_name"], "auth.login", "user", "demo",
                 row["display_name"], json.dumps({"mustChangePassword": False}, ensure_ascii=False)),
            )
            dconn.commit()
            dconn.close()
        _rl_clear(ip)
        return {
            "token":              token,
            "userId":             demo_user_id,
            "username":           "demo",
            "displayName":        row["display_name"],
            "role":               row["role"],
            "modules":            json.loads(row["modules"] or "[]"),
            "loginAt":            now,
            "mustChangePassword": False,
        }

    token      = secrets.token_hex(32)
    expires_at = (datetime.now() + timedelta(days=30)).isoformat()
    conn.execute(
        "INSERT INTO sessions (token, user_id, username, created_at, expires_at, last_active) VALUES (?,?,?,?,?,?)",
        (token, row["id"], row["username"], now, expires_at, now)
    )
    conn.commit()
    conn.close()
    _rl_clear(ip)
    _audit(token, 'auth.login', 'user', row['username'], row['display_name'] or row['username'],
           {'mustChangePassword': must_change})
    return {
        "token":              token,
        "userId":             row["id"],
        "username":           row["username"],
        "displayName":        row["display_name"],
        "role":               row["role"],
        "modules":            json.loads(row["modules"] or "[]"),
        "loginAt":            now,
        "mustChangePassword": must_change,
    }


@router.post("/api/auth/logout")
def auth_logout(authorization: str = Header(None)):
    token = _tok(authorization)
    if token.startswith(DEMO_TOKEN_PREFIX):
        # _audit() looks the token up in the real sessions table, which a demo
        # token never touches — skip it rather than log a meaningless miss.
        dconn = get_demo_db()
        dconn.execute("DELETE FROM sessions WHERE token=?", (token,))
        dconn.commit()
        dconn.close()
        return {"ok": True}
    _audit(token, 'auth.logout', 'user', '', '登出')
    if authorization and authorization.startswith("Bearer "):
        conn = get_db()
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()
    return {"ok": True}


@router.get("/api/auth/me")
def auth_me(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登入")
    token = authorization[7:]
    conn = get_db()
    row = conn.execute("""
        SELECT u.id, u.username, u.display_name, u.role, u.modules,
               COALESCE(u.must_change_password, 0) AS must_change_password
        FROM sessions s JOIN users u ON s.user_id = u.id
        WHERE s.token=? AND u.active=1
          AND (s.expires_at IS NULL OR s.expires_at > datetime('now'))
    """, (token,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(401, "Session 已過期，請重新登入")
    return {
        "userId":             row["id"],
        "username":           row["username"],
        "displayName":        row["display_name"],
        "role":               row["role"],
        "modules":            json.loads(row["modules"] or "[]"),
        "mustChangePassword": bool(row["must_change_password"]),
    }


@router.patch("/api/auth/change-password")
def change_password(body: ChangePasswordIn, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登入")
    token = authorization[7:]
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        row = conn.execute("""
            SELECT u.id, u.password_hash, u.display_name, u.username
            FROM sessions s JOIN users u ON s.user_id = u.id
            WHERE s.token=? AND u.active=1
              AND (s.expires_at IS NULL OR s.expires_at > ?)
        """, (token, now)).fetchone()
        if not row:
            raise HTTPException(401, "Session 已過期，請重新登入")
        if not _verify_pw(body.current_password, row["password_hash"]):
            raise HTTPException(400, "目前密碼不正確")
        if len(body.new_password) < MIN_PASSWORD_LEN:
            raise HTTPException(400, f"新密碼至少需要 {MIN_PASSWORD_LEN} 碼")
        if is_weak_password(body.new_password):
            raise HTTPException(400, "新密碼過於簡單或為已知弱密碼，請改用更強的密碼")
        if body.new_password == body.current_password:
            raise HTTPException(400, "新密碼不可與目前密碼相同")
        new_hash = _hash_pw(body.new_password)
        conn.execute(
            "UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
            (new_hash, row["id"]),
        )
        conn.execute("DELETE FROM sessions WHERE user_id=? AND token!=?", (row["id"], token))
        conn.commit()
    finally:
        conn.close()
    _audit(token, 'auth.change_password', 'user', '', '修改密碼')
    notify_module_activity("使用者管理", "變更密碼", row["display_name"] or row["username"],
                            row["display_name"] or row["username"], "users.html")
    return {"ok": True, "mustChangePassword": False}


# ── User Management ───────────────────────────────────────────────────────────

@router.get("/api/users")
def list_users(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute("""
        SELECT u.id, u.username, u.display_name, u.role, u.email, u.phone, u.modules,
               u.notification_muted, u.active, u.created_at,
               u.department_id, dep.name AS department_name,
               dep.division_id, dv.name AS division_name
        FROM users u
        LEFT JOIN departments dep ON dep.id = u.department_id
        LEFT JOIN divisions dv ON dv.id = dep.division_id
        ORDER BY u.id
    """).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["displayName"]        = d.pop("display_name")
        d["createdAt"]          = d.pop("created_at")
        d["modules"]             = json.loads(d["modules"] or "[]")
        d["notificationMuted"]   = json.loads(d.pop("notification_muted") or "[]")
        d["departmentId"]        = d.pop("department_id")
        d["departmentName"]      = d.pop("department_name")
        d["divisionId"]          = d.pop("division_id")
        d["divisionName"]        = d.pop("division_name")
        result.append(d)
    return result


@router.post("/api/users", status_code=201)
def create_user(body: UserIn, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    if not body.username or not body.password:
        raise HTTPException(400, "缺少帳號或密碼")
    if len(body.password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"密碼至少 {MIN_PASSWORD_LEN} 碼")
    if is_weak_password(body.password):
        raise HTTPException(400, "密碼過於簡單或為已知弱密碼，請改用更強的密碼")
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO users (username, password_hash, display_name, role, email, phone, modules,
                               notification_muted, active, created_at, must_change_password, department_id)
            VALUES (?,?,?,?,?,?,?,?,1,?,1,?)
        """, (
            body.username.strip(),
            _hash_pw(body.password),
            body.display_name or '',
            body.role or 'viewer',
            body.email or '',
            body.phone or '',
            json.dumps(body.modules or [], ensure_ascii=False),
            json.dumps(body.notification_muted or [], ensure_ascii=False),
            now,
            body.department_id or None,
        ))
        conn.commit()
        user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, "帳號已存在")
    conn.close()
    _audit(_tok(authorization), 'user.create', 'user', body.username, body.display_name or body.username)
    notify_module_activity("使用者管理", "建立帳號", actor.get("display_name") or actor["username"],
                            body.display_name or body.username, "users.html")
    return {"id": user_id, "created_at": now, "mustChangePassword": True}


@router.put("/api/users/{user_id}")
def update_user(user_id: int, body: UserIn, authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    conn = get_db()
    if not conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
        conn.close()
        raise HTTPException(404, "使用者不存在")
    sets, params = [], []
    if body.display_name is not None: sets.append("display_name=?"); params.append(body.display_name)
    if body.role         is not None: sets.append("role=?");         params.append(body.role)
    if body.email        is not None: sets.append("email=?");        params.append(body.email)
    if body.phone        is not None: sets.append("phone=?");        params.append(body.phone)
    if body.modules      is not None: sets.append("modules=?");      params.append(json.dumps(body.modules, ensure_ascii=False))
    if body.notification_muted is not None:
        sets.append("notification_muted=?")
        params.append(json.dumps(body.notification_muted, ensure_ascii=False))
    if body.department_id is not None:
        sets.append("department_id=?")
        params.append(body.department_id or None)   # 0 -> 未分類（清空 NULL）
    if body.password:
        if len(body.password) < MIN_PASSWORD_LEN:
            conn.close()
            raise HTTPException(400, f"密碼至少 {MIN_PASSWORD_LEN} 碼")
        if is_weak_password(body.password):
            conn.close()
            raise HTTPException(400, "密碼過於簡單或為已知弱密碼，請改用更強的密碼")
        sets.append("password_hash=?")
        params.append(_hash_pw(body.password))
        sets.append("must_change_password=?")
        params.append(1)
    if sets:
        params.append(user_id)
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
    conn.close()
    _audit(_tok(authorization), 'user.update', 'user', str(user_id), body.display_name or str(user_id))
    return {"ok": True}


@router.delete("/api/users/{user_id}")
def delete_user(user_id: int, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    row = conn.execute("SELECT username, display_name FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "使用者不存在")
    if row["username"] == "jeff":
        conn.close()
        raise HTTPException(400, "不可刪除超級管理員帳號")
    uname  = row["username"]
    ulabel = row["display_name"] or uname
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    _audit(_tok(authorization), 'user.delete', 'user', str(user_id), ulabel)
    notify_module_activity("使用者管理", "刪除帳號", actor.get("display_name") or actor["username"],
                            ulabel, "users.html")
    return {"ok": True}


@router.patch("/api/users/{user_id}/active")
def toggle_user_active(user_id: int, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    row = conn.execute("SELECT username, display_name, active FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "使用者不存在")
    if row["username"] == "jeff":
        conn.close()
        raise HTTPException(400, "不可停用超級管理員帳號")
    new_active = 0 if row["active"] else 1
    conn.execute("UPDATE users SET active=? WHERE id=?", (new_active, user_id))
    conn.commit()
    conn.close()
    ulabel = row["display_name"] or row["username"]
    _audit(_tok(authorization), 'user.active', 'user', str(user_id),
           f"{ulabel}（{'啟用' if new_active else '停用'}帳號）", {'active': bool(new_active)})
    notify_module_activity("使用者管理", "啟用帳號" if new_active else "停用帳號",
                            actor.get("display_name") or actor["username"], ulabel, "users.html")
    return {"ok": True, "active": bool(new_active)}


@router.get("/api/users/selectable")
def users_selectable(authorization: str = Header(None)):
    _require_user(authorization)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, username, display_name, role FROM users WHERE active=1 ORDER BY display_name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Unlock password ───────────────────────────────────────────────────────────

@router.post("/api/auth/verify-unlock")
def verify_unlock(body: VerifyUnlockIn, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT unlock_password_hash FROM users WHERE id=?", (user['id'],)
        ).fetchone()
    finally:
        conn.close()
    stored = (row['unlock_password_hash'] or '') if row else ''
    if not stored:
        raise HTTPException(500, "尚未設定解鎖密碼，請至使用者管理設定")
    if not _verify_pw(body.password, stored):
        raise HTTPException(403, "解鎖密碼不正確")
    _audit(_tok(authorization), 'quotation.unlock', 'quotation', body.ref, body.ref,
           {'unlocked_by': user['display_name']})
    return {"ok": True}


@router.patch("/api/users/{user_id}/unlock-password")
def set_unlock_password(user_id: int, body: SetUnlockPasswordIn, authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    if len(body.unlock_password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"解鎖密碼至少 {MIN_PASSWORD_LEN} 碼")
    if is_weak_password(body.unlock_password):
        raise HTTPException(400, "解鎖密碼過於簡單或為已知弱密碼，請改用更強的密碼")
    conn = get_db()
    try:
        row = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "使用者不存在")
        if row['role'] != 'superadmin':
            raise HTTPException(400, "僅超級管理員帳號可設定解鎖密碼")
        conn.execute(
            "UPDATE users SET unlock_password_hash=? WHERE id=?",
            (_hash_pw(body.unlock_password), user_id)
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), 'user.set_unlock_password', 'user', str(user_id), str(user_id))
    notify_module_activity("使用者管理", "設定解鎖密碼", actor.get("display_name") or actor["username"],
                            str(user_id), "users.html")
    return {"ok": True}


# ── Daily-task admin-view unlock ──────────────────────────────────────────────

@router.post("/api/auth/verify-daily-task-unlock")
def verify_daily_task_unlock(body: VerifyDailyTaskUnlockIn, authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT daily_task_pw_hash FROM users WHERE id=?", (user['id'],)
        ).fetchone()
    finally:
        conn.close()
    stored = (row['daily_task_pw_hash'] or '') if row else ''
    if not stored:
        raise HTTPException(428, "尚未設定每日工作事項密碼，請至使用者管理設定")
    if not _verify_pw(body.password, stored):
        raise HTTPException(403, "密碼不正確")
    _audit(_tok(authorization), 'daily_task.admin_unlock', 'daily_task', 'admin_view', 'admin_view')
    return {"ok": True}


@router.patch("/api/users/{user_id}/daily-task-password")
def set_daily_task_password(user_id: int, body: SetDailyTaskPasswordIn,
                             authorization: str = Header(None)):
    actor = _require_user(authorization, require_superadmin=True)
    if len(body.daily_task_password) < MIN_PASSWORD_LEN:
        raise HTTPException(400, f"密碼至少 {MIN_PASSWORD_LEN} 碼")
    if is_weak_password(body.daily_task_password):
        raise HTTPException(400, "密碼過於簡單，請改用更強的密碼")
    conn = get_db()
    try:
        row = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "使用者不存在")
        if row['role'] != 'superadmin':
            raise HTTPException(400, "僅超級管理員帳號可設定每日工作事項密碼")
        conn.execute(
            "UPDATE users SET daily_task_pw_hash=? WHERE id=?",
            (_hash_pw(body.daily_task_password), user_id)
        )
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), 'user.set_daily_task_password', 'user', str(user_id), str(user_id))
    notify_module_activity("使用者管理", "設定每日工作事項密碼", actor.get("display_name") or actor["username"],
                            str(user_id), "users.html")
    return {"ok": True}

