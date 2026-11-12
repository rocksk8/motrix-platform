# -*- coding: utf-8 -*-
"""「備份與監控」專頁的資料與動作（2026-11-13；系統選單提案 v2 批次 4a）。

[單位] helper:backup_monitor    [層] L1    [穩定度] 實作
[公開介面] HEARTBEAT_TEST_MIN_INTERVAL_SECONDS, RUN_MIN_INTERVAL_SECONDS, BackupBusy, BackupRateLimited, HeartbeatRateLimited, InvalidPingUrl, ping_host, run_backup_now, scrub_paths, set_ping_url, status, test_heartbeat
[契約題] tests/test_backup_monitor_2026_11_13.py
[不變式]
  ① **狀態一頁看完，全部唯讀、全部取自既有來源**：備份的最近時間與結果＝稽核紀錄的 `backup.*`（`archive` 寫的）、硬碟＝`system_checks._disk_targets`、心跳＝`heartbeat_status.assess`、
     告警＝`archive` 的警示檔（`BACKUP_ALERT.txt`）與稽核的 `backup.alert*`、保留天數＝設定中心 `retention`。本單位**不另記任何備份狀態**（不新增表、不新增寫入）；
     唯一會寫的是三個動作（立即備份、設定心跳網址、測試心跳），各自見 ③④⑤。
  ② **畫面不出現伺服器路徑與心跳網址本身**：所有文字經 `scrub_paths`（磁碟代號路徑、UNC 路徑、含 `/` 的絕對路徑一律換成「（路徑已隱藏）」）；心跳網址等同密碼（healthchecks.io 的 ping 網址知道就能假報平安），
     只回「有沒有設」與主機名（`ping_host`）。
  ③ **立即備份**（`run_backup_now`）＝跑與排程完全相同的 `archive._daily_backup()`＋`_weekly_backup()`（排程本來就每 2 小時跑一次每日備份，所以手動多跑一次不會有新的風險）；背景執行緒、同時只准一個、
     兩次啟動至少隔 `RUN_MIN_INTERVAL_SECONDS`（30 分鐘；最後啟動時間存 `system_settings.backup_now_last`，重啟後仍有效）。結果存 `system_settings.backup_now_result`（只在手動按時寫，寫入量可忽略）。永不丟例外到背景。
  ④ **設定心跳網址**（`set_ping_url`）：只收 http／https、無空白、≤ 300 字、主機不能是本機或內網位址（心跳測試是伺服器端發出的請求，不給它打內網）；空字串＝停用對外打卡。
     寫 `heartbeat_config.json`（保留其他鍵、先寫暫存檔再 `os.replace`，Windows 被占用時重試）；心跳排程（獨立行程）下一輪就讀到新網址，不必重啟。**稽核只記主機名，不記完整網址。**
  ⑤ **測試心跳**（`test_heartbeat`）：對目前設定的網址發一次 GET（逾時 10 秒、驗憑證），兩次測試至少隔 `HEARTBEAT_TEST_MIN_INTERVAL_SECONDS`（60 秒，記憶體計時；重啟歸零）。回白話結果，不回網址、不回例外名稱。
     不寫狀態檔（心跳的狀態檔寫入頻率是刻意壓低的，見 `heartbeat_status` 不變式 ③）。
  ⑥ 權限在路由（最高管理者）；本檔不判斷身分。`status()` 永不丟例外：每一塊各自 try，壞掉的那塊回 `{"error": "…"}`，其他照給。
"""
import ipaddress
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from core import paths as _paths
from db import get_db

from .settings import _get_setting, _set_setting

logger = logging.getLogger(__name__)

#: 兩次「立即備份」至少間隔（秒）
RUN_MIN_INTERVAL_SECONDS = 1800
#: 兩次「測試心跳」至少間隔（秒）
HEARTBEAT_TEST_MIN_INTERVAL_SECONDS = 60
_PING_URL_MAX = 300
_PING_TIMEOUT = 10
_RECENT_ALERT_DAYS = 30
_RECENT_ALERT_LIMIT = 10

_LAST_KEY = "backup_now_last"
_RESULT_KEY = "backup_now_result"

_run_lock = threading.Lock()
_running = {"on": False}
_hb_lock = threading.Lock()
_hb_last = {"at": 0.0}
_cfg_lock = threading.Lock()


class BackupBusy(Exception):
    """已經有一次備份在跑。"""


