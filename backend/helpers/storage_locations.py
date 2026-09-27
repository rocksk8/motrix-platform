# -*- coding: utf-8 -*-
"""儲存位置：雲端存檔根目錄、個資資料夾、更新交付資料夾的**唯一**解析處（CORE-SPEC 裁示表「儲存位置可設定」，2026-09-28）。

[單位] helper:storage_locations    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] KINDS, LABELS, PII_DIRNAME, SETTING_KEY, Unreadable, configured, resolve, path, validate, create, status, invalidate, save
[不變式] 讀這三個位置的程式一律經 `resolve`／`path`（守門 tests/platform/test_storage_locations_2026_09_28.py 掃描）。
         有設定 ⇒ 用設定（不存在就回 ""，**不退回自動判斷**：寫到別的地方比寫不進去更糟）；留空 ⇒ 照原本的自動判斷：
           雲端存檔根目錄＝掃磁碟機找「我的雲端硬碟\\系統存檔」（archive._auto_archive_base）
           個資資料夾＝雲端存檔根目錄旁的「系統存檔_個資」
           更新交付資料夾＝未設定（"")
         **本檔永不自動建立資料夾**：只有 `create`（最高管理員在設定頁明確按「建立」）會建，而且只建最後一層。
[契約題] tests/platform/test_storage_locations_2026_09_28.py
[注意] 設定存在 system_settings `storage_locations`：{"archive_root": "...", "pii_root": "...", "delivery_root": "..."}，
       空字串＝自動。讀取有 30 秒快取（即時備份每一筆都會讀）；存檔後呼叫 `invalidate()`。
       **讀不到設定（庫被鎖、損毀）≠ 沒設定**（D 稽核 SL-M1）：不快取；resolve 三個位置都回 ""（source="unknown"），
       寫入端照「找不到」告警、不寫——不退回自動判斷（使用者設了別處時，自動位置可能是已經不用的舊資料夾）；
       configured() 丟 Unreadable（設定頁回 503，不讓人看到空值、按儲存把真正的設定蓋掉）。
"""
import os
import time
import uuid

SETTING_KEY = "storage_locations"
KINDS = ("archive_root", "pii_root", "delivery_root")
LABELS = {"archive_root": "雲端存檔根目錄", "pii_root": "個資資料夾", "delivery_root": "更新交付資料夾"}
PII_DIRNAME = "系統存檔_個資"
_CACHE_TTL = 30
_cache = {"value": None, "at": 0.0}


class Unreadable(Exception):
    """讀不到儲存位置設定（與「沒設定」不同）。"""


def invalidate():
    _cache["value"] = None
    _cache["at"] = 0.0
    _cache["db"] = None


def _db_key():
    import db
    return getattr(db, "DB_PATH", None)


def _read_main_db():
    """一律讀**主庫**（不經 get_db：demo 模式的請求會被導到 demo 庫，而儲存位置是這台機器的設定，與 demo 無關）。
    沒有這一列 ⇒ {}（＝全部自動）；**讀不到 ⇒ None**（未知，D 稽核 SL-M1；記 WARNING）。"""
    import json
    import logging
    import sqlite3
    import db
    if not os.path.isfile(db.DB_PATH):
        return {}                                               # 還沒有庫（全新安裝前）＝沒設定；不因讀取而建出空庫
    try:
        conn = sqlite3.connect(db.DB_PATH, timeout=30)
        try:
            row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (SETTING_KEY,)).fetchone()
        finally:
            conn.close()
        val = json.loads(row[0]) if row else {}
        return val if isinstance(val, dict) else None
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return {}                                           # 庫還沒初始化＝沒設定
        logging.getLogger(__name__).warning("讀不到儲存位置設定（未知，不退回自動判斷）", exc_info=True)
        return None
    except Exception:                                           # noqa: BLE001
        logging.getLogger(__name__).warning("讀不到儲存位置設定（未知，不退回自動判斷）", exc_info=True)
        return None


