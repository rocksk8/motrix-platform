"""CORE-SPEC §9c ③ 管理者啟停：`system_settings.modules_disabled`（模組 key 陣列）。

- 由 superadmin 在「模組管理」頁切換；**重啟後生效**（2026-09-25 裁示：不做動態卸載路由）。
- 關閉 ⇒ 載入器不 import 該模組 ⇒ 路由不掛、排程不跑、選單不出現；資料表與資料**不動**。

啟動時的讀取刻意不走 `get_db()`：載入器在 `main.py` 很早就跑（早於 `init_db()`），而 sqlite
連到不存在的檔會**自動建一個空檔**——那會讓「主庫不存在就拒絕啟動」（`core.paths.require_db`）
的守門失效。所以只在主庫已存在時以唯讀模式讀；主庫不存在或表還沒建（全新安裝）⇒ 確定沒有停用。
**被鎖或損毀而讀不到**是另一回事（STATES-PLATFORM P-SW-05）：沿用上次成功讀到的快取，沒有快取就全部停用。
"""
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass


SETTING_KEY = "modules_disabled"
_log = logging.getLogger(__name__)


def _normalize(value) -> list:
    if not isinstance(value, list):
        return []
    return sorted({v.strip() for v in value if isinstance(v, str) and v.strip()})


#: 讀不到時的重試（STATES-PLATFORM P-SW-05）：次數上限 × 每次 sqlite 等鎖秒數。測試可調小。
READ_ATTEMPTS = 3
READ_TIMEOUT_SECONDS = 2.0

SOURCE_DB, SOURCE_NO_DB, SOURCE_CACHE, SOURCE_UNREADABLE = "db", "no_db", "cache", "unreadable"
#: 讀不到也沒有快取時，狀態表每個模組的原因。
UNREADABLE_REASON = "停用清單讀取失敗，模組暫不載入"


@dataclass(frozen=True)
class DisabledList:
    """啟動時讀到的停用清單。`keys` 是停用的 key；`all_disabled` ⇒ 所有模組都當成停用
    （`keys` 無意義）；`source` 見 SOURCE_*；`message` 是給管理者看的說明（正常讀到時為空）。"""
    keys: frozenset
    all_disabled: bool
    source: str
    message: str = ""


class _Unreadable(Exception):
    pass


def _db_path(db_path):
    if db_path is None:
        import db as _db
        db_path = _db.DB_PATH
    return db_path


def _read_db_once(path):
    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True, timeout=READ_TIMEOUT_SECONDS)
    try:
        try:
            row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (SETTING_KEY,)).fetchone()
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):        # 表還沒建（全新庫、init_db 之前）＝確定沒有人停用過
                return []
            raise
    finally:
        conn.close()
    if row is None:
        return []
    try:
        value = json.loads(row[0])
    except (TypeError, ValueError) as e:
        raise _Unreadable("內容無法解析：%s" % e)
    if not isinstance(value, list):
        raise _Unreadable("內容不是清單：%r" % (value,))
    return _normalize(value)


def _write_cache(path, keys):
    """原子寫入（先寫暫存檔再 os.replace）；寫不進去只記 WARNING——快取是備援，不擋啟動。"""
    from core import paths as _paths
    cache = _paths.modules_disabled_cache(path)
    tmp = cache + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"modules_disabled": sorted(keys)}, f, ensure_ascii=False)
        os.replace(tmp, cache)
    except OSError as e:
        _log.warning("停用清單快取寫入失敗（%s）：%s", cache, e)


def _read_cache(path):
    from core import paths as _paths
    cache = _paths.modules_disabled_cache(path)
    try:
        with open(cache, encoding="utf-8") as f:
            value = json.load(f).get("modules_disabled")
        if not isinstance(value, list):
            return None, cache
        return _normalize(value), cache
    except (OSError, ValueError, AttributeError):
        return None, cache


