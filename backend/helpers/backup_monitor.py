# -*- coding: utf-8 -*-
"""「備份與監控」專頁的資料與動作（2026-11-13；系統選單提案 v2 批次 4a）。

[單位] helper:backup_monitor    [層] L1    [穩定度] 實作
[公開介面] BackupLockProblem, DisableError, HEARTBEAT_TEST_MIN_INTERVAL_SECONDS, InvalidPingUrl, BackupBusy, BackupRateLimited, HeartbeatRateLimited, MSG_ALREADY_DONE, MSG_BUSY,
    RUN_MIN_INTERVAL_SECONDS, approve_disable, cancel_disable, pending_disable, ping_host, reject_disable, request_disable, run_backup_now, scrub_paths, set_ping_url, status, test_heartbeat
[契約題] tests/test_backup_monitor_2026_11_13.py
[不變式]
  ① **狀態一頁看完，全部唯讀、全部取自既有來源**：備份的最近時間與結果＝稽核紀錄的 `backup.*`（`archive` 寫的）、硬碟＝`system_checks._disk_targets`、心跳＝`heartbeat_status.assess`、
     告警＝`archive` 的警示檔（`BACKUP_ALERT.txt`）與稽核的 `backup.alert*`、保留天數＝設定中心 `retention`。本單位**不另記任何備份狀態**（不新增表、不新增寫入）；
     會寫的只有幾個動作（立即備份、設定／停用心跳網址、測試心跳），見 ③～⑧。
  ② **畫面不出現伺服器路徑與心跳網址本身**：所有文字經 `scrub_paths`（磁碟代號路徑、UNC、含反斜線的相對路徑、`/` 開頭的絕對路徑含單段、`a/b/c`；路徑中間有空白或中文也**整段遮到句尾**，
     寧可多遮）；心跳網址等同密碼（healthchecks.io 的 ping 網址知道就能假報平安），只回「有沒有設」與主機名（`ping_host`）。log 與信件也只有主機名。
  ③ **立即備份**（`run_backup_now`）＝跑與排程完全相同的 `archive._daily_backup()`＋`_weekly_backup()`；背景執行緒、兩次啟動至少隔 `RUN_MIN_INTERVAL_SECONDS`（30 分鐘；最後啟動時間存
     `system_settings.backup_now_last`，**只在背景執行緒真的啟動後才寫**，重啟後仍有效；時鐘往回撥也照樣擋）。結果存 `system_settings.backup_now_result`。永不丟例外到背景。
     今天的每日備份已完成 ⇒ 結果訊息寫 `MSG_ALREADY_DONE`（不是含糊的「完成」）。
  ④ **設定心跳網址**（`set_ping_url`）：只收 http／https、≤ 300 字、無空白／帳密、連接埠只能 80／443、主機不能是本機／內網／單標籤名／舊式數字位址，且**解析後每個位址都必須是公開位址**
     （`core.safe_ping`；解析網域算在整體時限內，最多 5 秒）。寫 `heartbeat_config.json`（保留其他鍵、先寫暫存檔再 `os.replace`）。**換網址一定寄信給所有最高管理者並留稽核（舊→新主機名，不含完整網址）。**
     **換成「另一個主機」＝等於關掉原本的監控，比照 ⑧：必填原因；有其他最高管理者 ⇒ 待核准（新網址只放旁邊的 `heartbeat_config.json.pending`，不進資料庫／稽核／信／畫面，核准後才寫入設定檔）；
     只有一位 ⇒ 立即＋寄信。第一次設定（原本空白）與同主機只換路徑 ⇒ 立即＋寄信。**輸入先截到 2000 字再遮路徑（`scrub_paths` 線性時間，lookbehind 含 `-`）。
  ⑤ **測試心跳**（`test_heartbeat`／`_ping`）：走 `core.safe_ping.get`——**不跟隨轉址**（3xx＝失敗並白話說明）、連線釘在檢查過的 IP（防 DNS rebinding）、整體 15 秒。兩次測試至少隔 60 秒（記憶體計時）。
     回白話結果，不回網址、不回例外名稱；不寫狀態檔。
  ⑥ 權限在路由（最高管理者）；本檔不判斷身分。`status()` 永不丟例外：每一塊各自 try，壞掉的那塊回 `{"error": "…"}`，其他照給。
  ⑦ **備份互斥**：立即備份在 `archive.backup_run_lock()` 之內跑，與每 2 小時的 `_daily_tick`、排程的 `backup_job.py` 同一時間只准一個（跨行程檔案鎖，行程死掉鎖自動放掉）；
     拿不到鎖 ⇒ `BackupBusy`（「已有備份在進行中」）。**鎖檔打不開**：手動備份**拒絕**（`BackupLockProblem`，白話說明可能是已有備份在跑或資料夾權限問題，路由回 503，不寫「最後啟動」時間）；
     排程備份照跑（不能因此整天沒備份），但記 ERROR 並寫系統告警（每個行程一次），**不安靜降級**。
  ⑧ **停用對外打卡**（`request_disable`／`approve_disable`／`cancel_disable`）：必填原因；只有一位在職最高管理者 ⇒ 立即停用＋寄信；有其他最高管理者 ⇒ 建立待核准申請
     （`config_ledger`，domain `monitor:heartbeat`，要另一位最高管理者核准，申請人不能核准自己的），核准後才寫設定檔。設了新網址（立即生效的那種）會讓待核准的停用／換主機申請作廢；新的申請也會取代舊的；撤回或作廢時一併刪掉 `.pending` 暫存檔。**撤回只有申請人能做**（留稽核）；**其他最高管理者可「駁回」**（`reject_disable`：必填原因、留稽核、寄信；在 ledger 裡記成帶「駁回：」前綴的 cancelled 事件，不動資料表）——申請人離職或長期不在時，這筆不會永遠掛著；畫面對申請人顯示「等待 ○○ 核准（已送出 N 小時）」與提示。
"""
import json
import logging
import os
import re
import threading
import time
import urllib.parse
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


