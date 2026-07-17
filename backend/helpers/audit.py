"""Audit log and in-app notification helpers."""
import json
import logging
from datetime import datetime

from db import get_db

logger = logging.getLogger(__name__)


def _notify(username: str, type_: str, ref_id: str, ref_label: str, message: str) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO notifications "
            "(username, type, ref_id, ref_label, message, is_read, created_at) "
            "VALUES (?,?,?,?,?,0,?)",
            (username, type_, ref_id, ref_label, message, datetime.now().isoformat()),
        )
        conn.commit()
    except Exception as e:
        logger.warning("_notify failed: %s", e)
    finally:
        conn.close()


def _audit(
    token: str,
    action: str,
    target_type: str = "",
    target_id: str = "",
    target_label: str = "",
    detail: dict = None,
) -> None:
    try:
        conn = get_db()
        user_id, username, display_name = None, "", ""
        if token:
            row = conn.execute(
                "SELECT u.id, u.username, u.display_name "
                "FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token=?",
                (token,),
            ).fetchone()
            if row:
                user_id, username, display_name = row["id"], row["username"], row["display_name"]
        conn.execute(
            "INSERT INTO audit_log "
            "(at,user_id,username,display_name,action,target_type,target_id,target_label,detail) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                datetime.now().isoformat(), user_id, username, display_name, action,
                target_type, target_id, target_label,
                json.dumps(detail or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
