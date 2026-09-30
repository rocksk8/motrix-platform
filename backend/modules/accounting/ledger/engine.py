# -*- coding: utf-8 -*-
"""分錄引擎（C1）：向各來源模組收集 `gl.events`，依內容雜湊冪等地產生傳票草稿、偵測來源事後被改（drift）。設計：proposal-gl/02-events-engine.md。

原則：只產生**草稿**（kind='auto'），過帳由會計走既有簽核；已過帳的傳票一律不改，來源變動 ⇒ 標 drift、產生反向草稿＋新內容草稿；
缺科目／期間已結帳 ⇒ 標 blocked_*，不猜、不放行；所有來源缺席的原因由 `contract.collect` 明說。所有函式不 commit（呼叫端決定交易）。

事件狀態（gl_source_events.status）：
  drafted 已產生草稿 → posted 傳票已過帳 → （來源被改）drift → reversed 反向傳票已過帳；
  superseded 草稿被新版本取代；orphan 來源已消失；rejected 使用者作廢了草稿（引擎不再重建）；
  blocked_closed 事件日落在已結帳／鎖定期間；blocked_no_account 缺角色／科目不可過帳。
"""
import datetime as _dt
import json

from modules.accounting.ledger import contract as _contract
from modules.accounting.ledger import periods as _periods
from modules.accounting.ledger import roles as _roles


class NoAccount(Exception):
    pass


def _now():
    return _dt.datetime.now().isoformat(timespec="seconds")


def _account_for(conn, line, on_date):
    """事件行→科目代號。行帶 `account_code`（例：銀行帳戶科目）就用它（須存在、可過帳、未停用）；否則依角色設定。"""
    code = (line.get("account_code") or "").strip()
    if code:
        m = conn.execute("SELECT postable, is_active FROM gl_account_meta WHERE code=?", (code,)).fetchone()
        if m is None:
            raise NoAccount("科目 %s 不存在" % code)
        if not m["postable"] or not m["is_active"]:
            raise NoAccount("科目 %s 不可過帳或已停用" % code)
        return code
    code = _roles.resolve_role(conn, line["role"], on_date=on_date)
    if not code:
        raise NoAccount("尚未設定科目角色 %s" % line["role"])
    return code


def _resolve(conn, ev):
    out = []
    for ln in ev["lines"]:
        if not ln["amount"]:
            continue
        out.append(dict(ln, _code=_account_for(conn, ln, ev["event_date"])))
    if not out:
        raise NoAccount("事件金額全部是 0")
    return out


def _voucher_row(conn, vid):
    if not vid:
        return None
    r = conn.execute("SELECT id, voucher_no, status, voided_at FROM vouchers_all WHERE id=?", (vid,)).fetchone()
    return dict(r) if r else None


def _make_draft(conn, ev, resolved, user, kind="auto", reverse=False, reverses_no="", date=None, event_id=0, code_hint=None):
    """寫一張草稿傳票（含維度欄位）。`reverse=True` 借貸對調。回 (voucher_id, voucher_no)。"""
    from modules.accounting.api.voucher_common import _amount_lines, insert_draft_voucher
    from modules.accounting.voucher import classify_category
    now = _now()
    lines = []
    for ln in resolved:
        side = ln["side"]
        if reverse:
            side = "C" if side == "D" else "D"
        lines.append({"account_code": ln["_code"], "summary": (ln.get("memo") or ev.get("doc_no") or ev["event_code"])[:60],
                      "debit": ln["amount"] if side == "D" else 0, "credit": ln["amount"] if side == "C" else 0,
                      "source_type": "", "source_key": ""})
    norm = _amount_lines(lines)
    party = (ev.get("party") or {}).get("name") or ""
    summary = ("%s%s %s %s" % ("【沖轉】" if reverse else "", ev.get("doc_no") or ev["source_key"], party, ev["event_code"]))[:60]
    vid, no = insert_draft_voucher(conn, date or ev["event_date"], summary, norm, user, now, classify_category(conn, norm), manual=0)
    conn.execute("UPDATE vouchers_all SET kind=?, origin=?, reverses_no=?, gl_event_id=?, is_backfill=? WHERE id=?",
                 (kind, "gl:%s" % ev["event_code"], reverses_no, event_id, 1 if ev.get("backfill") else 0, vid))
    for i, ln in enumerate(resolved, start=1):
        conn.execute("UPDATE voucher_lines SET case_no=?, party_key=?, tax_code=?, doc_no=? WHERE voucher_id=? AND line_no=?",
                     (ln.get("case_no") or ev.get("case_no") or "", ln.get("party_key") or (ev.get("party") or {}).get("key") or "",
                      ln.get("tax_code") or ev.get("tax_code") or "", ev.get("doc_no") or "", vid, i))
    return vid, no


