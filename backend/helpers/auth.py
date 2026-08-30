"""Password hashing, session validation, weak-password detection."""
import hashlib
import hmac
import os
import json
import logging
import secrets
from datetime import datetime

from fastapi import HTTPException

from db import get_db

logger = logging.getLogger(__name__)

_SUPERADMIN_MODULES = [
    "dashboard", "quotation", "customer", "sales",
    "procurement", "inventory", "equipment", "finance", "settings",
    "project_approve_eng", "project_approve_biz", "financial_view",
]

_LEGACY_WEAK_PASSWORDS = (
    "rock1125",
    "miac@60575481",
    "password",
    "123456",
    "admin",
    "motrix",
    "motrix123",
)

_CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "..", ".initial_admin_credentials.txt")
MIN_PASSWORD_LEN = 8

# Session tokens issued to the 'demo' showcase account are prefixed so
# auth_middleware can flip db.set_demo_mode(True) BEFORE looking the session up
# (the session itself only exists in the isolated demo DB, not the real one).
DEMO_TOKEN_PREFIX = "DEMO_"


# ── Hashing ───────────────────────────────────────────────────────────────────

def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _hash_pw(password: str) -> str:
    salt = os.urandom(16)
    dk   = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return salt.hex() + ":" + dk.hex()


def _verify_pw(password: str, stored: str) -> bool:
    if ":" not in stored:
        return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)
    salt_hex, dk_hex = stored.split(":", 1)
    salt = bytes.fromhex(salt_hex)
    dk   = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return hmac.compare_digest(dk.hex(), dk_hex)


# ── Weak-password policy ──────────────────────────────────────────────────────

def is_weak_password(password: str) -> bool:
    if not password or len(password) < MIN_PASSWORD_LEN:
        return True
    low = password.lower().strip()
    if low in {p.lower() for p in _LEGACY_WEAK_PASSWORDS}:
        return True
    if low in {"password1", "passw0rd", "admin123", "qwerty123"}:
        return True
    return False


def _write_initial_credentials(username: str, password: str) -> str:
    """Write one-time bootstrap credentials to the backend directory."""
    path = _CREDENTIALS_FILE
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                "MOTRIX ERP — 首次安裝管理員帳號（請登入後立即修改密碼，並刪除此檔）\n"
                f"建立時間: {datetime.now().isoformat()}\n"
                f"帳號: {username}\n"
                f"臨時密碼: {password}\n"
                "注意: 此檔僅出現在本機 backend 目錄，請勿分享或備份到公開位置。\n"
            )
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception as e:
        logger.warning("無法寫入初始憑證檔: %s", e)
    return path


# ── Session helpers ───────────────────────────────────────────────────────────

def user_has_module(user: dict, key: str) -> bool:
    """`user["modules"]` 是 _require_user() 回傳的原始 JSON 字串（未解析），
    這裡統一解析比對——供「admin+ 或具備特定模組」這類判斷共用（2026-08-31
    財務/出納權限分工新增），取代散落在各檔案裡各自重寫一次 role 判斷式的
    寫法：`if user["role"] not in ("superadmin","admin") and not user_has_module(user,"cashier"): raise ...`"""
    try:
        return key in json.loads(user.get("modules") or "[]")
    except Exception:
        return False


def _require_user(authorization: str, require_superadmin: bool = False, module: str = None) -> dict:
    """Validate session and check role/module permissions.

    module: if provided alongside require_superadmin=True, superadmin OR users
            with that module key in their modules list are permitted.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "未登入")
    token = authorization[7:]
    conn  = get_db()
    now   = datetime.now().isoformat()
    try:
        row = conn.execute("""
            SELECT u.id, u.username, u.display_name, u.role, u.active, u.modules
            FROM sessions s JOIN users u ON s.user_id = u.id
            WHERE s.token=? AND u.active=1
              AND (s.expires_at IS NULL OR s.expires_at > ?)
        """, (token, now)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(401, "Session 已過期，請重新登入")
    if require_superadmin and row["role"] != "superadmin":
        if module:
            user_mods = json.loads(row["modules"] or "[]")
            if module not in user_mods:
                raise HTTPException(403, "僅超級管理員或具授權模組的使用者可執行此操作")
        else:
            raise HTTPException(403, "僅超級管理員可執行此操作")
    return dict(row)


def _tok(auth: str) -> str:
    if auth and auth.startswith("Bearer "):
        return auth[7:]
    return auth or ""
