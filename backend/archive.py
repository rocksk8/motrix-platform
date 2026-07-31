"""Google Drive archive helpers: real-time, daily, and weekly backups + local SQLite snapshots."""
import json
import os
import shutil
import sqlite3
import threading
import logging
from datetime import datetime, date, timedelta

from db import get_db, DB_PATH
from helpers import _cleanup_sessions

logger = logging.getLogger(__name__)

_ARCHIVE_BASE = r"H:\我的雲端硬碟\系統存檔"
_REALTIME_DIR = os.path.join(_ARCHIVE_BASE, "即時備份")
_WEEKLY_DIR   = os.path.join(_ARCHIVE_BASE, "週備份")
_DAILY_DIR    = os.path.join(_ARCHIVE_BASE, "每日備份")

# Local always-on paths (independent of H: mount)
_BACKEND_DIR      = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT     = os.path.dirname(_BACKEND_DIR)
_LOCAL_DB_BACKUP  = os.path.join(_BACKEND_DIR, "db_backups")
_ALERT_DIR        = os.path.join(_PROJECT_ROOT, "backup_alerts")


def _archive_ok() -> bool:
    return os.path.isdir(_ARCHIVE_BASE)


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
            f"1. Google 雲端硬碟是否已掛載為 H: 且可存取「我的雲端硬碟\\系統存檔」\n"
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
    """Send async email to all admin/superadmin on ERROR-level backup failure."""
    try:
        from helpers.email_notify import _admin_emails, _async_send
        to = _admin_emails()
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
            "<li>Google 雲端硬碟是否已掛載為 H:（可存取「我的雲端硬碟/系統存檔」）</li>"
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
    """Remove sticky alert file when cloud archive path is healthy."""
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
    if not _archive_ok():
        _write_backup_alert(
            f"雲端備份路徑不存在或未掛載：{_ARCHIVE_BASE}。"
            f"即時/每日/週雲端備份已跳過。本機 SQLite 快照仍會寫入 {_LOCAL_DB_BACKUP}。"
        )
        return
    for d in [
        os.path.join(_REALTIME_DIR, "報價單"),
        os.path.join(_REALTIME_DIR, "客戶"),
        os.path.join(_REALTIME_DIR, "供應商"),
        _WEEKLY_DIR,
        _DAILY_DIR,
    ]:
        try:
            os.makedirs(d, exist_ok=True)
        except Exception as e:
            _write_backup_alert(f"無法建立備份目錄 {d}: {e}")
            return
    _clear_backup_alert_if_healthy()


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
            with open(marker, "w", encoding="utf-8") as f:
                f.write(datetime.now().isoformat())
            logger.info("SQLite snapshot saved: %s", dest)
            _system_audit(
                "backup.sqlite_snapshot",
                today,
                {"path": dest, "bytes": os.path.getsize(dest) if os.path.exists(dest) else 0},
            )
        if also_to_cloud and _archive_ok():
            try:
                cloud_day = os.path.join(_DAILY_DIR, today)
                os.makedirs(cloud_day, exist_ok=True)
                cloud_dest = os.path.join(cloud_day, "motrix_erp.db")
                shutil.copy2(dest, cloud_dest)
            except Exception as e:
                _write_backup_alert(f"SQLite 快照複製到雲端失敗: {e}")
        # Prune local snapshots older than 30 days
        _prune_local_db_backups(keep_days=30)
        return dest
    except Exception as e:
        logger.exception("_snapshot_sqlite failed")
        _write_backup_alert(f"本機 SQLite 快照失敗: {e}", level="ERROR")
        return None


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


def _prune_local_db_backups(keep_days: int = 30) -> None:
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
            path = os.path.join(_REALTIME_DIR, "報價單", f"{quote_no}.json")
            _atomic_json_write(path, payload)
            return
        except Exception as e:
            logger.exception("_backup_quotation H: write failed for %s", quote_no)
            _write_backup_alert(f"即時備份報價單失敗（H:）{quote_no}: {e}")

    # H: unavailable — write to local instant-backup dir
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
        path = os.path.join(_REALTIME_DIR, "客戶", "clients.json")
        _atomic_json_write(path, data)
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
        os.makedirs(os.path.join(_REALTIME_DIR, "供應商"), exist_ok=True)
        path = os.path.join(_REALTIME_DIR, "供應商", "suppliers.json")
        _atomic_json_write(path, data)
    except Exception as e:
        logger.exception("_backup_suppliers failed")
        _write_backup_alert(f"即時備份供應商失敗: {e}")


