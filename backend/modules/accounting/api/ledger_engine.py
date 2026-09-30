# -*- coding: utf-8 -*-
"""總帳：分錄引擎介面（A 階段：只有事件來源狀態與預覽，不產生傳票）。設計：proposal-gl/02-events-engine.md。

`GET /api/ledger/events/preview` 向所有 `gl.events` 提供者收集事件並驗證，回來源狀態、事件數、無效事件與缺席說明；
不寫任何資料。C 階段才加「產生草稿」。
"""
import datetime as _dt
import json

from fastapi import APIRouter, Body, Header, HTTPException, Query

from db import get_db
from helpers import _audit, _require_user, _tok, require_any_module
from modules.accounting.ledger import auto_run as _auto_run
from modules.accounting.ledger import contract as _contract
from modules.accounting.ledger import engine as _engine
from modules.accounting.ledger import features as _features

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


def _require_engine_read(authorization):
    user = _require_user(authorization)
    require_any_module(user, ("cashier", "finance"), "總帳")
    return user


@router.get("/events/preview")
def events_preview(start: str, end: str, authorization: str = Header(None)):
    _require_engine_read(authorization)
    try:
        s, e = _dt.date.fromisoformat(start), _dt.date.fromisoformat(end)
    except ValueError:
        raise HTTPException(400, "日期格式要是 YYYY-MM-DD。")
    if s > e:
        raise HTTPException(400, "起日不可晚於迄日。")
    conn = get_db()
    try:
        res = _contract.collect(s.isoformat(), e.isoformat(), conn=conn)
    finally:
        conn.close()
    return {"contract_version": _contract.CONTRACT_VERSION, "count": len(res["events"]), "sources": res["sources"],
            "notices": res["notices"], "invalid": res["invalid"][:50], "invalid_count": len(res["invalid"]),
            "events": res["events"][:200]}


# ── 分錄引擎（C1）：產生草稿、事件清單、整批確認。功能旗標 engine_drafts 開啟才可用（預設關）──────────

def _require_engine_write(authorization):
    user = _require_user(authorization)
    require_any_module(user, ("finance",), "分錄引擎")
    return user


def _require_flag(conn):
    if not _features.flags(conn).get("engine_drafts"):
        raise HTTPException(409, "分錄草稿功能尚未開啟（最高管理者在「總帳作業」開啟）。")


def _range(start, end):
    try:
        s, e = _dt.date.fromisoformat(start), _dt.date.fromisoformat(end)
    except ValueError:
        raise HTTPException(400, "日期格式要是 YYYY-MM-DD。")
    if s > e:
        raise HTTPException(400, "起日不可晚於迄日。")
    return s.isoformat(), e.isoformat()


@router.post("/engine/run")
def engine_run(body: dict = Body(...), authorization: str = Header(None)):
    """向所有來源收集事件並產生／更新傳票草稿（冪等；來源事後被改標 drift 並產生更正組）。"""
    user = _require_engine_write(authorization)
    s, e = _range(str((body or {}).get("start") or ""), str((body or {}).get("end") or ""))
    conn = get_db()
    try:
        _require_flag(conn)
        res = _engine.run(conn, s, e, (user or {}).get("username") or "")
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.engine.run", "gl_engine_runs", str(res["run_id"]), "產生分錄草稿 %s～%s：新增 %d" % (s, e, res["stats"]["created"]))
    return res


@router.get("/engine/events")
def engine_events(status: str = None, start: str = None, end: str = None, limit: int = Query(500, le=2000),
                  authorization: str = Header(None)):
    _require_engine_read(authorization)
    conn = get_db()
    try:
        _require_flag(conn)
        rows = _engine.list_events(conn, status, start, end, limit)
        conn.commit()
        counts = {}
        for r in rows:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {"events": rows, "counts": counts}
    finally:
        conn.close()


