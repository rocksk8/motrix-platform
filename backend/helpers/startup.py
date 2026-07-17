"""Server startup checks: admin seed, weak-password scan, session cleanup, Edge path."""
import json
import os
import logging
import secrets
from datetime import datetime, date

from db import get_db
from .auth import (
    _hash_pw, _SUPERADMIN_MODULES, _LEGACY_WEAK_PASSWORDS,
    _verify_pw, _write_initial_credentials,
)
from .settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)


# ── Edge executable resolution ────────────────────────────────────────────────

_EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _get_edge_path() -> str:
    """Return the Edge executable path.

    Checks system_settings['edge_path'] first; if empty or the path doesn't
    exist, falls back to known install locations.
    Raises RuntimeError if Edge cannot be found anywhere.
    """
    configured = (_get_setting("edge_path") or "").strip()
    if configured and os.path.exists(configured):
        return configured
    for candidate in _EDGE_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise RuntimeError(
        "找不到 Microsoft Edge 執行檔。"
        "請至「系統設定 → Edge 執行檔路徑」手動指定完整路徑。"
    )


# ── Startup routines ──────────────────────────────────────────────────────────

def init_default_admin() -> None:
    """Ensure the superadmin account exists; new installs get a random temp password."""
    conn = get_db()
    try:
        if not conn.execute("SELECT id FROM users WHERE username='jeff'").fetchone():
            temp_pw = secrets.token_urlsafe(14)
            conn.execute(
                "INSERT INTO users "
                "(username, password_hash, display_name, role, email, modules, active, "
                "created_at, must_change_password) "
                "VALUES ('jeff', ?, '黃玉龍', 'superadmin', 'jeff@miactw.com', ?, 1, ?, 1)",
                (
                    _hash_pw(temp_pw),
                    json.dumps(_SUPERADMIN_MODULES),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            path = _write_initial_credentials("jeff", temp_pw)
            logger.warning(
                "已建立預設 superadmin（jeff）。臨時密碼已寫入 %s — 請立即登入並修改密碼。", path
            )
        else:
            conn.execute(
                "UPDATE users SET display_name='黃玉龍' WHERE username='jeff' "
                "AND display_name IN ('Jeff 管理員','Jeff','jeff','jeff超級管理員','')"
            )
            conn.execute(
                "UPDATE users SET email='jeff@miactw.com' WHERE username='jeff' "
                "AND (email='' OR email IS NULL)"
            )
            conn.commit()
    finally:
        conn.close()


def flag_weak_passwords() -> None:
    """Mark accounts still using known weak/legacy passwords for forced rotation.

    Throttled to once per calendar day to avoid repeated PBKDF2 work on every restart.
    """
    today = date.today().isoformat()
    if _get_setting("security.last_weak_pw_scan") == today:
        return
    conn = get_db()
    try:
        try:
            rows = conn.execute(
                "SELECT id, username, password_hash, must_change_password FROM users WHERE active=1"
            ).fetchall()
        except Exception:
            return
        flagged = 0
        for r in rows:
            if r["must_change_password"]:
                continue
            stored = r["password_hash"] or ""
            for pw in _LEGACY_WEAK_PASSWORDS:
                try:
                    if _verify_pw(pw, stored):
                        conn.execute(
                            "UPDATE users SET must_change_password=1 WHERE id=?", (r["id"],)
                        )
                        flagged += 1
                        logger.warning("使用者 %s 仍使用弱/預設密碼，已標記 must_change_password", r["username"])
                        break
                except Exception:
                    continue
        if flagged:
            conn.commit()
            try:
                conn.execute(
                    "INSERT INTO audit_log "
                    "(at,user_id,username,display_name,action,target_type,target_id,target_label,detail) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        datetime.now().isoformat(), None, "system", "系統",
                        "security.flag_weak_password", "user", "",
                        f"{flagged} 個帳號",
                        json.dumps({"count": flagged}, ensure_ascii=False),
                    ),
                )
                conn.commit()
            except Exception:
                pass
    except Exception as e:
        logger.warning("flag_weak_passwords failed: %s", e)
    finally:
        conn.close()
    try:
        _set_setting("security.last_weak_pw_scan", today)
    except Exception:
        pass


def init_unlock_passwords() -> None:
    """Clear any unlock-password hashes that still match historical defaults.

    Throttled to once per calendar day.
    """
    today = date.today().isoformat()
    if _get_setting("security.last_unlock_pw_scan") == today:
        return
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, username, unlock_password_hash FROM users WHERE role='superadmin'"
        ).fetchall()
        cleared = 0
        for r in rows:
            stored = (r["unlock_password_hash"] or "").strip()
            if not stored:
                continue
            for pw in _LEGACY_WEAK_PASSWORDS:
                try:
                    if _verify_pw(pw, stored):
                        conn.execute(
                            "UPDATE users SET unlock_password_hash='' WHERE id=?", (r["id"],)
                        )
                        cleared += 1
                        logger.warning(
                            "已清除 superadmin %s 的預設/弱解鎖密碼，請至使用者管理重新設定",
                            r["username"],
                        )
                        break
                except Exception:
                    continue
        if cleared:
            conn.commit()
            try:
                conn.execute(
                    "INSERT INTO audit_log "
                    "(at,user_id,username,display_name,action,target_type,target_id,target_label,detail) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        datetime.now().isoformat(), None, "system", "系統",
                        "security.clear_default_unlock", "user", "",
                        f"{cleared} 個帳號",
                        json.dumps({"count": cleared}, ensure_ascii=False),
                    ),
                )
                conn.commit()
            except Exception:
                pass
    except Exception as e:
        logger.warning("init_unlock_passwords failed: %s", e)
    finally:
        conn.close()
    try:
        _set_setting("security.last_unlock_pw_scan", today)
    except Exception:
        pass


def _cleanup_sessions() -> None:
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM sessions WHERE expires_at IS NOT NULL AND expires_at < ?",
            (datetime.now().isoformat(),),
        )
        conn.commit()
    except Exception:
        logger.exception("_cleanup_sessions failed")
    finally:
        conn.close()