class BackupRateLimited(Exception):
    """距離上次手動備份太近；`wait_seconds`＝還要等多久。"""

    def __init__(self, wait_seconds: int):
        super().__init__(wait_seconds)
        self.wait_seconds = int(wait_seconds)


class HeartbeatRateLimited(Exception):
    def __init__(self, wait_seconds: int):
        super().__init__(wait_seconds)
        self.wait_seconds = int(wait_seconds)


class InvalidPingUrl(ValueError):
    """網址不合格（訊息是給使用者看的白話）。"""


# ── 文字清理 ───────────────────────────────────────────────────────────────────

_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/][^\s，。；、）)」』]*|\\\\[^\s，。；、）)」』]+|(?<![\w.])/(?:[\w.\-]+/)+[\w.\-]*)")


def scrub_paths(text) -> str:
    """把文字裡的檔案路徑換成「（路徑已隱藏）」（不變式 ②）。"""
    return _PATH_RE.sub("（路徑已隱藏）", str(text or ""))


# ── 狀態 ──────────────────────────────────────────────────────────────────────

def _latest(rows: dict, actions) -> tuple:
    """`rows`＝{action: 最近時間 ISO}；回 `(時間, action)`，沒有 ⇒ `("", "")`。"""
    best = ("", "")
    for a in actions:
        at = rows.get(a) or ""
        if at and at > best[0]:
            best = (at, a)
    return best


def _hours_since(at: str, now: datetime):
    try:
        return (now - datetime.fromisoformat(at)).total_seconds() / 3600
    except Exception:  # noqa: BLE001
        return None


def _audit_latest_map(conn, actions) -> dict:
    ph = ",".join("?" * len(actions))
    return {r["action"]: r["at"] for r in conn.execute(
        "SELECT action, MAX(at) AS at FROM audit_log WHERE action IN (%s) GROUP BY action" % ph, list(actions)).fetchall()}


_BACKUP_ACTIONS = ("backup.sqlite_snapshot", "backup.sqlite_snapshot_same", "backup.snapshot_rejected",
                   "backup.daily_ok", "backup.daily_partial", "backup.weekly_ok", "backup.monthly_ok", "backup.monthly_partial",
                   "backup.uploads_mirror", "backup.pdf_archive_mirror", "backup.pii_archive_mirror")


def _cloud_expected() -> bool:
    try:
        import archive as _archive
        return bool(_archive.cloud_archive_enabled())
    except Exception:  # noqa: BLE001
        return True


def _backups_block(now: datetime, stale_hours: int, cloud_expected: bool) -> list:
    conn = get_db()
    try:
        m = _audit_latest_map(conn, _BACKUP_ACTIONS)
    finally:
        conn.close()
    out = []

    def row(key, label, ok_actions, partial_actions=(), fail_actions=(), cloud_only=False, check_stale=False, help_text=""):
        at, act = _latest(m, tuple(ok_actions) + tuple(partial_actions) + tuple(fail_actions))
        r = {"key": key, "label": label, "at": at, "result": "never", "level": "na", "note": "", "help": help_text}
        if cloud_only and not cloud_expected:
            r.update(result="skipped", level="na", note="這台機器不上傳雲端，不做這一種備份。")
            out.append(r)
            return
        if not at:
            r["note"] = "還沒有成功的紀錄。"
            r["level"] = "na"
        elif act in fail_actions:
            r.update(result="failed", level="error", note="最近一次沒有完成。")
        elif act in partial_actions:
            r.update(result="partial", level="warn", note="最近一次有部分資料沒有備份成功。")
        else:
            r.update(result="ok", level="ok")
        if check_stale and at and r["result"] in ("ok", "partial"):
            h = _hours_since(at, now)
            if h is not None and h > stale_hours:
                r.update(level="error", note="已經超過 %d 小時沒有新的備份。" % stale_hours)
        out.append(r)

    row("local", "本機備份（資料庫快照）", ("backup.sqlite_snapshot", "backup.sqlite_snapshot_same"), (), ("backup.snapshot_rejected",),
        check_stale=True, help_text="每天自動把整個資料庫複製一份存在這台電腦上，是最後的還原保險。")
    row("daily", "雲端每日備份", ("backup.daily_ok",), ("backup.daily_partial",), (), cloud_only=True, check_stale=True,
        help_text="每天把各種資料匯出成檔案，存到雲端硬碟；近期誤刪、誤改時用它還原。")
    row("weekly", "雲端每週備份", ("backup.weekly_ok",), cloud_only=True, help_text="每週一份報價單與客戶的匯出，中期還原點。")
    row("monthly", "雲端每月備份", ("backup.monthly_ok",), ("backup.monthly_partial",), cloud_only=True,
        help_text="每月一份長期保存的備份（預設永久保留），給法遵與歷史查詢用。")
    return out