def _void_draft(conn, vid, user, reason):
    conn.execute("UPDATE vouchers_all SET voided_at=?, voided_by=?, void_reason=? WHERE id=? AND status='草稿' AND voided_at=''",
                 (_now(), user, reason, vid))


def _insert_event(conn, ev, status, rev=1, voucher_id=None, supersedes_id=None, note=""):
    now = _now()
    cur = conn.execute(
        "INSERT INTO gl_source_events(source_module, source_type, source_key, event_code, rev, event_date, content_hash, amount, status,"
        " voucher_id, supersedes_id, note, payload_json, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ev.get("source_module", ""), ev["source_type"], ev["source_key"], ev["event_code"], rev, ev["event_date"], ev["content_hash"],
         sum(l["amount"] for l in ev["lines"] if l["side"] == "D"), status, voucher_id, supersedes_id, note,
         json.dumps(ev, ensure_ascii=False), now, now))
    return cur.lastrowid


def sync_statuses(conn):
    """把引擎事件的狀態對回傳票現況（傳票被過帳／被作廢）。回被更新的筆數。"""
    n = 0
    for e in conn.execute("SELECT id, status, voucher_id, reversal_voucher_id FROM gl_source_events WHERE status IN ('drafted','drift','orphan')").fetchall():
        v = _voucher_row(conn, e["voucher_id"])
        rv = _voucher_row(conn, e["reversal_voucher_id"])
        new = None
        if e["status"] == "drafted":
            if v and v["voided_at"]:
                new = "rejected"
            elif v and v["status"] == "已過帳":
                new = "posted"
        elif e["status"] in ("drift", "orphan") and rv and rv["status"] == "已過帳" and not rv["voided_at"]:
            new = "reversed"
        if new:
            conn.execute("UPDATE gl_source_events SET status=? WHERE id=?", (new, e["id"]))
            n += 1
    return n


def _latest(conn, ev):
    r = conn.execute("SELECT * FROM gl_source_events WHERE source_type=? AND source_key=? AND event_code=? ORDER BY rev DESC LIMIT 1",
                     (ev["source_type"], ev["source_key"], ev["event_code"])).fetchone()
    return dict(r) if r else None


def _create_or_block(conn, ev, user, stats, rev=1, supersedes_id=None, existing_id=None):
    """新事件（或被取代的新版本／先前被擋的事件）→ 產生草稿或標 blocked。"""
    try:
        resolved = _resolve(conn, ev)
    except NoAccount as exc:
        return _set_blocked(conn, ev, "blocked_no_account", str(exc), rev, supersedes_id, existing_id, stats)
    lock = _periods.lock_error(conn, ev["event_date"])
    if lock:
        return _set_blocked(conn, ev, "blocked_closed", lock + "請重開期間，或改併入當期。", rev, supersedes_id, existing_id, stats)
    eid = existing_id or _insert_event(conn, ev, "pending", rev, None, supersedes_id)
    vid, no = _make_draft(conn, ev, resolved, user, event_id=eid)
    conn.execute("UPDATE gl_source_events SET status='drafted', voucher_id=?, content_hash=?, event_date=?, payload_json=?, note='', last_seen=? WHERE id=?",
                 (vid, ev["content_hash"], ev["event_date"], json.dumps(ev, ensure_ascii=False), _now(), eid))
    stats["created"] += 1
    return eid


