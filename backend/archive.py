"""Google Drive archive helpers: real-time, daily, and weekly backups + local SQLite snapshots."""
import json
import os
import shutil
import sqlite3
import string
import threading
import time
import uuid
import logging
from datetime import datetime, date, timedelta

import cloud_storage
from db import get_db, DB_PATH
from helpers import _cleanup_sessions, _get_setting, _set_setting

logger = logging.getLogger(__name__)

# 2026-09-01：保留天數原本寫死在下面各個 _prune_*() 呼叫點（本機30天／雲端每日365天／
# 雲端週730天／稽核紀錄730天），使用者要求「備份次數跟週期可調整避免檔案過大」，改為
# 存進 system_settings.backup_retention（見 routers/system.py 的
# GET/PATCH /api/settings/backup-retention），不用改程式碼重新部署就能調整。
# ⚠️ 2026-09-14：預設值已隨新的保留政策改過（每日 60／週 90／月永久），
# 見下方 _BACKUP_RETENTION_DEFAULT 的說明。以下這段是當時的歷史紀錄：
# cloud_daily_keep_days 2026-09-01 曾改為 1825 天（5年）——使用者確認目前雲端每日備份
# 僅 1.45GB，5年容量無虞，比原本 365 天更符合需求。
# 保留策略（2026-09-14 使用者裁示）——三層各自的角色不同，不要混在一起看：
#   每日備份  60 天：近期誤刪／誤改的回溯窗口。日常真正會用到的就是這一層。
#   週備份    90 天：每日層之外多一個粗顆粒的中期窗口。
#   月備份    永久：長期法遵與歷史查詢用。`cloud_monthly_keep_days = 0` 代表
#             「永不清除」，_prune_cloud_backups() 讀到 0 會整段跳過。
# 改小每日／週的天數是刻意的：舊值（每日 1825 天＝5 年、週 730 天）等於把長期
# 保存這件事壓在「每天一份整庫 .db」上，成本隨資料庫大小線性成長，而真正需要
# 長期保留的其實是月粒度。長期保存改由月備份層承擔之後，前兩層可以縮短。
#
# ⚠️ 上傳檔案鏡像／PDF存檔鏡像**不在這裡**，也永遠不會被任何 prune 邏輯掃到
# （_prune_cloud_backups() 只走 每日備份／週備份／月備份 三個目錄）——那兩份是
# 使用者明訂要長久保留的原始憑據。test_backup_retention_policy_2026_09_14.py
# 有一題專門守這件事，不要為了「順手清一下」把鏡像目錄加進 prune 清單。
_BACKUP_RETENTION_DEFAULT = {
    "local_db_keep_days":     30,
    "cloud_daily_keep_days":  60,
    "cloud_weekly_keep_days": 90,
    "cloud_monthly_keep_days": 0,      # 0 = 永久保留
    "local_pre_update_keep":  5,       # pre_update_* 快照保留份數（非天數）
    "audit_log_keep_days":    730,
}


def _backup_retention() -> dict:
    """可調整的備份保留天數設定，供 _daily_backup()/_snapshot_sqlite() 讀取。"""
    return {**_BACKUP_RETENTION_DEFAULT, **(_get_setting("backup_retention", {}) or {})}

# Google Drive for Desktop's drive letter is NOT stable across reboots/relogins
# (observed switching G:<->H: repeatedly, see 2026-08-24 note in _ensure_archive_dirs).
# Rather than hardcode a letter, scan mounted drives each time for the one that
# actually has this folder, so a letter swap can't silently break cloud backups.
_ARCHIVE_SUBPATH = os.path.join("我的雲端硬碟", "系統存檔")
_ARCHIVE_CACHE_TTL = 30  # seconds; avoid rescanning A-Z on every single real-time write
_archive_base_cache = {"path": None, "checked_at": 0.0}


def _detect_archive_base() -> str:
    """Scan mounted drive letters for one containing 我的雲端硬碟\\系統存檔.
    Returns the first match, or "" if none is currently mounted/accessible."""
    for letter in string.ascii_uppercase:
        candidate = f"{letter}:\\{_ARCHIVE_SUBPATH}"
        if os.path.isdir(candidate):
            return candidate
    return ""


def _archive_base() -> str:
    """Currently valid cloud archive path, or "" if not found on any drive."""
    cached = _archive_base_cache["path"]
    if cached and time.monotonic() - _archive_base_cache["checked_at"] < _ARCHIVE_CACHE_TTL:
        if os.path.isdir(cached):
            return cached
    detected = _detect_archive_base()
    _archive_base_cache["path"] = detected or None
    _archive_base_cache["checked_at"] = time.monotonic()
    return detected


def _realtime_dir() -> str:
    return os.path.join(_archive_base(), "即時備份")


def _weekly_dir() -> str:
    return os.path.join(_archive_base(), "週備份")


def _daily_dir() -> str:
    return os.path.join(_archive_base(), "每日備份")


def _monthly_dir() -> str:
    return os.path.join(_archive_base(), "月備份")


def _uploads_mirror_dir() -> str:
    return os.path.join(_archive_base(), "上傳檔案鏡像")


def _pdf_mirror_dir(subdir: str) -> str:
    return os.path.join(_archive_base(), "PDF存檔鏡像", subdir)


# Local always-on paths (independent of cloud drive mount)
_BACKEND_DIR      = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT     = os.path.dirname(_BACKEND_DIR)
_LOCAL_DB_BACKUP  = os.path.join(_BACKEND_DIR, "db_backups")
_ALERT_DIR        = os.path.join(_PROJECT_ROOT, "backup_alerts")
_UPLOADS_DIR      = os.path.join(_PROJECT_ROOT, "uploads")


def _active_backend() -> str:
    return cloud_storage.cloud_backup_target().get("backend", "local_drive")


def _archive_reachable() -> bool:
    """"Is the cloud backup destination currently reachable?" — branches on
    the configured backend (architecture map §6.4, 2026-09-07). Everything
    below this line that used to check "is the drive mounted" now goes
    through this, so switching backends doesn't require touching every
    call site's availability check, only the actual read/write dispatch
    (see the _cloud_*() helpers below)."""
    if _active_backend() == "s3":
        return cloud_storage.s3_available()
    return bool(_archive_base())


# ── 這台機器要不要上傳雲端（2026-09-15 使用者指示）────────────────────────────
#
# 「開發機的所有檔案不上傳雲端，但正式機需要上傳雲端」。
#
# **為什麼不能只靠下面的所有權標記**：那個是「防兩台互相覆蓋」的碰撞防護，不是
# 「這台永不上傳」的政策開關，而且它有兩條會反過來咬人的路徑：
#   ① marker 不存在時會**自動認領**——Drive 同步異常、有人手動刪掉、重新掛載
#      都可能讓它消失。開發機一旦認領成功，換成**正式機**被自己的防呆擋住，
#      雲端備份整個停掉，而且症狀是「沒有錯誤、只是沒有備份」。
#   ② 讀 marker 失敗時 fail-open（當作通過）→ 開發機就開始寫。
# 所以政策開關要獨立，而且要在所有權檢查**之前**生效（連認領動作都不做）。
#
# 判斷來源，依序：
#   1. 環境變數 `MOTRIX_CLOUD_ARCHIVE=off`／`on` —— 臨時覆寫，不用改檔案
#   2. 專案根目錄的 `.no_cloud_archive` 檔案 —— 開發機放這個。它在 `.gitignore`
#      裡，而 `build_deploy_package.ps1` 是用 `git archive` 打包（只含已追蹤且
#      已 commit 的內容），所以**這個檔案永遠不會被帶到正式機**。
#   3. 兩者都沒有 → 允許上傳（維持原本行為）
#
# ⚠️ **預設是「允許」而不是「禁止」**，因為兩個方向的風險不對稱：開發機誤傳的代價
# 是雲端多了垃圾（發現了可以刪）；正式機誤停的代價是備份靜靜消失好幾週——2026-08-24
# 真的發生過（磁碟機代號從 G: 變成 H: 之後三週沒人發現）。所以要停的那台明確標記，
# 判斷不出來的一律照傳。
_NO_CLOUD_MARKER_PATH = os.path.join(_PROJECT_ROOT, ".no_cloud_archive")
_ENV_CLOUD_FLAG = "MOTRIX_CLOUD_ARCHIVE"
_cloud_policy_state = {"enabled": None}     # 只為了「狀態變了才寫一次 log」


def cloud_archive_enabled() -> bool:
    """這台機器允不允許寫雲端存檔（含即時／每日／週／月備份與兩組鏡像）。

    **刻意不做快取**：判斷只是一次 `os.path.exists`，而換掉這個檔案就是為了立刻
    生效——要求使用者重啟服務才算數的開關，在「發現開發機正在污染雲端」那一刻
    是最沒有用的設計。
    """
    raw = (os.environ.get(_ENV_CLOUD_FLAG) or "").strip().lower()
    if raw in ("off", "0", "false", "no", "disabled"):
        enabled, why = False, f"環境變數 {_ENV_CLOUD_FLAG}={raw}"
    elif raw in ("on", "1", "true", "yes", "enabled"):
        enabled, why = True, f"環境變數 {_ENV_CLOUD_FLAG}={raw}"
    elif os.path.exists(_NO_CLOUD_MARKER_PATH):
        enabled, why = False, f"存在 {_NO_CLOUD_MARKER_PATH}"
    else:
        enabled, why = True, "未設定任何停用標記（預設允許）"

    if _cloud_policy_state["enabled"] != enabled:
        _cloud_policy_state["enabled"] = enabled
        logger.info("雲端存檔政策：%s（%s）", "允許上傳" if enabled else "停止上傳", why)
    return enabled


# ── 存檔所有權（2026-09-14）────────────────────────────────────────────────────
#
# **要解決的問題**：這個存檔目錄沒有任何「這是誰的」概念。`_detect_archive_base()`
# 是掃 A–Z 找第一個含 `我的雲端硬碟\系統存檔` 的磁碟機，而 `main.py` 是**無條件**
# 啟動 `_schedule_daily()`／`_schedule_weekly()`。所以任何跑這份程式碼、又掛著
# 同一個雲端硬碟的機器（開發機、備援機、DR 還原出來的機器、未來的分公司機）
# 都會寫進同一組資料夾。兩個實際後果都是**靜默**的：
#
#   ① `.done` marker 在雲端。先跑的那台贏，後跑的那台走
#      `_clear_backup_alert_if_healthy(); return`——**還順手把警示清掉**。
#      正式機當天沒備份，但備份頁面綠燈、沒有 audit、沒有信。
#   ② `_snapshot_sqlite()` 的雲端複製不看 marker，第二台會直接覆蓋當天的
#      `每日備份/{date}/motrix_erp.db`——那是還原優先序的第二層。
#
# 這不是假想：2026-09-07「conftest 雲端備份隔離死碼把測試假資料寫進真實 G: 碟」
# 就是同一類。磁碟機代號本身不是身分，資料夾路徑也不是——要有一個明確的標記。
#
# **作法**：存檔根目錄放一個 `.motrix_archive_owner`，內容是這個資料庫的
# instance id。對不上就整個拒寫並寄信，而不是默默覆蓋別人的備份。
# 第一次看到沒有 marker 的空存檔目錄時自動認領（正常升級路徑：正式機明天
# 第一次備份就把 marker 寫下去，之後開發機再掛上同一顆碟就會被擋下來）。

_ARCHIVE_OWNER_MARKER = ".motrix_archive_owner"
# `base` 是這份判定所屬的存檔根目錄——**快取一定要以路徑為鍵**：這個系統的
# 磁碟機代號本來就會漂移（見 _detect_archive_base()），換了一顆碟之後沿用上一顆
# 的所有權判定是錯的。2026-09-14 實測踩到過：一支完全無關的備份測試把
# `_archive_base` 指到自己的暫存目錄，卻吃到前一題留下的 False，於是 _daily_backup()
# 在掛鏡像之前就早退——**序列跑綠、平行跑紅**，最難查的那種。
_owner_cache = {"base": None, "ok": None, "checked_at": 0.0, "reason": ""}
_OWNER_CACHE_TTL = 300          # 秒；這個檢查要讀檔，不能每次即時備份都做一次


