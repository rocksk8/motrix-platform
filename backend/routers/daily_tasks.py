"""Daily work task management — superadmin creates/assigns, users complete & report.
Supports once-off and weekly recurring tasks (per-day occurrence tracking).
"""
import calendar
import json
import os
import threading
from datetime import date as _date, timedelta as _timedelta, datetime, timezone as _timezone
from typing import Optional, List

import csv as _csv
import io as _io

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import Response as _HTTPResponse
from pydantic import BaseModel

from db import get_db, spawn_bg_thread
from helpers import (
    _require_user, _tok, _audit, _notify, _purge_notifications,
    notify_daily_task_assigned, notify_daily_task_completed, notify_daily_task_overdue,
    notify_daily_task_overdue_manager,
    notify_daily_task_edited, notify_warranty_expiry, notify_range_task_deadline, _warranty_expiry,
    notify_case_stage_deadline, notify_case_stage_deadline_manager,
    notify_case_project_overdue,
    notify_cert_expiry, notify_backup_stale, notify_disk_space_low,
    notify_module_activity,
    _get_setting, _set_setting, notify_approval_reminder, _workdays_elapsed, require_any_module,
)
# 寄送結果的常數。**這兩個是不可變的字串字面值**，所以 `from ... import`
# 拿到副本沒有關係 —— ⚠️ 而**會被 monkeypatch 的東西不可以這樣拿**
# （`notify_approval_reminder` 上面那一行就是；測試 patch 的是
# `dt.notify_approval_reminder` 這個名字，所以它必須是模組屬性）。
# 📌 兩者的差別是「值會不會被換掉」，不是「寫法好不好看」。
from helpers.email_notify import (            # noqa: E402
    SEND_SENT as _SEND_SENT,
    SEND_PERMANENT_FAIL as _SEND_PERMANENT_FAIL,
)

router = APIRouter()

_WEEKDAY_NAMES = ['一', '二', '三', '四', '五', '六', '日']  # 0=Mon … 6=Sun


class DailyTaskIn(BaseModel):
    task_date:           str
    title:               str
    description:         Optional[str] = ''
    category:            Optional[str] = ''
    priority:            Optional[str] = '一般'
    assigned_to:         List[str] = []
    supervisors:         List[str] = []            # usernames who receive notifications
    recurrence_type:     Optional[str] = 'once'   # 'once' | 'weekly'
    recurrence_days:     Optional[List[int]] = []  # 0=Mon … 6=Sun
    recurrence_end_date: Optional[str] = ''        # '' = no end
    case_no:             Optional[str] = ''        # loose FK → quotations.quote_no


class TaskCompletionIn(BaseModel):
    completed:       bool = True
    report:          Optional[str] = ''
    occurrence_date: Optional[str] = ''  # required for weekly tasks


# ── Helpers ───────────────────────────────────────────────────────────────────

def _occurrences_in_month(row: dict, year: int, month: int) -> list:
    """For a weekly task, return all occurrence ISO-date strings within the given month."""
    rec_days = json.loads(row.get("recurrence_days") or "[]")
    if not rec_days:
        return []
    try:
        start = _date.fromisoformat(row["task_date"])
    except (ValueError, KeyError):
        return []
    end_str = row.get("recurrence_end_date") or ""
    end = _date.fromisoformat(end_str) if end_str else _date(9999, 12, 31)

    month_start = _date(year, month, 1)
    month_end   = _date(year, month, calendar.monthrange(year, month)[1])

    eff_start = max(start, month_start)
    eff_end   = min(end, month_end)
    if eff_start > eff_end:
        return []

    occs = []
    d = eff_start
    while d <= eff_end:
        if d.weekday() in rec_days:
            occs.append(d.isoformat())
        d += _timedelta(days=1)
    return occs


def _occurrences_on_date(row: dict, target_date: str) -> list:
    """Return [target_date] if a weekly task occurs on that date, else []."""
    try:
        d = _date.fromisoformat(target_date)
    except ValueError:
        return []
    rec_days = json.loads(row.get("recurrence_days") or "[]")
    if d.weekday() not in rec_days:
        return []
    try:
        start = _date.fromisoformat(row["task_date"])
    except (ValueError, KeyError):
        return []
    if d < start:
        return []
    end_str = row.get("recurrence_end_date") or ""
    if end_str:
        try:
            end = _date.fromisoformat(end_str)
            if d > end:
                return []
        except ValueError:
            pass
    return [target_date]


def _range_occurrences_in_month(row: dict, year: int, month: int) -> list:
    """For a range task, return all occurrence ISO-date strings within the given month."""
    start_str = row.get("task_date") or ""
    end_str   = row.get("recurrence_end_date") or ""
    if not start_str:
        return []
    try:
        start = _date.fromisoformat(start_str)
    except ValueError:
        return []
    end = _date.fromisoformat(end_str) if end_str else _date(9999, 12, 31)

    month_start = _date(year, month, 1)
    month_end   = _date(year, month, calendar.monthrange(year, month)[1])
    eff_start = max(start, month_start)
    eff_end   = min(end, month_end)
    if eff_start > eff_end:
        return []
    occs, d = [], eff_start
    while d <= eff_end:
        occs.append(d.isoformat())
        d += _timedelta(days=1)
    return occs


def _range_occurrence_on_date(row: dict, target_date: str) -> list:
    """Return [target_date] if a range task spans this date, else []."""
    start_str = row.get("task_date") or ""
    end_str   = row.get("recurrence_end_date") or ""
    if not start_str:
        return []
    try:
        d     = _date.fromisoformat(target_date)
        start = _date.fromisoformat(start_str)
    except ValueError:
        return []
    if d < start:
        return []
    if end_str:
        try:
            if d > _date.fromisoformat(end_str):
                return []
        except ValueError:
            pass
    return [target_date]


def _enrich(pairs: list, conn) -> list:
    """
    pairs: list of (row_dict_or_Row, occurrence_date_str)
    occurrence_date is the specific date this entry represents.
    For 'once' tasks it equals task_date; for 'weekly' it's the expanded date.
    """
    if not pairs:
        return []
    user_rows = conn.execute("SELECT username, display_name FROM users").fetchall()
    dn_map = {r["username"]: (r["display_name"] or r["username"]) for r in user_rows}

    task_ids = list({(dict(p[0]) if not isinstance(p[0], dict) else p[0])["id"] for p in pairs})
    ph = ",".join("?" * len(task_ids))
    comp_rows = conn.execute(
        f"SELECT task_id, username, occurrence_date, completed, report, completed_at, report_edit_count "
        f"FROM daily_task_completions WHERE task_id IN ({ph})",
        task_ids,
    ).fetchall() if task_ids else []

    # comp_map: task_id -> list[completion_dict]
    comp_map: dict = {}
    for c in comp_rows:
        comp_map.setdefault(c["task_id"], []).append({
            "username":       c["username"],
            "displayName":    dn_map.get(c["username"], c["username"]),
            "occurrenceDate": c["occurrence_date"],
            "completed":      bool(c["completed"]),
            "report":         c["report"] or "",
            "completedAt":    c["completed_at"] or "",
            "editCount":      c["report_edit_count"] or 0,
        })

    result = []
    for row, occ_date in pairs:
        d = dict(row) if not isinstance(row, dict) else dict(row)
        assigned    = json.loads(d.get("assigned_to") or "[]")
        rec_days    = json.loads(d.get("recurrence_days") or "[]")
        supervisors = json.loads(d.get("supervisors") or "[]")
        d["assigned_to"]         = assigned
        d["recurrence_days"]     = rec_days
        d["supervisors"]         = supervisors
        d["supervisors_info"]    = [{"username": u, "displayName": dn_map.get(u, u)} for u in supervisors]
        d["assignees"]           = [{"username": u, "displayName": dn_map.get(u, u)} for u in assigned]
        d["occurrence_date"]     = occ_date
        # For display: override task_date to the specific occurrence date
        d["display_date"]        = occ_date
        # Weekday label for weekly tasks
        if d.get("recurrence_type") == "weekly" and rec_days:
            d["recurrence_label"] = "每週" + "".join(_WEEKDAY_NAMES[i] for i in sorted(rec_days) if 0 <= i <= 6)
        else:
            d["recurrence_label"] = ""
        # For range tasks show all completions (any date = done); others: filter by occ_date
        all_comps = comp_map.get(d["id"], [])
        if d.get("recurrence_type") == "range":
            d["completions"] = all_comps
        else:
            d["completions"] = [c for c in all_comps if c["occurrenceDate"] == occ_date]
        result.append(d)
    return result


def _user_filter_sql(user: dict, username: Optional[str]) -> tuple:
    """Return (extra_sql, extra_params) for membership filter."""
    if user["role"] != "superadmin":
        # Non-superadmin: see tasks where they are an assignee OR a supervisor
        return (
            " AND (EXISTS (SELECT 1 FROM json_each(assigned_to) WHERE value=?)"
            "   OR EXISTS (SELECT 1 FROM json_each(supervisors)  WHERE value=?))",
            [user["username"], user["username"]],
        )
    if username:
        # Superadmin viewing a specific user: include assignee + supervisor tasks
        return (
            " AND (EXISTS (SELECT 1 FROM json_each(assigned_to) WHERE value=?)"
            "   OR EXISTS (SELECT 1 FROM json_each(supervisors)  WHERE value=?))",
            [username, username],
        )
    return ("", [])