@router.get("/engine/status")
def engine_status(authorization: str = Header(None)):
    """橫幅資料：自上次執行後有多少來源變動（新增／內容變動／已消失）、最近一次執行與自動執行的結果。唯讀，不動任何資料。"""
    _require_engine_read(authorization)
    conn = get_db()
    try:
        _require_flag(conn)
        return _auto_run.status(conn)
    finally:
        conn.close()


@router.get("/engine/runs")
def engine_runs(authorization: str = Header(None)):
    _require_engine_read(authorization)
    conn = get_db()
    try:
        _require_flag(conn)
        rows = [dict(r) for r in conn.execute("SELECT * FROM gl_engine_runs ORDER BY id DESC LIMIT 50")]
        for r in rows:
            r["notices"] = json.loads(r.pop("notices_json") or "[]")
        return {"runs": rows}
    finally:
        conn.close()


@router.post("/engine/batch")
def engine_batch(body: dict = Body(...), authorization: str = Header(None)):
    """整批確認：對勾選的傳票逐張執行送審／核准／過帳（各自走既有狀態機與權限檢查，一張失敗不影響其他）。
    action：submit｜approve｜post｜all（草稿→送審→核准到底→過帳，遇到非本人可簽的層即停並說明）。"""
    user = _require_engine_write(authorization)
    ids = [int(x) for x in ((body or {}).get("voucher_ids") or [])]
    action = str((body or {}).get("action") or "")
    if not ids or action not in ("submit", "approve", "post", "all"):
        raise HTTPException(400, "需要 voucher_ids 與 action（submit／approve／post／all）。")
    if len(ids) > 500:
        raise HTTPException(400, "一次最多 500 張。")
    from modules.accounting.api import vouchers as _v
    conn = get_db()
    try:
        _require_flag(conn)
        auto = {r[0] for r in conn.execute("SELECT id FROM vouchers_all WHERE kind IN ('auto','reversal') AND id IN (%s)" % ",".join("?" * len(ids)), ids)}
    finally:
        conn.close()
    results = []
    for vid in ids:
        if vid not in auto:
            results.append({"id": vid, "ok": False, "error": "不是引擎產生的傳票，這裡不處理（請到傳票頁）。"})
            continue
        try:
            results.append({"id": vid, "ok": True, "status": _advance(_v, vid, action, authorization)})
        except HTTPException as exc:
            results.append({"id": vid, "ok": False, "error": str(exc.detail)})
    conn = get_db()
    try:
        conn.execute("INSERT INTO gl_confirm_batches(action, created_by, created_at, total, ok_count, detail_json) VALUES (?,?,?,?,?,?)",
                     (action, (user or {}).get("username") or "", _dt.datetime.now().isoformat(timespec="seconds"), len(results),
                      sum(1 for r in results if r["ok"]), json.dumps(results, ensure_ascii=False)))
        _engine.sync_statuses(conn)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.engine.batch", "vouchers", ",".join(map(str, ids[:20])), "整批%s：%d 張，成功 %d" % (action, len(results), sum(1 for r in results if r["ok"])))
    return {"results": results, "ok": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"])}


def _status_of(vid):
    conn = get_db()
    try:
        r = conn.execute("SELECT status FROM vouchers_all WHERE id=? AND voided_at=''", (vid,)).fetchone()
        return r[0] if r else None
    finally:
        conn.close()


def _advance(_v, vid, action, authorization):
    """依 action 推進一張傳票，回最後狀態。過程中任何一步被既有規則擋下 ⇒ 丟 HTTPException（訊息原樣給使用者）。"""
    if action == "submit":
        _v.submit_voucher(vid, {}, authorization)
    elif action == "approve":
        _v.approve_voucher(vid, {}, authorization)
    elif action == "post":
        _v.post_voucher_endpoint(vid, {}, authorization)
    else:
        for _ in range(8):
            st = _status_of(vid)
            if st == "草稿":
                _v.submit_voucher(vid, {}, authorization)
            elif st in ("待審核", "簽核中"):
                _v.approve_voucher(vid, {}, authorization)
            elif st == "已核准":
                _v.post_voucher_endpoint(vid, {}, authorization)
            else:
                break
    return _status_of(vid)
