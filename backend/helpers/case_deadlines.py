# -*- coding: utf-8 -*-
"""M01 案件的每日到期檢查（2026-09-26 自 routers/daily_tasks.py 搬出，M12 搬遷前置）。

案件執行進度到期、案件專案期間超期、設備保固到期。原本寄生在 M12 每日任務的 08:00 排程裡 ⇒
停用每日任務會連帶停掉案件的提醒。現在以 `daily.check` 提供者登記給 L1 執行器（helpers/daily_checks.py）。
程式碼逐字搬移；測試 patch 的名字（notify_* 等）是本模組的屬性。
"""
import calendar
import json
import os
import threading
from datetime import date as _date, timedelta as _timedelta, datetime, timezone as _timezone
from typing import Optional, List

from db import get_db, spawn_bg_thread
from helpers import (
    _notify, _purge_notifications,
    notify_daily_task_assigned, notify_daily_task_completed, notify_daily_task_overdue,
    notify_daily_task_overdue_manager,
    notify_daily_task_edited, notify_warranty_expiry, notify_range_task_deadline, _warranty_expiry,
    notify_case_stage_deadline, notify_case_stage_deadline_manager,
    notify_case_project_overdue,
    notify_cert_expiry, notify_backup_stale, notify_disk_space_low,
    notify_module_activity,
    _get_setting, _set_setting, notify_approval_reminder, _workdays_elapsed,
)
from helpers.email_notify import (            # noqa: E402
    SEND_SENT as _SEND_SENT,
    SEND_PERMANENT_FAIL as _SEND_PERMANENT_FAIL,
    SEND_UNKNOWN as _SEND_UNKNOWN,
)

import logging as _log
_logger = _log.getLogger(__name__)


def _check_case_stage_deadline() -> None:
    """Notify assignees of case execution-progress stages (caseRecord.stages, stored in
    quotations.data_json) due in 3 days or due today, if not yet marked done."""
    today     = _date.today()
    today_str = today.isoformat()
    try:
        conn = get_db()
        users   = conn.execute("SELECT id, username, display_name FROM users").fetchall()
        dn_map  = {u["username"]: (u["display_name"] or u["username"]) for u in users}
        uid_map = {u["id"]: u["username"] for u in users}
        dept_map = {
            r["username"]: r["department_id"]
            for r in conn.execute("SELECT username, department_id FROM users WHERE department_id IS NOT NULL").fetchall()
        }
        dept_mgr_username = {
            r["id"]: r["mgr_username"]
            for r in conn.execute("""
                SELECT d.id, u.username AS mgr_username FROM departments d
                JOIN users u ON u.id = d.manager_user_id WHERE u.active=1
            """).fetchall()
        }
        # Phase 5（2026-08-23）：改成直接 JOIN case_stages 表，SQL 層就用 done=0 AND
        # due_date IN (...) 篩出真正要處理的列，取代原本「撈全部已成案案件的整包
        # stages JSON，Python 迴圈逐一比對到期日」的寫法——正規化橋樑（3a/3b/v52）
        # 已保證這張表對每個有執行進度的案件都是權威、完整的來源。
        check_date_3d = (today + _timedelta(days=3)).isoformat()
        check_date_0  = today_str
        date_to_type = {check_date_3d: (3, "3d"), check_date_0: (0, "deadline")}
        rows = conn.execute("""
            SELECT q.quote_no, q.customer_name, q.project_name, q.sales_person_id,
                   cs.id AS stage_id, cs.label, cs.due_date, cs.assigned_to
            FROM case_stages cs
            JOIN quotations q ON q.quote_no = cs.quote_no
            WHERE COALESCE(NULLIF(q.deal_tag,''), json_extract(q.data_json,'$.dealTag'), '') = '已成案'
              AND cs.done = 0
              AND cs.due_date IN (?, ?)
        """, (check_date_3d, check_date_0)).fetchall()
        conn.close()

        for row in rows:
            days_ahead, notif_type = date_to_type[row["due_date"]]
            check_date = row["due_date"]
            assignees = list(json.loads(row["assigned_to"] or "[]"))
            if not assignees:
                fallback = uid_map.get(row["sales_person_id"])
                if fallback:
                    assignees = [fallback]
            for username in assignees:
                if not username:
                    continue
                guard_key = f"casestage_notif.{row['quote_no']}.{row['stage_id']}.{username}.{notif_type}"
                if _get_setting(guard_key):
                    continue
                _set_setting(guard_key, today_str)
                display = dn_map.get(username, username)
                threading.Thread(
                    target=notify_case_stage_deadline,
                    args=(row["quote_no"], row["label"] or "", check_date, days_ahead,
                          username, display, row["customer_name"] or "", row["project_name"] or "", None),
                    daemon=True,
                ).start()
                _notify(username, "case_stage_deadline", row["quote_no"],
                        f"{row['quote_no']} · {row['label'] or ''}",
                        "案件執行進度「" + (row["label"] or "") + "」" +
                        ("今日到期" if days_ahead == 0 else f"{days_ahead} 天後到期"))
                # 案件/專案管理延伸（2026-08-22）：額外通知負責人所屬部門的主管，
                # 跟指派人自己收到的 case_stage_deadline 是兩條獨立路徑
                dept_id = dept_map.get(username)
                mgr_username = dept_mgr_username.get(dept_id) if dept_id else None
                if mgr_username and mgr_username != username:
                    _notify(mgr_username, "case_stage_deadline_manager", row["quote_no"],
                            f"{row['quote_no']} · {row['label'] or ''}",
                            f"部門成員 {display} 負責的案件執行進度「{row['label'] or ''}」" +
                            ("今日到期" if days_ahead == 0 else f"{days_ahead} 天後到期"))
                    threading.Thread(
                        target=notify_case_stage_deadline_manager,
                        args=(row["quote_no"], row["label"] or "", check_date, days_ahead,
                              username, display, dept_id, row["customer_name"] or "", row["project_name"] or ""),
                        daemon=True,
                    ).start()
        _logger.info("Case stage deadline check complete for %s", today_str)
    except Exception as exc:
        _logger.warning("_check_case_stage_deadline failed: %s", exc)


