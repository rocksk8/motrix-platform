# -*- coding: utf-8 -*-
"""分錄引擎自動執行（L1，W2 寫入串接矩陣）：每小時在背景跑一輪「產生／更新分錄草稿」——**只有功能旗標 `engine_drafts` 開著才跑**
（關著時什麼都不做、不碰資料庫寫入）。引擎只產生**草稿**（過帳仍由會計走簽核），冪等；區間＝上個月 1 日～今天
（更早的已知事件由引擎的 `effective_range` 一併偵測）。每一輪的結果記在 `gl_settings`：
`engine.auto_last`（時間）、`engine.auto_result`（JSON：新增／變動／錯誤），總帳作業頁的橫幅讀它。
比照 `tender_radar.schedule_tender_scan`：排程立即返回、背景執行緒 Timer、工作包在 try、重排放 finally（不會因一次例外靜默死亡）。
"""
import datetime as _dt
import json
import logging
import threading

from db import get_db
from modules.accounting.ledger import engine as _engine
from modules.accounting.ledger import features as _features

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600
FIRST_DELAY_SECONDS = 300           # 啟動後 5 分鐘才第一輪（不與啟動健康檢查搶資源）
USER = "auto"


def default_window(today=None):
    today = today or _dt.date.today()
    first_this = today.replace(day=1)
    prev_last = first_this - _dt.timedelta(days=1)
    return prev_last.replace(day=1).isoformat(), today.isoformat()


def _put(conn, key, value):
    conn.execute("INSERT INTO gl_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def run_once(today=None):
    """跑一輪。旗標關 ⇒ `{"skipped": "off"}`（不寫任何東西）。例外不往外丟（記 log 與 `engine.auto_result`）。"""
    conn = get_db()
    try:
        if not _features.flags(conn).get("engine_drafts"):
            return {"skipped": "off"}
        s, e = default_window(today)
        now = _dt.datetime.now().isoformat(timespec="seconds")
        try:
            res = _engine.run(conn, s, e, USER)
            out = {"ok": True, "range": [s, e], "stats": res["stats"], "run_id": res["run_id"]}
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            logger.exception("分錄引擎自動執行失敗")
            out = {"ok": False, "range": [s, e], "error": "%s: %s" % (type(exc).__name__, str(exc)[:200])}
        _put(conn, "engine.auto_last", now)
        _put(conn, "engine.auto_result", json.dumps(out, ensure_ascii=False))
        conn.commit()
        return out
    finally:
        conn.close()


def schedule():
    """啟動時呼叫一次：立即返回；第一輪在背景執行緒（daemon Timer）跑。⚠️ `threading.Timer` 走模組屬性（測試才 patch 得到）。"""
    t = threading.Timer(FIRST_DELAY_SECONDS, _tick)
    t.daemon = True
    t.start()


def _tick():
    try:
        run_once()
    except Exception:  # noqa: BLE001
        logger.exception("engine auto run tick failed")
    finally:
        t = threading.Timer(INTERVAL_SECONDS, _tick)
        t.daemon = True
        t.start()


def status(conn):
    """給總帳作業頁橫幅：最近一次（手動或自動）執行、自動執行的結果、目前有多少來源變動待更新。唯讀。"""
    last = conn.execute("SELECT id, started_at, started_by, range_start, range_end, scanned, created, drift, blocked FROM gl_engine_runs ORDER BY id DESC LIMIT 1").fetchone()
    g = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM gl_settings WHERE key IN ('engine.auto_last','engine.auto_result')")}
    try:
        auto = json.loads(g.get("engine.auto_result") or "null")
    except ValueError:
        auto = None
    s, e = default_window()
    pend = _engine.pending_changes(conn, s, e)
    return {"last_run": dict(last) if last else None, "auto_last": g.get("engine.auto_last") or "", "auto_result": auto,
            "pending": {k: pend[k] for k in ("new", "changed", "gone", "total")}, "range": pend["range"]}