def _set_blocked(conn, ev, status, note, rev, supersedes_id, existing_id, stats):
    if existing_id:
        conn.execute("UPDATE gl_source_events SET status=?, note=?, content_hash=?, event_date=?, payload_json=?, last_seen=? WHERE id=?",
                     (status, note, ev["content_hash"], ev["event_date"], json.dumps(ev, ensure_ascii=False), _now(), existing_id))
        eid = existing_id
    else:
        eid = _insert_event(conn, ev, status, rev, None, supersedes_id, note)
    stats["blocked"] += 1
    return eid


def _reverse_posted(conn, old, user, stats, why):
    """已過帳的舊傳票 ⇒ 產生反向草稿（日期＝今天，落在開放期間）；回 (reversal_id or None, 備註)。"""
    v = _voucher_row(conn, old["voucher_id"])
    if not v or v["voided_at"] or v["status"] != "已過帳":
        return None, ""
    ev = json.loads(old["payload_json"] or "{}")
    if not ev.get("lines"):
        return None, "找不到原事件內容，無法自動產生反向傳票，請手工沖轉 %s。" % v["voucher_no"]
    today = _dt.date.today().isoformat()
    lock = _periods.lock_error(conn, today)
    if lock:
        return None, "反向傳票的日期 %s 落在已結帳期間，請手工沖轉 %s。" % (today, v["voucher_no"])
    try:
        resolved = _resolve(conn, ev)
    except NoAccount as exc:
        return None, "無法產生反向傳票（%s），請手工沖轉 %s。" % (exc, v["voucher_no"])
    rid, rno = _make_draft(conn, ev, resolved, user, kind="reversal", reverse=True, reverses_no=v["voucher_no"], date=today, event_id=old["id"])
    stats["reversals"] += 1
    return rid, "已產生反向草稿 %s（%s）" % (rno, why)


def _process(conn, ev, user, stats):
    stats["scanned"] += 1
    latest = _latest(conn, ev)
    if latest is None:
        _create_or_block(conn, ev, user, stats)
        return
    if latest["status"] in ("blocked_closed", "blocked_no_account"):
        _create_or_block(conn, ev, user, stats, rev=latest["rev"], existing_id=latest["id"])      # 條件可能已改善（重開期間、補角色）
        return
    if latest["content_hash"] == ev["content_hash"]:
        conn.execute("UPDATE gl_source_events SET last_seen=? WHERE id=?", (_now(), latest["id"]))
        return
    v = _voucher_row(conn, latest["voucher_id"])
    stats["drift"] += 1
    if latest["status"] in ("superseded", "rejected", "reversed"):
        _create_or_block(conn, ev, user, stats, rev=latest["rev"] + 1, supersedes_id=latest["id"])
        return
    if v and not v["voided_at"] and v["status"] == "草稿":                                      # 草稿：安全地作廢重建
        _void_draft(conn, v["id"], user, "來源事件內容已變動，重新產生")
        conn.execute("UPDATE gl_source_events SET status='superseded', note='來源內容變動，草稿已由新版本取代' WHERE id=?", (latest["id"],))
        stats["drift"] -= 1
        stats["superseded"] += 1
        _create_or_block(conn, ev, user, stats, rev=latest["rev"] + 1, supersedes_id=latest["id"])
        return
    # 已過帳（或審核中）：不動舊傳票，標 drift；已過帳者另產反向草稿，再產新內容草稿
    rid, note = _reverse_posted(conn, latest, user, stats, "來源內容變動")
    if not note and v and not v["voided_at"] and v["status"] != "已過帳":
        note = "傳票 %s 正在審核（%s）；來源內容已變動，請退回或作廢它，以新草稿為準。" % (v["voucher_no"], v["status"])
    conn.execute("UPDATE gl_source_events SET status='drift', reversal_voucher_id=?, note=? WHERE id=?", (rid, note or "來源內容變動", latest["id"]))
    _create_or_block(conn, ev, user, stats, rev=latest["rev"] + 1, supersedes_id=latest["id"])