def _compute_task_diff(old: dict, new: "DailyTaskIn", dn_map: dict) -> list:
    """Return list of {field, label, old, new} dicts for every changed field."""
    _WD = ['週一', '週二', '週三', '週四', '週五', '週六', '週日']

    def _names(usernames):
        return "、".join(dn_map.get(u, u) for u in usernames) if usernames else "（無）"

    def _weekdays(days):
        return "、".join(_WD[d] for d in sorted(days) if 0 <= d <= 6) if days else "（無）"

    changes = []
    scalar_fields = [
        ("title",               "標題"),
        ("description",         "說明"),
        ("task_date",           "日期"),
        ("category",            "分類"),
        ("priority",            "優先級"),
        ("recurrence_type",     "週期類型"),
        ("recurrence_end_date", "結束日期"),
        ("case_no",             "關聯案件"),
    ]
    for field, label in scalar_fields:
        old_v = (old.get(field) or "").strip()
        new_v = (getattr(new, field) or "").strip()
        if old_v != new_v:
            changes.append({"field": field, "label": label,
                             "old": old_v or "（空）", "new": new_v or "（空）"})

    old_assigned = json.loads(old.get("assigned_to") or "[]")
    if sorted(old_assigned) != sorted(new.assigned_to):
        changes.append({"field": "assigned_to", "label": "指派對象",
                        "old": _names(old_assigned), "new": _names(new.assigned_to)})

    old_sup = json.loads(old.get("supervisors") or "[]")
    if sorted(old_sup) != sorted(new.supervisors):
        changes.append({"field": "supervisors", "label": "負責主管",
                        "old": _names(old_sup), "new": _names(new.supervisors)})

    old_days = sorted(json.loads(old.get("recurrence_days") or "[]"))
    new_days  = sorted(new.recurrence_days or [])
    if old_days != new_days:
        changes.append({"field": "recurrence_days", "label": "每週排程",
                        "old": _weekdays(old_days), "new": _weekdays(new_days)})

    return changes


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/api/daily-tasks")
def list_daily_tasks(
    year_month: Optional[str] = None,  # YYYY-MM
    date:       Optional[str] = None,  # YYYY-MM-DD (single day)
    username:   Optional[str] = None,
    case_no:    Optional[str] = None,  # filter by linked case number
    authorization: str = Header(None),
):
    user = _require_user(authorization)
    require_any_module(user, ('daily_task', 'case_manage'), "每日工作事項")
    conn = get_db()
    uf_sql, uf_params = _user_filter_sql(user, username)
    cn_sql    = " AND case_no=?" if case_no else ""
    cn_params = [case_no]       if case_no else []
    pairs = []

    if date:
        # Single day: once + range tasks on that date; weekly tasks recurring on that date
        once_rows = conn.execute(
            "SELECT * FROM daily_tasks WHERE is_deleted=0 AND recurrence_type='once' AND task_date=?" + uf_sql + cn_sql,
            [date] + uf_params + cn_params,
        ).fetchall()
        weekly_rows = conn.execute(
            "SELECT * FROM daily_tasks WHERE is_deleted=0 AND recurrence_type='weekly'"
            " AND task_date<=? AND (recurrence_end_date='' OR recurrence_end_date>=?)" + uf_sql + cn_sql,
            [date, date] + uf_params + cn_params,
        ).fetchall()
        range_rows = conn.execute(
            "SELECT * FROM daily_tasks WHERE is_deleted=0 AND recurrence_type='range'"
            " AND task_date<=? AND (recurrence_end_date='' OR recurrence_end_date>=?)" + uf_sql + cn_sql,
            [date, date] + uf_params + cn_params,
        ).fetchall()
        for r in once_rows:
            pairs.append((dict(r), r["task_date"]))
        for r in weekly_rows:
            for occ in _occurrences_on_date(dict(r), date):
                pairs.append((dict(r), occ))
        for r in range_rows:
            for occ in _range_occurrence_on_date(dict(r), date):
                pairs.append((dict(r), occ))

    elif year_month:
        try:
            y, m = map(int, year_month.split("-"))
        except ValueError:
            conn.close()
            raise HTTPException(400, "year_month 格式錯誤，應為 YYYY-MM")
        month_days = calendar.monthrange(y, m)[1]
        month_start = f"{year_month}-01"
        month_end   = f"{year_month}-{month_days:02d}"

        once_rows = conn.execute(
            "SELECT * FROM daily_tasks WHERE is_deleted=0 AND recurrence_type='once'"
            " AND task_date BETWEEN ? AND ?" + uf_sql + cn_sql,
            [month_start, month_end] + uf_params + cn_params,
        ).fetchall()
        weekly_rows = conn.execute(
            "SELECT * FROM daily_tasks WHERE is_deleted=0 AND recurrence_type='weekly'"
            " AND task_date<=? AND (recurrence_end_date='' OR recurrence_end_date>=?)" + uf_sql + cn_sql,
            [month_end, month_start] + uf_params + cn_params,
        ).fetchall()
        range_rows = conn.execute(
            "SELECT * FROM daily_tasks WHERE is_deleted=0 AND recurrence_type='range'"
            " AND task_date<=? AND (recurrence_end_date='' OR recurrence_end_date>=?)" + uf_sql + cn_sql,
            [month_end, month_start] + uf_params + cn_params,
        ).fetchall()

        for r in once_rows:
            pairs.append((dict(r), r["task_date"]))
        for r in weekly_rows:
            for occ in _occurrences_in_month(dict(r), y, m):
                pairs.append((dict(r), occ))
        for r in range_rows:
            for occ in _range_occurrences_in_month(dict(r), y, m):
                pairs.append((dict(r), occ))

    else:
        # No filter: once + range tasks — weekly only shown per-month
        rows = conn.execute(
            "SELECT * FROM daily_tasks WHERE is_deleted=0"
            " AND recurrence_type IN ('once','range')" + uf_sql + cn_sql
            + " ORDER BY task_date DESC, id DESC LIMIT 200",
            uf_params + cn_params,
        ).fetchall()
        for r in rows:
            pairs.append((dict(r), r["task_date"]))

    items = _enrich(pairs, conn)
    conn.close()
    # Sort by occurrence_date desc, then id desc
    items.sort(key=lambda x: (x.get("occurrence_date") or x.get("task_date") or "", x["id"]), reverse=True)
    return {"items": items}


@router.get("/api/daily-tasks/{task_id}")
def get_daily_task(task_id: int, occurrence_date: Optional[str] = None, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('daily_task', 'case_manage'), "每日工作事項")
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM daily_tasks WHERE id=? AND is_deleted=0", (task_id,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "工作事項不存在")
    d = dict(row)
    occ = occurrence_date or d["task_date"]
    items = _enrich([(d, occ)], conn)
    conn.close()
    t = items[0]
    if user["role"] != "superadmin" and user["username"] not in t["assigned_to"] and user["username"] not in t.get("supervisors", []):
        raise HTTPException(403, "無權限查看此工作事項")
    return t


@router.post("/api/daily-tasks", status_code=201)
def create_daily_task(body: DailyTaskIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('daily_task', 'case_manage'), "每日工作事項")
    if user["role"] != "superadmin":
        raise HTTPException(403, "僅最高管理者可建立工作事項")
    if not body.title.strip():
        raise HTTPException(400, "工作事項標題不可為空")
    if not body.task_date:
        raise HTTPException(400, "請指定日期")
    rec_type = body.recurrence_type or "once"
    rec_days = body.recurrence_days or []
    if rec_type == "weekly" and not rec_days:
        raise HTTPException(400, "每週排程須選擇至少一個星期幾")
    if rec_type == "range" and not body.recurrence_end_date:
        raise HTTPException(400, "區間任務須指定截止日期")
    if rec_type == "range" and body.recurrence_end_date and body.recurrence_end_date < body.task_date:
        raise HTTPException(400, "截止日期不可早於開始日期")
    now = datetime.now().isoformat()
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO daily_tasks "
        "(task_date, title, description, category, priority, assigned_to, supervisors,"
        " created_by, created_at, updated_at,"
        " recurrence_type, recurrence_days, recurrence_end_date, case_no) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (body.task_date, body.title.strip(), body.description or '',
         body.category or '', body.priority or '一般',
         json.dumps(body.assigned_to, ensure_ascii=False),
         json.dumps(body.supervisors, ensure_ascii=False),
         user["username"], now, now,
         rec_type,
         json.dumps(rec_days),
         body.recurrence_end_date or '',
         body.case_no or ''),
    )
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "daily_task.create", "daily_task", str(task_id),
           f"{body.task_date} {body.title}")
    if body.assigned_to:
        for u in body.assigned_to:
            _notify(u, "daily_task", str(task_id), body.title,
                    f"已指派工作事項給您：{body.title}（{body.task_date}）")
        spawn_bg_thread(
            notify_daily_task_assigned,
            args=(task_id, body.title, body.task_date, body.assigned_to,
                  body.description or ''),
        )
    return {"id": task_id, "created_at": now}