class BackupLockProblem(Exception):
    """備份鎖檔打不開（資料夾權限？），無法確認有沒有另一個備份在跑 ⇒ 手動備份不執行（審查 N4）。"""

    MESSAGE = ("現在無法確認是否已經有備份在進行（備份的鎖檔無法開啟，可能是資料夾權限問題，也可能有另一個備份正在進行）。"
               "為了避免兩份備份同時寫入，這次不執行。請稍後再試；問題持續請聯絡維運檢查資料夾權限。")


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

_MASK = "（路徑已隱藏）"
# 路徑可能含空白（`C:\Users\Jane Doe\Google Drive\…`、`G:\我的雲端硬碟\…`），所以無法用「碰到空白就結束」判斷尾端：
# 磁碟代號／UNC／含反斜線的相對路徑一律**吃到句子結尾**（換行、全形標點、引號、`: `／`; `／`, `／`. ` 之前）。寧可多遮一點字，也不洩漏路徑的後半段。
_TAIL = r"[^，。；、）」』\"'<>|\r\n\t]*?(?=[:;,.]\s|[，。；、）」』\"'<>|\r\n\t]|$)"
_PATH_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]" + _TAIL +                                  # C:\x\y z、C:/x/y
    r"|\\\\[^\\\s]" + _TAIL +                                         # \\server\share\x y
    r"|(?<![\w.~\\/:\-])[\w.~\-]+\\" + _TAIL +                        # backend\db_backups\a.db（相對、反斜線）
    r"|(?<![\w.:/\\])/(?=[\w.~\-])[^\s，。；、）)」』\"'<>|]+"          # /data、/home/x/y（單段也算）
    r"|(?<![\w.~:/\\\-])[A-Za-z0-9_.~\-]+(?:/[A-Za-z0-9_.\-]+){2,}"    # a/b/c、../x/y、~/x/y/z（至少兩個斜線）
    r"|(?<![\w.~:/\\\-])[A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-]+)*/[A-Za-z0-9_\-]+\.[A-Za-z0-9]{1,8}(?![\w/])"  # data/a.db（一層斜線但結尾是檔名）
    r")")
#: 輸入上限：例外文字可能很長（審查 N1：一長串破折號曾讓這個函式跑到 O(n²)）；畫面上本來就不會顯示更長的內容
_SCRUB_MAX = 2000
_DATE_LIKE = re.compile(r"^[\d./\-]+$")


def _mask(m):
    return m.group(0) if _DATE_LIKE.match(m.group(0)) else _MASK


def scrub_paths(text) -> str:
    """把文字裡的檔案路徑換成「（路徑已隱藏）」（不變式 ②）：磁碟代號、UNC、含反斜線的相對路徑、`/` 開頭的絕對路徑（單段也算）、
    兩層以上的 `a/b/c` 相對路徑、`data/a.db` 這種「資料夾/檔名」；路徑中間有空白、中文也整段遮。純日期（`2026/11/13`）不遮。"""
    return _PATH_RE.sub(_mask, str(text or "")[:_SCRUB_MAX])


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
            r["note"] = "尚無成功紀錄。"
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
        check_stale=True, help_text="每日自動將整個資料庫複製一份，存放於本機，作為最後的還原備援。")
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
    wait = _wait_after(last, datetime.now())
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