def _mirrors_block(cloud_expected: bool) -> dict:
    out = {"enabled": cloud_expected, "backend": "", "backendLabel": "", "reachable": None, "mirrors": []}
    if not cloud_expected:
        out["note"] = "這台機器設定為不上傳雲端（例如開發用的電腦），所以沒有雲端鏡像。"
        return out
    try:
        import archive as _archive
        b = _archive._active_backend()
        out["backend"] = b
        out["backendLabel"] = "S3 雲端儲存" if b == "s3" else "雲端硬碟（本機掛載的磁碟機）"
        out["reachable"] = bool(_archive._archive_reachable())
    except Exception as exc:  # noqa: BLE001
        logger.warning("備份監控：讀雲端狀態失敗：%s", type(exc).__name__)
    conn = get_db()
    try:
        m = _audit_latest_map(conn, ("backup.uploads_mirror", "backup.pdf_archive_mirror", "backup.pii_archive_mirror"))
    finally:
        conn.close()
    for key, label in (("backup.uploads_mirror", "上傳檔案鏡像"), ("backup.pdf_archive_mirror", "PDF 存檔鏡像"), ("backup.pii_archive_mirror", "勞報單（個資）鏡像")):
        out["mirrors"].append({"label": label, "at": m.get(key) or ""})
    return out


def _disks_block(th: dict) -> list:
    import shutil
    from . import system_checks as sc
    out = []
    for label, path in sc._disk_targets():
        try:
            u = shutil.disk_usage(path)
        except Exception:  # noqa: BLE001
            out.append({"label": label, "level": "warn", "note": "讀不到這顆硬碟（可能沒有掛上）。", "freeGb": None, "totalGb": None, "freePct": None})
            continue
        free_gb = u.free / (1024 ** 3)
        free_pct = (u.free / u.total * 100) if u.total else 0.0
        level = "ok"
        if free_gb < th["disk_free_min_gb"] and free_pct < th["disk_free_min_pct"]:
            level = "error"
        elif free_gb < th["disk_free_min_gb"] * 2 and free_pct < th["disk_free_min_pct"] * 2:
            level = "warn"
        out.append({"label": label, "level": level, "freeGb": round(free_gb, 1), "totalGb": round(u.total / (1024 ** 3), 1),
                    "freePct": round(free_pct, 1), "note": ""})
    return out


def ping_host() -> str:
    """心跳網址的主機名（沒設 ⇒ 空字串）。網址本身永遠不回傳。"""
    try:
        with open(_paths.HEARTBEAT_CONFIG, "r", encoding="utf-8") as f:
            url = (json.load(f).get("ping_url") or "").strip()
        return (urllib.parse.urlsplit(url).hostname or "") if url else ""
    except Exception:  # noqa: BLE001
        return ""


def _heartbeat_block() -> dict:
    from . import heartbeat_status as hs
    a = hs.assess()
    # 不回 assess 的 summary／problems：那是給維運看的字串，含 ping_url、seen_at 等英文欄位名；畫面文字由前端依 status／level 組白話
    return {"level": a["level"], "status": a["status"], "seenAt": a["seen_at"], "localOkAt": a["local_ok_at"],
            "extOkAt": a["ext_ok_at"], "since": a["since"], "pingUrlSet": a["ping_url_set"], "pingHost": ping_host(),
            "configExists": hs.config_exists(),
            "testMinIntervalSeconds": HEARTBEAT_TEST_MIN_INTERVAL_SECONDS}