def _check_project_deadline() -> None:
    """停用（2026-08-26 專案管理併入案件管理）：專案管理業務端點/頁面已下線，
    projects 表不會再有新的 endDate 被設定，案件本身的階段到期提醒已有對應
    機制（見同檔 _check_case_stage_deadline()，走 case_stages），不需要重複
    維護兩套。函式保留空殼是因為既有 3 處呼叫點不用跟著改。"""
    pass


def _prune_case_project_guard_keys(live_keys: set) -> None:
    """清掉不再需要的 `caseproj_notif.*` guard key（2026-09-10 新增）。

    這些 key 每個超期案件、每個 7 天區間各寫一列進 `system_settings`，原本
    寫進去就永遠不刪——案件結案、期限被改正、案件被刪除之後，舊 key 全部
    留著；一個超期兩年的案件光自己就會累積約 104 列。這個專案已經為同一種
    「只寫不刪、預期會自然停止但其實不會」的模式付過代價：`module_versions`
    曾長到 626,725 列、約佔 301MB 資料庫裡的 270MB（見 db.py `_m035` 的
    註解）。與其等它長大，不如在每次掃描結束時順手收斂。

    保留規則：只留「目前仍超期的案件、且是本次算出來的當前區間」那些 key。
    比當前更早的區間永遠不會再被查詢（判斷式只問「這個區間寄過沒」），留著
    沒有任何作用，所以一併刪掉——結果是每個超期案件最多只佔 1 列。
    """
    conn = get_db()
    try:
        existing = [r["key"] for r in conn.execute(
            "SELECT key FROM system_settings WHERE key LIKE 'caseproj_notif.%'"
        ).fetchall()]
        stale = [k for k in existing if k not in live_keys]
        if stale:
            conn.executemany("DELETE FROM system_settings WHERE key=?", [(k,) for k in stale])
            conn.commit()
            _logger.info("Pruned %d stale caseproj_notif guard keys", len(stale))
    except Exception as exc:
        # 收斂失敗不該讓整個每日檢查掛掉——通知本身已經寄出去了
        _logger.warning("_prune_case_project_guard_keys failed: %s", exc)
    finally:
        conn.close()