#: 「今天已經備份過」時給使用者的白話（`_daily_backup` 見到今天的完成記號會早退；本機快照與鏡像仍照常檢查，只是不重做 JSON 匯出）
MSG_ALREADY_DONE = "今天的雲端每日備份已經完成，沒有重做（本機快照與鏡像已照常檢查一次）。"
MSG_BUSY = "已有備份在進行中，請等它完成。"


def _wait_after(last: str, now: datetime) -> int:
    """距離上次手動備份還要等幾秒（0＝可以做）。**時鐘往回撥（`last` 在未來）也要擋**：只擋 `gap < 0` 以外會讓「改時鐘就能連按」；
    但最多只認 1 天內的倒退，更久的視為時鐘被重設、記錄無效（否則備份鈕會被未來的時間戳卡死）。"""
    if not last:
        return 0
    try:
        gap = (now - datetime.fromisoformat(last)).total_seconds()
    except (ValueError, TypeError):
        return 0
    if gap < -86400:
        return 0
    return max(0, int(RUN_MIN_INTERVAL_SECONDS - gap)) if gap >= 0 else int(RUN_MIN_INTERVAL_SECONDS - gap)


def _daily_already_done() -> bool:
    try:
        import archive as _archive
        today = datetime.now().date().isoformat()
        return bool(_archive._archive_ok() and _archive._cloud_marker_exists(
            os.path.join(_archive._daily_dir(), today, ".done"), "每日備份/%s/.done" % today))
    except Exception:  # noqa: BLE001
        return False


def _run_job(lock=None) -> None:
    """背景執行緒本體。`lock`＝`archive.backup_run_lock()` 已進入的鎖（由啟動端取得、這裡負責放掉）。"""
    started = datetime.now().isoformat(timespec="seconds")
    ok, message = True, "完成"
    try:
        import archive as _archive
        already = _daily_already_done()
        _archive._daily_backup()
        _archive._weekly_backup()
        if already:
            message = MSG_ALREADY_DONE
    except Exception as exc:  # noqa: BLE001
        ok, message = False, "備份沒有完成（%s），詳見系統日誌" % type(exc).__name__
        logger.exception("手動備份失敗")
    finally:
        try:
            _set_setting(_RESULT_KEY, {"started": started, "finished": datetime.now().isoformat(timespec="seconds"), "ok": ok, "message": message})
        except Exception:  # noqa: BLE001
            logger.exception("手動備份結果寫入失敗")
        _running["on"] = False
        if lock is not None:
            try:
                lock.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                logger.exception("備份鎖放不掉")


def run_backup_now(now: datetime = None) -> dict:
    """啟動一次手動備份（背景）。已在跑（同行程、或另一個行程如排程的 `backup_job.py`）⇒ `BackupBusy`；距離上次太近 ⇒ `BackupRateLimited`。
    回 `{"started": ISO}`。**30 分鐘限制的時間戳只在背景執行緒真的啟動之後才寫**（啟動失敗不會白白鎖住使用者 30 分鐘）。
    備份本體在 `archive.backup_run_lock()` 之內跑（與 `_daily_tick`／`backup_job.py` 互斥，不變式 ⑦）。"""
    import archive as _archive
    now = now or datetime.now()
    with _run_lock:
        if _running["on"]:
            raise BackupBusy()
        wait = _wait_after(_get_setting(_LAST_KEY, "") or "", now)
        if wait > 0:
            raise BackupRateLimited(wait)
        lock = _archive.backup_run_lock(strict=True)
        try:
            lock.__enter__()
        except _archive.BackupInProgress:
            raise BackupBusy() from None
        except _archive.BackupLockUnavailable:
            raise BackupLockProblem() from None
        _running["on"] = True
        stamp = now.isoformat(timespec="seconds")
        try:
            threading.Thread(target=_run_job, args=(lock,), name="backup-now", daemon=True).start()
        except BaseException:
            _running["on"] = False
            lock.__exit__(None, None, None)
            raise
        try:
            _set_setting(_LAST_KEY, stamp)
        except Exception:  # noqa: BLE001 — 備份已經開始；時間戳寫不進去只是少了一次 30 分鐘限制，不回 500
            logger.exception("手動備份時間戳寫入失敗")
    return {"started": stamp}


# ── 動作：心跳網址 ─────────────────────────────────────────────────────────────

