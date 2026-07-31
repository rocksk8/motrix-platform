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


def init_demo_account() -> None:
    """Ensure the 'demo' showcase account exists in the real DB (gatekeeper row
    used only to authenticate the login POST). All actual browsing after login
    happens against the isolated demo DB — see db.reset_demo_db() /
    routers/auth.py auth_login()."""
    conn = get_db()
    try:
        if not conn.execute("SELECT id FROM users WHERE username='demo'").fetchone():
            conn.execute(
                "INSERT INTO users "
                "(username, password_hash, display_name, role, modules, active, "
                "created_at, must_change_password) "
                "VALUES ('demo', ?, '展示帳號', 'superadmin', ?, 1, ?, 0)",
                (
                    _hash_pw("60575481"),
                    json.dumps(_SUPERADMIN_MODULES),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            logger.info("已建立展示帳號（demo），密碼 60575481")
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


def _version_to_updated_at(date_str: str, version: str, time_str: str = "") -> str:
    """Convert manifest date/time/version fields to an ISO datetime string.

    Priority:
      1. Explicit ``time`` field (HH:MM or HH:MM:SS) — most accurate.
      2. Version suffix letter (a→01:00, b→02:00, …) — ordering fallback.
      3. Midnight (T00:00:00) — last resort for no-suffix versions.
    """
    import re as _re
    if len(date_str) != 10:      # already a full datetime string
        return date_str
    if time_str:
        t = time_str.strip()
        if t.count(":") == 1:
            t += ":00"
        return f"{date_str}T{t}"
    m = _re.search(r'([a-z])$', version)
    if m:
        hour = ord(m.group(1)) - ord('a') + 1
        return f"{date_str}T{hour:02d}:00:00"
    return date_str + "T00:00:00"


def _sync_module_versions() -> None:
    """Upsert version_manifest.json entries into module_versions table.

    Key rules:
    - (module, version) is the natural unique key.
    - First run: inserts all historical records.
    - Subsequent runs: INSERT OR IGNORE skips existing rows, then UPDATE
      corrects updated_at / content for system-synced rows so manifest
      edits (e.g. adding a "time" field) take effect on next restart.
    - User-created entries (updated_by != 'system') are never modified.
    """
    manifest_path = os.path.join(os.path.dirname(__file__), "..", "version_manifest.json")
    if not os.path.exists(manifest_path):
        return
    try:
        with open(manifest_path, encoding="utf-8") as f:
            entries = json.load(f)
    except Exception:
        logger.exception("_sync_module_versions: failed to load version_manifest.json")
        return

    conn = get_db()
    try:
        inserted = updated = 0
        for e in entries:
            module   = (e.get("module")  or "").strip()
            version  = (e.get("version") or "").strip()
            content  = (e.get("content") or "").strip()
            date_str = (e.get("date") or e.get("updated_at") or "").strip()
            time_str = (e.get("time") or "").strip()
            if not module or not version:
                continue

            updated_at = _version_to_updated_at(date_str, version, time_str)

            cur = conn.execute(
                "INSERT OR IGNORE INTO module_versions "
                "(module, version, updated_at, content, updated_by) VALUES (?,?,?,?,?)",
                (module, version, updated_at, content, "system"),
            )
            inserted += cur.rowcount

            # Sync: update timestamp / content on existing system-synced rows
            rv = conn.execute(
                "UPDATE module_versions SET updated_at=?, content=? "
                "WHERE module=? AND version=? AND updated_by='system' "
                "  AND (updated_at!=? OR content!=?)",
                (updated_at, content, module, version, updated_at, content),
            )
            updated += rv.rowcount

        conn.commit()
        if inserted:
            logger.info("_sync_module_versions: inserted %d new entries from manifest", inserted)
        if updated:
            logger.info("_sync_module_versions: synced %d existing rows from manifest", updated)
    except Exception:
        logger.exception("_sync_module_versions failed")
    finally:
        conn.close()