def save(values: dict) -> dict:
    """寫進**主庫**的 system_settings（與 helpers.settings._set_setting 同格式），並清快取。⇒ 存進去的值。"""
    import json
    import sqlite3
    from datetime import datetime
    import db
    val = {k: str((values or {}).get(k) or "").strip() for k in KINDS}
    conn = sqlite3.connect(db.DB_PATH, timeout=30)
    try:
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                     (SETTING_KEY, json.dumps(val, ensure_ascii=False), datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()
    invalidate()
    return val


def _load():
    """{kind: 路徑} 或 None（讀不到）。只快取讀到的結果：讀不到不快取，下一次再試。"""
    key = _db_key()
    if (_cache["value"] is not None and _cache.get("db") == key
            and time.monotonic() - _cache["at"] < _CACHE_TTL):
        return dict(_cache["value"])
    raw = _read_main_db()
    if raw is None:
        return None
    val = {k: str(raw.get(k) or "").strip() for k in KINDS}
    _cache["value"], _cache["at"], _cache["db"] = val, time.monotonic(), key
    return dict(val)


def configured() -> dict:
    """{kind: 設定的路徑（去頭尾空白；沒設＝""）}。快取以「哪一個庫」為鍵：換庫（測試夾具）不會讀到上一個庫的設定。
    讀不到 ⇒ 丟 Unreadable（不回空值：空值會被當成「全部自動」）。"""
    val = _load()
    if val is None:
        raise Unreadable("讀不到儲存位置設定（資料庫被鎖或無法讀取），請稍後再試")
    return val


def _auto_archive_root() -> str:
    import archive                                   # 延後 import：archive 也 import 本檔
    return archive._auto_archive_base()


def resolve(kind: str, values: dict = None) -> dict:
    """⇒ {"path": 路徑或 "", "source": "setting"｜"auto"｜"unset"}。
    values：用來試算「如果這樣設」的結果（設定頁儲存前的驗證）；None ⇒ 讀目前的設定。"""
    if kind not in KINDS:
        raise ValueError("不認得的儲存位置：%r" % kind)
    cfg = _load() if values is None else {k: str((values or {}).get(k) or "").strip() for k in KINDS}
    if cfg is None:
        return {"path": "", "source": "unknown"}               # SL-M1：讀不到 ≠ 沒設定，不退回自動判斷
    if cfg[kind]:
        if kind == "archive_root" and values is None and not os.path.isdir(cfg[kind]):
            return {"path": "", "source": "setting"}           # 設了但現在不存在 ⇒ 找不到（告警），不改寫別處
        return {"path": cfg[kind], "source": "setting"}
    if kind == "archive_root":
        p = _auto_archive_root()
        return {"path": p, "source": "auto" if p else "unset"}
    if kind == "pii_root":
        if values is None:
            # 目前生效的雲端存檔根目錄——經 archive._archive_base（模組屬性、呼叫當下查）：
            # 測試夾具把它換成 tmp 時，個資資料夾跟著落在 tmp 旁，不會掃到真實磁碟機（conftest 雲端隔離）
            import archive
            base = archive._archive_base()
        else:
            base = cfg["archive_root"] or _auto_archive_root()
        return {"path": os.path.join(os.path.dirname(base), PII_DIRNAME) if base else "", "source": "auto" if base else "unset"}
    return {"path": "", "source": "unset"}


def path(kind: str) -> str:
    return resolve(kind)["path"]


def _norm(p):
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def _contains(outer, inner):
    o, i = _norm(outer), _norm(inner)
    return i == o or i.startswith(o.rstrip(os.sep) + os.sep)


def _writable(p) -> bool:
    probe = os.path.join(p, ".motrix-write-test-%s" % uuid.uuid4().hex)
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def validate(values: dict) -> list:
    """設定頁儲存前的檢查 ⇒ [{kind, message}]（空＝可以存）。有填的：絕對路徑、存在、可寫；
    個資資料夾（含留空時自動算出的那一個）與雲端存檔根目錄、更新交付資料夾不可以互相包含或相同。"""
    problems = []
    vals = {k: str((values or {}).get(k) or "").strip() for k in KINDS}
    for k in KINDS:
        p = vals[k]
        if not p:
            continue
        if not os.path.isabs(p):
            problems.append({"kind": k, "message": "%s要填完整路徑（例：G:\\我的雲端硬碟\\…）" % LABELS[k]})
        elif not os.path.isdir(p):
            problems.append({"kind": k, "message": "%s不存在：%s（可以按「建立」，建立後請到雲端硬碟確認共用權限）" % (LABELS[k], p)})
        elif not _writable(p):
            problems.append({"kind": k, "message": "%s無法寫入：%s（請確認權限）" % (LABELS[k], p)})
    if problems:
        return problems
    pii = resolve("pii_root", vals)["path"]
    others = [("archive_root", vals["archive_root"] or resolve("archive_root", vals)["path"]),
              ("delivery_root", vals["delivery_root"])]
    if pii:
        for k, other in others:
            if other and (_contains(pii, other) or _contains(other, pii)):
                problems.append({"kind": "pii_root", "message": "個資資料夾不可以與%s互相包含或相同（%s ⇔ %s）"
                                 % (LABELS[k], pii, other)})
    return problems


def create(kind: str, target: str) -> str:
    """最高管理員明確建立：只建**最後一層**（上一層必須已存在），已存在就拒絕。⇒ 建好的絕對路徑。"""
    if kind not in KINDS:
        raise ValueError("不認得的儲存位置：%r" % kind)
    t = str(target or "").strip()
    if not t or not os.path.isabs(t):
        raise ValueError("%s要填完整路徑" % LABELS[kind])
    if os.path.exists(t):
        raise ValueError("%s已經存在：%s" % (LABELS[kind], t))
    parent = os.path.dirname(os.path.normpath(t))
    if not os.path.isdir(parent):
        raise ValueError("上一層資料夾不存在：%s（只建最後一層，避免在錯的地方建出一整串）" % parent)
    os.mkdir(t)
    return t


def status() -> dict:
    """設定頁顯示用：{kind: {configured, path, source, exists}}（不做寫入測試：只在儲存時測）。"""
    cfg = _load()
    if cfg is None:
        return {k: {"label": LABELS[k], "configured": "", "path": "", "source": "unknown", "exists": False}
                for k in KINDS}
    out = {}
    for k in KINDS:
        r = resolve(k)
        shown = r["path"] or cfg[k]
        out[k] = {"label": LABELS[k], "configured": cfg[k], "path": shown, "source": r["source"],
                  "exists": bool(shown) and os.path.isdir(shown)}
    return out