def _alerts_block(now: datetime) -> dict:
    out = {"current": None, "recent": []}
    try:
        import archive as _archive
        p = os.path.join(_paths.BACKUP_ALERT_DIR, "BACKUP_ALERT.txt")
        if os.path.exists(p):
            out["current"] = {"reason": scrub_paths(_archive._alert_reason(p)) or "（沒有說明）",
                              "at": datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds")}
    except Exception as exc:  # noqa: BLE001
        logger.warning("備份監控：讀警示檔失敗：%s", type(exc).__name__)
    cut = (now - timedelta(days=_RECENT_ALERT_DAYS)).isoformat(timespec="seconds")
    kinds = {"backup.alert": "alert", "backup.alert_email_failed": "email_failed", "backup.alert_cleared": "cleared"}
    conn = get_db()
    try:
        rows = conn.execute("SELECT at, action, target_label FROM audit_log WHERE action IN (?,?,?) AND at >= ? ORDER BY at DESC LIMIT ?",
                            (*kinds, cut, _RECENT_ALERT_LIMIT)).fetchall()
    finally:
        conn.close()
    for r in rows:
        out["recent"].append({"at": r["at"], "kind": kinds[r["action"]], "text": scrub_paths(r["target_label"])})
    return out


def _retention_block() -> dict:
    from . import settings_groups, settings_registry as sr     # noqa: F401
    keys = ("log_keep_days", "local_db_keep_days", "cloud_daily_keep_days", "cloud_weekly_keep_days", "cloud_monthly_keep_days")
    return {k: sr.get("retention", k) for k in keys}


def _manual_block() -> dict:
    last = _get_setting(_LAST_KEY, "") or ""
    res = _get_setting(_RESULT_KEY, {}) or {}
    wait = 0
    try:
        if last:
            wait = max(0, int(RUN_MIN_INTERVAL_SECONDS - (datetime.now() - datetime.fromisoformat(last)).total_seconds()))
    except Exception:  # noqa: BLE001
        wait = 0
    return {"running": bool(_running["on"]), "lastStartedAt": last, "waitSeconds": wait,
            "minIntervalSeconds": RUN_MIN_INTERVAL_SECONDS,
            "lastResult": {"finishedAt": str(res.get("finished") or ""), "ok": bool(res.get("ok")),
                           "message": scrub_paths(res.get("message") or "")} if isinstance(res, dict) and res else None}


def status(now: datetime = None) -> dict:
    """整頁的狀態（不變式 ①）。每一塊各自 try：壞掉的那塊回 `{"error": …}`，其他照給。永不丟例外。"""
    now = now or datetime.now()
    out = {"generatedAt": now.isoformat(timespec="seconds")}
    from . import system_checks as sc
    th = sc.alert_thresholds()
    out["thresholds"] = th
    cloud = _cloud_expected()

    def block(name, fn):
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning("備份監控：%s 讀取失敗：%s", name, type(exc).__name__)
            out[name] = {"error": "這一塊暫時讀不到（詳見系統日誌）。"}

    block("backups", lambda: _backups_block(now, th["backup_stale_hours"], cloud))
    block("cloud", lambda: _mirrors_block(cloud))
    block("disks", lambda: _disks_block(th))
    block("heartbeat", _heartbeat_block)
    block("alerts", lambda: _alerts_block(now))
    block("retention", _retention_block)
    block("manual", _manual_block)
    return out


# ── 動作：立即備份 ─────────────────────────────────────────────────────────────

def _run_job() -> None:
    started = datetime.now().isoformat(timespec="seconds")
    ok, message = True, "完成"
    try:
        import archive as _archive
        _archive._daily_backup()
        _archive._weekly_backup()
    except Exception as exc:  # noqa: BLE001
        ok, message = False, "備份沒有完成（%s），詳見系統日誌" % type(exc).__name__
        logger.exception("手動備份失敗")
    finally:
        try:
            _set_setting(_RESULT_KEY, {"started": started, "finished": datetime.now().isoformat(timespec="seconds"), "ok": ok, "message": message})
        except Exception:  # noqa: BLE001
            logger.exception("手動備份結果寫入失敗")
        _running["on"] = False


def run_backup_now(now: datetime = None) -> dict:
    """啟動一次手動備份（背景）。已在跑 ⇒ `BackupBusy`；距離上次太近 ⇒ `BackupRateLimited`。回 `{"started": ISO}`。"""
    now = now or datetime.now()
    with _run_lock:
        if _running["on"]:
            raise BackupBusy()
        last = _get_setting(_LAST_KEY, "") or ""
        try:
            if last:
                gap = (now - datetime.fromisoformat(last)).total_seconds()
                if 0 <= gap < RUN_MIN_INTERVAL_SECONDS:
                    raise BackupRateLimited(RUN_MIN_INTERVAL_SECONDS - gap)
        except (ValueError, TypeError):
            pass
        stamp = now.isoformat(timespec="seconds")
        _set_setting(_LAST_KEY, stamp)
        _running["on"] = True
    try:
        threading.Thread(target=_run_job, name="backup-now", daemon=True).start()
    except Exception:
        _running["on"] = False
        raise
    return {"started": stamp}


# ── 動作：心跳網址 ─────────────────────────────────────────────────────────────

def _validate_ping_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if len(url) > _PING_URL_MAX:
        raise InvalidPingUrl("網址太長了（最多 %d 個字）。請確認有沒有多貼了別的內容。" % _PING_URL_MAX)
    if re.search(r"\s", url) or any(ord(c) < 32 for c in url):
        raise InvalidPingUrl("網址裡不能有空白或換行，請重新複製。")
    sp = urllib.parse.urlsplit(url)
    if sp.scheme not in ("http", "https") or not sp.hostname:
        raise InvalidPingUrl("網址要以 https:// 開頭，例如 https://hc-ping.com/…（從 healthchecks.io 的 Ping URL 複製）。")
    host = sp.hostname.lower()
    blocked = host in ("localhost", "localhost.localdomain") or host.endswith((".local", ".internal", ".localdomain"))
    try:
        ip = ipaddress.ip_address(host)
        blocked = blocked or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    except ValueError:
        pass
    if blocked:
        raise InvalidPingUrl("這是本機或公司內網的位址，外部的監控服務連不到它。請貼監控服務給你的網址。")
    return url


def _write_config(url: str) -> None:
    path = _paths.HEARTBEAT_CONFIG
    with _cfg_lock:
        cfg = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            cfg = d if isinstance(d, dict) else {}
        except FileNotFoundError:
            pass
        except Exception:  # noqa: BLE001
            logger.warning("heartbeat_config.json 讀不懂，將以新內容覆寫（只保留 ping_url）")
        cfg["ping_url"] = url
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        last_exc = None
        for _ in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:      # 心跳排程剛好在讀 ⇒ 稍等再換
                last_exc = exc
                time.sleep(0.1)
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise last_exc


def set_ping_url(url: str) -> dict:
    """驗證並寫入心跳網址（空字串＝停用對外打卡）。不合格 ⇒ `InvalidPingUrl`。回 `{pingUrlSet, pingHost}`（不回網址）。"""
    clean = _validate_ping_url(url)
    _write_config(clean)
    return {"pingUrlSet": bool(clean), "pingHost": (urllib.parse.urlsplit(clean).hostname or "") if clean else ""}


# ── 動作：測試心跳 ─────────────────────────────────────────────────────────────

def _read_ping_url() -> str:
    try:
        with open(_paths.HEARTBEAT_CONFIG, "r", encoding="utf-8") as f:
            return (json.load(f).get("ping_url") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _ping(url: str) -> tuple:
    """對網址發一次 GET ⇒ `(ok, 白話訊息)`。"""
    try:
        with urllib.request.urlopen(url, timeout=_PING_TIMEOUT) as resp:
            if 200 <= resp.status < 300:
                return True, "監控服務有收到這次打卡。"
            return False, "監控服務回應了，但不是成功的結果。請確認網址有沒有貼完整。"
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            return False, "監控服務說找不到這個網址，請確認有沒有貼完整、或在監控服務裡是不是被刪除了。"
        if exc.code in (401, 403):
            return False, "監控服務拒絕了這次打卡，請確認網址是不是正確的 Ping URL。"
        if exc.code == 429:
            return False, "打得太頻繁，監控服務暫時拒絕了。請稍後再試。"
        return False, "監控服務回應了錯誤，請稍後再試；問題持續請檢查網址。"
    except Exception as exc:  # noqa: BLE001
        logger.warning("測試心跳失敗：%s", type(exc).__name__)
        return False, "這台電腦連不到監控服務。請確認網路可以連到外部，以及網址有沒有貼對。"


def test_heartbeat() -> dict:
    """對目前設定的心跳網址打一次卡（不變式 ⑤）。沒設 ⇒ `{"ok": False, "message": …}`；太頻繁 ⇒ `HeartbeatRateLimited`。"""
    with _hb_lock:
        wait = HEARTBEAT_TEST_MIN_INTERVAL_SECONDS - (time.monotonic() - _hb_last["at"])
        if _hb_last["at"] and wait > 0:
            raise HeartbeatRateLimited(wait)
        _hb_last["at"] = time.monotonic() or 1.0
    url = _read_ping_url()
    if not url:
        return {"ok": False, "message": "還沒有設定監控網址，請先貼上網址並儲存。"}
    ok, msg = _ping(url)
    return {"ok": ok, "message": msg}