@router.put("/api/daily-tasks/{task_id}")
def update_daily_task(task_id: int, body: DailyTaskIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('daily_task', 'case_manage'), "每日工作事項")
    if user["role"] != "superadmin":
        raise HTTPException(403, "僅最高管理者可修改工作事項")
    rec_type = body.recurrence_type or "once"
    rec_days = body.recurrence_days or []
    if rec_type == "weekly" and not rec_days:
        raise HTTPException(400, "每週排程須選擇至少一個星期幾")
    if rec_type == "range" and not body.recurrence_end_date:
        raise HTTPException(400, "區間任務須指定截止日期")
    if rec_type == "range" and body.recurrence_end_date and body.recurrence_end_date < body.task_date:
        raise HTTPException(400, "截止日期不可早於開始日期")
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM daily_tasks WHERE id=? AND is_deleted=0", (task_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "工作事項不存在")
    old_row      = dict(row)
    old_assigned = json.loads(old_row.get("assigned_to") or "[]")

    user_rows = conn.execute("SELECT username, display_name FROM users").fetchall()
    dn_map    = {r["username"]: (r["display_name"] or r["username"]) for r in user_rows}

    changes = _compute_task_diff(old_row, body, dn_map)

    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE daily_tasks SET task_date=?, title=?, description=?, category=?, priority=?,"
        " assigned_to=?, supervisors=?, updated_at=?,"
        " recurrence_type=?, recurrence_days=?, recurrence_end_date=?, case_no=?"
        " WHERE id=?",
        (body.task_date, body.title.strip(), body.description or '',
         body.category or '', body.priority or '一般',
         json.dumps(body.assigned_to, ensure_ascii=False),
         json.dumps(body.supervisors, ensure_ascii=False),
         now,
         rec_type, json.dumps(rec_days), body.recurrence_end_date or '',
         body.case_no or '',
         task_id),
    )
    if changes:
        conn.execute(
            "INSERT INTO daily_task_edit_log (task_id, changed_by, changed_at, changes_json)"
            " VALUES (?,?,?,?)",
            (task_id, user["username"], now, json.dumps(changes, ensure_ascii=False)),
        )
    conn.commit()
    conn.close()
    _audit(_tok(authorization), "daily_task.update", "daily_task", str(task_id),
           f"{body.task_date} {body.title}")

    # Notify newly added assignees
    new_assignees = [u for u in body.assigned_to if u not in old_assigned]
    if new_assignees:
        for u in new_assignees:
            _notify(u, "daily_task", str(task_id), body.title,
                    f"已指派工作事項給您：{body.title}（{body.task_date}）")
        spawn_bg_thread(
            notify_daily_task_assigned,
            args=(task_id, body.title, body.task_date, new_assignees,
                  body.description or ''),
        )

    # Notify supervisors about the edit
    if changes:
        editor_display = dn_map.get(user["username"], user["username"])
        supervisors    = body.supervisors or []
        spawn_bg_thread(
            notify_daily_task_edited,
            args=(task_id, body.title, body.task_date,
                  user["username"], editor_display, changes, supervisors),
        )

    return {"ok": True, "updated_at": now}


