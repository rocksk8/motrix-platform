"""System settings CRUD (system_settings table)."""

#: G1（MODULE-GUIDE §2）：底線開頭但屬於 L1 公開介面的名稱——改簽章或刪除照介面變更升版。
#: L1 以外只可以用這裡列出的底線名稱（守門：test_l1_interface_snapshot::test_l2_uses_only_declared_l1_underscore_names）。
__l1_public__ = (
    "_get_setting",
    "_set_setting",
)

import json
import logging
from datetime import datetime

from db import get_db

logger = logging.getLogger(__name__)


def _get_setting(key: str, default=None):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT value_json FROM system_settings WHERE key=?", (key,)
        ).fetchone()
        return json.loads(row["value_json"]) if row else default
    except Exception:
        # 2026-08-28：曾經靜默吞掉所有例外（含 JSON 解析失敗），使用者只會看到設定
        # 悄悄變回預設值、完全查無線索。改為留一筆 log，下次若真的是資料層問題
        # （例如 value_json 被寫壞），至少 server.log 能追出是哪個 key、什麼原因。
        logger.warning("_get_setting(%r) failed, returning default", key, exc_info=True)
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
