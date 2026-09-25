"""
MOTRIX ERP 獨立備份腳本

由 Windows 工作排程器每日 02:00 自動執行，與 ERP server 生命週期無關。
即使 server crash 或從未啟動，備份仍正常運行。

手動執行：
    cd backend
    python backup_job.py
"""
import logging
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

from core import paths as _paths  # noqa: E402（上一行 sys.path 之後才 import 得到）

_LOG_DIR = _paths.LOGS_DIR
os.makedirs(_LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(_LOG_DIR, "backup_job.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    logger.info("=== MOTRIX ERP backup_job 開始 ===")
    exit_code = 0
    try:
        from archive import _daily_backup, _weekly_backup
        _daily_backup()
        logger.info("每日備份完成")
    except Exception:
        logger.exception("每日備份失敗")
        exit_code = 1
    try:
        from archive import _weekly_backup
        _weekly_backup()
        logger.info("週備份完成")
    except Exception:
        logger.exception("週備份失敗")
        exit_code = 1
    logger.info("=== MOTRIX ERP backup_job 結束（exit=%d）===", exit_code)
    sys.exit(exit_code)