def _archive_instance_id() -> str:
    """本機這套系統的識別碼，存在 system_settings，第一次呼叫時產生。

    綁在**資料庫**上而不是機器名：DR 換機重建時資料庫是跟著還原過去的，
    識別碼跟著走才對——新機器應該要能接手舊機器的存檔目錄，而不是被自己的
    防呆擋在門外。反過來說，同一個存檔目錄被兩套**不同的資料庫**寫，
    才是真正要擋的情況。
    """
    iid = _get_setting("archive_instance_id", "")
    if not iid:
        iid = uuid.uuid4().hex
        _set_setting("archive_instance_id", iid)
    return iid


def _archive_owner_ok() -> bool:
    """存檔目錄是不是屬於這套系統。不是就寫 ERROR 警示並回 False（＝停寫）。

    只支援 local_drive——S3 後端用的是明確指定的 bucket + prefix，本來就不會
    「掃到別人的」，沒有這個問題。

    **讀不到／寫不進 marker 一律 fail-open**（當作通過，只留 log）：這層是
    針對罕見情境的防呆，不該因為一次暫時性的 IO 錯誤就把每天的備份整個停掉——
    那會是拿一個大問題去換一個小問題。
    """
    if not cloud_archive_enabled():
        # 這台機器根本不上傳（開發機）——**連 marker 都不要碰**。自動認領那段
        # 是這個機制最危險的地方：開發機認領成功就等於把正式機鎖在門外。
        return False

    if _active_backend() == "s3":
        return True

    base = _archive_base()
    if not base:
        return True                         # 碟沒掛上是另一個問題，由 _archive_reachable() 管

    now = time.monotonic()
    if (_owner_cache["ok"] is not None
            and _owner_cache["base"] == base
            and now - _owner_cache["checked_at"] < _OWNER_CACHE_TTL):
        return _owner_cache["ok"]

    verdict, reason = True, ""
    try:
        marker_path = os.path.join(base, _ARCHIVE_OWNER_MARKER)
        mine = _archive_instance_id()

        if not os.path.exists(marker_path):
            # 認領：第一次使用（或使用者刻意刪掉 marker 以轉移所有權）
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump({"instance_id": mine,
                           "machine": os.environ.get("COMPUTERNAME", ""),
                           "claimed_at": datetime.now().isoformat()},
                          f, ensure_ascii=False, indent=2)
            logger.info("Claimed cloud archive ownership: %s", marker_path)
        else:
            with open(marker_path, encoding="utf-8") as f:
                owner = json.load(f) or {}
            if owner.get("instance_id") != mine:
                verdict = False
                reason = (
                    f"這個雲端存檔目錄屬於另一套系統"
                    f"（機器：{owner.get('machine') or '不明'}，"
                    f"認領於 {owner.get('claimed_at') or '不明'}）。"
                    f"為避免覆蓋對方的備份、或因為對方已寫下當日 .done 而讓本機"
                    f"靜默略過備份，**本機的雲端備份已全部停止**（本機 SQLite "
                    f"快照不受影響，仍會寫入 {_LOCAL_DB_BACKUP}）。"
                    f"若這台才是正式機、要接手這個存檔目錄，"
                    f"請刪除 {marker_path} 後重啟服務即可重新認領。"
                )
    except Exception as e:
        logger.warning("_archive_owner_ok check failed (fail-open): %s", e)
        verdict, reason = True, ""

    _owner_cache.update({"base": base, "ok": verdict, "checked_at": now, "reason": reason})
    if not verdict:
        _write_backup_alert(reason, level="ERROR")
    return verdict


def _archive_ok() -> bool:
    """雲端備份現在可不可以寫：目的地連得上 **而且** 這個存檔目錄是本機的。

    所有原本只問「碟掛著沒」的呼叫點都走這裡，所以所有權檢查一次就覆蓋到
    即時／每日／週／月備份與兩組鏡像，不用逐一改呼叫端。
    """
    if not cloud_archive_enabled():
        return False
    if not _archive_reachable():
        return False
    return _archive_owner_ok()


# ── Backend-dispatching read/write helpers (2026-09-07) ────────────────────────
#
# Each call site still computes its "local_drive" absolute path exactly as
# before (via _realtime_dir()/_daily_dir()/_weekly_dir()/_uploads_mirror_dir())
# — that computation, and the existing test monkeypatches of those directory
# functions, are untouched. These helpers only add a second branch: when
# `backend == "s3"`, the local absolute path is ignored and an S3 key
# (relative to the configured prefix, forward-slash separated) is used
# instead. This keeps 100% of existing "local_drive" behavior byte-for-byte
# identical (it is, and always was, the production default) while adding the
# new backend as a strictly additive alternative.