def _check_case_project_timeline_deadline() -> None:
    """Scan active cases; notify admin if case project endDate is overdue. Re-send every 7 days."""
    today = _date.today()
    today_str = today.isoformat()
    live_guard_keys = set()
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT quote_no, customer_name, project_name,
                   json_extract(data_json, '$.caseRecord.projectTimeline.endDate') AS end_date_json
            FROM quotations
            WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') != '已結案'
              AND json_extract(data_json, '$.caseRecord.projectTimeline.endDate') IS NOT NULL
        """).fetchall()
        conn.close()

        for row in rows:
            try:
                end_date_str = (row["end_date_json"] or "").strip('"')
                if not end_date_str:
                    continue
                end_date = _date.fromisoformat(end_date_str)
            except Exception:
                continue

            if end_date >= today:
                continue  # not yet overdue

            days_overdue = (today - end_date).days
            bucket = days_overdue // 7  # day 0-6 → bucket 0, day 7-13 → bucket 1, etc.
            guard_key = f"caseproj_notif.{row['quote_no']}.{bucket}"
            live_guard_keys.add(guard_key)
            if _get_setting(guard_key):
                continue  # already sent for this 7-day bucket

            _set_setting(guard_key, today_str)
            # 這裡刻意用 threading.Thread 而非 db.spawn_bg_thread()：本函式是
            # 排程觸發、不掛在任何 request 上，contextvar 本來就該是預設值，
            # 屬於 MOTRIX-ERP-QUICK.md §3.5 明列的例外 (a)。不要「順手改成
            # spawn_bg_thread」——那會讓它去複製一個根本不存在的 request context。
            threading.Thread(
                target=notify_case_project_overdue,
                args=(row["quote_no"], row["customer_name"] or "", row["project_name"] or "",
                      end_date_str, days_overdue),
                daemon=True,
            ).start()

        _prune_case_project_guard_keys(live_guard_keys)
        _logger.info("Case project timeline deadline check complete for %s", today_str)
    except Exception as exc:
        _logger.warning("_check_case_project_timeline_deadline failed: %s", exc)


_WARR_THRESHOLDS = (7, 30)  # days — must be in ascending order


def _check_warranty_expiry() -> None:
    """Scan active-case devices; send email once per device × threshold crossing."""
    today     = _date.today()
    today_str = today.isoformat()
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT quote_no, customer_name, sales_person,
                   json_extract(data_json, '$.caseRecord') AS cr_json
            FROM quotations
            WHERE COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '') = '已成案'
              AND json_extract(data_json, '$.caseRecord') IS NOT NULL
        """).fetchall()
        conn.close()

        for row in rows:
            try:
                cr = json.loads(row["cr_json"] or "{}")
            except Exception:
                continue
            devices = cr.get("devices") or []
            for dev in devices:
                ws = dev.get("warrantyStart") or ""
                wm = dev.get("warrantyMonths")
                if not ws or not wm:
                    continue
                expiry, days_left = _warranty_expiry(ws, wm)
                if expiry is None or days_left > 30:
                    continue

                threshold = 7 if days_left <= 7 else 30
                sn = (dev.get("sn") or dev.get("mac") or dev.get("name") or "")[:32]
                guard_key = f"warranty_notif.{row['quote_no']}_{sn}_{threshold}"
                if _get_setting(guard_key):
                    continue  # already sent for this threshold

                _set_setting(guard_key, today_str)
                threading.Thread(
                    target=notify_warranty_expiry,
                    args=(
                        dev.get("name") or sn or "未知設備",
                        row["customer_name"] or "",
                        row["quote_no"],
                        days_left,
                        expiry.isoformat(),
                        row["sales_person"] or "",
                    ),
                    daemon=True,
                ).start()
        _logger.info("Warranty expiry check complete for %s", today_str)
    except Exception as exc:
        _logger.warning("_check_warranty_expiry failed: %s", exc)



# ── `daily.check` 提供者（INTEGRATION-POINTS IP-10）─────────────────────────────
def run_daily_checks(mode: str = "daily") -> None:
    """mode：daily（08:00）／startup（啟動補跑）。案件類檢查都看未來，兩種模式做一樣的事。"""
    _check_warranty_expiry()
    _check_case_stage_deadline()
    _check_case_project_timeline_deadline()
    _check_project_deadline()


from core import registry as _registry  # noqa: E402
_registry.provide("daily.check", "case_deadlines", run_daily_checks)
