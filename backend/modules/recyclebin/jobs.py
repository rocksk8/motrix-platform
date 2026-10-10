# -*- coding: utf-8 -*-
"""每日工作：孤兒隔離檔搬回、清除超過 30 天的暫存區項目（逐筆稽核）、磁碟水位告警。

形狀照 lodging／標案雷達：啟動時只排一個背景 Timer（立即返回），每小時檢查一次『今天跑過沒』；跑完一定重排（`finally`），丟一次例外不會讓排程靜默死亡。
清除只在 `schedulers` 閘門開著時排（MOTRIX_DISABLE_SCHEDULERS=1 ⇒ 不排）；`run_daily()` 可被測試／手動直接呼叫。
稽核：`recyclebin.purge_auto`（每筆一列，操作者＝系統）、`recyclebin.reconcile`、`recyclebin.disk_warn`。通知：有清除或水位超標 ⇒ 通知所有最高管理者（每天最多一則）。
"""
import logging
import threading
from datetime import datetime

from db import get_db
from helpers import _audit
from helpers.audit import _notify
from modules.recyclebin import service as S

logger = logging.getLogger(__name__)

SETTING_LAST_RUN = "recyclebin_last_run"
RUN_HOUR = 3                                  # 凌晨 3 點之後第一個檢查週期跑
_FIRST_DELAY_SECONDS = 180
_CHECK_SECONDS = 3600


def _last_run():
    from helpers.settings import _get_setting
    return _get_setting(SETTING_LAST_RUN, "") or ""


def _mark_run(day: str):
    from helpers.settings import _set_setting
    _set_setting(SETTING_LAST_RUN, day)


def run_daily(now=None) -> dict:
    """做一輪。回 `{"reconciled": n, "purged": n, "failed": n, "overWarn": bool}`。個別筆失敗只記 log、不中斷。"""
    now = now or datetime.now()
    out = {"reconciled": 0, "purged": 0, "failed": 0, "overWarn": False}
    conn = get_db()
    try:
        out["reconciled"] = S.reconcile(conn)
        if out["reconciled"]:
            _audit("", "recyclebin.reconcile", "recycle_bin", "", "孤兒隔離檔搬回", {"folders": out["reconciled"]})
        for bin_id in S.due_ids(conn, now.date().isoformat()):
            try:
                r = S._row(conn, bin_id)
                label = "%s %s" % (r["entity_type"], r["entity_id"])
                S.purge(conn, bin_id, by="system")
                _audit("", "recyclebin.purge_auto", "recycle_bin", str(bin_id), label,
                       {"entity_type": r["entity_type"], "entity_id": r["entity_id"], "deleted_at": r["deleted_at"], "purge_after": r["purge_after"]})
                out["purged"] += 1
            except Exception as e:                               # noqa: BLE001
                out["failed"] += 1
                logger.exception("recyclebin purge #%s failed", bin_id)
                _audit("", "recyclebin.purge_failed", "recycle_bin", str(bin_id), str(e)[:200], {"error": str(e)[:500]})
        st = S.status(conn)
        out["overWarn"] = bool(st["overWarn"])
        if out["overWarn"]:
            _audit("", "recyclebin.disk_warn", "recycle_bin", "", "暫存區磁碟用量超標", {"usedBytes": st["usedBytes"], "warnBytes": st["warnBytes"]})
        if out["purged"] or out["overWarn"]:
            msg = []
            if out["purged"]:
                msg.append("已自動清除 %d 筆超過 %d 天的刪除項目" % (out["purged"], S.RB.RETENTION_DAYS))
            if out["overWarn"]:
                msg.append("隔離區用量 %.1f GB 已超過 %.0f GB" % (st["usedBytes"] / 1024 ** 3, st["warnBytes"] / 1024 ** 3))
            for u in S.superadmins(conn):
                _notify(u, "recyclebin_daily", now.date().isoformat(), "刪除暫存區", "；".join(msg), "recycle-bin.html")
    finally:
        conn.close()
    return out


def tick(now=None) -> bool:
    """今天還沒跑、且已過 RUN_HOUR ⇒ 跑一輪。回有沒有跑。"""
    now = now or datetime.now()
    day = now.date().isoformat()
    if now.hour < RUN_HOUR or _last_run() == day:
        return False
    run_daily(now)
    _mark_run(day)
    return True


def _loop():
    try:
        tick()
    except Exception:                                            # noqa: BLE001
        logger.exception("recyclebin daily job failed")
    finally:
        t = threading.Timer(_CHECK_SECONDS, _loop)
        t.daemon = True
        t.start()


def schedule_daily():
    """啟動時呼叫一次：立即返回；背景 daemon Timer 之後每小時檢查一次。⚠️ `threading.Timer` 走模組屬性，monkeypatch 才打得到。"""
    t = threading.Timer(_FIRST_DELAY_SECONDS, _loop)
    t.daemon = True
    t.start()