@router.delete("/api/daily-tasks/{task_id}")
def delete_daily_task(task_id: int, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('daily_task', 'case_manage'), "每日工作事項")
    if user["role"] != "superadmin":
        raise HTTPException(403, "僅最高管理者可刪除工作事項")
    conn = get_db()
    row = conn.execute(
        "SELECT title, task_date FROM daily_tasks WHERE id=? AND is_deleted=0", (task_id,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "工作事項不存在")
    now = datetime.now().isoformat()
    conn.execute("UPDATE daily_tasks SET is_deleted=1, updated_at=? WHERE id=?", (now, task_id))
    conn.commit()
    conn.close()
    _purge_notifications(str(task_id), ['daily_task'])
    _audit(_tok(authorization), "daily_task.delete", "daily_task", str(task_id),
           f"{row['task_date']} {row['title']}")
    notify_module_activity("工作事項", "刪除", user.get("display_name") or user["username"],
                            f"{row['task_date']} {row['title']}", "daily-tasks.html")
    return {"ok": True}


@router.get("/api/settings/reminder-send-failures")
def get_reminder_send_failures(authorization: str = Header(None)):
    """簽核提醒**永久寄不出去**的那幾筆。

    ## 🔴 這個端點存在的理由，比「多一個 API」深一層
    YA5 要求失敗要有落點，而 A 的原話是：
    > ⚠️ **落點要看得到** —— ☠️ 只寫進 log 的話就是把這一條原封不動換了個位置。

    📌 那正是這一整節在修的形狀：**一個沒有人看得到的事實等於沒有發生過。**
    ⇒ 一筆紀錄回答的是「**哪一張單子、哪一階、為什麼、試了幾次**」，
    而那四個合起來才足以讓人去處置它（通常是去幫那個人填 email）。

    ⚠️ 限 superadmin：它列得出單號與簽核流程的狀態。
    """
    _require_user(authorization, require_superadmin=True, module='settings')
    # 最新的排前面 —— 使用者要看的是「現在還卡著什麼」。
    return {"items": list(reversed(reminder_send_failures()))}


@router.get("/api/daily-tasks/{task_id}/history")
def get_task_history(
    task_id:  int,
    page:     int = 1,
    per_page: int = 20,
    authorization: str = Header(None),
):
    """Return paginated list of all past occurrences + completions for a task.
    Works even when the task is soft-deleted (history preservation)."""
    user = _require_user(authorization)
    require_any_module(user, ('daily_task', 'case_manage'), "每日工作事項")
    conn = get_db()
    row = conn.execute("SELECT * FROM daily_tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "工作事項不存在")
    d = dict(row)
    assigned  = json.loads(d.get("assigned_to") or "[]")
    sup_list  = json.loads(d.get("supervisors") or "[]")
    if user["role"] != "superadmin" and user["username"] not in assigned and user["username"] not in sup_list:
        conn.close()
        raise HTTPException(403, "無權限查看此工作事項歷史")

    user_rows = conn.execute("SELECT username, display_name FROM users").fetchall()
    dn_map = {r["username"]: (r["display_name"] or r["username"]) for r in user_rows}

    comp_rows = conn.execute(
        "SELECT username, occurrence_date, completed, report, completed_at, report_edit_count "
        "FROM daily_task_completions WHERE task_id=?",
        (task_id,),
    ).fetchall()
    comp_map: dict = {}
    for c in comp_rows:
        comp_map.setdefault(c["occurrence_date"], []).append({
            "username":    c["username"],
            "displayName": dn_map.get(c["username"], c["username"]),
            "completed":   bool(c["completed"]),
            "completedAt": c["completed_at"] or "",
            "report":      c["report"] or "",
            "editCount":   c["report_edit_count"] or 0,
        })

    rt    = d.get("recurrence_type") or "once"
    today = _date.today()

    if rt == "once":
        all_occs = [d["task_date"]]
    else:
        rec_days = json.loads(d.get("recurrence_days") or "[]")
        try:
            start = _date.fromisoformat(d["task_date"])
        except ValueError:
            start = today
        end_str   = d.get("recurrence_end_date") or ""
        end_date  = _date.fromisoformat(end_str) if end_str else today
        end_date  = min(end_date, today)
        all_occs  = []
        cur = start
        while cur <= end_date:
            if cur.weekday() in rec_days:
                all_occs.append(cur.isoformat())
            cur += _timedelta(days=1)

    all_occs.sort(reverse=True)
    total    = len(all_occs)
    per_page = max(1, min(per_page, 100))
    page     = max(1, page)
    offset   = (page - 1) * per_page
    page_occs = all_occs[offset: offset + per_page]

    _WD = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    occurrences = []
    for occ_date in page_occs:
        comps = comp_map.get(occ_date, [])
        full: list = []
        for u in assigned:
            found = next((c for c in comps if c["username"] == u), None)
            full.append(found or {
                "username": u, "displayName": dn_map.get(u, u),
                "completed": False, "completedAt": "", "report": "",
            })
        done = sum(1 for c in full if c["completed"])
        wd   = _WD[_date.fromisoformat(occ_date).weekday()]
        occurrences.append({
            "occurrence_date": occ_date,
            "weekday":         wd,
            "done_count":      done,
            "total":           len(assigned),
            "all_done":        done == len(assigned) and len(assigned) > 0,
            "completions":     full,
        })

    rec_days_l  = json.loads(d.get("recurrence_days") or "[]")
    rlabel = ("每週" + "".join(_WEEKDAY_NAMES[i] for i in sorted(rec_days_l) if 0 <= i <= 6)) \
             if rt == "weekly" else ""
    conn.close()
    return {
        "task": {
            "id":               d["id"],
            "title":            d["title"],
            "recurrence_type":  rt,
            "recurrence_label": rlabel,
            "assigned_to":      assigned,
            "assignees":        [{"username": u, "displayName": dn_map.get(u, u)} for u in assigned],
            "is_deleted":       bool(d.get("is_deleted")),
        },
        "total_occurrences": total,
        "page":     page,
        "per_page": per_page,
        "occurrences": occurrences,
    }


@router.get("/api/daily-tasks/{task_id}/edit-log")
def get_task_edit_log(task_id: int, authorization: str = Header(None)):
    """Return the edit history for a task (field-level diff records)."""
    user = _require_user(authorization)
    require_any_module(user, ('daily_task', 'case_manage'), "每日工作事項")
    conn = get_db()
    row = conn.execute("SELECT * FROM daily_tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "工作事項不存在")
    d        = dict(row)
    assigned = json.loads(d.get("assigned_to") or "[]")
    sup_list = json.loads(d.get("supervisors") or "[]")
    if (user["role"] != "superadmin"
            and user["username"] not in assigned
            and user["username"] not in sup_list):
        conn.close()
        raise HTTPException(403, "無權限查看此工作事項編輯紀錄")

    user_rows = conn.execute("SELECT username, display_name FROM users").fetchall()
    dn_map    = {r["username"]: (r["display_name"] or r["username"]) for r in user_rows}

    logs = conn.execute(
        "SELECT id, changed_by, changed_at, changes_json "
        "FROM daily_task_edit_log WHERE task_id=? ORDER BY changed_at DESC",
        (task_id,),
    ).fetchall()
    conn.close()

    result = []
    for lg in logs:
        try:
            changes = json.loads(lg["changes_json"] or "[]")
        except Exception:
            changes = []
        result.append({
            "id":               lg["id"],
            "changedBy":        lg["changed_by"],
            "changedByDisplay": dn_map.get(lg["changed_by"], lg["changed_by"]),
            "changedAt":        lg["changed_at"],
            "changes":          changes,
        })
    return {"items": result}


@router.get("/api/daily-tasks/{task_id}/history/export")
def export_task_history(task_id: int, authorization: str = Header(None)):
    """Stream all occurrences + completions as UTF-8-BOM CSV (Excel-compatible)."""
    user = _require_user(authorization)
    require_any_module(user, ('daily_task', 'case_manage'), "每日工作事項")
    conn = get_db()
    row = conn.execute("SELECT * FROM daily_tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "工作事項不存在")
    d = dict(row)
    assigned = json.loads(d.get("assigned_to") or "[]")
    if user["role"] != "superadmin" and user["username"] not in assigned:
        conn.close()
        raise HTTPException(403, "無權限匯出此工作事項")

    user_rows = conn.execute("SELECT username, display_name FROM users").fetchall()
    dn_map = {r["username"]: (r["display_name"] or r["username"]) for r in user_rows}

    comp_rows = conn.execute(
        "SELECT username, occurrence_date, completed, report, completed_at "
        "FROM daily_task_completions WHERE task_id=?",
        (task_id,),
    ).fetchall()
    comp_map: dict = {}
    for c in comp_rows:
        comp_map.setdefault(c["occurrence_date"], []).append({
            "username":  c["username"],
            "dn":        dn_map.get(c["username"], c["username"]),
            "completed": bool(c["completed"]),
            "at":        c["completed_at"] or "",
            "report":    c["report"] or "",
        })

    rt    = d.get("recurrence_type") or "once"
    today = _date.today()
    if rt == "once":
        all_occs = [d["task_date"]]
    else:
        rec_days = json.loads(d.get("recurrence_days") or "[]")
        try:
            start = _date.fromisoformat(d["task_date"])
        except ValueError:
            start = today
        end_str  = d.get("recurrence_end_date") or ""
        end_date = _date.fromisoformat(end_str) if end_str else today
        end_date = min(end_date, today)
        all_occs = []
        cur = start
        while cur <= end_date:
            if cur.weekday() in rec_days:
                all_occs.append(cur.isoformat())
            cur += _timedelta(days=1)
    all_occs.sort(reverse=True)
    conn.close()

    _WD = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    buf    = _io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(["工作事項", "日期", "星期", "指派人員", "完成狀態", "完成時間", "回報內容"])
    for occ_date in all_occs:
        comps = comp_map.get(occ_date, [])
        wd = _WD[_date.fromisoformat(occ_date).weekday()]
        for u in assigned:
            c = next((x for x in comps if x["username"] == u), None)
            writer.writerow([
                d["title"], occ_date, wd,
                dn_map.get(u, u),
                "已完成" if (c and c["completed"]) else "未完成",
                (c["at"]     if c else ""),
                (c["report"] if c else ""),
            ])

    return _HTTPResponse(
        content=buf.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"task_{task_id}_history.csv\""},
    )


@router.patch("/api/daily-tasks/{task_id}/complete")
def complete_daily_task(task_id: int, body: TaskCompletionIn, authorization: str = Header(None)):
    user = _require_user(authorization)
    require_any_module(user, ('daily_task', 'case_manage'), "每日工作事項")
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM daily_tasks WHERE id=? AND is_deleted=0", (task_id,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "工作事項不存在")
    assigned = json.loads(row["assigned_to"] or "[]")
    if user["username"] not in assigned:
        conn.close()
        raise HTTPException(403, "您未被指派此工作事項")

    # Determine occurrence_date
    occ_date = (body.occurrence_date or "").strip()
    if not occ_date:
        occ_date = row["task_date"]  # fallback for once tasks

    # Detect edit vs first-time completion before upsert
    prior = conn.execute(
        "SELECT report FROM daily_task_completions "
        "WHERE task_id=? AND occurrence_date=? AND username=? AND completed=1",
        (task_id, occ_date, user["username"]),
    ).fetchone()
    is_edit = prior is not None
    old_report = dict(prior)["report"] if prior else ""

    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO daily_task_completions "
        "(task_id, username, occurrence_date, completed, report, completed_at) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(task_id, occurrence_date, username) DO UPDATE SET "
        "completed=excluded.completed, report=excluded.report, completed_at=excluded.completed_at, "
        "report_edit_count=daily_task_completions.report_edit_count+1",
        (task_id, user["username"], occ_date,
         1 if body.completed else 0,
         body.report or '',
         now if body.completed else ''),
    )
    conn.commit()
    conn.close()
    action = "daily_task.complete" if body.completed else "daily_task.uncomplete"
    _audit(_tok(authorization), action, "daily_task", str(task_id),
           f"{row['task_date']} {row['title']} ({occ_date})", {"report": body.report or ""})
    if body.completed:
        supervisors = json.loads(row["supervisors"] or "[]")
        spawn_bg_thread(
            notify_daily_task_completed,
            args=(task_id, row["title"], occ_date,
                  user["username"], user.get("display_name") or user["username"],
                  body.report or "", supervisors, is_edit, old_report),
        )
    return {"ok": True, "completed_at": now if body.completed else ""}


# ── Overdue notification scheduler ────────────────────────────────────────────

import logging as _log
_logger = _log.getLogger(__name__)


def _check_overdue_and_notify(check_date: Optional[str] = None) -> None:
    """Scan tasks for check_date (default: yesterday); email every incomplete assignee once.
    Guards against duplicate runs (restart / crash) by writing last_check BEFORE the loop.
    If check_date is provided explicitly, the global guard is skipped for that date."""
    if check_date is None:
        target    = _date.today() - _timedelta(days=1)
        check_date = target.isoformat()
        # Guard: only proceed if this date hasn't been processed yet
        last_check = _get_setting("dt_overdue_last_check") or ""
        if last_check >= check_date:
            return  # already processed — safe to skip
        # Write the guard FIRST so a restart/exception won't re-trigger emails
        _set_setting("dt_overdue_last_check", check_date)
    else:
        target = _date.fromisoformat(check_date)

    target_wd = target.weekday()

    try:
        conn = get_db()
        tasks = conn.execute(
            "SELECT id, title, task_date, recurrence_type, recurrence_days, "
            "recurrence_end_date, assigned_to,"
            " COALESCE(supervisors,'[]') AS supervisors "
            "FROM daily_tasks WHERE is_deleted=0"
        ).fetchall()

        dn_map = {
            r["username"]: (r["display_name"] or r["username"])
            for r in conn.execute("SELECT username, display_name FROM users").fetchall()
        }
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

        for row in tasks:
            assigned = json.loads(row["assigned_to"] or "[]")
            if not assigned:
                continue

            rt = row["recurrence_type"] or "once"
            if rt == "range":
                continue  # range tasks handled by _check_range_task_deadline
            if rt == "once":
                if row["task_date"] != check_date:
                    continue
                occ_date = check_date
            else:  # weekly
                rec_days = json.loads(row["recurrence_days"] or "[]")
                if target_wd not in rec_days:
                    continue
                if row["task_date"] > check_date:
                    continue
                end_str = row["recurrence_end_date"] or ""
                if end_str and check_date > end_str:
                    continue
                occ_date = check_date

            sup_list = json.loads(row["supervisors"] or "[]")
            for username in assigned:
                comp = conn.execute(
                    "SELECT completed FROM daily_task_completions "
                    "WHERE task_id=? AND occurrence_date=? AND username=?",
                    (row["id"], occ_date, username),
                ).fetchone()
                if not comp or not comp["completed"]:
                    display = dn_map.get(username, username)
                    threading.Thread(
                        target=notify_daily_task_overdue,
                        args=(row["id"], row["title"], occ_date, username, display, sup_list),
                        daemon=True,
                    ).start()
                    # 2026-08-22g：額外通知該成員所屬部門的主管（處/部門組織架構延伸）——
                    # 跟上面的 supervisors（逐任務手動指定）是兩條獨立路徑，主管等於
                    # 逾期者本人時不重複通知自己
                    dept_id = dept_map.get(username)
                    mgr_username = dept_mgr_username.get(dept_id) if dept_id else None
                    if mgr_username and mgr_username != username:
                        _notify(mgr_username, "daily_task_overdue_manager", str(row["id"]), row["title"],
                                f"部門成員 {display} 負責的工作事項「{row['title']}」於 {occ_date} 截止日前尚未完成回報")
                        threading.Thread(
                            target=notify_daily_task_overdue_manager,
                            args=(row["id"], row["title"], occ_date, username, display, dept_id),
                            daemon=True,
                        ).start()

        conn.close()
        _logger.info("Daily task overdue check complete for %s", check_date)
    except Exception as exc:
        _logger.warning("_check_overdue_and_notify failed for %s: %s", check_date, exc)


def _check_range_task_deadline() -> None:
    """Notify assignees of range tasks expiring today or in 3 days (if not yet complete)."""
    today     = _date.today()
    today_str = today.isoformat()
    try:
        conn = get_db()
        dn_map = {r["username"]: (r["display_name"] or r["username"])
                  for r in conn.execute("SELECT username, display_name FROM users").fetchall()}
        for days_ahead, notif_type in ((3, "3d"), (0, "deadline")):
            check_date = (today + _timedelta(days=days_ahead)).isoformat()
            tasks = conn.execute(
                "SELECT id, title, recurrence_end_date, assigned_to, "
                "COALESCE(supervisors,'[]') AS supervisors "
                "FROM daily_tasks WHERE is_deleted=0 AND recurrence_type='range' "
                "AND recurrence_end_date=?",
                (check_date,),
            ).fetchall()
            for row in tasks:
                assigned = json.loads(row["assigned_to"] or "[]")
                sup_list = json.loads(row["supervisors"] or "[]")
                for username in assigned:
                    comp = conn.execute(
                        "SELECT id FROM daily_task_completions "
                        "WHERE task_id=? AND username=? AND completed=1",
                        (row["id"], username),
                    ).fetchone()
                    if comp:
                        continue
                    guard_key = f"range_notif.{row['id']}.{username}.{notif_type}"
                    if _get_setting(guard_key):
                        continue
                    _set_setting(guard_key, today_str)
                    display = dn_map.get(username, username)
                    threading.Thread(
                        target=notify_range_task_deadline,
                        args=(row["id"], row["title"], check_date, days_ahead,
                              username, display, sup_list),
                        daemon=True,
                    ).start()
        conn.close()
        _logger.info("Range task deadline check complete for %s", today_str)
    except Exception as exc:
        _logger.warning("_check_range_task_deadline failed: %s", exc)


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


# ── HTTPS 憑證到期檢查（2026-09-11）──────────────────────────────────────────
# 在此之前這件事完全沒有任何監控。目前服務中的是 mkcert 自簽憑證、2028-12-10
# 到期（星期日），而 mkcert 不會自己更新——到期後的第一個上班日，全公司的
# Passkey 會一起失效，而那時候不會有人記得「mkcert」是什麼。
#
# 門檻依「憑證總效期」自動切換，不必有人在換憑證來源時記得回來改常數：
#   mkcert 自簽 ≈ 822 天 → 要手動重產，得早點講
#   Let's Encrypt = 90 天，Posh-ACME 在剩 30 天時就會自動續期
#     → 剩 21 天還沒換掉，代表自動續期已經失敗，那才是真警報。
#       若對 LE 沿用 60 天門檻，每張憑證都會在一切正常的情況下誤報一次，
#       而狼來了的告警等於沒有告警。
_CERT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "certs", "cert.pem"
)
_CERT_LONG_LIVED_DAYS   = 180              # 總效期超過此天數 → 視為手動簽發
_CERT_THRESHOLDS_MANUAL = (0, 7, 21, 60)   # 必須遞增
_CERT_THRESHOLDS_ACME   = (0, 1, 7, 21)


def _read_serving_cert(path: str = None) -> Optional[dict]:
    """讀出目前服務中的憑證資訊；沒有憑證檔（純 HTTP 模式）時回傳 None。

    刻意讀檔而不是對自己開一條 TLS 連線：`start.bat`／`autostart.bat` 載入的
    就是這個檔（`if exist certs\\cert.pem` 才加 --ssl-* 參數），讀檔沒有網路
    依賴、不受服務當下狀態影響，測試也不必真的起一個 TLS server。
    """
    path = path or _CERT_PATH
    if not os.path.exists(path):
        return None
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes as _hashes

        with open(path, "rb") as fh:
            cert = x509.load_pem_x509_certificate(fh.read())

        # cryptography 42+ 把 not_valid_after 標為 deprecated，改用 *_utc；
        # 舊版沒有那個屬性，兩邊都接以免升級/降級任一方向都會炸。
        not_after = getattr(cert, "not_valid_after_utc", None)
        if not_after is None:
            not_after = cert.not_valid_after.replace(tzinfo=_timezone.utc)
        not_before = getattr(cert, "not_valid_before_utc", None)
        if not_before is None:
            not_before = cert.not_valid_before.replace(tzinfo=_timezone.utc)

        try:
            issuer_cn = cert.issuer.get_attributes_for_oid(
                x509.oid.NameOID.COMMON_NAME)[0].value
        except Exception:
            issuer_cn = ""

        today = datetime.now(_timezone.utc).date()
        return {
            "not_after":   not_after.date().isoformat(),
            "days_left":   (not_after.date() - today).days,
            "total_days":  (not_after.date() - not_before.date()).days,
            "issuer_cn":   issuer_cn,
            "fingerprint": cert.fingerprint(_hashes.SHA256()).hex()[:16],
            "path":        path,
        }
    except Exception as exc:
        _logger.warning("_read_serving_cert(%s) failed: %s", path, exc)
        return None


def _prune_cert_guard_keys(live_keys: set) -> None:
    """只保留本次算出來的 guard key，其餘 `cert_notif.*` 一律刪掉。

    理由同 `_prune_case_project_guard_keys()`：換一張憑證就換一組 fingerprint，
    舊的 key 永遠不會再被查詢；而比當前更早的門檻也不會再被問（剩餘天數只會
    遞減）。不收斂的話這裡會重演 `module_versions` 那種「只寫不刪」的長期累積。
    結果是這個前綴在 system_settings 裡最多只佔 1 列。
    """
    conn = get_db()
    try:
        existing = [r["key"] for r in conn.execute(
            "SELECT key FROM system_settings WHERE key LIKE 'cert_notif.%'"
        ).fetchall()]
        stale = [k for k in existing if k not in live_keys]
        if stale:
            conn.executemany(
                "DELETE FROM system_settings WHERE key=?", [(k,) for k in stale])
            conn.commit()
    except Exception as exc:
        _logger.warning("_prune_cert_guard_keys failed: %s", exc)
    finally:
        conn.close()


def _check_cert_expiry() -> None:
    """每日檢查 HTTPS 憑證剩餘天數；每個門檻各寄一次，已過期後每 7 天重寄。"""
    try:
        info = _read_serving_cert()
        if info is None:
            return  # 純 HTTP 模式（或憑證檔讀不到），沒有到期日要顧

        days_left  = info["days_left"]
        is_acme    = info["total_days"] <= _CERT_LONG_LIVED_DAYS
        thresholds = _CERT_THRESHOLDS_ACME if is_acme else _CERT_THRESHOLDS_MANUAL

        if days_left > thresholds[-1]:
            _prune_cert_guard_keys(set())   # 還很遠，順手把舊憑證留下的 key 收掉
            return

        if days_left < 0:
            bucket = f"exp{(-days_left) // 7}"       # 過期後每 7 天重寄一次
        else:
            bucket = next(str(t) for t in thresholds if days_left <= t)

        guard_key = f"cert_notif.{info['fingerprint']}_{bucket}"
        if _get_setting(guard_key):
            _prune_cert_guard_keys({guard_key})
            return

        _set_setting(guard_key, _date.today().isoformat())
        # 同 _check_case_project_timeline_deadline()：排程觸發、不掛在任何 request
        # 上，刻意用 threading.Thread 而非 db.spawn_bg_thread()（§3.5 例外 (a)）。
        threading.Thread(
            target=notify_cert_expiry,
            args=(days_left, info["not_after"], info["issuer_cn"], info["path"], is_acme),
            daemon=True,
        ).start()
        _logger.warning(
            "HTTPS cert expiring: %s days left (expires %s, issuer=%s)",
            days_left, info["not_after"], info["issuer_cn"],
        )
        _prune_cert_guard_keys({guard_key})
    except Exception as exc:
        _logger.warning("_check_cert_expiry failed: %s", exc)


# ── 備份新鮮度與磁碟空間（2026-09-14）──────────────────────────────────────────
#
# 這兩支補的是同一個結構性盲區：**備份系統的所有告警都是備份自己發出來的**。
# archive.py 在雲端碟掉了、某張表匯不出來的時候都會寫 BACKUP_ALERT + 寄信，
# 但「備份根本沒有跑」這件事沒有任何人會講——排程被停用、Timer 執行緒沒起來、
# 兩台機器共用同一個雲端資料夾導致其中一台看到 .done 就早退，症狀全部是
# **一片安靜**：伺服器活著、heartbeat 照打、備份頁面綠燈，只有真的要還原的
# 那天才會發現最後一份是三個月前的。
#
# 磁碟空間同理：滿了之後第一個壞掉的通常是備份（寫不進去）或測試（暫存寫不
# 進去），而這兩者都不會讓人第一時間聯想到磁碟。
#
# 做法比照 _check_cert_expiry()：掛在既有的每日 08:00 排程上，不另起 job；
# 用 system_settings 當「今天寄過了沒」的 guard，一天最多一封。

_BACKUP_STALE_HOURS = 36        # 每日備份的容許間隔（正常 24h，留一天的餘裕）
_DISK_FREE_MIN_PCT  = 10        # 剩餘空間低於此百分比 → 告警
# 2026-09-15：20 → 50 GB。這兩個門檻是 AND（見 _check_disk_space 的說明），所以在
# 1 TB 的碟上百分比那關永遠先滿足，實際的觸發點就是這個絕對值。20 GB 對一台
# 「每跑一次測試就寫 3～4 GB」的開發機來說太晚——剩 20 GB 時只剩五次測試的餘裕，
# 而且備份寫不進去通常會先發作。
_DISK_FREE_MIN_GB   = 50        # 或剩餘絕對量低於此 GB → 告警（大碟用百分比會太晚）

# 測試暫存總量超過這個值就寄信。**這條跟剩餘空間無關**：2026-09-15 實測 84 個
# `motrix-pytest-*` 目錄吃掉 136 GB，而碟上還剩 293 GB——剩餘空間的門檻不管怎麼調
# 都不會響（調到會響的程度就等於天天誤報）。照不到這種事的原因不是門檻太鬆，是
# 「只看剩多少」永遠看不到「有東西在無聲累積」。
_TEMP_BLOAT_MIN_GB  = 20

# 這些前綴是測試／打包留下的暫存，清掉一律安全。`motrix-*` 是帶時間戳或標籤的
# pytest basetemp——名字每次都不一樣，所以沒有任何機制會覆蓋或清除它；
# `pytest-of-*` 是 pytest 自己的預設 basetemp，它會輪替只留最新 3 份。
_TEMP_BLOAT_PREFIXES = ("motrix-pytest", "motrix-bench", "pytest-of-")


def _latest_audit_at(conn, actions: tuple) -> Optional[datetime]:
    """回傳 audit_log 裡這幾個 action 最後一次發生的時間，沒有就 None。"""
    ph = ",".join("?" * len(actions))
    row = conn.execute(
        f"SELECT MAX(at) AS at FROM audit_log WHERE action IN ({ph})", actions).fetchone()
    if not row or not row["at"]:
        return None
    try:
        return datetime.fromisoformat(row["at"])
    except ValueError:
        return None


def _check_backup_freshness() -> None:
    """每日檢查「最後一次成功備份」離現在多久；超過 _BACKUP_STALE_HOURS 就寄信。

    分兩條線各自判斷，因為它們的失效原因完全不同：
      本機 SQLite 快照（`backup.sqlite_snapshot`）——不依賴雲端碟，這條斷掉
        代表備份程式本身沒在跑（排程被關、Timer 執行緒死掉、服務一直沒起來）。
      雲端每日 JSON（`backup.daily_ok` / `backup.daily_partial`）——這條斷掉
        而本機那條還活著，代表雲端目的地出問題，或者**別台機器搶先寫了今天的
        .done 害這台早退**（見 archive.py `_daily_backup()`）。

    `backup.daily_partial` 也算「有跑」：它代表備份確實執行了、只是有表失敗，
    那個情境本來就有自己的告警，這裡不重複叫。

    全新環境（audit_log 一筆備份紀錄都沒有）**不告警**——那是還沒跑過第一次，
    不是壞掉；等第一次跑完之後這支才有意義的基準可以比。
    """
    try:
        conn = get_db()
        try:
            local_at = _latest_audit_at(conn, ("backup.sqlite_snapshot",))
            cloud_at = _latest_audit_at(conn, ("backup.daily_ok", "backup.daily_partial"))
        finally:
            conn.close()

        # 2026-09-15：這台機器刻意不上傳雲端（開發機，見 archive.cloud_archive_enabled）
        # → 雲端那條線本來就不會有紀錄，拿它當故障會變成每天一封假警報。**本機快照
        # 那條照舊檢查**：那才是「備份程式有沒有在跑」的指標，跟雲端政策無關。
        # archive 比照本檔既有慣例在函式內匯入（見 _disk_targets()）。
        try:
            import archive as _archive
            cloud_expected = _archive.cloud_archive_enabled()
        except Exception:
            cloud_expected = True       # 判斷不出來就照原本行為檢查，不要靜默少查一條

        if local_at is None and (cloud_at is None and cloud_expected):
            return          # 從來沒備份過 = 全新環境，不是故障
        if not cloud_expected and local_at is None:
            return          # 同上：不上傳雲端的機器只看本機那條，它也還沒跑過

        now = datetime.now()
        stale = []
        lines = [("本機 SQLite 快照", local_at)]
        if cloud_expected:
            lines.append(("雲端每日備份", cloud_at))
        for label, ts in lines:
            if ts is None:
                stale.append((label, None))
            else:
                hours = (now - ts).total_seconds() / 3600
                if hours > _BACKUP_STALE_HOURS:
                    stale.append((label, ts))

        guard_key = "backup_stale_last_notified"
        if not stale:
            if _get_setting(guard_key):
                _set_setting(guard_key, "")     # 恢復正常 → 清掉，下次再壞會立刻再寄
            return

        today = _date.today().isoformat()
        if _get_setting(guard_key) == today:
            return                               # 今天已經寄過

        # 🔴 **旗標在寄信成功之後才寫，不可以先寫。**
        # 原本是先 `_set_setting(guard_key, today)` 再開執行緒 ⇒
        # 通知只要丟例外，今天就**不會再試**；而那個例外是必然的
        # （`notify_backup_stale` 缺 `datetime` import）⇒ **永遠不會寄到**。
        # 🔑 「不要記錄失敗」與「要記得重試」是兩件事，前者做對不代表後者會發生。
        #
        # ⚠️ **例外要在執行緒裡面接，不能靠下面那個 `except`。**
        # 那個 `except` 只包得到「啟動執行緒」這個動作，包不到執行緒裡面發生的事
        # ⇒ 例外被 Python 印掉或吞掉，而 `_logger` 上一個字都沒有。
        # ☠️ **那就是那個 NameError 活到今天的原因：它每天都在發生，而沒有留下過痕跡。**
        # 🔑〈防護的副作用落在盲側〉：背景執行緒讓告警不會拖慢排程，
        # 代價是「**告警自己壞了**」變成不可觀測的——而那正是最需要被觀測的那一種失敗。
        def _send_alert():
            try:
                notify_backup_stale(stale, _BACKUP_STALE_HOURS)
            except Exception:  # noqa: BLE001
                _logger.exception("notify_backup_stale failed —— 旗標不寫，今天仍會重試")
                return
            _set_setting(guard_key, today)

        # 📌 **刻意不用 `spawn_bg_thread`**：C 的題 patch 的是 `dt.threading.Thread`，
        # 換過去 patch 會打不到（`spawn_bg_thread` 在 `db` 模組裡叫 `threading.Thread`）
        # ⇒ 那兩題會失去同步執行而變成靠時序，而 flaky 比不一致貴。
        # 例外可見性已由上面的 wrapper 解決，那才是那三件要的東西。
        # ⚠️ 這裡是**實作的形狀被測試的 patch 點決定的**——正解是「patch 打在對的層級」，
        # 不是「實作遷就 patch」。凍結解除後要回來看這一段。
        threading.Thread(
            target=_send_alert,
            args=(),
            daemon=True,
        ).start()
        _logger.error("備份新鮮度告警：%s",
                      "；".join(f"{l}={'從未執行' if t is None else t.isoformat()}"
                                for l, t in stale))
    except Exception as exc:
        _logger.warning("_check_backup_freshness failed: %s", exc)


def _disk_targets() -> list:
    """要監看的磁碟：資料庫所在的磁碟一定要看；雲端存檔目前若掛得起來也看一份
    （Google Drive 這類同步碟報出來的空間是雲端配額，一樣會滿）。回傳
    [(標籤, 路徑)]，重複的磁碟機代號只留一份。"""
    import db as _db
    targets = [("資料庫與程式碟", os.path.dirname(os.path.abspath(_db.DB_PATH)))]
    try:
        import archive
        # 2026-09-15：不上傳雲端的機器不監看雲端碟。那顆碟滿了不是這台的事，兩台
        # 都監看只會讓同一件事寄兩封信；而且在開發機上它根本不是備份目的地。
        base = archive._archive_base() if archive.cloud_archive_enabled() else ""
        if base:
            targets.append(("雲端存檔碟", base))
    except Exception:
        pass

    seen, out = set(), []
    for label, path in targets:
        try:
            key = os.path.splitdrive(os.path.abspath(path))[0].upper()
        except Exception:
            key = path
        if key in seen:
            continue
        seen.add(key)
        out.append((label, path))
    return out


def _check_disk_space() -> None:
    """每日檢查磁碟剩餘空間；低於門檻寄信。一天最多一封（同 _check_backup_freshness）。

    兩個門檻取「較寬鬆的那個滿足就算健康」：小碟看百分比、大碟看絕對 GB。
    只看百分比的話，2 TB 的碟剩 10%（200 GB）就叫太早；只看 GB 的話，
    256 GB 的系統碟剩 20 GB 其實已經很緊了卻還不叫。
    """
    try:
        import shutil as _shutil
        problems = []
        for label, path in _disk_targets():
            try:
                usage = _shutil.disk_usage(path)
            except Exception:
                continue        # 碟沒掛上／路徑不可用 → 那是備份告警的守備範圍
            free_gb  = usage.free / (1024 ** 3)
            free_pct = (usage.free / usage.total * 100) if usage.total else 0
            if free_gb < _DISK_FREE_MIN_GB and free_pct < _DISK_FREE_MIN_PCT:
                problems.append({
                    "label": label, "path": path,
                    "free_gb": round(free_gb, 1),
                    "total_gb": round(usage.total / (1024 ** 3), 1),
                    "free_pct": round(free_pct, 1),
                })

        guard_key = "disk_low_last_notified"
        if not problems:
            if _get_setting(guard_key):
                _set_setting(guard_key, "")
            return

        today = _date.today().isoformat()
        if _get_setting(guard_key) == today:
            return
        _set_setting(guard_key, today)

        threading.Thread(target=notify_disk_space_low, args=(problems,), daemon=True).start()
        _logger.error("磁碟空間告警：%s",
                      "；".join(f"{p['label']} 剩 {p['free_gb']}GB／{p['free_pct']}%"
                                for p in problems))
    except Exception as exc:
        _logger.warning("_check_disk_space failed: %s", exc)


def _temp_bloat_dirs() -> list:
    """列出 `%TEMP%` 底下的測試／打包暫存目錄與各自大小，大的在前。

    回傳 `[{name, path, gb}]`。掃不到或沒有權限的目錄一律跳過——這是觀測用的
    數字，不該因為某個子目錄讀不到就整支壞掉。
    """
    import tempfile
    base = tempfile.gettempdir()
    out = []
    try:
        entries = list(os.scandir(base))
    except OSError:
        return out
    for e in entries:
        try:
            if not e.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        if not e.name.startswith(_TEMP_BLOAT_PREFIXES):
            continue
        total = 0
        for root, _dirs, files in os.walk(e.path, onerror=lambda _e: None):
            for f in files:
                try:
                    total += os.stat(os.path.join(root, f)).st_size
                except OSError:
                    continue
        out.append({"name": e.name, "path": e.path, "bytes": total,
                    "gb": round(total / (1024 ** 3), 2)})
    # 比大小一律用原始 bytes：`gb` 是顯示用的，先四捨五入再加總會把一堆
    # 小於 5 MB 的目錄全算成 0。
    out.sort(key=lambda x: x["bytes"], reverse=True)
    return out


def _check_temp_bloat() -> None:
    """每日檢查測試暫存是否無聲累積；超過 `_TEMP_BLOAT_MIN_GB` 就寄信。一天一封。

    為什麼要獨立於剩餘空間告警：那支只會在「快滿了」才叫，而這種累積在一顆 1 TB
    的碟上可以吃掉 136 GB 都還離「快滿了」很遠（2026-09-15 實測）。等它把碟吃滿
    才叫，症狀會先表現成「測試跑不起來」或「備份寫不進去」，很難聯想到這裡。
    """
    try:
        dirs = _temp_bloat_dirs()
        total_raw_gb = sum(d["bytes"] for d in dirs) / (1024 ** 3)
        total_gb = round(total_raw_gb, 1)
        guard_key = "temp_bloat_last_notified"
        if total_raw_gb < _TEMP_BLOAT_MIN_GB:
            if _get_setting(guard_key):
                _set_setting(guard_key, "")
            return

        today = _date.today().isoformat()
        if _get_setting(guard_key) == today:
            return
        _set_setting(guard_key, today)

        threading.Thread(target=notify_disk_space_low, args=([],),
                         kwargs={"temp_bloat": dirs, "temp_total_gb": total_gb},
                         daemon=True).start()
        _logger.error("測試暫存佔用告警：共 %s GB，%s 個目錄（最大：%s）",
                      total_gb, len(dirs), dirs[0]["name"] if dirs else "-")
    except Exception as exc:
        _logger.warning("_check_temp_bloat failed: %s", exc)


# ── 簽核逾期催辦（2026-08-21）────────────────────────────────────────────────
# 報價單／承攬商匯款申請／開票申請憑據三張表的 approval JSON 形狀完全相同
# （{requestedBy, requestedAt, tiers:[{approvers:[{username,status}]}], currentTier}），
# 但比照這三個 router 各自重複一份 _active_tiers()/_current_tier_idx() 小工具的既有
# 慣例（quotations.py／contractor_vouchers.py／invoice_vouchers.py 皆有一份幾乎逐字
# 相同的版本，刻意不跨 router import 以避免循環依賴），這裡也自己放一份。

def _active_tiers(appr: dict) -> list:
    return appr.get("tiers") or []


def _current_tier_idx(appr: dict) -> int:
    return appr.get("currentTier") or 0


_APPROVAL_REMINDER_SOURCES = [
    {
        "table": "quotations", "no_col": "quote_no", "label": "報價單",
        "select_extra": "customer_name, project_name",
        "desc": lambda row, snap: (row["customer_name"] or "")
                                   + (("｜" + row["project_name"]) if row["project_name"] else ""),
    },
    {
        "table": "contractor_payment_vouchers", "no_col": "voucher_no", "label": "匯款申請",
        "select_extra": "snapshot_json",
        "desc": lambda row, snap: snap.get("vendorName") or "外包人員點工",
    },
    {
        "table": "invoice_vouchers", "no_col": "voucher_no", "label": "開票申請憑據",
        "select_extra": "snapshot_json",
        "desc": lambda row, snap: snap.get("customerName") or "",
    },
    {
        "table": "shipping_notes", "no_col": "note_no", "label": "出貨單",
        "select_extra": "customer_name, project_name",
        "desc": lambda row, snap: (row["customer_name"] or "")
                                   + (("｜" + row["project_name"]) if row["project_name"] else ""),
    },
    {
        "table": "payment_requests", "no_col": "request_no", "label": "請款單",
        "select_extra": "snapshot_json",
        "desc": lambda row, snap: snap.get("customerName") or "",
    },
]


#: 前三階，之後**以五為基準**。使用者原話：
#: 「第三天、第五天、再來第十天以五為基準重新寄信」。
REMINDER_FIRST_STAGES = (1, 3, 5)
REMINDER_STEP_AFTER = 5


def reminder_stage(days):
    """第 N 個工作日要寄哪一階，或 `None`（不寄）。

    `1 → "d1"`、`3 → "d3"`、`5 → "d5"`、`10 → "d10"`、`15 → "d15"`…
    **其餘一律 `None`。**

    ## ☠️ 這裡取代的是什麼
    ```python
    if   days_elapsed >= 5:  _fire(True,  f"5d.{today_str}")   ← 鍵含日期
    elif days_elapsed >= 3:  _fire(True,  "3d")
    else:                    _fire(False, "1d")
    ```
    第 5 天之後 dedup 鍵每天都是新的 ⇒ **每天一封**。
    一筆卡 20 個工作日的單子會寄 **1 + 1 + 16 = 18 封**。

    ## 📌 為什麼是具名純函式
    原本這段邏輯是迴圈裡的三個 `if`，**沒有任何辦法單獨問它**
    「第 7 天會不會寄」。〈決定邏輯抽純函式才測得到「換一種設定」〉。

    ⚠️ 第 0 天與負數的判斷**留在這裡**，不是只留在呼叫端 ——
    搬到呼叫端的話，那道防線就搬到了一個沒有人看的地方。
    """
    try:
        days = int(days)
    except (TypeError, ValueError):
        return None
    if days < 1:
        return None
    if days in REMINDER_FIRST_STAGES:
        return f"d{days}"
    if days > REMINDER_FIRST_STAGES[-1] and days % REMINDER_STEP_AFTER == 0:
        return f"d{days}"
    return None


def reminder_stages_at_or_below(days):
    """所有**不超過** `days` 的階段，由小到大。

    🔴 它回答的是**另一個問題**：不是「這次寄哪一封」，
    而是「**要把哪幾階記成已寄**」。

    ☠️ 一筆單子從第 2 天停機到第 12 天 ⇒ 只該寄 `d10` **一封**，
    而 `d1`／`d3`／`d5` 要**一併標記成已寄** —— 不標的話下一次排程會補一遍，
    使用者會在同一天收到四封，**而那正是這一節要消滅的東西**。
    🔑 **「補掉欠的」與「補寄欠的」只差一個字，而收件匣裡差四封。**

    ⚠️ 用同一個答案回答兩個問題的話，其中一個一定會錯。
    """
    try:
        days = int(days)
    except (TypeError, ValueError):
        return []
    out = [f"d{n}" for n in REMINDER_FIRST_STAGES if n <= days]
    n = REMINDER_FIRST_STAGES[-1] + REMINDER_STEP_AFTER
    while n <= days:
        out.append(f"d{n}")
        n += REMINDER_STEP_AFTER
    return out


#: 永久性寄送失敗的落點。
#:
#: 📌〈計數器要有落點〉：「要記錄失敗原因」**先指出記在哪張表**，
#: 否則那句要求**永遠不會被違反，也永遠不會被滿足**。
#: ⚠️ 用 `system_settings` 一列而不是新開一張表：這是**運維紀錄**不是業務資料，
#: 而新增一張表要 migration、要進備份決策、要有人決定保留期
#: ——今天已經為 `geocode_cache` 走過一次那個流程。
REMINDER_FAILURE_SETTING = "approval_reminder_failures"

#: 最多留幾筆。⚠️ 不設上限的話，一個永遠不會被修的收件人
#: 會讓那一列無限成長，而 `system_settings` 會進每日備份。
REMINDER_FAILURE_KEEP = 200


def reminder_send_failures():
    """永久性寄送失敗的紀錄。**最新的在後面。**

    每一筆：文件別／單號／階段／失敗類別／時間／嘗試次數。
    ☠️ **只寫進 log 的話，就是把這條缺陷原封不動換了個位置** ——
    所以它同時有一個端點（`GET /api/settings/reminder-send-failures`）。
    """
    rows = _get_setting(REMINDER_FAILURE_SETTING, []) or []
    return rows if isinstance(rows, list) else []


def _record_reminder_failure(doc_type, doc_no, stage, reason):
    """記一筆永久性失敗。**同一張單子的同一階只留一筆，累加嘗試次數。**

    ⚠️ 每次都追加一筆的話，一張永遠寄不出去的單子會把這張清單灌滿，
    而**真正需要被看到的那幾筆會被擠掉**（`REMINDER_FAILURE_KEEP`）。
    """
    key = f"{doc_type}|{doc_no}|{stage}"
    rows = [dict(r) for r in reminder_send_failures() if isinstance(r, dict)]
    now = datetime.now().isoformat(timespec="seconds")
    for row in rows:
        if row.get("key") == key:
            row["attempts"] = int(row.get("attempts", 0) or 0) + 1
            row["at"] = now
            row["reason"] = reason
            break
    else:
        rows.append({"key": key, "docType": doc_type, "docNo": doc_no,
                     "stage": stage, "reason": reason, "attempts": 1,
                     "at": now})
    _set_setting(REMINDER_FAILURE_SETTING, rows[-REMINDER_FAILURE_KEEP:])


def reminder_dedup_key(stage):
    """某一階的去重鍵。**只吃階段，不吃日期。**

    🔑 **這支函式的簽名本身就是那道防線**：不收日期參數
    ⇒ 「每天一個新鍵」在**結構上**不可能，
    而不是靠下一個人記得不要把 `today_str` 串進去。
    📌 〈修作法不要修結果〉。
    """
    return f"stage.{stage}"


def _check_approval_reminders() -> None:
    """簽核卡在柱列的催辦：**第 1／3／5 個工作日各一封，之後每 5 個工作日一封**
    （10、15、20…），3 天起同步通知全部 superadmin，直到簽核完成或退回為止。
    一律從 approval.requestedAt（原始送審時間）起算工作日，不因換層歸零；
    guard key 帶入 requestedAt，文件退回重新送審後 requestedAt 換新值，催辦
    倒數會自然重新從 0 天起算，不會被舊一輪的 guard 卡住讓新一輪永遠不寄。
    工作日計算只排除週六日，不排除國定假日（見 helpers/dates.py _workdays_elapsed
    docstring，系統目前沒有假日行事曆表可用，屬已知限制）。"""
    today     = _date.today()
    today_str = today.isoformat()
    try:
        conn = get_db()
        superadmins = [r["username"] for r in conn.execute(
            "SELECT username FROM users WHERE role='superadmin' AND active=1"
        ).fetchall()]

        for src in _APPROVAL_REMINDER_SOURCES:
            rows = conn.execute(
                f"SELECT {src['no_col']} AS doc_no, {src['select_extra']}, "
                f"json_extract(data_json,'$.approval') AS approval_json "
                f"FROM {src['table']} WHERE status IN ('待審核','簽核中')"
            ).fetchall()
            for row in rows:
                try:
                    appr = json.loads(row["approval_json"] or "{}")
                except Exception:
                    continue
                requested_at = appr.get("requestedAt") or ""
                if not requested_at:
                    continue
                try:
                    start_date = _date.fromisoformat(requested_at[:10])
                except Exception:
                    continue
                days_elapsed = _workdays_elapsed(start_date, today)
                if days_elapsed < 1:
                    continue

                tiers  = _active_tiers(appr)
                ct_idx = _current_tier_idx(appr)
                if tiers and ct_idx < len(tiers):
                    approvers     = tiers[ct_idx].get("approvers") or []
                    first_pending = next((a for a in approvers if a.get("status") != "approved"), None)
                    recipients    = [first_pending["username"]] if first_pending else []
                elif tiers:
                    continue  # 所有層皆已完成但 status 尚未更新 — 暫態，略過
                else:
                    recipients = list(superadmins)
                if not recipients:
                    continue

                snap = {}
                if "snapshot_json" in row.keys():
                    try:
                        snap = json.loads(row["snapshot_json"] or "{}")
                    except Exception:
                        snap = {}
                desc      = src["desc"](row, snap)
                doc_no    = row["doc_no"]
                doc_type  = src["label"]
                guard_base = f"approval_notif.{src['table']}.{doc_no}.{requested_at}"

                def _mark(stage: str) -> None:
                    _set_setting(f"{guard_base}.{reminder_dedup_key(stage)}",
                                 today_str)

                def _sent(stage: str) -> bool:
                    return bool(_get_setting(
                        f"{guard_base}.{reminder_dedup_key(stage)}"))

                # 🔴 **欠的階段一次結清，而只寄最高的那一封。**
                #
                # ⚠️ 判準是「**這個階段寄過沒有**」，不是「今天是不是第 5 天」——
                # 週末與停機會讓門檻被整個跳過，而那時
                # 「今天剛好是第幾天」問不出正確答案。
                owed = [st for st in reminder_stages_at_or_below(days_elapsed)
                        if not _sent(st)]
                if owed:
                    highest = owed[-1]
                    # 3 天門檻起才同步通知 superadmin（維持原本的分界）。
                    also_superadmin = int(highest[1:]) >= 3

                    # 🔴🔴 **先寄，成功才記「已通知」。**
                    #
                    # ☠️ 原本是「先 `_mark()` 再開 daemon 執行緒寄」
                    # ⇒ 信掉了而標記留著 ⇒ **那張單子永遠不會再被提醒**，
                    # 🔑 而它的症狀是**沒有症狀**：畫面正常、log 裡一行
                    # warning，而沒有人在看那一行。
                    #
                    # ⚠️ **同步呼叫不是效率的退讓**：`_check_approval_reminders`
                    # 本來就跑在背景排程裡，**沒有理由再開一層執行緒**——
                    # 而那一層正是「呼叫端拿不到結果」的成因。
                    # 📌 信裡的天數是**實際等了幾天**（12），不是門檻值（10）。
                    outcome = notify_approval_reminder(
                        doc_type, doc_no, desc, days_elapsed, recipients,
                        also_superadmin)

                    if outcome == _SEND_PERMANENT_FAIL:
                        # **這一封**永遠寄不出去（收件人沒有 email）
                        # ⇒ 標記＋留一筆看得見的失敗紀錄。
                        # ☠️ 不標記的話排程每天重試到天荒地老，
                        # 🔑 而「每天重試」與「已經修好了」在 log 上長得一樣。
                        _record_reminder_failure(doc_type, doc_no, highest,
                                                 outcome)
                    elif outcome != _SEND_SENT:
                        # `transient_fail`（SMTP 抖了）或 `skipped`
                        # （這台機器刻意不寄）⇒ **什麼都不記，明天再試**。
                        # ⚠️ 站內通知也一起延後：它跟標記綁在一起，
                        # 否則重試的每一天都會再產生一則站內通知。
                        continue

                    # ⚠️ **欠的低階段一併標記**（WA6）：不標的話下一次排程
                    # 會把它們補寄一遍，使用者同一天收到四封。
                    for st in owed:
                        _mark(st)
                    notify_targets = (list(set(recipients + superadmins))
                                      if also_superadmin else recipients)
                    for u in notify_targets:
                        _notify(u, "approval_reminder", doc_no, doc_no,
                                f"{doc_type} {doc_no} 已等待簽核 "
                                f"{days_elapsed} 個工作日，敬請儘速處理")
        conn.close()
        _logger.info("Approval reminder check complete for %s", today_str)
    except Exception as exc:
        _logger.warning("_check_approval_reminders failed: %s", exc)


def _prune_request_log(keep_days: int = 90) -> None:
    """清掉 90 天前的操作軌跡（2026-09-14，DB v80）。

    這張表每個人每次操作都寫一列，不設保留期限的話它會變成整個資料庫裡最大的一張，
    備份也跟著變大。90 天的取捨：**足夠回頭查「上個月那筆資料是誰改的」**，又不會
    讓一份本質上是觀測資料的東西無限累積。要調整就改這個參數。

    同時也是隱私上的分寸——逐條行為紀錄留越久，外洩時的代價越大。
    """
    from datetime import datetime as _dt, timedelta as _td
    cutoff = (_dt.now() - _td(days=keep_days)).isoformat()
    try:
        conn = get_db()
        cur = conn.execute("DELETE FROM user_request_log WHERE at < ?", (cutoff,))
        conn.commit()
        conn.close()
        if cur.rowcount:
            _logger.info("操作軌跡清理：刪除 %d 筆 %d 天前的紀錄", cur.rowcount, keep_days)
    except Exception as e:
        _logger.warning("_prune_request_log failed: %s", e)


def schedule_overdue_check() -> None:
    """Call once on server startup. Repeats daily at 08:00.
    On startup: immediately processes ALL missed days since last check (catch-up),
    so late boots or multi-day outages never silently skip overdue notifications."""

    def _daily_run():
        """Regular 08:00 run — processes yesterday."""
        _check_overdue_and_notify()
        _check_warranty_expiry()
        _check_range_task_deadline()
        _check_case_stage_deadline()
        _check_case_project_timeline_deadline()
        _check_project_deadline()
        _check_approval_reminders()
        _check_cert_expiry()
        _check_backup_freshness()
        _check_disk_space()
        _check_temp_bloat()
        _prune_request_log()

    def _startup_catchup():
        """Process every day from (last_check + 1) through yesterday in order."""
        last_str  = _get_setting("dt_overdue_last_check") or ""
        today     = _date.today()
        yesterday = today - _timedelta(days=1)

        if not last_str:
            # First ever run — only process yesterday to avoid spamming historical tasks
            _check_overdue_and_notify()
            _check_warranty_expiry()
            # 2026-09-11：這一行原本只在下面的「補跑」分支有、這裡沒有，全新環境
            # 第一次啟動當天的區間工作事項到期提醒會被靜默跳過。它跟同批其他檢查
            # 一樣是**看未來**的（今天／+3 天），不會因為補跑歷史而洗版，
            # 沒有理由獨漏——單純是當初漏了。
            _check_range_task_deadline()
            _check_case_stage_deadline()
            _check_case_project_timeline_deadline()
            _check_project_deadline()
            _check_approval_reminders()
            _check_cert_expiry()
            _check_backup_freshness()
            _check_disk_space()
            _check_temp_bloat()
            return

        # Advance day-by-day through any gap
        try:
            current = _date.fromisoformat(last_str) + _timedelta(days=1)
        except ValueError:
            current = yesterday  # malformed guard value — fall back to yesterday

        while current <= yesterday:
            _check_overdue_and_notify(current.isoformat())
            _set_setting("dt_overdue_last_check", current.isoformat())
            current += _timedelta(days=1)

        _check_warranty_expiry()
        _check_range_task_deadline()
        _check_case_stage_deadline()
        _check_case_project_timeline_deadline()
        _check_project_deadline()
        _check_approval_reminders()
        _check_cert_expiry()
        _check_backup_freshness()
        _check_disk_space()
        _check_temp_bloat()
        _logger.info("Startup catch-up complete, processed up to %s", yesterday)

    # Always run catch-up on startup (the guard inside prevents duplicate emails)
    threading.Thread(target=_startup_catchup, daemon=True).start()

    def _next_08() -> float:
        now  = datetime.now()
        t08  = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if t08 <= now:
            t08 += _timedelta(days=1)
        return (t08 - now).total_seconds()

    def _loop():
        _daily_run()
        t = threading.Timer(_next_08(), _loop)
        t.daemon = True
        t.start()

    t = threading.Timer(_next_08(), _loop)
    t.daemon = True
    t.start()
