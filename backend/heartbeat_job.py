"""Independent heartbeat pinger: confirms local ERP is responding, then pings an
external dead-man's-switch service (e.g. healthchecks.io) so it can alert the
admin by email if this host stops checking in (host offline or app crashed).

Run standalone via Task Scheduler every few minutes — does not import the app,
so it still runs even if uvicorn/main:app is down.

2026-11-11：本機檢查**兩種協定都試**（https 先，再 http）。伺服器用哪一種不是這支腳本決定的：
autostart.bat 每次重啟迴圈都依 certs/cert.pem／key.pem 在不在決定 `--ssl-*`，所以協定會跟著憑證檔變。
腳本寫死一種，就會在協定一變時**安靜地**全面誤報（2026-09-07 起兩個多月即是如此；healthchecks.io 因此一直紅燈、
真正的斷電反而沒有新告警）。狀態檔另外記 since／seen_at／scheme／local_ok_at／ext_ok_at，
給 app 的每日檢查與狀態快照看「監控本身有沒有在正常運作」（helpers/heartbeat_status.py）。
"""
import json
import logging
import logging.handlers
import os
import ssl
import urllib.parse
import urllib.request
from datetime import datetime

from core import paths as _paths  # 只取路徑常數，不載入 app

_CONFIG_PATH = _paths.HEARTBEAT_CONFIG
_LOG_PATH    = os.path.join(_paths.LOGS_DIR, "heartbeat_job.log")
_STATE_PATH  = os.path.join(_paths.LOGS_DIR, "heartbeat_state.json")
# 本機服務埠與檢查路徑。⚠️ 埠要與 autostart.bat／start.bat 的 `--port` 一致——
# tests/test_heartbeat_watch_2026_11_11.py 會讀那兩支批次檔比對，不一致就紅（防「兩邊各改各的」的安靜背離）。
_LOCAL_PORT  = 666
_LOCAL_PATH  = "/api/ping"
# 協定：https 先（正式機自 2026-09-07 起是 HTTPS），再 http（沒有憑證檔時 autostart.bat 會退回明文）。
_SCHEMES     = ("https", "http")
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
_TIMEOUT     = 10
_LOG_MAX_BYTES = 5 * 1024 * 1024      # 單檔上限；加 backupCount 共 3 份（≤ 15MB）
_LOG_BACKUPS   = 2

os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
# 2026-09-30 寫入量（使用者：「盡可能降低硬碟的重複寫入」）：log 加大小上限（5MB×3 代，總量 ≤ 20MB）；
# 正常時只在「狀態改變」或「每天第一筆」才記（原本每 5 分鐘 2 行、永不輪替）。
logging.basicConfig(
    handlers=[logging.handlers.RotatingFileHandler(_LOG_PATH, maxBytes=_LOG_MAX_BYTES, backupCount=_LOG_BACKUPS, encoding="utf-8")],
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _local_urls() -> list:
    return ["%s://127.0.0.1:%d%s" % (sc, _LOCAL_PORT, _LOCAL_PATH) for sc in _SCHEMES]


def _probe_local():
    """依序試每一種協定；回「第一個回 2xx 的協定」，全都不通 ⇒ None。"""
    for sc, url in zip(_SCHEMES, _local_urls()):
        if _http_get(url):
            return sc
    return None


def _should_log(prev: dict, status: str, now: datetime, scheme: str = None) -> bool:
    """這一次要不要寫一筆「結果」log。狀態＝ok／local_down／ext_fail／ext_unset。
    - 狀態和上次不同 ⇒ 記（含從壞回好）
    - 本機服務改用另一種協定（https⇄http；通常是憑證檔出現或消失）⇒ 記
    - 正常（ok／ext_unset）：同一天只記第一筆
    - 壞的狀態（local_down／ext_fail）持續：每小時記一筆（不淹沒 log，也看得出還在壞）"""
    prev = prev or {}
    if prev.get("status") != status:
        return True
    if scheme and prev.get("scheme") and prev["scheme"] != scheme:
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


def _save_state(status: str, now: datetime, prev: dict = None, scheme: str = None) -> None:
    """寫狀態檔（只在「該記 log」的那幾次寫：狀態改變／正常每天第一筆／壞的持續每小時一筆——寫入量不變）。
    欄位給 helpers/heartbeat_status.py 與 tools/prod_status_snapshot.py 讀：
      since 目前這個狀態從何時開始；seen_at 這份檔最後寫入時間（正常最多隔一天、壞的最多隔一小時）；
      scheme 本機服務目前講的協定；local_ok_at／ext_ok_at 本機／對外打卡最後一次成功（對外成功才算 ext）。"""
    prev = prev or {}
    iso = now.isoformat(timespec="seconds")
    since = prev.get("since") if (prev.get("status") == status and prev.get("since")) else iso
    local_ok = status in ("ok", "ext_unset", "ext_fail")
    try:
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"status": status, "day": now.strftime("%Y-%m-%d"), "hour": now.strftime("%Y-%m-%d %H"),
                       "since": since, "seen_at": iso, "scheme": scheme or "",
                       "local_ok_at": iso if local_ok else prev.get("local_ok_at", ""),
                       "ext_ok_at": iso if status == "ok" else prev.get("ext_ok_at", "")}, f)
    except Exception:
        logger.exception("failed to write heartbeat_state.json")


def _load_ping_url() -> str:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return (json.load(f).get("ping_url") or "").strip()
    except Exception:
        logger.exception("failed to read heartbeat_config.json")
        return ""


def _ssl_context_for(url: str):
    """只有「打本機 loopback 的 https」才略過憑證驗證（自簽憑證沒有受信任的 CA，
    同 backend/tools/_healthcheck_ping.py）。其他一律回 None＝urllib 預設驗證，
    所以對外打卡的 ping_url（healthchecks.io 等）仍照常驗憑證。"""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _http_get(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT, context=_ssl_context_for(url)) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        logger.warning("GET %s failed: %s", url, e)
        return False


def main() -> None:
    ping_url = _load_ping_url()
    now = datetime.now()
    prev = _load_state()

    scheme = _probe_local()
    if scheme is None:
        status = "local_down"
        if ping_url:
            _http_get(ping_url.rstrip("/") + "/fail")
        if _should_log(prev, status, now):
            logger.error("本機 /api/ping（%s 都試過）未回應，ERP 服務可能已停止", "／".join(_SCHEMES))
            _save_state(status, now, prev, "")
        return

    if not ping_url:
        status, msg, level = "ext_unset", "本機 /api/ping 正常（%s）；heartbeat_config.json ping_url 尚未設定，僅檢查本機服務，不對外打卡" % scheme, logging.WARNING
    elif _http_get(ping_url):
        status, msg, level = "ok", "本機 /api/ping 正常（%s）；外部心跳打卡成功" % scheme, logging.INFO
    else:
        status, msg, level = "ext_fail", "本機 /api/ping 正常（%s）；外部心跳打卡失敗（本機服務正常，可能是本機對外網路異常）" % scheme, logging.WARNING
    if _should_log(prev, status, now, scheme):
        logger.log(level, msg)
        _save_state(status, now, prev, scheme)


if __name__ == "__main__":
    main()
