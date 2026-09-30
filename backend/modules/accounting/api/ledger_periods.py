# -*- coding: utf-8 -*-
"""總帳：會計年度／期間／結帳鎖定／期初餘額 API。設計：proposal-gl/03-periods-close.md。

權限（P1，主持 2026-09-30 裁示先沿用現有鍵）：讀＝cashier／finance；結帳、重開、建年度、期初＝finance（superadmin 直通）；
鎖定、解鎖＝superadmin。
"""
import sqlite3

from fastapi import APIRouter, Body, Header, HTTPException

from db import get_db
from helpers import _audit, _require_user, _tok, require_any_module
from modules.accounting.ledger import opening as _opening
from modules.accounting.ledger import periods as _periods

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

_READ = ("cashier", "finance")
_WRITE = ("finance",)


def _who(user):
    return (user or {}).get("username") or ""


def _require_read(authorization):
    user = _require_user(authorization)
    require_any_module(user, _READ, "總帳")
    return user


def _require_write(authorization):
    user = _require_user(authorization)
    require_any_module(user, _WRITE, "總帳結帳")
    return user


def _require_superadmin(authorization, what="鎖定或解鎖期間"):
    user = _require_user(authorization)
    if user.get("role") != "superadmin":
        raise HTTPException(403, "只有最高管理者（會計主管）可以%s。" % what)
    return user


def _run(conn, fn, *args):
    """把服務層的中文錯誤轉成 400；DB 觸發器的 ABORT 轉成 409（不讓它變 500）。"""
    try:
        return fn(conn, *args)
    except (_periods.PeriodError, _opening.OpeningError) as exc:
        conn.rollback()
        raise HTTPException(400, str(exc))
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise HTTPException(409, str(exc))


@router.get("/years")
def years(authorization: str = Header(None)):
    _require_read(authorization)
    conn = get_db()
    try:
        return {"years": _periods.list_years(conn), "fiscal_start_month": _periods.fiscal_start_month(conn),
                "batches": _opening.list_batches(conn)}
    finally:
        conn.close()


@router.post("/years")
def create_year(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_write(authorization)
    try:
        year = int((body or {}).get("year"))
    except (TypeError, ValueError):
        raise HTTPException(400, "請填年度（整數）。")
    conn = get_db()
    try:
        _run(conn, _periods.create_year, year, _who(user))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.year.create", "gl_fiscal_years", str(year), "建立會計年度 %d" % year)
    return {"ok": True, "year": year}


@router.put("/settings")
def put_settings(body: dict = Body(...), authorization: str = Header(None)):
    """目前只有 fiscal_year_start_month；已建立任何年度後不可再改（避免期間對不上）。"""
    _require_write(authorization)
    conn = get_db()
    try:
        if "fiscal_year_start_month" in (body or {}):
            try:
                m = int(body["fiscal_year_start_month"])
            except (TypeError, ValueError):
                raise HTTPException(400, "起始月份要是 1～12。")
            if not 1 <= m <= 12:
                raise HTTPException(400, "起始月份要是 1～12。")
            if conn.execute("SELECT 1 FROM gl_fiscal_years").fetchone():
                raise HTTPException(409, "已經建立過會計年度，不能再改起始月份。")
            _periods.set_setting(conn, "fiscal_year_start_month", m)
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.settings.update", "gl_settings", "fiscal_year_start_month", "更新總帳設定：%s" % ", ".join(sorted((body or {}).keys())))
    return {"ok": True}


@router.get("/periods/{period_id}/checklist")
def checklist(period_id: int, authorization: str = Header(None)):
    _require_read(authorization)
    conn = get_db()
    try:
        p = conn.execute("SELECT * FROM gl_periods WHERE id=?", (period_id,)).fetchone()
        if p is None:
            raise HTTPException(404, "找不到這個期間。")
        return _periods.checklist(conn, dict(p))
    finally:
        conn.close()


@router.post("/periods/{period_id}/close")
def close(period_id: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_write(authorization)
    conn = get_db()
    try:
        h = _run(conn, _periods.close_period, period_id, _who(user), bool((body or {}).get("accept_warnings")),
                 str((body or {}).get("reason") or ""))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.period.close", "gl_periods", str(period_id), "期間結帳")
    return {"ok": True, "tb_hash": h}


@router.post("/periods/{period_id}/reopen")
def reopen(period_id: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_write(authorization)
    conn = get_db()
    try:
        stale = _run(conn, _periods.reopen_period, period_id, _who(user), str((body or {}).get("reason") or ""))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.period.reopen", "gl_periods", str(period_id),
           "重開期間：%s" % (body or {}).get("reason"))
    return {"ok": True, "stale_later_periods": stale}


@router.post("/periods/{period_id}/lock")
def lock(period_id: int, authorization: str = Header(None)):
    user = _require_superadmin(authorization)
    conn = get_db()
    try:
        _run(conn, _periods.lock_period, period_id, _who(user))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.period.lock", "gl_periods", str(period_id), "期間鎖定")
    return {"ok": True}


@router.post("/periods/{period_id}/unlock")
def unlock(period_id: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_superadmin(authorization)
    conn = get_db()
    try:
        _run(conn, _periods.unlock_period, period_id, _who(user), str((body or {}).get("reason") or ""))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.period.unlock", "gl_periods", str(period_id),
           "期間解鎖：%s" % (body or {}).get("reason"))
    return {"ok": True}


@router.get("/period-log")
def period_log(year: int = None, authorization: str = Header(None)):
    _require_read(authorization)
    conn = get_db()
    try:
        return {"log": _periods.read_log(conn, year)}
    finally:
        conn.close()


# ── 期初餘額 ─────────────────────────────────────────────────────────────

@router.post("/opening/preview")
def opening_preview(body: dict = Body(...), authorization: str = Header(None)):
    _require_write(authorization)
    conn = get_db()
    try:
        return _run(conn, _opening.preview, (body or {}).get("rows") or [], (body or {}).get("items") or [])
    finally:
        conn.close()


@router.post("/opening")
def opening_create(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_write(authorization)
    body = body or {}
    conn = get_db()
    try:
        res = _run(conn, _opening.create_batch, body.get("year"), str(body.get("opening_date") or ""),
                   body.get("rows") or [], body.get("items") or [], str(body.get("filename") or ""), _who(user))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.opening.create", "gl_opening_batches", str(res["batch_id"]),
           "匯入期初餘額 %s 年度（傳票 %s）" % (body.get("year"), res["voucher_no"]))
    return {"ok": True, **res}


@router.post("/opening/{batch_id}/undo")
def opening_undo(batch_id: int, authorization: str = Header(None)):
    user = _require_superadmin(authorization, "撤銷期初批次")          # B：期初撤銷只有最高管理者直接做（一般人走申請）
    conn = get_db()
    try:
        _run(conn, _opening.undo_batch, batch_id, _who(user))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.opening.undo", "gl_opening_batches", str(batch_id), "撤銷期初餘額批次")
    return {"ok": True}
