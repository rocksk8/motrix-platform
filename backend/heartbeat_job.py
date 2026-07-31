"""Independent heartbeat pinger: confirms local ERP is responding, then pings an
external dead-man's-switch service (e.g. healthchecks.io) so it can alert the
admin by email if this host stops checking in (host offline or app crashed).

Run standalone via Task Scheduler every few minutes — does not import the app,
so it still runs even if uvicorn/main:app is down.
"""
import json
import logging
import os
import urllib.request

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_BACKEND_DIR, "heartbeat_config.json")
_LOG_PATH    = os.path.join(_BACKEND_DIR, "logs", "heartbeat_job.log")
_LOCAL_PING  = "http://127.0.0.1:666/api/ping"
_TIMEOUT     = 10

os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
logging.basicConfig(
    filename=_LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger(__name__)


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
    if not ping_url:
        logger.warning("heartbeat_config.json ping_url 尚未設定，僅檢查本機服務，不對外打卡")

    local_ok = _http_get(_LOCAL_PING)
    if not local_ok:
        logger.error("本機 /api/ping 未回應，ERP 服務可能已停止")
        if ping_url:
            _http_get(ping_url.rstrip("/") + "/fail")
        return

    logger.info("本機 /api/ping 正常")
    if ping_url:
        if _http_get(ping_url):
            logger.info("外部心跳打卡成功")
        else:
            logger.warning("外部心跳打卡失敗（本機服務正常，可能是本機對外網路異常）")


if __name__ == "__main__":
    main()
