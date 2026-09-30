# -*- coding: utf-8 -*-
"""總帳申請（會計規定 C 類，2026-09-30）：結帳、重開期間、年度決算、期初批次建立，一般財務人員送申請、
最高管理者（會計主管）核准後**自動執行**；最高管理者自己做則直接執行（不走申請）。

流程：pending →（核准並執行成功）approved ／（退回）returned ／（申請人撤回）withdrawn。
- 核准時先執行；執行失敗（例如期間前置條件不成立）⇒ 申請維持 pending、回錯誤原因（核准人可退回或稍後再核准），
  不會出現「已核准但沒執行」。
- 申請只增不刪；每一次決定都留決定人／時間／說明。
- 執行時的動作人＝申請人（帳上「誰結的帳」是申請人，核准人在申請紀錄與稽核）。
純服務層：不 commit（呼叫端 commit）、不寄信、不寫稽核。
"""
import datetime as _dt
import json

from modules.accounting.ledger import closing as _closing
from modules.accounting.ledger import opening as _opening
from modules.accounting.ledger import periods as _periods

PENDING, APPROVED, RETURNED, WITHDRAWN = "待審核", "已核准", "已退回", "已撤回"
STATUS_LABEL = {PENDING: "待核准", APPROVED: "已核准並執行", RETURNED: "已退回", WITHDRAWN: "已撤回"}
ACTIONS = ("period_close", "period_reopen", "year_close", "opening_create")
_MAX_PARAMS_BYTES = 2_000_000


class RequestError(ValueError):
    """申請流程的錯誤（訊息給人看）。"""


class RequestConflict(RequestError):
    """狀態不允許這個動作（已被決定／已撤回）⇒ 409。"""


def _int(v, what):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise RequestError("%s要是整數。" % what)
    if n <= 0:
        raise RequestError("%s要是正整數。" % what)
    return n


def _period(conn, period_id):
    p = conn.execute("SELECT id, year, period_no, start_date, end_date, status FROM gl_periods WHERE id=?", (period_id,)).fetchone()
    if not p:
        raise RequestError("找不到期間 %s。" % period_id)
    return p


def _year_open(conn, year):
    y = conn.execute("SELECT status FROM gl_fiscal_years WHERE year=?", (year,)).fetchone()
    if not y:
        raise RequestError("年度 %d 不存在，請先建立會計年度。" % year)
    if y["status"] != "open":
        raise RequestError("%d 年度已經決算，不能再送這個申請。" % year)


def normalize(conn, action, params):
    """驗證並整理參數 ⇒ (params, 顯示名稱)。只留該動作認得的欄位（多餘欄位丟掉，避免夾帶）。"""
    if action not in ACTIONS:
        raise RequestError("不支援的申請類型：%s（可申請：%s）。" % (action, "、".join(ACTIONS)))
    p = params if isinstance(params, dict) else {}
    if action in ("period_close", "period_reopen"):
        pid = _int(p.get("period_id"), "期間")
        per = _period(conn, pid)
        base = "%d 年第 %d 期（%s～%s）" % (per["year"], per["period_no"], per["start_date"], per["end_date"])
        if action == "period_close":
            if per["status"] != "open":                     # 送出前就擋：不要讓最高管理者核准一個做不了的申請
                raise RequestError("這個期間現在是「%s」，只有開放的期間可以結帳。" % {"closed": "已結帳", "locked": "已鎖定"}.get(per["status"], per["status"]))
            return ({"period_id": pid, "accept_warnings": bool(p.get("accept_warnings")), "reason": str(p.get("reason") or "").strip()[:500]}, "結帳：" + base)
        reason = str(p.get("reason") or "").strip()
        if not reason:
            raise RequestError("重開期間必須填寫理由。")
        if per["status"] == "locked":
            raise RequestError("這個期間已鎖定，請先由最高管理者解鎖。")
        if per["status"] != "closed":
            raise RequestError("這個期間目前是開放的，不需要重開。")
        return ({"period_id": pid, "reason": reason[:500]}, "重開期間：" + base)
    if action == "year_close":
        y = _int(p.get("year"), "年度")
        _year_open(conn, y)
        return ({"year": y, "accept_warnings": bool(p.get("accept_warnings"))}, "年度決算：%d 年度" % y)
    year = _int(p.get("year"), "年度")
    _year_open(conn, year)
    rows, items = p.get("rows") or [], p.get("items") or []
    if not isinstance(rows, list) or not isinstance(items, list) or not (rows or items):
        raise RequestError("期初餘額批次需要科目餘額（rows）或往來明細（items）。")
    out = {"year": year, "opening_date": str(p.get("opening_date") or ""), "rows": rows, "items": items, "filename": str(p.get("filename") or "")[:200]}
    if len(json.dumps(out, ensure_ascii=False)) > _MAX_PARAMS_BYTES:
        raise RequestError("期初批次資料太大（上限約 2MB）。")
    return (out, "建立期初餘額批次：%d 年度（%d 列科目餘額、%d 筆往來明細）" % (year, len(rows), len(items)))


def _next_no(conn, now):
    day = now[:10].replace("-", "")
    n = conn.execute("SELECT COUNT(*) FROM gl_action_requests WHERE request_no LIKE ?", ("LA-%s-%%" % day,)).fetchone()[0] + 1
    while conn.execute("SELECT 1 FROM gl_action_requests WHERE request_no=?", ("LA-%s-%03d" % (day, n),)).fetchone():
        n += 1
    return "LA-%s-%03d" % (day, n)