def _validate_ping_url(url: str, *, resolve: bool = True) -> str:
    """驗證心跳網址並回乾淨的網址；空字串 ⇒ 回 ""（呼叫端另行處理「停用」）。
    字串規則見 `core.safe_ping.check_url`；`resolve=True` 時再**解析主機名**，只要有任何一個位址不是公開位址就拒絕（M1）。
    DNS 暫時解析不到不擋（離線機器也要能存），真正連線前（測試心跳、心跳排程）會再檢查一次，且連線釘在檢查過的 IP。"""
    from core import safe_ping
    url = (url or "").strip()
    if not url:
        return ""
    if len(url) > _PING_URL_MAX:
        raise InvalidPingUrl("網址太長了（最多 %d 個字）。請確認是否有多貼了別的內容。" % _PING_URL_MAX)
    if re.search(r"\s", url) or any(ord(c) < 32 for c in url):
        raise InvalidPingUrl("網址裡不能有空白或換行，請重新複製。")
    try:
        _scheme, host, port = safe_ping.check_url(url)
        if resolve:
            try:
                safe_ping.public_addresses(host, port)
            except safe_ping.UnsafeTarget:
                raise
            except safe_ping.PingFailed:
                pass
    except safe_ping.UnsafeTarget as exc:
        raise InvalidPingUrl(exc.reason) from None
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


def _host_of(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "") if url else ""
    except ValueError:
        return ""


def _display(actor) -> str:
    if isinstance(actor, dict):
        return actor.get("display_name") or actor.get("username") or "某位最高管理者"
    return str(actor or "某位最高管理者")


def _username(actor) -> str:
    return (actor.get("username") or "") if isinstance(actor, dict) else str(actor or "")