def _orphans(conn, start, end, seen, ok_sources, user, stats):
    for e in conn.execute("SELECT * FROM gl_source_events WHERE status IN ('drafted','posted') AND event_date BETWEEN ? AND ?", (start, end)).fetchall():
        e = dict(e)
        if e["source_module"] not in ok_sources or (e["source_type"], e["source_key"], e["event_code"]) in seen:
            continue
        v = _voucher_row(conn, e["voucher_id"])
        if v and not v["voided_at"] and v["status"] == "草稿":
            _void_draft(conn, v["id"], user, "來源事件已不存在")
            conn.execute("UPDATE gl_source_events SET status='orphan', note='來源已不存在，草稿已作廢' WHERE id=?", (e["id"],))
        else:
            rid, note = _reverse_posted(conn, e, user, stats, "來源已不存在")
            conn.execute("UPDATE gl_source_events SET status='orphan', reversal_voucher_id=?, note=? WHERE id=?", (rid, note or "來源已不存在", e["id"]))
        stats["orphans"] += 1


def run(conn, start, end, user):
    """向所有來源收集事件並落到傳票草稿。回 `{stats, notices, invalid, sources, run_id}`。"""
    started = _now()
    _roles.ensure_meta(conn)
    _roles.ensure_default_roles(conn)
    res = _contract.collect(start, end, conn=conn)
    stats = {"scanned": 0, "created": 0, "drift": 0, "superseded": 0, "reversals": 0, "blocked": 0, "orphans": 0}
    sync_statuses(conn)
    seen = set()
    for ev in res["events"]:
        seen.add((ev["source_type"], ev["source_key"], ev["event_code"]))
        _process(conn, ev, user, stats)
    ok_sources = {k for k, v in res["sources"].items() if v == "ok"}
    _orphans(conn, start, end, seen, ok_sources, user, stats)
    sync_statuses(conn)
    cur = conn.execute(
        "INSERT INTO gl_engine_runs(started_at, finished_at, started_by, range_start, range_end, scanned, created, drift, blocked, notices_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)", (started, _now(), user, start, end, stats["scanned"], stats["created"], stats["drift"], stats["blocked"],
                                          json.dumps(res["notices"], ensure_ascii=False)))
    return {"stats": stats, "notices": res["notices"], "invalid": res["invalid"][:50], "invalid_count": len(res["invalid"]),
            "sources": res["sources"], "run_id": cur.lastrowid}


def list_events(conn, status=None, start=None, end=None, limit=500):
    sync_statuses(conn)
    q = ("SELECT e.id, e.source_module, e.source_type, e.source_key, e.event_code, e.rev, e.event_date, e.amount, e.status, e.note,"
         " e.voucher_id, v.voucher_no, v.status AS voucher_status, e.reversal_voucher_id, rv.voucher_no AS reversal_no, rv.status AS reversal_status"
         " FROM gl_source_events e LEFT JOIN vouchers_all v ON v.id=e.voucher_id LEFT JOIN vouchers_all rv ON rv.id=e.reversal_voucher_id WHERE 1=1")
    args = []
    if status:
        q += " AND e.status=?"
        args.append(status)
    if start:
        q += " AND e.event_date>=?"
        args.append(start)
    if end:
        q += " AND e.event_date<=?"
        args.append(end)
    q += " ORDER BY e.event_date DESC, e.id DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) for r in conn.execute(q, args)]
