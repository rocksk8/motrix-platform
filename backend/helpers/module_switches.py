"""CORE-SPEC §9c ③ 管理者啟停：`system_settings.modules_disabled`（模組 key 陣列）。

- 由 superadmin 在「模組管理」頁切換；**重啟後生效**（2026-09-25 裁示：不做動態卸載路由）。
- 關閉 ⇒ 載入器不 import 該模組 ⇒ 路由不掛、排程不跑、選單不出現；資料表與資料**不動**。

啟動時的讀取刻意不走 `get_db()`：載入器在 `main.py` 很早就跑（早於 `init_db()`），而 sqlite
連到不存在的檔會**自動建一個空檔**——那會讓「主庫不存在就拒絕啟動」（`core.paths.require_db`）
的守門失效。所以只在主庫已存在時以唯讀模式讀；讀不到（全新安裝、表還沒建）⇒ 視為沒有停用。
"""
import json
import logging
import os
import sqlite3


SETTING_KEY = "modules_disabled"
_log = logging.getLogger(__name__)


def _normalize(value) -> list:
    if not isinstance(value, list):
        return []
    return sorted({v.strip() for v in value if isinstance(v, str) and v.strip()})


def read_disabled_at_startup(db_path: str = None) -> frozenset:
    """載入器用：主庫不存在或讀不到 ⇒ 空集合（並記 WARNING，讀不到不等於沒人停用）。

    路徑在呼叫當下讀 `db.DB_PATH`（不是 `core.paths.DB_PATH`）：測試夾具只改前者，
    讀後者會讓測試去讀真實的開發庫。"""
    if db_path is None:
        import db as _db
        db_path = _db.DB_PATH
    path = db_path
    if not os.path.isfile(path):
        return frozenset()
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
        try:
            row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (SETTING_KEY,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        _log.warning("讀不到 %s（%s）⇒ 本次啟動視為沒有停用任何模組", SETTING_KEY, e)
        return frozenset()
    if row is None:
        return frozenset()
    try:
        return frozenset(_normalize(json.loads(row[0])))
    except (TypeError, ValueError) as e:
        _log.warning("%s 內容無法解析（%s）⇒ 本次啟動視為沒有停用任何模組", SETTING_KEY, e)
        return frozenset()


def configured_disabled() -> list:
    """目前設定值（可能與本次啟動實際生效的不同 ⇒ 待重啟）。"""
    from helpers.settings import _get_setting
    return _normalize(_get_setting(SETTING_KEY, []))


def set_enabled(key: str, enabled: bool) -> list:
    """寫入設定，回新的停用清單。重啟後生效。

    讀、改、寫在**同一個寫入交易**裡（BEGIN IMMEDIATE）：兩位 superadmin 同時切換不同模組時，
    後寫的不可以蓋掉先寫的（AUDIT-X-9c C-4／STATES P-SW-10）。第二個寫入者在 BEGIN 等鎖，
    拿到鎖時讀到的已經是第一個寫入者提交後的清單。"""
    from datetime import datetime
    from db import get_db
    conn = get_db()
    try:
        conn.isolation_level = None                       # 交易自己管：BEGIN IMMEDIATE 先拿寫鎖再讀
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (SETTING_KEY,)).fetchone()
            try:
                cur = set(_normalize(json.loads(row[0]))) if row else set()
            except (TypeError, ValueError):
                _log.warning("%s 內容無法解析 ⇒ 以空清單為基礎寫入", SETTING_KEY)
                cur = set()
            if enabled:
                cur.discard(key)
            else:
                cur.add(key)
            new = sorted(cur)
            conn.execute(
                "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (SETTING_KEY, json.dumps(new, ensure_ascii=False), datetime.now().isoformat()))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return new