def _notify_superadmins(title: str, rows: list, reason: str) -> bool:
    """寄信給所有最高管理者（不論本人）。寄信失敗不影響動作本身，只記 WARNING；回有沒有排入寄送。"""
    try:
        from . import email_notify as _en
        return bool(_en.send_registered("heartbeat_stale", title=title, rows=rows, to_group=True, reason=reason,
                                        badge_text="安全通知", badge_color="#DC2626",
                                        note="對外心跳監控的設定被變更了。如果這不是最高管理者自己做的，請立刻到「系統 → 備份與監控」頁確認，並更換監控網址。"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("心跳設定變更通知信寄送失敗：%s", type(exc).__name__)
        return False


_MON_DOMAIN = "monitor:heartbeat"
_FIELD_DISABLE = "external_ping"
_FIELD_CHANGE = "external_ping_host"
_MON_FIELDS = (_FIELD_DISABLE, _FIELD_CHANGE)
_REASON_MIN = 2
_REASON_MAX = 300


class DisableError(ValueError):
    """停用／換監控服務的申請不能做（訊息是給使用者看的白話）。"""


def _pending_file() -> str:
    """待核准的新網址暫存檔（與 `heartbeat_config.json` 同資料夾、同樣的保護）。**網址不進資料庫**（資料庫備份會被複製到雲端硬碟，ledger 又會在畫面上列出內容）；
    ledger 只記舊／新主機名。"""
    return _paths.HEARTBEAT_CONFIG + ".pending"


def _read_pending_url() -> str:
    try:
        with open(_pending_file(), "r", encoding="utf-8") as f:
            return (json.load(f).get("ping_url") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _clear_pending_file() -> None:
    try:
        os.remove(_pending_file())
    except OSError:
        pass


def _clean_reason(reason) -> str:
    r = (reason or "").strip() if isinstance(reason, str) else ""
    if len(r) < _REASON_MIN:
        raise DisableError("請寫下原因（至少兩個字），會留在紀錄裡並通知所有最高管理者。")
    if len(r) > _REASON_MAX:
        raise DisableError("原因太長了（最多 %d 個字）。" % _REASON_MAX)
    return r


def _begin(conn):
    from core.txn import begin_write
    return begin_write(conn)


def _other_superadmins(conn, username: str) -> int:
    """除了 `username` 以外、在職的**真人**最高管理者人數（展示帳號 demo 不算：把它算進去，只有一位真人時申請會等一個永遠不會來的核准）。"""
    from . import config_ledger as L
    return len(L.real_superadmins(conn, username))


def _refuse_demo(actor) -> None:
    """展示帳號不是真人，不能核准／駁回任何申請（它的請求平常走隔離的展示庫，到不了這裡；這是第二道）。"""
    from . import config_ledger as L
    if _username(actor) == L.DEMO_USERNAME:
        raise DisableError("展示帳號不能核准或駁回申請。")


def _hours_waiting(at) -> int:
    """申請送出後過了幾個整小時（讀不懂時間 ⇒ 0）。"""
    try:
        return max(0, int((datetime.now() - datetime.fromisoformat(str(at))).total_seconds() // 3600))
    except (TypeError, ValueError):
        return 0


def _approver_names(requester: str) -> list:
    """可以核准的人（在職的其他最高管理者）的顯示名稱；畫面只有最高管理者看得到。"""
    from . import config_ledger as L
    conn = get_db()
    try:
        names = L.real_superadmins(conn, requester)            # 真人、在職、不含申請人與展示帳號
        by = {r["username"]: r["display_name"] for r in conn.execute("SELECT username, display_name FROM users WHERE active=1 AND role='superadmin'").fetchall()}
    finally:
        conn.close()
    return [(by.get(u) or u) for u in sorted(names)]


def _pending_rows(conn) -> list:
    from . import config_ledger as L
    return [r for r in L.pending(conn, _MON_DOMAIN) if r["field"] in _MON_FIELDS]


def _mail_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def set_ping_url(url: str, actor=None, reason: str = "", ip: str = "") -> dict:
    """驗證並設定心跳網址。**空字串不在這裡處理**（停用走 `request_disable`）。不合格 ⇒ `InvalidPingUrl`。
    - 第一次設定（原本沒有）、或只換同一個主機上的路徑／檢查碼 ⇒ **立即生效**，寄信給所有最高管理者＋稽核（只寫主機名）。
    - **換成另一個主機**（等於把外部監控換給別人；指向任何永遠回 200 的主機就等於關掉監控，審查 N2）⇒ 必填原因；
      有其他在職最高管理者 ⇒ **待另一位核准**（新網址暫存在 `heartbeat_config.json.pending`，核准後才寫入設定）；只有一位 ⇒ 立即生效＋寄信。
    回 `{pingUrlSet, pingHost, changed, pending, id?, oldHost, newHost, mailed}`（不回網址）。"""
    from . import config_ledger as L
    clean = _validate_ping_url(url)
    if not clean:
        raise InvalidPingUrl("要停用對外回報，請按「停用對外回報」，並寫下原因；有多位最高管理者時需要另一位核准。")
    old = _read_ping_url()
    old_host, new_host = _host_of(old), _host_of(clean)
    base = {"pingUrlSet": bool(old), "pingHost": old_host, "oldHost": old_host, "newHost": new_host}
    if clean == old:
        return {**base, "changed": False, "pending": False, "mailed": False}
    host_changes = bool(old) and old_host != new_host
    why = _clean_reason(reason) if host_changes else (reason.strip() if isinstance(reason, str) else "")
    user = _username(actor)
    if host_changes:
        conn = get_db()
        try:
            others = _other_superadmins(conn, user)
        finally:
            conn.close()
        if others > 0:
            conn = get_db()
            try:
                _begin(conn)
                for r in _pending_rows(conn):
                    L.supersede(conn, r["id"], user, "被較新的申請取代")
                with open(_pending_file(), "w", encoding="utf-8") as f:
                    json.dump({"ping_url": clean}, f)
                rec = L.record(conn, _MON_DOMAIN, "heartbeat", [{"field": _FIELD_CHANGE, "old": old_host, "new": new_host}], why, actor, ip=ip,
                               risk="security", effective_at=datetime.now().isoformat(timespec="seconds"), approvals_required=1,
                               audit_action="system.heartbeat_change_requested", target_label="對外心跳監控", link="backup-monitor.html")
                conn.commit()
            except BaseException:
                if conn.in_transaction:
                    conn.rollback()
                _clear_pending_file()
                raise
            finally:
                conn.close()
            mailed = _notify_superadmins(
                "有人申請把對外心跳監控換到另一個主機，等待另一位最高管理者核准",
                [("申請人", _display(actor)), ("時間", _mail_now()), ("原本的監控主機", old_host), ("要換成的主機", new_host), ("原因", why)],
                "%s 申請把心跳監控換到 %s" % (_display(actor), new_host))
            return {**base, "changed": False, "pending": True, "id": rec["ids"][0], "mailed": mailed}
    _write_config(clean)
    _void_pending(actor)
    mailed = _notify_superadmins(
        "對外心跳監控的網址被更換", [("操作人", _display(actor)), ("時間", _mail_now()),
                                  ("原本的監控主機", old_host or "（原本沒有設定）"), ("新的監控主機", new_host)] + ([("原因", why)] if why else []),
        "%s 更換了心跳監控網址（新主機：%s）" % (_display(actor), new_host))
    return {**base, "pingUrlSet": True, "pingHost": new_host, "changed": True, "pending": False, "mailed": mailed}


# ── 動作：停用對外打卡／換監控主機（讓外部監控收不到「我還活著」，多位最高管理者時要第二人核准）──────────────

def pending_disable() -> dict:
    """目前待核准的申請（停用或換主機；沒有 ⇒ None）。不含網址。"""
    conn = get_db()
    try:
        rows = _pending_rows(conn)
    finally:
        conn.close()
    if not rows:
        return None
    r = rows[0]
    return {"id": r["id"], "kind": "change" if r["field"] == _FIELD_CHANGE else "disable",
            "hoursWaiting": _hours_waiting(r["at"]), "waitingFor": _approver_names(r["actor"]),
            "newHost": (r.get("new") or "") if r["field"] == _FIELD_CHANGE else "",
            "requestedBy": r.get("actor_display") or r["actor"], "requestedByUser": r["actor"], "at": r["at"],
            "reason": scrub_paths(r.get("reason") or ""), "approvals": len(r.get("approvals") or []), "required": int(r.get("approvals_required") or 0)}


def _void_pending(actor) -> None:
    """已經用新網址立即生效 ⇒ 舊的待核准申請作廢（含暫存網址檔）。盡力而為，失敗不影響換網址。"""
    try:
        from . import config_ledger as L
        conn = get_db()
        try:
            began = _begin(conn)
            n = sum(1 for r in _pending_rows(conn) if L.supersede(conn, r["id"], _username(actor), "已設定新的監控網址"))
            if n:
                conn.commit()
            elif began:
                conn.rollback()
        finally:
            conn.close()
        _clear_pending_file()
    except Exception:  # noqa: BLE001
        logger.warning("待核准申請作廢失敗", exc_info=True)


_void_pending_disable = _void_pending       # 舊名（相容）


def request_disable(actor, reason: str, ip: str = "") -> dict:
    """停用對外打卡。必填原因。只有一位在職最高管理者 ⇒ 立刻停用並寄信通知；有其他最高管理者 ⇒ 建立待核准申請
    （要另一位按核准才真的停用）。回 `{disabled, pending, id?}`。已經沒設網址 ⇒ `DisableError`。"""
    from . import config_ledger as L
    reason = _clean_reason(reason)
    if not _read_ping_url():
        raise DisableError("目前沒有設定對外回報，不需要停用。")
    user = _username(actor)
    conn = get_db()
    try:
        _begin(conn)
        for r in _pending_rows(conn):
            L.supersede(conn, r["id"], user, "被較新的申請取代")
        others = _other_superadmins(conn, user)
        change = [{"field": _FIELD_DISABLE, "old": "已設定", "new": "停用"}]
        if others == 0:
            _write_config("")
            L.record(conn, _MON_DOMAIN, "heartbeat", change, reason, actor, ip=ip, risk="security",
                     audit_action="system.heartbeat_disabled", target_label="對外心跳監控", link="backup-monitor.html")
            conn.commit()
            out = {"disabled": True, "pending": False}
        else:
            rec = L.record(conn, _MON_DOMAIN, "heartbeat", change, reason, actor, ip=ip, risk="security",
                           effective_at=datetime.now().isoformat(timespec="seconds"), approvals_required=1,
                           audit_action="system.heartbeat_disable_requested", target_label="對外心跳監控", link="backup-monitor.html")
            conn.commit()
            out = {"disabled": False, "pending": True, "id": rec["ids"][0]}
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    _clear_pending_file()
    if out["disabled"]:
        _notify_superadmins("對外心跳監控已被停用", [("操作人", _display(actor)), ("時間", _mail_now()), ("原因", reason)],
                            "%s 停用了對外心跳監控" % _display(actor))
    else:
        _notify_superadmins("有人申請停用對外心跳監控，等待另一位最高管理者核准",
                            [("申請人", _display(actor)), ("時間", _mail_now()), ("原因", reason)],
                            "%s 申請停用對外心跳監控" % _display(actor))
    return out


def approve_disable(change_id: int, actor, ip: str = "") -> dict:
    """第二位最高管理者核准申請（停用或換主機）：票數夠就真的執行（寫設定檔失敗 ⇒ 整筆回復、票不算，可以重按）。申請人自己不能核准。
    回 `{disabled, changed, kind}`。"""
    from . import config_ledger as L
    _refuse_demo(actor)
    user = _username(actor)
    conn = get_db()
    try:
        _begin(conn)
        row = conn.execute("SELECT domain, field, actor, reason, old_json, new_json FROM config_changes WHERE id=?", (int(change_id),)).fetchone()
        if row is None or row["domain"] != _MON_DOMAIN or row["field"] not in _MON_FIELDS:
            raise DisableError("找不到這筆申請。")
        kind = "change" if row["field"] == _FIELD_CHANGE else "disable"
        res = L.approve(conn, int(change_id), actor, "")
        if not res["ok"]:
            raise DisableError({"申請人不能核准自己的變更": "這是您自己提出的申請，要由另一位最高管理者核准。",
                                "這筆變更已不是待生效狀態": "這筆申請已經處理過了（可能已被核准、撤回或被新的申請取代）。",
                                "您已經核准過了": "您已經核准過了。"}.get(res["why"], "沒有核准成功。"))
        done = res["approvals"] >= res["required"]
        if done:
            if kind == "disable":
                _write_config("")
            else:
                new_url = _read_pending_url()
                if not new_url:
                    raise DisableError("申請的新網址暫存檔已遺失（可能伺服器資料夾被清理過）。請申請人重新送出申請。")
                _validate_ping_url(new_url, resolve=False)
                _write_config(new_url)
            L.promote_due(conn, domain=_MON_DOMAIN)
            L.audit_event(conn, actor, "system.heartbeat_disabled" if kind == "disable" else "system.heartbeat_changed", "heartbeat",
                          {"requestedBy": row["actor"], "approvedBy": user, "reason": row["reason"], "changeId": int(change_id)},
                          target_label="對外心跳監控")
        conn.commit()
        requested_by, reason = row["actor"], row["reason"]
        new_host = json.loads(row["new_json"] or "null") if kind == "change" else ""
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    if done:
        if kind == "change":
            _clear_pending_file()
        _notify_superadmins("對外心跳監控已被停用" if kind == "disable" else "對外心跳監控已換到另一個主機",
                            [("申請人", requested_by), ("核准人", _display(actor)), ("時間", _mail_now())]
                            + ([("新的監控主機", new_host)] if kind == "change" else []) + [("原因", reason or "")],
                            "對外心跳監控已%s（%s 申請、%s 核准）" % ("停用" if kind == "disable" else "換主機", requested_by, _display(actor)))
    return {"disabled": done and kind == "disable", "changed": done and kind == "change", "kind": kind}


def cancel_disable(change_id: int, actor) -> dict:
    """撤回申請（**只有提出申請的人**；PM 裁示。對方長期不在、想反悔的別人，可另外提出自己的申請取代這一筆）。留稽核。"""
    from . import config_ledger as L
    conn = get_db()
    try:
        _begin(conn)
        row = conn.execute("SELECT domain, field, actor FROM config_changes WHERE id=?", (int(change_id),)).fetchone()
        if row is None or row["domain"] != _MON_DOMAIN or row["field"] not in _MON_FIELDS:
            raise DisableError("找不到這筆申請。")
        if L.state_of(conn, int(change_id)) == "pending" and (row["actor"] or "") != _username(actor):
            raise DisableError("只有提出這筆申請的人可以撤回。")
        if not L.cancel(conn, int(change_id), actor, "撤回"):
            raise DisableError("這筆申請已經處理過了。")
        L.audit_event(conn, actor, "system.heartbeat_disable_cancelled", "heartbeat",
                      {"changeId": int(change_id), "kind": "change" if row["field"] == _FIELD_CHANGE else "disable"}, target_label="對外心跳監控")
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    _clear_pending_file()
    return {"cancelled": True}


def reject_disable(change_id: int, actor, reason: str = "") -> dict:
    """駁回別人提出的申請（停用／換主機）：**不是申請人**才能駁回（申請人要放棄請用 `cancel_disable`）；必填原因；留稽核、寄信給所有最高管理者。
    ledger 沒有獨立的「駁回」事件（EVENTS 是共用的；加事件要動共用表格），這裡記成 `cancelled`、原因加「駁回：」前綴，稽核用獨立的 `system.heartbeat_disable_rejected`。"""
    from . import config_ledger as L
    _refuse_demo(actor)
    why = _clean_reason(reason)
    conn = get_db()
    try:
        _begin(conn)
        row = conn.execute("SELECT domain, field, actor, actor_display FROM config_changes WHERE id=?", (int(change_id),)).fetchone()
        if row is None or row["domain"] != _MON_DOMAIN or row["field"] not in _MON_FIELDS:
            raise DisableError("找不到這筆申請。")
        if L.state_of(conn, int(change_id)) != "pending":
            raise DisableError("這筆申請已經處理過了。")
        if (row["actor"] or "") == _username(actor):
            raise DisableError("這是您自己提出的申請，要放棄請按「撤回」。")
        kind = "change" if row["field"] == _FIELD_CHANGE else "disable"
        requested_by = row["actor_display"] or row["actor"]
        L.cancel(conn, int(change_id), actor, "駁回：" + why)
        L.audit_event(conn, actor, "system.heartbeat_disable_rejected", "heartbeat",
                      {"changeId": int(change_id), "kind": kind, "requestedBy": row["actor"], "reason": why}, target_label="對外心跳監控")
        conn.commit()
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()
    _clear_pending_file()
    _notify_superadmins("對外心跳監控的變更申請被駁回",
                        [("申請人", requested_by), ("駁回人", _display(actor)), ("申請內容", "換到另一個監控主機" if kind == "change" else "停用對外回報"),
                         ("時間", _mail_now()), ("駁回原因", why)],
                        "%s 提出的申請被 %s 駁回" % (requested_by, _display(actor)))
    return {"rejected": True, "kind": kind}


# ── 動作：測試心跳 ─────────────────────────────────────────────────────────────

def _read_ping_url() -> str:
    try:
        with open(_paths.HEARTBEAT_CONFIG, "r", encoding="utf-8") as f:
            return (json.load(f).get("ping_url") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _ping(url: str) -> tuple:
    """對網址發一次 GET ⇒ `(ok, 白話訊息)`。走 `core.safe_ping.get`：不跟隨轉址、每個解析出的位址都得是公開位址、連線釘在檢查過的 IP、
    只准 80／443、整體時限 15 秒（H1／M1／L5）。訊息與 log 都不含網址（不變式 ②⑤）。"""
    from core import safe_ping
    try:
        status = safe_ping.get(url, timeout=_PING_TIMEOUT)
    except safe_ping.RedirectBlocked:
        return False, ("監控服務要求轉到另一個網址，為了安全，系統不會跟著轉址。請回到監控服務的網站，重新複製正確的 Ping URL 貼上"
                       "（通常是網址貼錯了，或服務換了位址）。")
    except safe_ping.UnsafeTarget as exc:
        return False, exc.reason
    except safe_ping.PingFailed as exc:
        logger.warning("測試心跳失敗：%s", getattr(exc, "kind", "") or type(exc).__name__)
        if exc.kind == "dns":
            return False, "找不到這個網站的位址。請確認網址是否有貼對，以及這台電腦的網路與 DNS 是否正常。"
        if exc.kind == "tls":
            return False, "監控服務的安全憑證驗證未通過。請確認網址沒有貼錯；如果網址正確，請聯絡維運檢查這台電腦的日期時間與憑證。"
        if exc.kind == "timeout":
            return False, "等候逾時，監控服務未回應。請稍後再試，或確認這台電腦的網路可以連到外部。"
        return False, "這台電腦無法連線至監控服務。請確認網路可以連到外部，以及網址是否有貼對。"
    except Exception as exc:  # noqa: BLE001
        logger.warning("測試心跳失敗：%s", type(exc).__name__)
        return False, "這台電腦無法連線至監控服務。請確認網路可以連到外部，以及網址是否有貼對。"
    if 200 <= status < 300:
        return True, "監控服務有收到這次回報。"
    if status in (404, 410):
        return False, "監控服務回報找不到這個網址，請確認是否有貼完整、或在監控服務裡是否被刪除了。"
    if status in (401, 403):
        return False, "監控服務拒絕了這次回報，請確認網址是否為正確的 Ping URL。"
    if status == 429:
        return False, "打得太頻繁，監控服務暫時拒絕了。請稍後再試。"
    if status >= 500:
        return False, "監控服務那邊暫時出問題了，請稍後再試。"
    return False, "監控服務回應了，但不是成功的結果。請確認網址是否有貼完整。"


def test_heartbeat() -> dict:
    """對目前設定的心跳網址打一次卡（不變式 ⑤）。沒設 ⇒ `{"ok": False, "message": …}`；太頻繁 ⇒ `HeartbeatRateLimited`。"""
    with _hb_lock:
        wait = HEARTBEAT_TEST_MIN_INTERVAL_SECONDS - (time.monotonic() - _hb_last["at"])
        if _hb_last["at"] and wait > 0:
            raise HeartbeatRateLimited(wait)
        _hb_last["at"] = time.monotonic() or 1.0
    url = _read_ping_url()
    if not url:
        return {"ok": False, "message": "尚未設定監控網址，請先貼上網址並儲存。"}
    ok, msg = _ping(url)
    return {"ok": ok, "message": msg}