def create(conn, user, action, params):
    """建立申請（pending）。同一人同一動作同一參數已有待核准 ⇒ 擋（避免連按產生多張）。"""
    p, label = normalize(conn, action, params)
    blob = json.dumps(p, ensure_ascii=False, sort_keys=True)
    uname = (user or {}).get("username") or ""
    dup = conn.execute("SELECT request_no FROM gl_action_requests WHERE status='待審核' AND action=? AND requested_by=? AND params_json=?",
                       (action, uname, blob)).fetchone()
    if dup:
        raise RequestConflict("你已經送出同一個申請（%s），請等待最高管理者核准。" % dup["request_no"])
    now = _dt.datetime.now().isoformat(timespec="seconds")
    no = _next_no(conn, now)
    display = (user or {}).get("display_name") or uname
    appr = json.dumps({"tiers": [], "currentTier": 0, "requestedBy": uname, "requestedByDisplay": display, "requestedAt": now}, ensure_ascii=False)
    rid = conn.execute("INSERT INTO gl_action_requests(request_no, action, label, params_json, status, requested_by, requested_by_display, requested_at, approval_json)"
                       " VALUES (?,?,?,?,?,?,?,?,?)",
                       (no, action, label, blob, PENDING, uname, display, now, appr)).lastrowid
    return get(conn, rid)


def get(conn, rid):
    row = conn.execute("SELECT * FROM gl_action_requests WHERE id=?", (rid,)).fetchone()
    return _row(row) if row else None


def _row(r):
    d = dict(r)
    d.pop("approval_json", None)
    d["status_label"] = STATUS_LABEL.get(d["status"], d["status"])
    try:
        d["params"] = json.loads(d.pop("params_json") or "{}")
    except ValueError:
        d["params"] = {}
    try:
        d["result"] = json.loads(d.pop("result_json") or "{}")
    except ValueError:
        d["result"] = {}
    if d["action"] == "opening_create":              # 列表不帶整批資料
        d["params"] = {k: v for k, v in d["params"].items() if k not in ("rows", "items")}
    return d


def list_requests(conn, username=None, status=None, limit=200):
    q, args = "SELECT * FROM gl_action_requests WHERE 1=1", []
    if username:
        q, args = q + " AND requested_by=?", args + [username]
    if status:
        q, args = q + " AND status=?", args + [status]
    return [_row(r) for r in conn.execute(q + " ORDER BY id DESC LIMIT ?", args + [int(limit)])]


def pending_rows(conn):
    return list_requests(conn, status=PENDING, limit=500)


def _load_pending(conn, rid):
    row = conn.execute("SELECT * FROM gl_action_requests WHERE id=?", (rid,)).fetchone()
    if not row:
        raise RequestError("找不到這張申請。")
    if row["status"] != PENDING:
        raise RequestConflict("這張申請已經是「%s」，不能再處理。" % STATUS_LABEL.get(row["status"], row["status"]))
    return row


def _execute(conn, row):
    p = json.loads(row["params_json"] or "{}")
    who = row["requested_by"]
    try:
        if row["action"] == "period_close":
            return {"tb_hash": _periods.close_period(conn, p["period_id"], who, bool(p.get("accept_warnings")), p.get("reason") or "")}
        if row["action"] == "period_reopen":
            return {"stale_later_periods": _periods.reopen_period(conn, p["period_id"], who, p.get("reason") or "")}
        if row["action"] == "year_close":
            return dict(_closing.close_year(conn, p["year"], who, bool(p.get("accept_warnings"))) or {})
        return dict(_opening.create_batch(conn, p["year"], p.get("opening_date") or "", p.get("rows") or [], p.get("items") or [], p.get("filename") or "", who))
    except (_periods.PeriodError, _closing.ClosingError, _opening.OpeningError) as exc:
        raise RequestError(str(exc))


def approve(conn, rid, approver):
    """核准並執行。⇒ 更新後的申請。執行失敗 ⇒ RequestError（申請仍 pending，呼叫端要 rollback）。"""
    row = _load_pending(conn, rid)
    result = _execute(conn, row)
    now = _dt.datetime.now().isoformat(timespec="seconds")
    conn.execute("UPDATE gl_action_requests SET status=?, decided_by=?, decided_at=?, result_json=? WHERE id=?",
                 (APPROVED, (approver or {}).get("username") or "", now, json.dumps(result, ensure_ascii=False, default=str), rid))
    return get(conn, rid)


def send_back(conn, rid, approver, note):
    row = _load_pending(conn, rid)
    if not (note or "").strip():
        raise RequestError("退回要填寫原因。")
    now = _dt.datetime.now().isoformat(timespec="seconds")
    conn.execute("UPDATE gl_action_requests SET status=?, decided_by=?, decided_at=?, decision_note=? WHERE id=?",
                 (RETURNED, (approver or {}).get("username") or "", now, note.strip()[:500], rid))
    return get(conn, row["id"])


def withdraw(conn, rid, user):
    row = _load_pending(conn, rid)
    if row["requested_by"] != ((user or {}).get("username") or ""):
        raise RequestError("只有申請人可以撤回自己的申請。")
    now = _dt.datetime.now().isoformat(timespec="seconds")
    conn.execute("UPDATE gl_action_requests SET status=?, decided_by=?, decided_at=? WHERE id=?",
                 (WITHDRAWN, row["requested_by"], now, rid))
    return get(conn, rid)
