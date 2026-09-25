# -*- coding: utf-8 -*-
"""L1 每日 08:00 檢查執行器（2026-09-26；取代 routers/daily_tasks.py::schedule_overdue_check）。

- 模組的檢查以提供者 `daily.check` 登記（多提供者、以名稱區分；INTEGRATION-POINTS IP-10）：
  `fn(mode)`，mode＝"startup"（啟動補跑）／"daily"（每天 08:00）。補跑要回溯幾天由各模組自己決定
  （每日任務的逾期檢查照舊用 `dt_overdue_last_check` 逐日補）。模組不在 ⇒ 少那一類檢查，其餘照常。
- 系統健康檢查（helpers/system_checks.py）一律執行，不依賴任何 L2 模組。
- 任一檢查丟例外只記錄，不中斷其他檢查；重排放在 finally（一次例外不可以讓排程從此不跑）。
"""
import logging
import threading
from datetime import datetime, timedelta

from core import registry
from helpers import system_checks

_logger = logging.getLogger(__name__)


def run_module_checks(mode: str) -> list:
    """回傳執行過的提供者名稱（依名稱排序）。"""
    ran = []
    for name, fn in sorted(registry.providers("daily.check").items()):
        try:
            fn(mode)
        except Exception:                     # noqa: BLE001
            _logger.exception("daily.check %s（%s）failed", name, mode)
        ran.append(name)
    return ran


def run_once(mode: str) -> list:
    ran = run_module_checks(mode)
    try:
        system_checks.run_all(prune=(mode == "daily"))
    except Exception:                         # noqa: BLE001
        _logger.exception("system_checks.run_all failed")
    return ran


def _next_08() -> float:
    now = datetime.now()
    t08 = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if t08 <= now:
        t08 += timedelta(days=1)
    return (t08 - now).total_seconds()


def schedule_daily_checks() -> None:
    """啟動時呼叫一次：背景補跑一次（startup），之後每天 08:00（daily）。"""
    threading.Thread(target=run_once, args=("startup",), daemon=True).start()

    def _loop():
        try:
            run_once("daily")
        finally:
            # 🔴 重排放在 finally：一次未捕捉的例外不可以讓排程從此不跑（形狀同原 daily_tasks）
            t = threading.Timer(_next_08(), _loop)
            t.daemon = True
            t.start()

    t = threading.Timer(_next_08(), _loop)
    t.daemon = True
    t.start()