def read_disabled_list(db_path: str = None) -> DisabledList:
    """載入器用（STATES-PLATFORM P-SW-05：讀不到停用清單時，**不可以默默反轉管理者的決定**）。

    - 主庫不存在 ⇒ 空（不建出空檔：sqlite 連到不存在的檔會自動建一個，那會讓 `require_db` 守門失效）；
    - 讀到 ⇒ 用它，並寫快取（`core.paths.modules_disabled_cache`，主庫旁）；
    - 讀不到（被鎖、損毀、內容壞掉）⇒ 重試 READ_ATTEMPTS 次 ⇒ 仍讀不到用快取（記 ERROR）
      ⇒ 沒有快取 ⇒ **全部停用**（記 ERROR；寧可少開，不可多開）。

    路徑在呼叫當下讀 `db.DB_PATH`（不是 `core.paths.DB_PATH`）：測試夾具只改前者。"""
    path = _db_path(db_path)
    if not os.path.isfile(path):
        return DisabledList(frozenset(), False, SOURCE_NO_DB)
    err = None
    for _ in range(max(1, READ_ATTEMPTS)):
        try:
            keys = _read_db_once(path)
        except _Unreadable as e:              # 內容壞掉：重試也一樣，不等
            err = e
            break
        except sqlite3.Error as e:
            err = e
            continue
        _write_cache(path, keys)
        return DisabledList(frozenset(keys), False, SOURCE_DB)
    cached, cache_path = _read_cache(path)
    if cached is not None:
        try:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(cache_path)))
        except OSError:
            when = "?"
        msg = "停用清單讀取失敗（%s），本次啟動沿用上次成功讀到的清單（%s）：%s" % (
            err, when, "、".join(cached) or "沒有停用任何模組")
        _log.error(msg)
        return DisabledList(frozenset(cached), False, SOURCE_CACHE, msg)
    msg = "停用清單讀取失敗（%s），也沒有上次的紀錄 ⇒ 所有模組暫不載入；排除原因後重啟服務" % (err,)
    _log.error(msg)
    return DisabledList(frozenset(), True, SOURCE_UNREADABLE, msg)


def read_disabled_at_startup(db_path: str = None) -> frozenset:
    """相容用（CORE 1.2 的介面）：回停用的 key 集合。讀不到而且沒有快取時，回 `modules/` 底下
    所有資料夾名（＝全部停用），不再回空集合。新程式用 `read_disabled_list()`。"""
    got = read_disabled_list(db_path)
    if not got.all_disabled:
        return got.keys
    from core import loader as _loader
    try:
        return frozenset(n for n in os.listdir(_loader.MODULES_DIR)
                         if os.path.isfile(os.path.join(_loader.MODULES_DIR, n, "module.json")))
    except OSError:
        return frozenset()


def configured_disabled() -> list:
    """目前設定值（可能與本次啟動實際生效的不同 ⇒ 待重啟）。"""
    from helpers.settings import _get_setting
    return _normalize(_get_setting(SETTING_KEY, []))


def set_enabled(key: str, enabled: bool) -> list:
    """寫入設定，回新的停用清單。重啟後生效。

    讀、改、寫在**同一個寫入交易**裡（`core.txn.write_txn`＝讀之前先 BEGIN IMMEDIATE）：兩位 superadmin
    同時切換不同模組時，後寫的不可以蓋掉先寫的（AUDIT-X-9c C-4／STATES P-SW-10）。第二個寫入者在拿鎖時等，
    拿到鎖時讀到的已經是第一個寫入者提交後的清單。"""
    from datetime import datetime
    from db import get_db
    from core.txn import write_txn
    conn = get_db()
    with write_txn(conn):                                  # 例外 ⇒ rollback＋close
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
        conn.commit()
    conn.close()
    # 快取跟著更新（交易提交之後）：否則「停用後重啟、剛好主庫被鎖」會沿用停用前的快取，
    # 把剛停用的模組又載入（P-SW-05）。
    _write_cache(_db_path(None), new)
    return new