def _cloud_write_json(local_abs_path: str, s3_key: str, data) -> None:
    if _active_backend() == "s3":
        cloud_storage.s3_put_bytes(s3_key, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    else:
        os.makedirs(os.path.dirname(local_abs_path), exist_ok=True)
        _atomic_json_write(local_abs_path, data)


def _cloud_copy_file(local_src: str, local_dest_abs: str, s3_key: str) -> None:
    if _active_backend() == "s3":
        cloud_storage.s3_upload_file(local_src, s3_key)
    else:
        os.makedirs(os.path.dirname(local_dest_abs), exist_ok=True)
        shutil.copy2(local_src, local_dest_abs)


def _cloud_stat(local_dest_abs: str, s3_key: str):
    """Returns (size, mtime_epoch) for an existing destination, or None —
    used by _mirror_uploads() to decide whether a file needs re-copying."""
    if _active_backend() == "s3":
        return cloud_storage.s3_stat(s3_key)
    if not os.path.exists(local_dest_abs):
        return None
    st = os.stat(local_dest_abs)
    return st.st_size, st.st_mtime


def _cloud_marker_exists(local_marker_abs: str, s3_key: str) -> bool:
    if _active_backend() == "s3":
        return cloud_storage.s3_stat(s3_key) is not None
    return os.path.exists(local_marker_abs)


def _cloud_write_marker(local_marker_abs: str, s3_key: str) -> None:
    if _active_backend() == "s3":
        cloud_storage.s3_put_bytes(s3_key, b"")
    else:
        os.makedirs(os.path.dirname(local_marker_abs), exist_ok=True)
        open(local_marker_abs, "w").close()


def _cloud_list_top_level(local_dir_abs: str, s3_rel_dir: str) -> list:
    if _active_backend() == "s3":
        return cloud_storage.s3_list_prefixes(s3_rel_dir)
    if not os.path.isdir(local_dir_abs):
        return []
    return [n for n in os.listdir(local_dir_abs) if os.path.isdir(os.path.join(local_dir_abs, n))]


def _cloud_delete_dir(local_dir_abs: str, s3_rel_dir: str) -> None:
    if _active_backend() == "s3":
        cloud_storage.s3_delete_prefix(s3_rel_dir)
    else:
        shutil.rmtree(local_dir_abs, ignore_errors=True)


def _atomic_json_write(path: str, data) -> None:
    """Write JSON atomically: write to .tmp then os.replace() to avoid corrupt files on crash."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _system_audit(action: str, target_label: str = "", detail: dict = None) -> None:
    """Write audit_log as system (no session token)."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO audit_log (at,user_id,username,display_name,action,"
            "target_type,target_id,target_label,detail) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                datetime.now().isoformat(),
                None,
                "system",
                "系統",
                action,
                "backup",
                "",
                target_label or "",
                json.dumps(detail or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("_system_audit failed for %s", action)


def _write_backup_alert(reason: str, level: str = "WARN") -> None:
    """
    Surface backup problems where ops will notice:
    - project folder backup_alerts/BACKUP_ALERT.txt (overwritten)
    - dated log line under backup_alerts/YYYY-MM-DD.log
    - audit_log (throttled once per day for same reason key)
    - Email to admin/superadmin when level=="ERROR" (throttled daily)
    """
    try:
        os.makedirs(_ALERT_DIR, exist_ok=True)
        now = datetime.now().isoformat(timespec="seconds")
        banner = (
            f"[{level}] MOTRIX ERP 備份警示\n"
            f"時間: {now}\n"
            f"原因: {reason}\n"
            f"\n"
            f"請確認：\n"
            f"1. Google 雲端硬碟是否已掛載（任一代號皆可）且可存取「我的雲端硬碟\\系統存檔」\n"
            f"2. 本機 SQLite 快照是否仍存在於 backend\\db_backups\\\n"
            f"3. 處理完成後可刪除本檔；系統會在問題持續時再次寫入\n"
        )
        alert_path = os.path.join(_ALERT_DIR, "BACKUP_ALERT.txt")
        with open(alert_path, "w", encoding="utf-8") as f:
            f.write(banner)

        day_log = os.path.join(_ALERT_DIR, f"{date.today().isoformat()}.log")
        with open(day_log, "a", encoding="utf-8") as f:
            f.write(f"{now}\t{level}\t{reason}\n")

        # Throttle audit: one alert per reason per day
        throttle = os.path.join(_ALERT_DIR, f".alerted_{date.today().isoformat()}_{level}")
        reason_key = reason[:80]
        throttle_detail = os.path.join(_ALERT_DIR, f".reason_{date.today().isoformat()}")
        already = False
        if os.path.exists(throttle_detail):
            try:
                with open(throttle_detail, "r", encoding="utf-8") as f:
                    already = reason_key in f.read()
            except Exception:
                already = False
        if not already:
            _system_audit(
                "backup.alert",
                reason[:120],
                {"level": level, "reason": reason, "alertPath": alert_path},
            )
            with open(throttle_detail, "a", encoding="utf-8") as f:
                f.write(reason_key + "\n")
            open(throttle, "a").close()

            # Email alert for ERROR-level failures (throttled via same daily marker)
            if level == "ERROR":
                _send_backup_error_email(reason, now)

        logger.warning("BACKUP ALERT: %s", reason)
    except Exception:
        logger.exception("_write_backup_alert failed")


def _send_backup_error_email(reason: str, ts: str) -> None:
    """Send async email to superadmin (最高管理者) on ERROR-level backup failure
    — 2026-08-24 改用 _superadmin_emails() 而非 _admin_emails()：備份基礎設施出問題
    （例如雲端硬碟磁碟機代號跑掉）需要有權限處理伺服器/磁碟機掛載的人知道，不是
    一般 admin 職務範圍；_superadmin_emails() 找不到人時仍會 fallback 回全體
    admin/superadmin，不會真的寄不出去。"""
    try:
        from helpers.email_notify import _superadmin_emails, _async_send
        to = _superadmin_emails()
        if not to:
            return
        html = (
            "<div style='font-family:Arial,sans-serif;padding:24px;max-width:600px'>"
            "<h2 style='color:#DC2626'>⚠ MOTRIX ERP — 備份嚴重錯誤</h2>"
            f"<p style='color:#374151'>發生時間：{ts}</p>"
            "<div style='background:#FEE2E2;border:1px solid #FCA5A5;border-radius:6px;"
            "padding:12px 16px;margin:12px 0'>"
            f"<strong>錯誤原因：</strong><br>{reason}</div>"
            "<p style='color:#374151'>請儘速確認：</p>"
            "<ol style='color:#374151'>"
            "<li>Google 雲端硬碟是否已掛載（任一代號皆可，可存取「我的雲端硬碟/系統存檔」）</li>"
            "<li>本機 SQLite 快照（<code>backend/db_backups/</code>）是否仍存在</li>"
            "<li>伺服器磁碟空間是否不足</li>"
            "</ol>"
            "<p style='color:#6B7280;font-size:12px'>此訊息每日每類錯誤最多寄送一次。</p>"
            "</div>"
        )
        _async_send(to, "[MOTRIX] ⚠ 備份嚴重錯誤警示", html)
    except Exception:
        logger.exception("_send_backup_error_email failed")


def _clear_backup_alert_if_healthy() -> None:
    """Remove sticky alert file when cloud archive path is healthy.

    2026-09-15：這台機器不上傳雲端時也要清。那個警示檔講的是「雲端備份寫不進去」，
    在一台**刻意不寫雲端**的機器上是過期資訊——留著它會讓人以為有故障要處理。
    """
    if not cloud_archive_enabled():
        alert_path = os.path.join(_ALERT_DIR, "BACKUP_ALERT.txt")
        try:
            if os.path.exists(alert_path):
                os.remove(alert_path)
                logger.info("本機不上傳雲端存檔 — 清掉過期的 BACKUP_ALERT.txt")
        except Exception:
            logger.exception("failed to clear backup alert")
        return
    if not _archive_ok():
        return
    alert_path = os.path.join(_ALERT_DIR, "BACKUP_ALERT.txt")
    try:
        if os.path.exists(alert_path):
            os.remove(alert_path)
            logger.info("Cloud archive path OK — cleared BACKUP_ALERT.txt")
    except Exception:
        logger.exception("failed to clear backup alert")


def _ensure_archive_dirs():
    """雲端存檔的目錄預建與可用性告警。

    🔴 **這一行不可以在模組層被呼叫**（`BK20`，2026-09-22）。

    ☠️ 它原本在 `main.py` 的模組層 ⇒ 任何在 conftest 的 patch 生效之前
    `import main` 的路徑，會在**真實的雲端硬碟**上建目錄。
    而 `BK19` 的守門裝在 fixture 裡 —— 它跑的時候，損害已經造成。
    📌 〈防護的副作用落在盲側〉：**裝在事後的守門，對「事前」那一段沒有意見。**
    ⇒ 現在它在 `main.py` 的 `MOTRIX_DISABLE_SCHEDULERS` 區塊裡。

    🔑 **為什麼搬得動**：`archive.py` 的寫入端本來就自己建目錄
    （`exist_ok=True`，326／334／359／420／764／1145 六處）——
    就算這一行沒跑，真正要寫的那一刻仍然會建。
    ⇒ 它的作用是「**提早發現雲端碟不見了**」的告警，不是「讓寫入成功」。

    ☠️ **不要用「正式機與開發機都不設 `MOTRIX_DISABLE_SCHEDULERS`」當理由**
    （我原本是這樣寫的，A-2 2026-09-22 給了現成反例）：
    666 的啟動指令就設了它。那台機器沒事只是因為 `cloud_archive_enabled()`
    是 false，這個函式第一行就 `return` ——
    🔑 **結論一樣，而支撐它的理由不是那一個。**
    ⚠️ 理由會被下一個人引用，而他可能在一台 `cloud_archive_enabled()`
    為 true 的機器上用 `DISABLE_SCHEDULERS=1` 啟動。
    """
    # 2026-09-15：這台機器不上傳雲端（開發機）→ 什麼都不做，也**不要寫任何警示**。
    # 這不是故障，是設定；在這裡寄信或留警示檔只會訓練大家忽略這封信。
    if not cloud_archive_enabled():
        return
    # 所有權不符時 _archive_owner_ok() 自己已經寫了一則**說明具體原因**的 ERROR
    # 警示（見該函式）。這裡不能再往下走進「路徑不存在或未掛載」那段，否則會用
    # 一個完全錯的理由蓋掉真正的原因——碟明明掛得好好的，問題是它是別人的。
    if _archive_reachable() and not _archive_owner_ok():
        return
    if not _archive_ok():
        # 2026-08-24：這個路徑不可用的情境曾經連續三週以上每天觸發（磁碟機代號從
        # G: 被改成 H: 之後就一直沒偵測到），但過去這裡只寫 WARN（不寄信），只留在
        # backup_alerts/ 裡沒人主動看，直到使用者要求「備份失敗要寄警示信」才發現。
        # 整條雲端備份（即時/每日/週+uploads鏡像）全跳過屬於系統性失效，改為
        # ERROR 等級才會觸發 _send_backup_error_email()，避免同一個問題再度悄悄
        # 卡好幾週沒人知道。
        reason = (f"S3 bucket 無法連線（設定：{cloud_storage.cloud_backup_target()['s3'].get('bucket') or '未設定'}）"
                   if _active_backend() == "s3" else
                   f"雲端備份路徑不存在或未掛載：任一磁碟機代號下都找不到 {_ARCHIVE_SUBPATH}")
        _write_backup_alert(
            f"{reason}。即時/每日/週雲端備份已跳過。本機 SQLite 快照仍會寫入 {_LOCAL_DB_BACKUP}。",
            level="ERROR",
        )
        return
    if _active_backend() == "s3":
        # S3 有沒有「資料夾」是假的（key 裡有沒有 "/" 純粹是命名習慣），不需要、
        # 也不能像本機磁碟機那樣預先 os.makedirs()——略過，直接視為就緒。
        _clear_backup_alert_if_healthy()
        return
    for d in [
        os.path.join(_realtime_dir(), "報價單"),
        os.path.join(_realtime_dir(), "客戶"),
        os.path.join(_realtime_dir(), "供應商"),
        _weekly_dir(),
        _daily_dir(),
        _monthly_dir(),
        _uploads_mirror_dir(),
    ]:
        try:
            os.makedirs(d, exist_ok=True)
        except Exception as e:
            _write_backup_alert(f"無法建立備份目錄 {d}: {e}", level="ERROR")
            return
    _clear_backup_alert_if_healthy()


# ══════════════════════════════════════════════════════════════════════════════
# 快照內容檢查（§12 BK10／BK12／BK13／BK22／BK24／BK25／BK26）
# ══════════════════════════════════════════════════════════════════════════════
#
# 🔴 為什麼需要這一段：2026-08-30／08-31／09-03 三天的雲端每日備份是一份
#    **結構正確而資料是空的**資料庫 —— `PRAGMA quick_check = ok`、表數也對
#    （68／70 張）、檔案大小看起來合理，只是裡面沒有資料。
#    成因已結案（`BK11`：本機 pytest 的雲端隔離死碼，`a55fe26` 已修），
#    ☠️ **而「修好」不等於「看得見」**：同一個形狀的下一次仍然會靜靜通過。
#
# 🔑 判準分兩部分，**缺一不可**（A-2 用 `BK21` 推翻了只有第一部分的版本）：
#
#    ① 身分對照   快照的 稽核紀錄／報價單／客戶 ≥ 同一天 `彙總.json`
#                 抓「拿到的是另一個資料庫」
#    ② 每列位元組 bytes(.db) ÷ 彙總的稽核筆數，要落在校準出來的區間內
#                 抓「某一張表失控膨脹」——08-02／08-03 整庫 311 MB 的那一種，
#                 ☠️ 而那兩天**三張表全部正常**，①完全抓不到。
#
# ⚠️ ② 預設關閉（`BK26`）：`[800, 8000]` 只在**一個安裝、61 天**上驗過。
#    🔑 換一個客戶（稽核少而附件多）分布就不同，而寫死的界線不會報錯，
#    只會在別人的機器上一直誤判。⇒ 要嘛隨安裝自我校準，要嘛只在自己的機器開。

#: 身分對照要比的三張表（鍵＝`彙總.json` 裡的檔名）。
#: 🔑 D 逐日實測 61 天的單調性選出來的：只增不減。
#: ❌ 通知（09-01 148 → 09-02 124 會減少）與模組版本（劇烈震盪）不在內。
SNAPSHOT_IDENTITY_TABLES = ("稽核紀錄", "報價單", "客戶")

#: 身分對照那三張表在資料庫裡的真名。
_SNAPSHOT_IDENTITY_SQL = {
    "稽核紀錄": "audit_log",
    "報價單":   "quotations",
    "客戶":     "customers",
}

#: 沒有 `彙總.json` 可以對照時，能驗的只剩「這是不是我們的資料庫」。
#: ⚠️ **這一層擋不到那三天**（它們 68 張表都在）—— 它擋的是「拿到的根本
#: 不是這個系統的庫」。真正抓那三天的是 `snapshot_content_ok()` 的身分對照，
#: 而那道檢查跑在 `_daily_backup()` 匯出 JSON 之後。
#: 📌 寫在這裡是因為〈防護的副作用落在盲側〉：一個列在清單上的檢查，
#:    會讓人以為那一側有人在守。**這一層守的範圍比看起來小。**
SNAPSHOT_REQUIRED_TABLES = (
    "schema_version", "users", "system_settings",
    "audit_log", "quotations", "customers",
)

#: `BK25`：合法的 VACUUM 會讓每列位元組掉到接近下界（08-04 是 1,334）。
#: ☠️ **不可以為了容納它而放寬下界** —— 放到 300 以下就同時放掉了
#: 08-30／08-31／09-03（330／328／319）。
#: 🔑 〈判準的寬窄都會騙人〉：**為了容納例外而放寬的判準，放掉的是它本來要抓的。**
#: ⚙️ 反向控制在測試裡：那三天不可以出現在這個清單上。
SNAPSHOT_RATIO_EXCEPTIONS = frozenset({
    # 2026-08-04：08-02／08-03 膨脹之後跑過 VACUUM 而緊縮（`BK23`，成因未複驗）。
    "2026-08-04",
    "2026-08-05",
})

#: 自我校準需要的最少樣本數。少於這個數就**不判斷**。
#:
#: 🔴 A-2 2026-09-22 推翻了「樣本不足就退回一組常數」的寫法：
#: ☠️ 樣本為空的時候，正好是**全新安裝的前幾天** ——
#:    那正是「別台機器的數字最不適用」的時刻，
#:    而它同時與 `BK29`（前 7 天沒有基準要跳過）直接矛盾。
#: 🔑 **沒有基準時，正確的行為是「不判斷」，不是「用別人的基準判斷」。**
_SNAPSHOT_RATIO_MIN_SAMPLES = 5

#: 自我校準時，上界離中位數的倍數。
#: 🔑 用**倍數**不用絕對值：這個指標分子分母同步成長，
#: ⇒ 資料長大時界線自己跟著長，不需要每個月回來調數字。
_SNAPSHOT_RATIO_SPREAD = 3.0

#: 下界的倍數。⚠️ 比上界寬，理由見 `snapshot_ratio_bounds()`。
_SNAPSHOT_RATIO_LOW_SPREAD = 4.0


def _median(samples):
    """中位數。樣本不足回 `None`。

    ⚠️ 用中位數不用平均：校準資料本身**就可能含有我們要抓的那種異常**
    （08-02／08-03 是 65 倍的離群值），
    ☠️ 而一個被異常值校準過的界線，會把那種異常認成正常。
    """
    values = sorted(float(v) for v in (samples or []) if v)
    if len(values) < _SNAPSHOT_RATIO_MIN_SAMPLES:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


#: `BK22` 定案版的倍率區間。**無單位、不綁安裝** ⇒ 可以開著出貨。
#:
#: A-2 用 61 天實算：正常日 0.568~1.758（含 08-04 那天合法的 VACUUM），
#: 膨脹那兩天 103，空庫那三天 0.12。
#: 下界對正常最小值餘裕 1.89x、對異常仍有 2.5x 距離；上界餘裕 1.71x、距離 34x。
#: 🔑 兩側各有獨立用途，**下界不是冗餘的**：
#:    上界抓「別的表膨脹」（分子暴增，08-02 的 module_versions）；
#:    下界抓「分母那張表自己被灌爆」——而身分對照是「只增不減」，那一種它看不到。
SNAPSHOT_SIZE_RATIO_LO = 0.3
SNAPSHOT_SIZE_RATIO_HI = 3.0

#: 倍率法要幾份歷史才算得出來。
#:
#: 🔴 `BK29`：**前 7 天沒有基準 ⇒ 跳過，不是紅。**
#: ☠️ 少了這一條，每一個全新安裝的第一天都會收到假警報，
#: 📌 而第一天收到的假警報，會決定使用者往後怎麼看待這個系統的告警。
#: ⚠️ 它必須與 `BK22` **同一包**：先出 BK22 再補 BK29 的話，
#:    中間每一個新裝的客戶都會踩到。
SNAPSHOT_SIZE_HISTORY_MIN = 7


def snapshot_size_ratio(today_bytes, history_bytes):
    """今天的快照是前幾份的幾倍。歷史不足 `SNAPSHOT_SIZE_HISTORY_MIN` 份 ⇒ `None`。

    ⚠️ 回 `None` 不是回 0，也不是丟例外（`BK29`）——
    🔑 「還沒有基準」與「比值是 0」是兩件事（〈null 不等於 0〉）。
    """
    values = sorted(float(v) for v in (history_bytes or []) if v)
    if len(values) < SNAPSHOT_SIZE_HISTORY_MIN:
        return None
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
    if not median:
        return None
    return float(today_bytes) / median


def snapshot_size_ok(today_bytes, history_bytes) -> bool:
    """倍率落在 `[0.3, 3.0]` 之內嗎。**算不出基準時回 `True`（跳過）。**

    ☠️ 這裡 fail-open 是刻意的，而且是唯一正確的：
    「還沒有基準」不是「這份快照有問題」，
    🔑 而把它判成紅的代價是**每一個新客戶的第一天都收到假警報**。
    📌 明著寫下來，不要讓它看起來像「這一側有人在守」——
       前 7 天這一側**沒有人在守**，守的只有身分對照那一半。
    """
    ratio = snapshot_size_ratio(today_bytes, history_bytes)
    if ratio is None:
        return True
    return SNAPSHOT_SIZE_RATIO_LO <= ratio <= SNAPSHOT_SIZE_RATIO_HI


def snapshot_ratio_bounds(samples=None) -> tuple:
    """每列位元組的合格區間 `(下界, 上界)`。

    `samples` 是這個安裝的歷史比值。給了就**隨安裝自我校準**（`BK26`）；
    沒給就退回 `_SNAPSHOT_RATIO_FALLBACK`。

    ⚠️ 用中位數不用平均：08-02／08-03 那種 65 倍的離群值會把平均整個拖走，
    🔑 而校準資料本身就可能含有我們要抓的那種異常 ——
    ☠️ **一個被異常值校準過的界線，會把那種異常認成正常。**
    """
    median = _median(samples)
    if median is None:
        return None
    # ⚠️ **上下不對稱**（A-2 2026-09-22 實算 61 天）：
    #    下界是唯一薄的一側，而踩到它的是**合法的 VACUUM**（08-04）。
    #    對稱的 ÷3 對 1,334 只有 1.42x 餘裕；÷4 拉到 1.89x，
    #    而對已知異常（330）仍保有 2.14x 的距離。
    # 📌 這比開一份例外清單好：〈守門要驗「有沒有人做過決定」〉配的反向控制
    #    就是「不可以靠把東西寫進排除清單變綠」。
    return (median / _SNAPSHOT_RATIO_LOW_SPREAD,
            median * _SNAPSHOT_RATIO_SPREAD)


def bytes_per_audit_row(db_bytes, audit_rows):
    """每列位元組。

    ⚠️ 分母 0 ⇒ 回 `None`，**不是 0**（`BK24`）。
    🔑 全新安裝的第一天稽核紀錄就是 0 ——〈null 不等於 0〉：
    ☠️ 回 0 的話它會落在下界之外，**每一個全新安裝的第一天都收到一則假警報**，
    而第一天收到的假警報會決定使用者往後怎麼看待這個系統的告警。
    """
    if not audit_rows:
        return None
    return db_bytes / audit_rows


def snapshot_content_ok(counts: dict, summary: dict, db_bytes: int = 0,
                        day: str = None, ratio_samples=None,
                        ratio_enabled: bool = False) -> bool:
    """這份快照的內容合不合格。

    `counts`  快照檔裡實際數到的筆數（鍵同 `SNAPSHOT_IDENTITY_TABLES`）
    `summary` 同一天 `彙總.json` 的筆數 —— **另一條程式路徑寫的**，
              🔑 而那正是它有效的原因：`BK11` 那三天 JSON 全部正確。

    ⚠️ `ratio_enabled` 預設 `False`（`BK26`）。
    """
    for label in SNAPSHOT_IDENTITY_TABLES:
        want = summary.get(label)
        if want is None:
            continue
        got = counts.get(label)
        if got is None or got < want:
            return False

    if not ratio_enabled:
        return True
    if day and day in SNAPSHOT_RATIO_EXCEPTIONS:
        return True
    ratio = bytes_per_audit_row(db_bytes, summary.get("稽核紀錄") or 0)
    if ratio is None:
        # 分母 0 ⇒ 跳過第二部分，不是紅（`BK24`）。
        return True
    lo, hi = snapshot_ratio_bounds(ratio_samples)
    return lo <= ratio <= hi


def _snapshot_row_counts(path: str) -> tuple:
    """直接開**快照檔本身**數筆數。回 `(表名集合, {標籤: 筆數})`。

    ☠️ 觀測點必須是快照檔，不是來源庫 —— 來源庫從來沒有壞過，
    🔑 壞的是那一刻被複製出來的東西。
    ⚠️ 讀不開就回 `(None, {})`：呼叫端要把它當**失敗**，不是當通過
    （〈fail closed〉——「我不知道它裡面是什麼」不可以被當成「它是好的」）。
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None, {}
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        counts = {}
        for label, table in _SNAPSHOT_IDENTITY_SQL.items():
            if table in names:
                counts[label] = conn.execute(
                    "SELECT COUNT(*) FROM %s" % table).fetchone()[0]
        return names, counts
    except sqlite3.Error:
        return None, {}
    finally:
        conn.close()


def _recent_snapshot_sizes(exclude_day: str = None) -> list:
    """本機既有快照的檔案大小，當作倍率法的基準（`BK22`／`BK29`）。

    🔑 用**本機**那一層而不是雲端：雲端要走網路，而這道檢查跑在每一次快照之後。
    ⚠️ 排除今天自己那一份 —— 拿自己當基準的話倍率永遠是 1.0，
    ☠️ 而那是〈假綠燈：斷言驗到自己設的值〉的標準形狀。
    """
    sizes = []
    try:
        for name in sorted(os.listdir(_LOCAL_DB_BACKUP)):
            if exclude_day and name == exclude_day:
                continue
            candidate = os.path.join(_LOCAL_DB_BACKUP, name, "motrix_erp.db")
            if os.path.isfile(candidate):
                sizes.append(os.path.getsize(candidate))
    except OSError:
        return []
    return sizes


def _summary_is_comparable() -> bool:
    """身分對照的**前提**：JSON 與快照要來自同一個資料庫。

    ```
    JSON 走 `get_db()`         ⇒ 讀的是 `db.DB_PATH` **當下**的值
    快照走 `DB_PATH`           ⇒ 那是 `from db import DB_PATH` **匯入當下**的值
    ```
    🔑 正式機上兩者永遠是同一個檔 —— 而那正是這道對照有效的原因：
    **兩條不同的程式路徑讀同一份資料**，所以它們對不上就代表有東西壞了。

    ☠️ 兩者指到不同檔案時，比出來的差異是真的，**而它證明不了任何事**：
    它只是在說「這兩個資料庫的內容不一樣」—— 那本來就不一樣。
    📌 〈證據的適用範圍〉：**一個為真的比較，比的不一定是你以為的那兩個東西。**

    ⚠️ 這個情況只在測試環境出現（fixture 換掉 `db.DB_PATH`，
    而 `archive.DB_PATH` 是 import 當下抓的值）。
    ⚠️ 回 `False` 的時候**一定要留一行 log** ——
    ☠️ 一道安靜關掉自己的守門，跟一道通過的守門長得一模一樣。
    """
    import db as _db_mod
    live = getattr(_db_mod, "DB_PATH", DB_PATH)
    if os.path.abspath(DB_PATH) == os.path.abspath(live):
        return True
    logger.warning(
        "身分對照略過：快照來源 %s 與 JSON 來源 %s 不是同一個資料庫，"
        "兩者的筆數差異證明不了任何事。", DB_PATH, live)
    return False


def _snapshot_health(path: str, summary: dict = None, day: str = None) -> tuple:
    """`(合格嗎, 原因清單, 筆數)`。`summary` 給了才跑得了身分對照。"""
    if not os.path.isfile(path):
        return False, ["快照檔不存在：%s" % path], {}
    names, counts = _snapshot_row_counts(path)
    if names is None:
        return False, ["快照檔讀不開，看不出裡面有什麼資料：%s" % path], {}

    missing = [t for t in SNAPSHOT_REQUIRED_TABLES if t not in names]
    if missing:
        return False, [
            "快照裡缺少核心資料表（%s）——這份檔案不是這個系統的資料庫，"
            "或者結構不完整" % "、".join(missing)], counts

    # 🔴 `BK22` 定案版：倍率法。**無單位、不綁安裝** ⇒ 開著出貨。
    #    上界抓「別的表膨脹」（08-02／08-03 整庫 311 MB，而三張表全部正常
    #    ⇒ 身分對照對它完全免疫）；
    #    下界抓「分母那張表自己被灌爆」（身分對照是只增不減，看不到那一種）。
    # ⚠️ 歷史不足 7 份 ⇒ `snapshot_size_ok()` 回 True（`BK29` 明訂跳過）。
    history = _recent_snapshot_sizes(exclude_day=day)
    if not snapshot_size_ok(os.path.getsize(path), history):
        ratio = snapshot_size_ratio(os.path.getsize(path), history)
        return False, [
            "快照大小是前 %d 份的 %.2f 倍（合格區間 %s~%s）——"
            "不是「這一份特別大／特別小」，是**有東西失控了**"
            % (len(history), ratio, SNAPSHOT_SIZE_RATIO_LO,
               SNAPSHOT_SIZE_RATIO_HI)], counts

    if summary is not None and not snapshot_content_ok(
            counts, summary, db_bytes=os.path.getsize(path), day=day):
        return False, [
            "快照的資料筆數少於同一天的彙總紀錄（快照 %s ／彙總 %s）——"
            "這份快照很可能不是正式資料庫" % (
                {k: counts.get(k) for k in SNAPSHOT_IDENTITY_TABLES},
                {k: summary.get(k) for k in SNAPSHOT_IDENTITY_TABLES})], counts

    return True, [], counts


def _snapshot_sqlite(also_to_cloud: bool = True):
    """
    Consistent SQLite snapshot under backend/db_backups/YYYY-MM-DD/motrix_erp.db.
    Optionally copy into cloud daily folder. Returns local snapshot path or None.
    """
    today = date.today().isoformat()
    dest_dir = os.path.join(_LOCAL_DB_BACKUP, today)
    marker = os.path.join(dest_dir, ".done")
    dest = os.path.join(dest_dir, "motrix_erp.db")
    try:
        os.makedirs(dest_dir, exist_ok=True)
        if not os.path.exists(marker) or not os.path.exists(dest):
            # Use SQLite Online Backup API for a consistent copy while DB may be open
            src = sqlite3.connect(DB_PATH)
            try:
                dst = sqlite3.connect(dest)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
            # 🔴🔴 BK10：寫 `.done` 之前先看那份檔裡面有什麼。
            #
            # ☠️ 在這之前，`_snapshot_sqlite()` 是**寫完就算成功** ——
            #    沒有任何人看過快照裡面有沒有東西。
            #    2026-08-30／08-31／09-03 三份雲端備份就是這樣過關的：
            #    `PRAGMA quick_check = ok`、表數也對，只是裡面沒有資料。
            #
            # ⚠️ 這裡**沒有 `彙總.json` 可以對照** —— `_daily_backup()` 的順序是
            #    先快照、後匯出 JSON。所以這一關只驗得了「這是不是我們的庫」。
            # 🔑 真正抓那三天的是身分對照，它跑在 `_daily_backup()` 匯出之後。
            #    ⇒ **這一關守的範圍比它看起來小，不要把它當成那三天已經有人守。**
            healthy, reasons, counts = _snapshot_health(dest)
            if not healthy:
                # 📌 不寫 `.done` ⇒ 下一次排程會重做，而不是把殘缺的那份留著。
                _write_backup_alert(
                    "SQLite 快照的內容不合格，**未標記完成**（%s）：%s"
                    % (today, "；".join(reasons)), level="ERROR")
                _system_audit("backup.snapshot_rejected", today,
                              {"path": dest, "reasons": reasons, "counts": counts})
                # ⚠️ 刻意**不往下跑清理**：這一刻我們手上唯一確定的事，是今天這份
                #    快照不能信。在那種狀態下去刪舊的快照，等於用一份壞的換掉一份好的。
                # 📌 代價（明著寫下來）：若快照持續不合格，本機 `db_backups/` 會一直長。
                #    ☠️ 而那是**看得見**的；反過來那一種不是。
                return None
            with open(marker, "w", encoding="utf-8") as f:
                f.write(datetime.now().isoformat())
            logger.info("SQLite snapshot saved: %s", dest)
            _system_audit(
                "backup.sqlite_snapshot",
                today,
                {"path": dest,
                 "bytes": os.path.getsize(dest) if os.path.exists(dest) else 0,
                 "counts": counts},
            )
        if also_to_cloud and _archive_ok():
            try:
                cloud_dest = os.path.join(_daily_dir(), today, "motrix_erp.db")
                _cloud_copy_file(dest, cloud_dest, f"每日備份/{today}/motrix_erp.db")
            except Exception as e:
                _write_backup_alert(f"SQLite 快照複製到雲端失敗: {e}", level="ERROR")
        # Prune local snapshots per configured retention (see _backup_retention())
        _ret = _backup_retention()
        _prune_local_db_backups(keep_days=_ret["local_db_keep_days"],
                                pre_update_keep=_ret["local_pre_update_keep"])
        return dest
    except Exception as e:
        logger.exception("_snapshot_sqlite failed")
        _write_backup_alert(f"本機 SQLite 快照失敗: {e}", level="ERROR")
        return None


def _mirror_directory_incremental(local_root: str, dst_root_abs: str, s3_dir_root: str,
                                   exclude_demo_dirs: bool = True) -> int:
    """共用的「按檔案 size+mtime 判斷是否需要複製」鏡像邏輯（2026-09-07 從
    `_mirror_uploads()` 抽出，供 `_mirror_pdf_archives()` 共用，見該函式與
    `_mirror_uploads()` 各自的 docstring 說明用途差異）。只複製新增/變動過的
    檔案，鏡像只增不減；`exclude_demo_dirs=True` 時跳過任何 `_` 開頭的子目錄
    （demo 隔離資料夾慣例，見 db.py），回傳實際複製的檔案數。"""
    if not os.path.isdir(local_root):
        return 0
    copied = 0
    for root, dirs, files in os.walk(local_root):
        if exclude_demo_dirs:
            dirs[:] = [d for d in dirs if not d.startswith('_demo')]
        rel_root = os.path.relpath(root, local_root)
        dst_dir = dst_root_abs if rel_root == '.' else os.path.join(dst_root_abs, rel_root)
        s3_dir = s3_dir_root if rel_root == '.' else f"{s3_dir_root}/{rel_root.replace(os.sep, '/')}"
        for fname in files:
            src = os.path.join(root, fname)
            dst = os.path.join(dst_dir, fname)
            s3_key = f"{s3_dir}/{fname}"
            try:
                existing = _cloud_stat(dst, s3_key)
                if existing is not None:
                    s = os.stat(src)
                    d_size, d_mtime = existing
                    if s.st_size == d_size and int(s.st_mtime) <= int(d_mtime):
                        continue
                _cloud_copy_file(src, dst, s3_key)
                copied += 1
            except Exception:
                logger.exception("_mirror_directory_incremental failed for %s", src)
    return copied


def _mirror_uploads() -> int:
    """Incrementally sync uploads/（專案照片等實體檔案）到雲端 _uploads_mirror_dir()。

    這些檔案不在 quotations/customers/... 那幾張表裡，daily/weekly backup 原本完全
    沒有覆蓋到——db 救得回來，但照片救不回來。跟 JSON 每日備份不同的是，這裡改用
    「按檔案 size+mtime 判斷是否需要複製」的鏡像做法，而不是每天整包重新複製一份：
    上傳的照片一旦寫入通常不會再變動，若每天都整份複製，一年下來雲端空間會被同一批
    照片的 365 份重複拷貝塞滿。只複製新增/變動過的檔案，且鏡像只增不減——即使來源
    檔案被刪除，鏡像裡的舊副本仍保留（跟每日/週備份「保留歷史」的精神一致）。

    Demo 隔離目錄（uploads/_demo_projects 等，見 db.py）故意跳過：demo 帳號的資料
    本來就每次登入都會被清空，不是需要保存的真實資料。
    """
    copied = _mirror_directory_incremental(_UPLOADS_DIR, _uploads_mirror_dir(), "上傳檔案鏡像")
    if copied:
        logger.info("uploads mirror: copied %d new/changed file(s) to %s", copied, _uploads_mirror_dir())
        _system_audit("backup.uploads_mirror", date.today().isoformat(), {"copied": copied})
    return copied


def _pdf_archive_dirs() -> list:
    """回傳目前設定生效的 6 類 PDF 存檔目錄 (子資料夾代稱, 實際絕對路徑)。
    刻意呼叫 pdf_gen.py 的 `_get_*_pdf_base()` 而非直接拼預設路徑——這些
    base path 可能被 superadmin 透過 `system_settings` 改到公司共用網路磁碟等
    自訂位置（見 pdf_gen.py 各 getter docstring），備份要跟著實際生效的路徑走，
    不能假設一定是專案根目錄底下的預設資料夾。背景排程本來就不掛在任何
    request 上，`is_demo_mode()` 這些 getter 內部的判斷會自然落在預設值 False，
    跟 `get_db()` 的既有推理一致，永遠拿到正式（非 demo）路徑。"""
    import pdf_gen
    return [
        ("報價單", pdf_gen._get_pdf_base()),
        ("出貨單", pdf_gen._get_shipping_pdf_base()),
        ("承攬商匯款申請", pdf_gen._get_contractor_voucher_pdf_base()),
        ("開票申請憑據", pdf_gen._get_invoice_voucher_pdf_base()),
        ("請款單", pdf_gen._get_payment_request_pdf_base()),
        ("結案報表", pdf_gen._get_case_closing_pdf_base()),
    ]


def _mirror_pdf_archives() -> int:
    """比照 `_mirror_uploads()` 的鏡像邏輯，把 6 類 PDF 存檔目錄（報價單／出貨單／
    承攬商匯款申請／發票開立簽核單／請款單／結案報表）也納入每日雲端備份範圍
    （2026-09-07，見 MOTRIX-ERP-QUICK.md §11 已知限制條目）。這些目錄各自在
    專案根目錄下獨立存在（如 `報價單PDF/`），不在 `uploads/` 底下，過去
    `_mirror_uploads()` 完全掃不到——只有 quotations 等資料表本身有每日 JSON
    備份，已經產生好的 PDF 檔案本身從來沒被備份過，DB 救得回來但 PDF 檔案救不回來，
    跟 uploads 的照片是同一類風險。"""
    total = 0
    for subdir, local_dir in _pdf_archive_dirs():
        copied = _mirror_directory_incremental(local_dir, _pdf_mirror_dir(subdir), f"PDF存檔鏡像/{subdir}")
        total += copied
    if total:
        logger.info("PDF archive mirror: copied %d new/changed file(s) across %d categories",
                     total, len(_pdf_archive_dirs()))
        _system_audit("backup.pdf_archive_mirror", date.today().isoformat(), {"copied": total})
    return total


def _prune_audit_log(keep_days: int = 730) -> None:
    """Delete audit_log rows older than keep_days. Daily backup exports first, so nothing is lost."""
    try:
        cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()
        conn = get_db()
        cur = conn.execute("DELETE FROM audit_log WHERE at < ?", (cutoff,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        if deleted:
            logger.info("audit_log pruned: %d rows older than %d days removed", deleted, keep_days)
    except Exception:
        logger.exception("_prune_audit_log failed")


_SERVER_LOG_PATH = os.path.join(_BACKEND_DIR, "logs", "server.log")
_SERVER_LOG_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
_SERVER_LOG_KEEP_GENERATIONS = 5


def _rotate_server_log_if_large(
    log_path: str = None, max_bytes: int = _SERVER_LOG_MAX_BYTES, keep: int = _SERVER_LOG_KEEP_GENERATIONS,
) -> bool:
    """`logs/server.log` 是正式機 `autostart.bat` 用 shell `>>` 重導向寫入的
    （見該檔），不是走 Python `logging` 的 handler——伺服器 24/7 常駐執行，這個
    檔案完全沒有任何大小上限或輪替機制，長期下來可能把磁碟塞滿（正式機已經
    踩過一次「表格無限增生塞爆每日備份」的類似事故，見 §12 module_versions
    62萬列那次）。

    **這裡刻意不能用改檔名輪替（如 server_YYYY-MM-DD.log）**：`apply_update.ps1`
    的健康檢查（`$logPath = ...` 底下的 `logs/server.log`）寫死讀這個檔名判斷部署是否
    成功，換了輪替方式會讓那個檢查永遠讀到空/舊檔案，等於整套部署安全機制
    悄悄失效。改用 copytruncate：先複製目前內容到 `logs/server.log.N`（保留最新
    `keep` 份，最舊的直接刪除），再原地把 `server.log` truncate 成 0 bytes——
    `autostart.bat` 裡 `>>` 開的是 append 模式 file handle，每次寫入永遠先 seek
    到檔案目前結尾再寫，truncate 之後下一次寫入會正確從新的（空的）結尾開始，
    不需要通知或重啟寫入端。

    **⚠️ 尚未在真正跑著 autostart.bat 的正式機上驗證過**：Windows 上 cmd.exe
    的 `>>` 重導向所開檔案的共用權限（sharing flags）是否真的允許外部行程同時
    truncate，這裡沒有實機測試過，只能確保「truncate 失敗就整個放棄、log 檔案
    維持原樣繼續成長」（不會比現狀更糟，只是輪替沒生效），下次正式機套用後
    要留意 `logs/server.log` 是否真的有被清空過，見 QUICK.md §12 2026-09-07 條目。
    回傳是否真的執行了輪替（供呼叫端寫 log/測試斷言用）。"""
    path = log_path or _SERVER_LOG_PATH
    try:
        if not os.path.exists(path) or os.path.getsize(path) < max_bytes:
            return False
        log_dir = os.path.dirname(path)
        # 最舊的直接砍掉（.{keep} 若存在），其餘依序往後遞增一代
        oldest = f"{path}.{keep}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for gen in range(keep - 1, 0, -1):
            src = f"{path}.{gen}"
            if os.path.exists(src):
                os.replace(src, f"{path}.{gen + 1}")
        shutil.copy2(path, f"{path}.1")
        # copytruncate：原地清空，而不是刪除/改名，讓仍持有 append handle 的
        # 寫入端（autostart.bat 的 `>>`）下一次寫入自然從新的檔案結尾（0）開始
        with open(path, "r+b") as f:
            f.truncate(0)
        logger.info("server.log rotated (was >= %d bytes), kept %d generation(s) under %s", max_bytes, keep, log_dir)
        return True
    except Exception:
        logger.exception("_rotate_server_log_if_large failed — server.log 維持原樣未輪替")
        return False


def _prune_local_db_backups(keep_days: int = 30, pre_update_keep: int = 5) -> None:
    """清理 backend/db_backups/ 底下的兩種資料夾——它們的命名規則不同，
    所以清理規則也不同，這是 2026-09-14 補上的第二種：

    1. `YYYY-MM-DD/`  — 每日排程快照，依 keep_days 天數清除（原本就有）。
    2. `pre_update_YYYYMMDD_HHMMSS/` — apply_update.ps1 每次套用前留的整庫快照。
       **原本完全沒有被清到**：上面那個迴圈只刪「檔名 parse 得出日期」的，
       `pre_update_...` 進 `except ValueError: continue` 就直接跳過了。
       結果是每部署一次就永久多一份整庫副本——開發機實測累積到 49 份、
       整個 db_backups 吃掉 1.8 GB，正式機只會更多（那才是真正跑套用的地方）。
       改成比照 rollback_snapshots 的做法**按份數保留最新 N 份**，不用天數：
       這些快照的價值來自「最近幾次部署」而不是「最近幾天」，隔了三個月才
       部署一次的話，用天數會把唯一一份退路也刪掉。

    兩段各自 try/except：pre_update 這段是後加的，不該讓它的意外影響到原本
    就在運作的每日快照清理。
    """
    try:
        if not os.path.isdir(_LOCAL_DB_BACKUP):
            return
        cutoff = date.today().toordinal() - keep_days
        for name in os.listdir(_LOCAL_DB_BACKUP):
            path = os.path.join(_LOCAL_DB_BACKUP, name)
            if not os.path.isdir(path):
                continue
            try:
                d = date.fromisoformat(name)
            except ValueError:
                continue
            if d.toordinal() < cutoff:
                shutil.rmtree(path, ignore_errors=True)
                logger.info("Pruned old SQLite snapshot dir: %s", path)
    except Exception:
        logger.exception("_prune_local_db_backups failed")

    try:
        _prune_pre_update_snapshots(keep=pre_update_keep)
    except Exception:
        logger.exception("_prune_pre_update_snapshots failed")


_PRE_UPDATE_PREFIX = "pre_update_"


def _prune_pre_update_snapshots(keep: int = 5) -> None:
    """只保留最新 `keep` 份 `pre_update_*` 快照（見 _prune_local_db_backups
    docstring）。`keep <= 0` 視為「不清理」，不會把全部刪光——這是刻意的
    防呆：設定值被寫成 0 或空字串時，安全的行為是什麼都不做，而不是把所有
    部署退路一次刪掉。

    排序用資料夾名稱字串排序即可（`pre_update_YYYYMMDD_HHMMSS` 這個格式的
    字典序等於時間序），不依賴檔案系統的 mtime——mtime 會被複製/還原動作
    改掉，名字裡的時間戳才是真的。
    """
    if keep <= 0:
        return
    if not os.path.isdir(_LOCAL_DB_BACKUP):
        return
    snaps = sorted(
        n for n in os.listdir(_LOCAL_DB_BACKUP)
        if n.startswith(_PRE_UPDATE_PREFIX)
        and os.path.isdir(os.path.join(_LOCAL_DB_BACKUP, n))
    )
    for name in snaps[:-keep] if len(snaps) > keep else []:
        shutil.rmtree(os.path.join(_LOCAL_DB_BACKUP, name), ignore_errors=True)
        logger.info("Pruned old pre-update snapshot: %s", name)


def _prune_cloud_backups(daily_keep_days: int = 60, weekly_keep_days: int = 90,
                         monthly_keep_days: int = 0) -> None:
    """Delete dated folders under 每日備份／週備份／月備份 (wherever the cloud
    drive is currently mounted) once older than the retention window. Mirrors
    _prune_local_db_backups's safety: only ever deletes a folder whose name
    parses cleanly as the expected date pattern for that directory
    (YYYY-MM-DD for daily, YYYY-Wxx for weekly, YYYY-MM for monthly) —
    anything else (unexpected file/folder name) is left untouched, never
    guessed at. No-ops entirely if the cloud drive isn't mounted (never
    operates on a partial/offline view of the archive).

    `monthly_keep_days <= 0` 代表**永久保留**（預設值，2026-09-14 使用者裁示
    「長久只留月備份」），整段直接跳過。

    ⚠️ 這支函式**只**走這三個目錄。`上傳檔案鏡像/` 與 `PDF存檔鏡像/` 是使用者
    明訂要長久保留的原始憑據（照片、簽回單、各類單據 PDF），任何情況下都不該
    被這裡掃到——不要因為「順手清一下舊照片」把它們加進來。
    test_backup_retention_policy_2026_09_14.py 有一題專門守這件事。
    """
    if not _archive_ok():
        return

    cutoff_daily = date.today().toordinal() - daily_keep_days
    try:
        for name in _cloud_list_top_level(_daily_dir(), "每日備份"):
            try:
                d = date.fromisoformat(name)
            except ValueError:
                continue
            if d.toordinal() < cutoff_daily:
                _cloud_delete_dir(os.path.join(_daily_dir(), name), f"每日備份/{name}")
                logger.info("Pruned old cloud daily backup dir: %s", name)
    except Exception:
        logger.exception("_prune_cloud_backups (daily) failed")

    cutoff_weekly = date.today().toordinal() - weekly_keep_days
    try:
        for name in _cloud_list_top_level(_weekly_dir(), "週備份"):
            try:
                year_str, week_str = name.split('-W')
                d = datetime.strptime(f"{year_str} {week_str} 1", "%Y %W %w").date()
            except (ValueError, IndexError):
                continue
            if d.toordinal() < cutoff_weekly:
                _cloud_delete_dir(os.path.join(_weekly_dir(), name), f"週備份/{name}")
                logger.info("Pruned old cloud weekly backup dir: %s", name)
    except Exception:
        logger.exception("_prune_cloud_backups (weekly) failed")

    if monthly_keep_days <= 0:
        return          # 永久保留（預設）
    cutoff_monthly = date.today().toordinal() - monthly_keep_days
    try:
        for name in _cloud_list_top_level(_monthly_dir(), "月備份"):
            try:
                d = date.fromisoformat(f"{name}-01")     # YYYY-MM → 當月 1 號
            except ValueError:
                continue
            if d.toordinal() < cutoff_monthly:
                _cloud_delete_dir(os.path.join(_monthly_dir(), name), f"月備份/{name}")
                logger.info("Pruned old cloud monthly backup dir: %s", name)
    except Exception:
        logger.exception("_prune_cloud_backups (monthly) failed")


def _backup_quotation(quote_no: str):
    try:
        conn = get_db()
        row  = conn.execute("SELECT * FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        conn.close()
        if not row:
            return
        payload = dict(row)
    except Exception as e:
        logger.exception("_backup_quotation failed reading DB for %s", quote_no)
        return

    if _archive_ok():
        try:
            path = os.path.join(_realtime_dir(), "報價單", f"{quote_no}.json")
            _cloud_write_json(path, f"即時備份/報價單/{quote_no}.json", payload)
            return
        except Exception as e:
            logger.exception("_backup_quotation cloud write failed for %s", quote_no)
            _write_backup_alert(f"即時備份報價單失敗（雲端）{quote_no}: {e}")

    # cloud archive unavailable — write to local instant-backup dir
    try:
        local_dir = os.path.join(_LOCAL_DB_BACKUP, "quotation_instant")
        os.makedirs(local_dir, exist_ok=True)
        path = os.path.join(local_dir, f"{quote_no}.json")
        _atomic_json_write(path, payload)
    except Exception as e:
        logger.exception("_backup_quotation local fallback failed for %s", quote_no)
        _write_backup_alert(f"即時備份報價單失敗（本機）{quote_no}: {e}")


def _backup_customers():
    if not _archive_ok():
        return
    try:
        conn  = get_db()
        rows  = conn.execute("SELECT * FROM customers ORDER BY id").fetchall()
        conn.close()
        data  = {
            "exported_at": datetime.now().isoformat(),
            "count": len(rows),
            "data": [dict(r) for r in rows],
        }
        path = os.path.join(_realtime_dir(), "客戶", "clients.json")
        _cloud_write_json(path, "即時備份/客戶/clients.json", data)
    except Exception as e:
        logger.exception("_backup_customers failed")
        _write_backup_alert(f"即時備份客戶失敗: {e}")


def _backup_suppliers():
    if not _archive_ok():
        return
    try:
        conn = get_db()
        rows = conn.execute("SELECT * FROM suppliers ORDER BY id").fetchall()
        conn.close()
        data = {
            "exported_at": datetime.now().isoformat(),
            "count": len(rows),
            "data": [dict(r) for r in rows],
        }
        path = os.path.join(_realtime_dir(), "供應商", "suppliers.json")
        _cloud_write_json(path, "即時備份/供應商/suppliers.json", data)
    except Exception as e:
        logger.exception("_backup_suppliers failed")
        _write_backup_alert(f"即時備份供應商失敗: {e}")


# 每日 JSON 匯出裡一律不留內嵌影像（2026-09-14）。
#
# 為什麼要有這一層：承攬人員把**身分證正反面**與存摺影像以 base64 存在欄位裡，
# 協力廠商的 data_json、承攬付款憑據的 snapshot_json 又各自把存摺影像包在裡面
# （snapshot 甚至是包在 personnel[] 陣列中）。實測 5 位承攬人員就是 3.2 MB，
# 逐表 JSON 每天寫一次、還鏡像到雲端、保留 30 天——等於把一疊身分證掃描件
# 每天複製一份放到雲端資料夾。
#
# 影像本身沒有不見：整庫複製那兩層（本機 db_backups + 雲端 motrix_erp.db）
# 是完整的 .db 檔。這裡拿掉的是「人看得懂那一份」裡的影像，剩下的欄位照舊。
#
# 刻意寫成**一條通則**而不是逐表挑欄位：下一個把圖塞進 JSON 欄位的人
# 不需要記得回來改這裡。tests/test_system_audit_2026_09_14.py 的
# test_backup_export_has_no_inline_images 會盯著。
_INLINE_IMAGE_PREFIX = "data:image/"
_IMAGE_PLACEHOLDER = "<影像未收錄於 JSON 匯出，請用整庫備份還原>"


def _strip_inline_images(value):
    """遞迴把 data:image/... 的 base64 影像換成佔位字串。

    存成 TEXT 的 JSON 欄位（data_json / snapshot_json）會先 parse 再處理，
    處理完重新序列化——所以匯出的還是合法 JSON 字串，只是影像被抽掉。
    parse 不起來就原樣保留，不要為了清影像把資料弄壞。
    """
    if isinstance(value, str):
        if value.startswith(_INLINE_IMAGE_PREFIX):
            return _IMAGE_PLACEHOLDER
        if _INLINE_IMAGE_PREFIX in value:
            try:
                parsed = json.loads(value)
            except Exception:
                return value
            return json.dumps(_strip_inline_images(parsed), ensure_ascii=False)
        return value
    if isinstance(value, dict):
        return {k: _strip_inline_images(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_inline_images(v) for v in value]
    return value


def _daily_backup_tables() -> dict:
    """每日 JSON 匯出的 {檔名: SQL}。

    **2026-09-14 從 _daily_backup() 裡搬出來**，理由有兩個：
      ① `tests/test_system_audit_2026_09_14.py` 原本得用正規表示式去解析
         函式裡那個 local dict 的原始碼；改成直接 import 呼叫就不可能解析歪掉。
      ② 測試需要能塞一條壞查詢進去，驗證「單張表失敗時不可以還是報
         backup.daily_ok」——local 變數沒辦法 monkeypatch。

    新增資料表時請一起決定要不要進來（鍵＝檔名、值＝完整 SELECT）。
    漏掉會被 test_every_table_is_either_backed_up_or_explicitly_excluded 擋下。
    ⚠️ 這一層是 §8.3「還原優先序」的**最後手段**（本機整庫 → 雲端整庫 →
    JSON 重建）。前兩層是整個 .db 檔，涵蓋全部 76 張表；這裡的 41 張是
    「人看得懂、可以單獨挑出來重建」的那一份。
    """
    return {
        # ── 主檔 ──
        "報價單":           "SELECT * FROM quotations ORDER BY id",
        "客戶":             "SELECT * FROM customers ORDER BY id",
        "供應商":           "SELECT * FROM suppliers ORDER BY id",
        "料號":             "SELECT * FROM parts ORDER BY id",
        "專案":             "SELECT * FROM projects ORDER BY id",
        # ── 帳號與組織（2026-09-14 補）──
        # 使用者**刻意逐欄列出、略過所有憑證欄位**：password_hash /
        # unlock_password_hash / daily_task_pw_hash 是雜湊，本身不算祕密，
        # 但 totp_secret 與 totp_recovery_codes 是**可以直接拿去產生有效
        # 驗證碼的金鑰**，寫進人看得懂的 JSON 等於把兩階段驗證抄一份出來。
        # 整庫複製那一層本來就含這些欄位（.db 檔），JSON 這層不需要再抄。
        # 代價：從 JSON 還原時所有人都要重設密碼、重新綁定 2FA/Passkey——
        # 走到最後手段本來就該這樣做（來路不明的舊憑證不該直接沿用）。
        "使用者":           ("SELECT id, username, display_name, role, email, phone, "
                             "modules, active, created_at, must_change_password, "
                             "notification_muted, department_id, totp_enabled "
                             "FROM users ORDER BY id"),
        "部門":             "SELECT * FROM departments ORDER BY id",
        "事業處":           "SELECT * FROM divisions ORDER BY id",
        "簽核代理":         "SELECT * FROM approval_delegates ORDER BY id",
        # 通行金鑰只留 metadata 用途：告訴管理員「誰原本有綁 Passkey、要通知誰重綁」。
        #
        # ⚠️ **不可以 SELECT ***：credential_id / public_key 宣告成 BLOB，
        # 取出來是 Python bytes，json.dumps() 直接 TypeError，於是這張表
        # 每天靜默記一筆 "error"、從上線起就沒有真的被匯出過（2026-09-16 修，
        # 見 §12）。SQL 本身跑得起來，所以 test_every_backup_query_actually_runs
        # 一路是綠的——觀測點停在「查詢執行成功」，離真正的失敗點還差一步。
        #
        # 而且這兩欄匯出本來也沒有意義：Passkey 的私鑰在使用者的裝置／認證器裡，
        # 備份裡的公鑰與憑證 ID 不能讓任何人登入，也不能拿去重建憑證（重綁一定
        # 得由本人的裝置重新簽發）。本表在 §8.3 最後手段裡要回答的是「誰原本有綁、
        # 要通知誰重綁」——user_id + name + created_at 就足夠，二進位欄位純屬負擔。
        "通行金鑰":         ("SELECT id, user_id, name, sign_count, rp_id, "
                             "created_at, last_used_at "
                             "FROM webauthn_credentials ORDER BY id"),
        # ── 系統設定 ──
        # §0 記載過：正式機的 webauthn_rp_id / webauthn_origin 不在 git 裡，
        # 還原舊 db 時這兩個值會整個消失。這張表是那次事故的直接對策。
        #
        # ⚠️ **但這張表裡有真的祕密**，不能直接 SELECT *：
        #   email_notify.smtp_password       寄信用的 SMTP 密碼
        #   google_calendar.client_secret    OAuth client secret
        #   google_calendar.refresh_token    可以無限換取 access token
        # 這三個跟使用者的 totp_secret 同一個等級——寫進人看得懂的 JSON
        # 等於把可直接使用的認證素材放進備份資料夾（還會鏡像到雲端）。
        # 用 json_remove() 只挖掉這幾個欄位，其餘設定（收件人、SMTP 主機、
        # calendar_id…）照常保留，還原時只要重新填這三個值。
        # 新增祕密設定時要記得加進來——tests/test_system_audit_2026_09_14.py
        # 的 test_settings_export_has_no_live_secrets 會掃匯出結果，漏掉會紅。
        "系統設定":         ("SELECT key, CASE key "
                             "WHEN 'email_notify' THEN json_remove(value_json, '$.smtp_password') "
                             "WHEN 'google_calendar' THEN json_remove(value_json, '$.client_secret', '$.refresh_token') "
                             "ELSE value_json END AS value_json, updated_at "
                             "FROM system_settings ORDER BY key"),
        # ── 案件與單據 ──
        "案件階段":         "SELECT * FROM case_stages ORDER BY id",
        "案件階段拜訪":     "SELECT * FROM case_stage_visits ORDER BY id",
        "案件動態":         "SELECT * FROM case_updates ORDER BY id",
        "案件額外支出":     "SELECT * FROM case_extra_expenses ORDER BY id",
        "案件變更申請":     "SELECT * FROM case_change_requests ORDER BY id",
        "案件待辦":         "SELECT * FROM case_action_items ORDER BY id",
        "出貨單":           "SELECT * FROM shipping_notes ORDER BY id",
        "完工單":           "SELECT * FROM completion_notes ORDER BY id",
        "請款單":           "SELECT * FROM payment_requests ORDER BY id",
        "開票申請憑據":     "SELECT * FROM invoice_vouchers ORDER BY id",
        "承攬付款憑據":     "SELECT * FROM contractor_payment_vouchers ORDER BY id",
        "承攬派工":         "SELECT * FROM contractor_dispatches ORDER BY id",
        "承攬人員":         "SELECT * FROM contractors ORDER BY id",
        "協力廠商":         "SELECT * FROM vendor_contractors ORDER BY id",
        "T100匯出確認":     "SELECT * FROM t100_export_confirmations ORDER BY id",
        # ── 業務開發 ──
        "業務開發案件":     "SELECT * FROM dev_cases ORDER BY id",
        "業務開發記錄":     "SELECT * FROM dev_logs ORDER BY id",
        # ── 工作與日誌 ──
        "每日工作":         "SELECT * FROM daily_tasks ORDER BY id",
        "每日工作完成":     "SELECT * FROM daily_task_completions ORDER BY id",
        "每日工作異動":     "SELECT * FROM daily_task_edit_log ORDER BY id",
        "工作日誌":         "SELECT * FROM work_logs ORDER BY id",
        "專案日誌":         "SELECT * FROM project_logs ORDER BY id",
        "專案階段":         "SELECT * FROM project_stages ORDER BY id",
        # ── 其他業務資料 ──
        "薪資單":           "SELECT * FROM payslips ORDER BY id",
        "網路架構規劃書":   "SELECT * FROM network_plans ORDER BY id",
        "庫存品項":         "SELECT * FROM stock_items ORDER BY id",
        "庫存批次":         "SELECT * FROM stock_batches ORDER BY batch_no",  # 無 id 欄
        # 2026-09-21：採購建議的下單／到貨紀錄。**必須進備份**——
        # 「這個料號是哪天下單的、哪天到貨的」在系統裡沒有第二個來源，
        # 採購建議本身是即時從庫存算出來的，重算得出清單但重算不出這段歷史。
        "採購建議狀態":     "SELECT * FROM purchase_suggestion_status ORDER BY part_no",  # 無 id 欄
        # ── 標案雷達（2026-09-21）──
        # ⚠️ 三條都用 `SELECT *` 而不是列舉欄位：這三張沒有敏感欄位
        # （不像 users.password_hash／webauthn_credentials 是刻意略過的），
        # 而**列舉欄位的表，日後加欄位不會有人發現它沒被備份**。
        #
        # 🔴 `tender_watches` 是**必須**不是建議：其餘兩張最壞是失去歷史，
        # 它失去的是**設定**。還原之後系統跑得起來、每個畫面都正常，
        # 而雷達從此什麼都找不到——使用者只會覺得「最近都沒標案」，
        # 不會覺得「備份漏了東西」。**壞掉會被報修，設定不見不會。**
        #
        # ⚠️ `tenders` 看起來像「選型資料庫」那一類（可重跑所以不必備份），**但它不是**：
        # 選型資料庫的內容由 sync_*.py 產生、**git 裡有來源**；
        # `tenders` 的來源是一個**會把已截止標案刪掉的外部網站**，
        # 重跑只拿得回「今天還掛著的」。別被表面的相似騙了。
        "標案搜尋條件":     "SELECT * FROM tender_watches ORDER BY id",
        "標案":             "SELECT * FROM tenders ORDER BY id",
        "標案命中":         "SELECT * FROM tender_hits ORDER BY id",
        # ── 紀錄類 ──
        "稽核紀錄":         "SELECT * FROM audit_log ORDER BY id",
        # 🔑 Google 額度計數器（§16 GB1）。**它算不回來。**
        # ☠️ 掉了就從 0 重算 ⇒ 我們會以為還有額度，而自動降回免費**太晚觸發**
        #    ⇒ 真的花到錢。〈計數器要有落點〉的落點本身也要有備份。
        # 📌 它很小（一個週期一個 SKU 一列），進 JSON 幾乎沒有成本。
        "地理查詢用量":     "SELECT * FROM geocode_usage ORDER BY id",
        "通知":             "SELECT * FROM notifications ORDER BY id",
        "模組版本":         "SELECT * FROM module_versions ORDER BY id",
        # ── 會計項目（v93，2026-09-23 補）────────────────────────────
        #
        # 🔑 **整張備份，不要只備 `source != 'statutory'` 的那幾列。**
        # 表面上法定那 547 筆長得像「選型資料庫」那一類（由 migration 產生、
        # 來源 `data/account_items_112.json` 在 git 裡 ⇒ 可重建 ⇒ 不必備份），
        # ☠️ **而那個類比在還原的那一刻會害人**：
        # ```
        # 只備自訂  => 災難還原時有人打開「會計項目.json」，看到 3 筆
        #             => 他會以為科目表壞了／備份漏了
        # ```
        # 📌 而代價只是每天多抄 547 列靜態資料 —— **位元組很便宜，
        #    在還原現場誤判「資料沒了」很貴。**
        # ⚙️ 兩者分得出來：`source` 欄位是 `statutory` / `custom`。
        "會計項目":         "SELECT * FROM account_items ORDER BY code",  # 無 id 欄
        # ── 傳票（v95，2026-09-23）──────────────────────────────────
        #
        # 🔴 這五張是**會計憑證本身**，不是軌跡：掉了就是帳掉了。
        # ⚠️ `voucher_edit_log` 看起來像「紀錄類」（audit_log 那一群），**而它不是**：
        #    施工圖 `§2.3` 要求「改過傳票日期要留改前→改後」，那是**憑證的一部分**，
        #    ☠️ 少了它，一張傳票**看起來完全正常**，而沒有人回得出它被改過什麼。
        # 📌 `voucher_template_versions` 同理：摘要凍結時存了
        #    `summary_template_id` ＋ `version`，**指向的那一版不見了就追不回來**。
        # 🔴 **`vouchers_all` 不是筆誤**：`vouchers` 是只露出未作廢的 VIEW，
        #    備份它等於**把已作廢的傳票排除在備份之外**。
        # ☠️ 而作廢單正是最需要留存的那一種（稽核要看得到「這一張作廢過」），
        #    ⇒ 用 VIEW 備份的話，還原之後**那些單會整個消失，而帳面看起來很正常**。
        "傳票":             "SELECT * FROM vouchers_all ORDER BY id",
        "傳票分錄":         "SELECT * FROM voucher_lines ORDER BY voucher_id, line_no",
        "傳票異動":         "SELECT * FROM voucher_edit_log ORDER BY id",
        "傳票範本":         "SELECT * FROM voucher_templates ORDER BY id",
        "傳票範本版本":     ("SELECT * FROM voucher_template_versions"
                             " ORDER BY template_id, version"),  # 無 id 欄
    }


def _export_table_json_set(conn, dest_dir_abs: str, s3_prefix: str, now: str) -> dict:
    """把 _daily_backup_tables() 的每一張表各匯出成一個 JSON 檔到指定目的地，
    回傳 {表名: 筆數 or "error"} 的 summary。

    抽出來的理由是月備份層（2026-09-14）要寫的內容跟每日備份**完全相同**，
    只是目的地資料夾不一樣。與其複製一份幾乎一樣的迴圈（兩份會慢慢分岔，
    然後某天有人只在其中一份加了新表），不如讓兩邊共用同一段——新增資料表
    時只會有一個地方要改，而 test_system_audit_2026_09_14.py 的
    `_NOT_IN_JSON_BACKUP` 清單守的也正是這一個地方。

    per-table 的 try/except 是刻意保留的（原本就在 _daily_backup() 裡）：
    一張表壞掉不該讓其他 40 張也備不成。呼叫端負責看 summary 裡有沒有
    "error" 並決定要報 daily_ok 還是 daily_partial。
    """
    summary: dict = {}
    for fname, sql in _daily_backup_tables().items():
        try:
            rows = [_strip_inline_images(dict(r)) for r in conn.execute(sql).fetchall()]
            _cloud_write_json(
                os.path.join(dest_dir_abs, f"{fname}.json"),
                f"{s3_prefix}/{fname}.json",
                {"exported_at": now, "count": len(rows), "data": rows},
            )
            summary[fname] = len(rows)
        except Exception:
            logger.exception("table export %s failed (dest=%s)", fname, s3_prefix)
            summary[fname] = "error"
    return summary


def _monthly_backup():
    """月備份（2026-09-14 使用者裁示「長久只留月備份」）——**永久保留**的那一層。

    內容跟每日備份一模一樣（41 張表 JSON ＋ 整份 motrix_erp.db），差別只在
    目的地是 `月備份/YYYY-MM/` 而且不會被 _prune_cloud_backups() 清除
    （除非有人把 cloud_monthly_keep_days 設成大於 0 的值）。

    **執行時機是「當月第一次成功的每日備份」**，不是月底也不是 1 號——理由是
    1 號那天機器有可能沒開、備份有可能失敗，綁死日期會讓整個月直接沒有長期
    備份且沒人發現。綁在「當月第一次成功」上則不管哪天開機都一定拿得到一份。
    `.done` marker 在 `月備份/YYYY-MM/.done`，同月不會重複寫。

    由 _daily_backup() 在 JSON 匯出成功之後呼叫；失敗只告警不影響每日那一層
    （每日層才是日常回溯真正會用到的）。
    """
    month_label = date.today().strftime('%Y-%m')
    month_dir   = os.path.join(_monthly_dir(), month_label)
    marker      = os.path.join(month_dir, '.done')
    s3_dir      = f"月備份/{month_label}"
    if _cloud_marker_exists(marker, f"{s3_dir}/.done"):
        return

    conn = get_db()
    try:
        now     = datetime.now().isoformat()
        summary = _export_table_json_set(conn, month_dir, s3_dir, now)
    finally:
        conn.close()

    summary["month"] = month_label
    summary["exported_at"] = now

    # 整庫 .db 也要進月備份——JSON 那層刻意不收憑證欄位與內嵌影像（見 §8.3），
    # 只有整庫檔案是完整的。長期保留的那一份如果只有 JSON，等於長期保留了一份
    # 殘缺的資料。來源用本機當日快照（_snapshot_sqlite() 在 _daily_backup()
    # 一開頭就已經跑過，這時一定存在）。
    today_snapshot = os.path.join(_LOCAL_DB_BACKUP, date.today().isoformat(), "motrix_erp.db")
    # 🔴🔴 BK12：月備份的來源就是那份每日快照 ⇒ **快照是空的，永久備份就永久是空的。**
    # ☠️ 月備份一個月只跑一次，而 `.done` 照寫 ⇒ 那個月不會再試。
    # ✅ 2026-09 這一份是正常的 —— 📌 **那是運氣，不是設計**：
    #    月備份剛好沒有落在 08-30／08-31／09-03 那三天。
    # 🔑 這裡**有 `summary` 可以對照**（JSON 已經匯出完），所以身分對照跑得起來。
    # ⚠️ 前提不成立時**仍然驗結構**，只是不做身分對照 ——
    # 🔑 「這份檔是不是我們的資料庫」不需要對照組，而那一半照樣守得住。
    # ☠️ 整個跳過的話，`BK12`（月備份複製了一份空庫）就沒有人守了。
    snap_ok, snap_reasons, _snap_counts = _snapshot_health(
        today_snapshot,
        summary=summary if _summary_is_comparable() else None,
        day=month_label)
    if os.path.isfile(today_snapshot) and not snap_ok:
        summary["db_snapshot"] = False
        _write_backup_alert(
            "月備份（%s）的當日快照內容不合格，**未複製、未標記完成**：%s"
            % (month_label, "；".join(snap_reasons)), level="ERROR")
    elif os.path.isfile(today_snapshot):
        try:
            _cloud_copy_file(today_snapshot,
                             os.path.join(month_dir, "motrix_erp.db"),
                             f"{s3_dir}/motrix_erp.db")
            summary["db_snapshot"] = True
        except Exception as e:
            summary["db_snapshot"] = False
            _write_backup_alert(f"月備份整庫複製失敗（{month_label}）: {e}", level="ERROR")
    else:
        summary["db_snapshot"] = False
        _write_backup_alert(
            f"月備份找不到當日本機 SQLite 快照（{today_snapshot}），"
            f"{month_label} 這份長期備份只有 JSON、沒有整庫檔案", level="ERROR")

    _cloud_write_json(os.path.join(month_dir, '彙總.json'), f"{s3_dir}/彙總.json", summary)

    # 🔴🔴 BK5：`summary["db_snapshot"] = False` 先前**不在 `failed` 裡**。
    # ☠️ 成因是一個型別比對：`False == "error"` 是假的
    #    ⇒ 整庫 `.db` 複製失敗時照樣寫 `.done`
    #    ⇒ 那個月的永久備份**永遠殘缺**，而沒有人會再試一次。
    # 🔑 代價是實的：資料庫 82 張表而 JSON 只涵蓋 45 張 ⇒ **37 張只靠那份整庫檔**，
    #    其中包含選型資料庫七類的 28 張表。
    # 📌 〈假綠燈〉：告警**已經有了**（`level="ERROR"`），而 `.done` 也寫了 ——
    #    「有沒有人被通知」與「這件事會不會再試一次」是兩個問題。
    failed = [k for k, v in summary.items() if v == "error"]
    if summary.get("db_snapshot") is False:
        failed.append("整庫檔案")
    if failed:
        # 月備份是永久保留的那一份，內容不完整比每日層嚴重得多——**不寫 .done**，
        # 讓明天的每日備份再試一次，直到這個月真的拿到一份完整的為止。
        _system_audit("backup.monthly_partial", month_label, summary)
        _write_backup_alert(
            "月備份（%s）有 %d 張表匯出失敗：%s。**尚未標記完成**，明日每日備份會再試一次。"
            % (month_label, len(failed), "、".join(failed)), level="ERROR")
        return

    _cloud_write_marker(marker, f"{s3_dir}/.done")
    _system_audit("backup.monthly_ok", month_label, summary)
    logger.info("Monthly backup completed: %s", month_dir)


def _daily_backup():
    # Always snapshot SQLite locally first (independent of the cloud drive)
    _snapshot_sqlite(also_to_cloud=True)

    # 同樣不依賴雲端是否可用、也不受下方「今天已經跑過」的 .done 早退影響——
    # server.log 的成長跟雲端備份完全無關，見 _rotate_server_log_if_large() docstring
    _rotate_server_log_if_large()

    if not _archive_ok():
        _write_backup_alert(
            f"雲端備份路徑不可用（任一磁碟機代號下都找不到 {_ARCHIVE_SUBPATH}），"
            f"已略過 JSON 每日備份與 uploads/ 鏡像；本機 SQLite 快照見 {_LOCAL_DB_BACKUP}",
            level="ERROR",
        )
        return

    try:
        _mirror_uploads()
    except Exception:
        logger.exception("_mirror_uploads failed in daily schedule")
        _write_backup_alert("uploads/ 雲端鏡像失敗，詳見 server.log", level="ERROR")

    try:
        _mirror_pdf_archives()
    except Exception:
        logger.exception("_mirror_pdf_archives failed in daily schedule")
        _write_backup_alert("PDF 存檔雲端鏡像失敗，詳見 server.log", level="ERROR")

    try:
        today_label = date.today().isoformat()
        day_dir     = os.path.join(_daily_dir(), today_label)
        marker      = os.path.join(day_dir, '.done')
        if _cloud_marker_exists(marker, f"每日備份/{today_label}/.done"):
            _clear_backup_alert_if_healthy()
            return
        conn = get_db()
        now  = datetime.now().isoformat()

        summary: dict = {"date": today_label, "exported_at": now}
        summary.update(_export_table_json_set(
            conn, day_dir, f"每日備份/{today_label}", now))

        conn.close()
        _cloud_write_json(os.path.join(day_dir, '彙總.json'), f"每日備份/{today_label}/彙總.json", summary)

        # 🔴🔴 BK10 身分對照 —— **這一關才是抓 08-30／08-31／09-03 的那一關。**
        #
        # 🔑 為什麼排在這裡而不是排在 `_snapshot_sqlite()` 裡：
        #    對照組是**同一天的 `彙總.json`**，而它到上面那一行才存在。
        #    兩邊是兩條不同的程式路徑（JSON 走 `get_db()`、快照走 `DB_PATH`）
        #    ⇒ 那三天 JSON 全部正確，只有快照是空的 ⇒ **比得出來。**
        #
        # ⚠️ 這時候雲端那份 `.db` 已經複製過去了（`_snapshot_sqlite()` 做的）。
        #    ☠️ **我不刪它** —— 刪掉使用者的備份檔是破壞性動作，而且刪錯就沒了。
        #    ⇒ 能做的是：**不寫 `.done`** ＋ 告警。不寫 marker 的效果是
        #    明天的排程會把這一天整個重做一次，而那正是我們要的。
        #
        # ⚠️ **只在快照檔存在時比。**
        # 🔑 快照根本沒產生出來是另一件事，而 `_snapshot_sqlite()` 已經對它
        #    發過告警了 —— 在這裡再判一次，等於把「整庫沒做成」與「整庫內容
        #    不對」混成同一則訊息，而那兩件事的處置不同。
        # ☠️ 明著寫下這是一道 fail-open 的接縫：**檔案不見就不比**。
        #    擋它的是上游那一關，不是這一關。
        _snap_today = os.path.join(_LOCAL_DB_BACKUP, today_label, "motrix_erp.db")
        _snap_ok, _snap_reasons, _snap_counts = (True, [], {})
        # 🔴 前提見 `_summary_is_comparable()`：兩邊要來自同一個資料庫。
        if _summary_is_comparable() and os.path.isfile(_snap_today):
            _snap_ok, _snap_reasons, _snap_counts = _snapshot_health(
                _snap_today, summary=summary, day=today_label)
        if not _snap_ok:
            _system_audit("backup.daily_snapshot_mismatch", today_label,
                          {"reasons": _snap_reasons, "counts": _snap_counts})
            _write_backup_alert(
                "每日備份（%s）的整庫快照與當日彙總對不上，**未標記完成**：%s。"
                "☠️ 檔案在、大小合理、結構也對，而裡面的資料不是正式庫的 ——"
                "2026-08-30／08-31／09-03 三天就是這個樣子。"
                % (today_label, "；".join(_snap_reasons)), level="ERROR")
            return

        _cloud_write_marker(marker, f"每日備份/{today_label}/.done")
        logger.info("Daily backup completed: %s", day_dir)

        # 單張表匯出失敗**不可以還是報 daily_ok**（2026-09-14）。
        # 上面那個 per-table try/except 是刻意的：一張表壞掉不該讓其他 40 張
        # 也備不成。但原本失敗只在 log 留一行、在彙總.json 記一個 "error"，
        # 然後照樣寫 .done、照樣送 backup.daily_ok——備份頁面顯示綠燈，
        # 實際上那張表每天都是空的，要還原時才會發現。
        # （這不是假設：庫存批次 "ORDER BY id" 就是這樣，表存在、語法正確，
        #  只有執行時才炸。現在 tests/test_system_audit_2026_09_14.py 的
        #  test_every_backup_query_actually_runs 會先攔下來。）
        # 用 WARN 不用 ERROR：整庫複製那一層不受影響、沒有資料遺失風險，
        # 不值得每天寄信給所有管理員；要升級成寄信把 level 改成 "ERROR" 即可。
        failed = [k for k, v in summary.items() if v == "error"]
        if failed:
            _system_audit("backup.daily_partial", today_label, summary)
            _write_backup_alert(
                "每日 JSON 匯出有 %d 張表失敗：%s"
                "（其餘已完成；整庫複製不受影響，但 JSON 還原會少這幾張）"
                % (len(failed), "、".join(failed)),
                level="WARN")
        else:
            _system_audit("backup.daily_ok", today_label, summary)
            _clear_backup_alert_if_healthy()

        # 月備份（永久保留層，2026-09-14）——放在每日 JSON 匯出**之後**，因為它
        # 要複製的整庫快照由本函式開頭的 _snapshot_sqlite() 產生；而且只有每日
        # 這一層確定寫得進去，月備份才有可能寫得進去。自己有 .done marker，
        # 同月只會真的做一次，其餘日子是一次 marker 檢查就返回。
        # 失敗不影響每日層：包在自己的 try 裡，日常回溯靠的是每日層。
        try:
            _monthly_backup()
        except Exception:
            logger.exception("_monthly_backup failed in daily schedule")
            _write_backup_alert("月備份（永久保留層）失敗，詳見 server.log", level="ERROR")

        retention = _backup_retention()
        _prune_audit_log(keep_days=retention["audit_log_keep_days"])
        _prune_cloud_backups(daily_keep_days=retention["cloud_daily_keep_days"],
                              weekly_keep_days=retention["cloud_weekly_keep_days"],
                              monthly_keep_days=retention["cloud_monthly_keep_days"])
    except Exception as e:
        logger.exception("_daily_backup failed")
        _write_backup_alert(f"每日雲端 JSON 備份失敗: {e}", level="ERROR")


def _schedule_daily():
    _daily_backup()
    try:
        _cleanup_sessions()
    except Exception:
        logger.exception("_cleanup_sessions failed in daily schedule")
    t = threading.Timer(2 * 3600, _schedule_daily)
    t.daemon = True
    t.start()


def _weekly_backup():
    if not _archive_ok():
        # Already alerted by daily / ensure_dirs; avoid spam
        return
    try:
        week_label = date.today().strftime('%Y-W%W')
        week_dir   = os.path.join(_weekly_dir(), week_label)
        marker     = os.path.join(week_dir, '.done')
        s3_dir     = f"週備份/{week_label}"
        if _cloud_marker_exists(marker, f"{s3_dir}/.done"):
            return
        conn = get_db()
        qs   = [dict(r) for r in conn.execute("SELECT * FROM quotations ORDER BY created_at").fetchall()]
        cs   = [dict(r) for r in conn.execute("SELECT * FROM customers ORDER BY id").fetchall()]
        conn.close()
        now  = datetime.now().isoformat()
        _cloud_write_json(os.path.join(week_dir, '報價單_全部.json'), f"{s3_dir}/報價單_全部.json",
                           {"exported_at": now, "count": len(qs), "data": qs})
        by_status: dict = {}
        for q in qs:
            s = (q.get('status') or '草稿').replace('/', '-')
            by_status.setdefault(s, []).append(q)
        for status, items in by_status.items():
            _cloud_write_json(os.path.join(week_dir, f'報價單_{status}.json'), f"{s3_dir}/報價單_{status}.json",
                               {"exported_at": now, "status": status, "count": len(items), "data": items})
        _cloud_write_json(os.path.join(week_dir, '客戶.json'), f"{s3_dir}/客戶.json",
                           {"exported_at": now, "count": len(cs), "data": cs})
        _cloud_write_json(os.path.join(week_dir, '彙總.json'), f"{s3_dir}/彙總.json",
                           {"week": week_label, "exported_at": now, "quotations": len(qs), "customers": len(cs)})
        _cloud_write_marker(marker, f"{s3_dir}/.done")
        _system_audit("backup.weekly_ok", week_label, {"quotations": len(qs), "customers": len(cs)})
    except Exception as e:
        logger.exception("_weekly_backup failed")
        _write_backup_alert(f"週備份失敗: {e}", level="ERROR")


def _schedule_weekly():
    _weekly_backup()
    t = threading.Timer(6 * 3600, _schedule_weekly)
    t.daemon = True
    t.start()
