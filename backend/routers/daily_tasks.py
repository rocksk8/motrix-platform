"""Daily work task management — superadmin creates/assigns, users complete & report.
Supports once-off and weekly recurring tasks (per-day occurrence tracking).
"""
import calendar
import json
import threading
from datetime import date as _date, timedelta as _timedelta, datetime
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
    notify_project_deadline, notify_project_deadline_manager, notify_module_activity,
    _get_setting, _set_setting, notify_approval_reminder, _workdays_elapsed,
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
    """Notify assigned members of projects whose expected completion date
    (projects.data_json.endDate) is 3 days out or today, if project not yet closed.
    Falls back to admin/superadmin when no members are assigned."""
    today     = _date.today()
    today_str = today.isoformat()
    try:
        conn = get_db()
        users       = conn.execute("SELECT id, username, display_name, role FROM users WHERE active=1").fetchall()
        dn_map      = {u["username"]: (u["display_name"] or u["username"]) for u in users}
        uid_map     = {u["id"]: u["username"] for u in users}
        admin_users = [u["username"] for u in users if u["role"] in ("admin", "superadmin")]
        dept_mgr_username = {
            r["id"]: r["mgr_username"]
            for r in conn.execute("""
                SELECT d.id, u.username AS mgr_username FROM departments d
                JOIN users u ON u.id = d.manager_user_id WHERE u.active=1
            """).fetchall()
        }
        rows = conn.execute("""
            SELECT id, code, name, status, assigned_user_ids, department_id,
                   json_extract(data_json, '$.endDate') AS end_date
            FROM projects
            WHERE status NOT IN ('完工','結案','取消')
              AND json_extract(data_json, '$.endDate') IS NOT NULL
              AND json_extract(data_json, '$.endDate') != ''
        """).fetchall()
        conn.close()

        for days_ahead, notif_type in ((3, "3d"), (0, "deadline")):
            check_date = (today + _timedelta(days=days_ahead)).isoformat()
            for row in rows:
                if row["end_date"] != check_date:
                    continue
                try:
                    assigned_ids = json.loads(row["assigned_user_ids"] or "[]")
                except Exception:
                    assigned_ids = []
                usernames = [uid_map[uid] for uid in assigned_ids if uid in uid_map] or admin_users
                for username in usernames:
                    guard_key = f"project_notif.{row['code']}.{username}.{notif_type}"
                    if _get_setting(guard_key):
                        continue
                    _set_setting(guard_key, today_str)
                    display = dn_map.get(username, username)
                    threading.Thread(
                        target=notify_project_deadline,
                        args=(row["id"], row["code"], row["name"], check_date, days_ahead, username, display),
                        daemon=True,
                    ).start()
                    _notify(username, "project_deadline", row["code"], row["name"],
                            f"專案「{row['name']}」" + ("今日到期" if days_ahead == 0 else f"{days_ahead} 天後到期"))

                # 案件/專案管理延伸（2026-08-22）：額外通知專案所屬部門的主管（一個專案通知一次，
                # 不像上面逐 assignee 迴圈——專案本身就有 department_id，不用查表）
                dept_id = row["department_id"]
                mgr_username = dept_mgr_username.get(dept_id) if dept_id else None
                if mgr_username:
                    mgr_guard_key = f"project_notif_mgr.{row['code']}.{notif_type}"
                    if not _get_setting(mgr_guard_key):
                        _set_setting(mgr_guard_key, today_str)
                        _notify(mgr_username, "project_deadline_manager", row["code"], row["name"],
                                f"部門專案「{row['name']}」" + ("今日到期" if days_ahead == 0 else f"{days_ahead} 天後到期"))
                        threading.Thread(
                            target=notify_project_deadline_manager,
                            args=(row["id"], row["code"], row["name"], check_date, days_ahead, dept_id),
                            daemon=True,
                        ).start()
        _logger.info("Project deadline check complete for %s", today_str)
    except Exception as exc:
        _logger.warning("_check_project_deadline failed: %s", exc)


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
]


def _check_approval_reminders() -> None:
    """簽核卡在柱列超過工作日 1/3/5 天分級催辦：1、3 天門檻各寄一次，3 天起同步
    通知全部 superadmin，5 天以上每個工作日都重複寄，直到簽核完成或退回為止。
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

                def _fire(also_superadmin: bool, dedup_key: str) -> None:
                    g = f"{guard_base}.{dedup_key}"
                    if _get_setting(g):
                        return
                    _set_setting(g, today_str)
                    threading.Thread(
                        target=notify_approval_reminder,
                        args=(doc_type, doc_no, desc, days_elapsed, recipients, also_superadmin),
                        daemon=True,
                    ).start()
                    notify_targets = list(set(recipients + superadmins)) if also_superadmin else recipients
                    for u in notify_targets:
                        _notify(u, "approval_reminder", doc_no, doc_no,
                                f"{doc_type} {doc_no} 已等待簽核 {days_elapsed} 個工作日，敬請儘速處理")

                if days_elapsed >= 5:
                    _fire(True, f"5d.{today_str}")
                elif days_elapsed >= 3:
                    _fire(True, "3d")
                else:
                    _fire(False, "1d")
        conn.close()
        _logger.info("Approval reminder check complete for %s", today_str)
    except Exception as exc:
        _logger.warning("_check_approval_reminders failed: %s", exc)


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
        _check_project_deadline()
        _check_approval_reminders()

    def _startup_catchup():
        """Process every day from (last_check + 1) through yesterday in order."""
        last_str  = _get_setting("dt_overdue_last_check") or ""
        today     = _date.today()
        yesterday = today - _timedelta(days=1)

        if not last_str:
            # First ever run — only process yesterday to avoid spamming historical tasks
            _check_overdue_and_notify()
            _check_warranty_expiry()
            _check_case_stage_deadline()
            _check_project_deadline()
            _check_approval_reminders()
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
        _check_project_deadline()
        _check_approval_reminders()
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