def _daily_backup():
    # Always snapshot SQLite locally first (independent of H:)
    _snapshot_sqlite(also_to_cloud=True)

    if not _archive_ok():
        _write_backup_alert(
            f"雲端備份路徑不可用（{_ARCHIVE_BASE}），已略過 JSON 每日備份；"
            f"本機 SQLite 快照見 {_LOCAL_DB_BACKUP}"
        )
        return
    try:
        today_label = date.today().isoformat()
        day_dir     = os.path.join(_DAILY_DIR, today_label)
        os.makedirs(day_dir, exist_ok=True)
        marker = os.path.join(day_dir, '.done')
        if os.path.exists(marker):
            _clear_backup_alert_if_healthy()
            return
        conn = get_db()
        now  = datetime.now().isoformat()

        tables = {
            "報價單":     "SELECT * FROM quotations ORDER BY id",
            "客戶":       "SELECT * FROM customers ORDER BY id",
            "供應商":     "SELECT * FROM suppliers ORDER BY id",
            "料號":       "SELECT * FROM parts ORDER BY id",
            "專案":       "SELECT * FROM projects ORDER BY id",
            "稽核紀錄":   "SELECT * FROM audit_log ORDER BY id",
            "通知":       "SELECT * FROM notifications ORDER BY id",
            "模組版本":   "SELECT * FROM module_versions ORDER BY id",
        }
        summary: dict = {"date": today_label, "exported_at": now}
        for fname, sql in tables.items():
            try:
                rows = [dict(r) for r in conn.execute(sql).fetchall()]
                _atomic_json_write(
                    os.path.join(day_dir, f"{fname}.json"),
                    {"exported_at": now, "count": len(rows), "data": rows},
                )
                summary[fname] = len(rows)
            except Exception:
                logger.exception("daily_backup table %s failed", fname)
                summary[fname] = "error"

        conn.close()
        _atomic_json_write(os.path.join(day_dir, '彙總.json'), summary)
        open(marker, 'w').close()
        logger.info("Daily backup completed: %s", day_dir)
        _system_audit("backup.daily_ok", today_label, summary)
        _clear_backup_alert_if_healthy()
        _prune_audit_log(keep_days=730)
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
        week_dir   = os.path.join(_WEEKLY_DIR, week_label)
        os.makedirs(week_dir, exist_ok=True)
        marker = os.path.join(week_dir, '.done')
        if os.path.exists(marker):
            return
        conn = get_db()
        qs   = [dict(r) for r in conn.execute("SELECT * FROM quotations ORDER BY created_at").fetchall()]
        cs   = [dict(r) for r in conn.execute("SELECT * FROM customers ORDER BY id").fetchall()]
        conn.close()
        now  = datetime.now().isoformat()
        _atomic_json_write(os.path.join(week_dir, '報價單_全部.json'),
                           {"exported_at": now, "count": len(qs), "data": qs})
        by_status: dict = {}
        for q in qs:
            s = (q.get('status') or '草稿').replace('/', '-')
            by_status.setdefault(s, []).append(q)
        for status, items in by_status.items():
            _atomic_json_write(os.path.join(week_dir, f'報價單_{status}.json'),
                               {"exported_at": now, "status": status, "count": len(items), "data": items})
        _atomic_json_write(os.path.join(week_dir, '客戶.json'),
                           {"exported_at": now, "count": len(cs), "data": cs})
        _atomic_json_write(os.path.join(week_dir, '彙總.json'),
                           {"week": week_label, "exported_at": now, "quotations": len(qs), "customers": len(cs)})
        open(marker, 'w').close()
        _system_audit("backup.weekly_ok", week_label, {"quotations": len(qs), "customers": len(cs)})
    except Exception as e:
        logger.exception("_weekly_backup failed")
        _write_backup_alert(f"週備份失敗: {e}", level="ERROR")


def _schedule_weekly():
    _weekly_backup()
    t = threading.Timer(6 * 3600, _schedule_weekly)
    t.daemon = True
    t.start()
