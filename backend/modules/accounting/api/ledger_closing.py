# -*- coding: utf-8 -*-
"""總帳：年度結轉與決算 API（B5）。設計：proposal-gl/03-periods-close.md §5。

產生結轉傳票、決算＝finance；年度重開＝superadmin（留稽核）。四大表匯出＝cashier／finance（決算後匯出凍結版）。
"""
import urllib.parse

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import Response

from db import get_db
from helpers import _audit, _require_user, _tok, require_any_module
from modules.accounting.api import ledger_requests as _requests
from helpers.xlsx_out import add_pdf_sibling, check_export_rate, export_logged
from modules.accounting.ledger import closing as _closing
from modules.accounting.ledger import export as _export
from modules.accounting.ledger import periods as _periods

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


def _require_closing_read(authorization):
    user = _require_user(authorization)
    require_any_module(user, ("cashier", "finance"), "總帳")
    return user


def _require_closing_write(authorization):
    user = _require_user(authorization)
    require_any_module(user, ("finance",), "年度結轉")
    return user


def _require_closing_super(authorization):
    user = _require_user(authorization)
    if user.get("role") != "superadmin":
        raise HTTPException(403, "只有最高管理者可以重開會計年度。")
    return user


def _run(conn, fn, *args):
    try:
        return fn(conn, *args)
    except (_closing.ClosingError, _periods.PeriodError) as exc:
        conn.rollback()
        raise HTTPException(400, str(exc))


def _who(user):
    return (user or {}).get("username") or ""


@router.get("/years/{year}/closing/preview")
def closing_preview(year: int, authorization: str = Header(None)):
    _require_closing_read(authorization)
    conn = get_db()
    try:
        return _run(conn, _closing.preview, year)
    finally:
        conn.commit()
        conn.close()


@router.post("/years/{year}/closing/generate")
def closing_generate(year: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_closing_write(authorization)
    conn = get_db()
    try:
        made = _run(conn, _closing.generate, year, _who(user), bool((body or {}).get("regenerate")))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.closing.generate", "gl_fiscal_years", str(year), "產生結轉傳票：%s" % ",".join(m["voucher_no"] for m in made))
    return {"ok": True, "vouchers": made}


@router.post("/years/{year}/close")
def year_close(year: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_closing_write(authorization)
    if user.get("role") != "superadmin":                # C：一般財務人員送申請，最高管理者核准後自動執行
        return _requests.submit(user, "year_close", dict(body or {}, year=year), authorization)
    conn = get_db()
    try:
        res = _run(conn, _closing.close_year, year, _who(user), bool((body or {}).get("accept_warnings")))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.year.close", "gl_fiscal_years", str(year), "年度決算")
    return {"ok": True, **res}


@router.post("/years/{year}/reopen")
def year_reopen(year: int, body: dict = Body(default={}), authorization: str = Header(None)):
    user = _require_closing_super(authorization)
    conn = get_db()
    try:
        res = _run(conn, _closing.reopen_year, year, _who(user), str((body or {}).get("reason") or ""))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.year.reopen", "gl_fiscal_years", str(year), "年度重開：%s" % (body or {}).get("reason"))
    return {"ok": True, **res}


@router.get("/years/{year}/statements")
def year_statements(year: int, authorization: str = Header(None)):
    """該年度四大表：已決算 ⇒ 凍結快照（`source='frozen'`），否則即時（`source='live'`）。"""
    _require_closing_read(authorization)
    conn = get_db()
    try:
        stm, source = _run(conn, _export.year_statements, year)
        return {"year": year, "source": source, "statements": stm}
    finally:
        conn.commit()
        conn.close()


@router.get("/years/{year}/statements/export")
@export_logged("xlsx", "accounting", "ledger-statements")
def year_statements_export(year: int, authorization: str = Header(None)):
    user = _require_closing_read(authorization)
    check_export_rate(user["id"], "excel")
    conn = get_db()
    try:
        stm, source = _run(conn, _export.year_statements, year)
    finally:
        conn.commit()
        conn.close()
    data = _export.statements_workbook(stm, year, source)
    _audit(_tok(authorization), "ledger.statements.export", "gl_fiscal_years", str(year), "匯出四大表（%s）" % source)
    name = urllib.parse.quote("財務報表_%s年度%s.xlsx" % (year, "_決算" if source == "frozen" else ""))
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + name})


# ── 匯出：PDF 姊妹（使用者規則 2026-09-30：每個 Excel 匯出都要同時提供 PDF、每次匯出都要留紀錄）──
add_pdf_sibling(router, "/years/{year}/statements/export/pdf", year_statements_export, module="accounting", name="ledger-statements", title="財務報表")
