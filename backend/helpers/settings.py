"""System settings CRUD (system_settings table)."""
import json
from datetime import datetime

from db import get_db


def _get_setting(key: str, default=None):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT value_json FROM system_settings WHERE key=?", (key,)
        ).fetchone()
        return json.loads(row["value_json"]) if row else default
    except Exception:
        return default
    finally:
        conn.close()


def _set_setting(key: str, value) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
