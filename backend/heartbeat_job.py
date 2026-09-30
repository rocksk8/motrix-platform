"""Independent heartbeat pinger: confirms local ERP is responding, then pings an
external dead-man's-switch service (e.g. healthchecks.io) so it can alert the
admin by email if this host stops checking in (host offline or app crashed).

Run standalone via Task Scheduler every few minutes — does not import the app,
so it still runs even if uvicorn/main:app is down.
"""
import json
import logging
import logging.handlers
import os
import urllib.request
from datetime import datetime

from core import paths as _paths  # 只取路徑常數，不載入 app

_CONFIG_PATH = _paths.HEARTBEAT_CONFIG
_LOG_PATH    = os.path.join(_paths.LOGS_DIR, "heartbeat_job.log")
_STATE_PATH  = os.path.join(_paths.LOGS_DIR, "heartbeat_state.json")
_LOCAL_PING  = "http://127.0.0.1:666/api/ping"
_TIMEOUT     = 10
LOG_MAX_BYTES = 5 * 1024 * 1024      # 單檔上限；加 backupCount 共 3 份（≤ 15MB）
LOG_BACKUPS   = 2

os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
# 2026-09-30 寫入量（使用者：「盡可能降低硬碟的重複寫入」）：log 加大小上限（5MB×3 代，總量 ≤ 20MB）；
# 正常時只在「狀態改變」或「每天第一筆」才記（原本每 5 分鐘 2 行、永不輪替）。
logging.basicConfig(
    handlers=[logging.handlers.RotatingFileHandler(_LOG_PATH, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")],
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def should_log(prev: dict, status: str, now: datetime) -> bool:
    """這一次要不要寫一筆「結果」log。狀態＝ok／local_down／ext_fail／ext_unset。
    - 狀態和上次不同 ⇒ 記（含從壞回好）
    - 正常（ok／ext_unset）：同一天只記第一筆
    - 壞的狀態（local_down／ext_fail）持續：每小時記一筆（不淹沒 log，也看得出還在壞）"""
    prev = prev or {}
    if prev.get("status") != status:
        return True
    if status in ("ok", "ext_unset"):
        return prev.get("day") != now.strftime("%Y-%m-%d")
    return prev.get("hour") != now.strftime("%Y-%m-%d %H")


def _load_state() -> dict:
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(status: str, now: datetime) -> None:
    try:
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"status": status, "day": now.strftime("%Y-%m-%d"), "hour": now.strftime("%Y-%m-%d %H")}, f)
    except Exception:
        logger.exception("failed to write heartbeat_state.json")


def _load_ping_url() -> str:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return (json.load(f).get("ping_url") or "").strip()
    except Exception:
        logger.exception("failed to read heartbeat_config.json")
        return ""


def _http_get(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        logger.warning("GET %s failed: %s", url, e)
        return False


def main() -> None:
    ping_url = _load_ping_url()
    now = datetime.now()
    prev = _load_state()

    local_ok = _http_get(_LOCAL_PING)
    if not local_ok:
        status = "local_down"
        if ping_url:
            _http_get(ping_url.rstrip("/") + "/fail")
        if should_log(prev, status, now):
            logger.error("本機 /api/ping 未回應，ERP 服務可能已停止")
            _save_state(status, now)
        return

    if not ping_url:
        status, msg, level = "ext_unset", "本機 /api/ping 正常；heartbeat_config.json ping_url 尚未設定，僅檢查本機服務，不對外打卡", logging.WARNING
    elif _http_get(ping_url):
        status, msg, level = "ok", "本機 /api/ping 正常；外部心跳打卡成功", logging.INFO
    else:
        status, msg, level = "ext_fail", "本機 /api/ping 正常；外部心跳打卡失敗（本機服務正常，可能是本機對外網路異常）", logging.WARNING
    if should_log(prev, status, now):
        logger.log(level, msg)
        _save_state(status, now)


if __name__ == "__main__":
    main()
