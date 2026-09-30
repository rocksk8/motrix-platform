# -*- coding: utf-8 -*-
"""總帳：營業稅 401 彙總、對帳、稅額結轉草稿、Excel 工作底稿（C5；proposal-gl/05-tax401.md）。功能旗標 `tax401`（預設關）。

只讀＝cashier／finance；產生稅額結轉草稿＝finance（寫稽核）。401 由總帳分錄彙總，不另讀單據；與應收應付模組的發票逐項對比（模組不在 ⇒ 明說未對比）。
"""
import urllib.parse

from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import Response

from core import registry
from db import get_db
from helpers import _audit, _require_user, _tok, require_any_module
from helpers.xlsx_out import check_export_rate
from modules.accounting.ledger import export as _export
from modules.accounting.ledger import features as _features
from modules.accounting.ledger import tax401 as _tax
from modules.accounting.ledger import withholding as _wh

router = APIRouter(prefix="/api/ledger", tags=["ledger"])

_READ = ("cashier", "finance")
_WRITE = ("finance",)


def _require_tax_read(authorization):
    user = _require_user(authorization)
    require_any_module(user, _READ, "總帳")
    return user


def _require_tax_write(authorization):
    user = _require_user(authorization)
    require_any_module(user, _WRITE, "總帳結帳")
    return user


def _flag(conn):
    if not _features.flags(conn).get("tax401"):
        raise HTTPException(409, "營業稅 401 功能尚未開啟（最高管理者在「總帳作業」開啟）。")


def _invoices():
    p = registry.single_provider("receivables.tax_invoices")
    return None if p is None else p()


@router.get("/tax401")
def tax401(year: int, period: int, authorization: str = Header(None)):
    _require_tax_read(authorization)
    conn = get_db()
    try:
        _flag(conn)
        try:
            out = _tax.summarize(conn, year, period, _invoices())
        except _tax.TaxError as exc:
            raise HTTPException(400, str(exc))
        return out
    finally:
        conn.commit()               # ensure_map 補種預設欄位對照（冪等）
        conn.close()


@router.get("/tax401/export")
def tax401_export(year: int, period: int, authorization: str = Header(None)):
    user = _require_tax_read(authorization)
    check_export_rate(user["id"], "excel")
    conn = get_db()
    try:
        _flag(conn)
        try:
            s = _tax.summarize(conn, year, period, _invoices())
        except _tax.TaxError as exc:
            raise HTTPException(400, str(exc))
    finally:
        conn.commit()
        conn.close()
    data = _export.tax401_workbook(s)
    _audit(_tok(authorization), "ledger.tax401.export", "gl_tax_settlements", "%s-%s" % (year, period), "匯出營業稅 401 工作底稿")
    name = urllib.parse.quote("營業稅401_%s年第%s期.xlsx" % (year, period))
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''" + name})


@router.post("/tax401/settlement")
def tax401_settlement(body: dict = Body(...), authorization: str = Header(None)):
    """產生（或重建）該期的稅額結轉傳票草稿；對帳不平、期間已結帳 ⇒ 400 並說明。"""
    user = _require_tax_write(authorization)
    b = body or {}
    conn = get_db()
    try:
        _flag(conn)
        try:
            res = _tax.generate_settlement(conn, int(b.get("year")), int(b.get("period")), (user or {}).get("username") or "", _invoices())
        except (_tax.TaxError, ValueError, TypeError) as exc:
            conn.rollback()
            raise HTTPException(400, str(exc))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.tax401.settlement", "gl_tax_settlements", "%s-%s" % (b.get("year"), b.get("period")),
           "產生稅額結轉草稿 %s（應實繳 %d、新留抵 %d）" % (res["voucher_no"], res["payable"], res["carry_new"]))
    return res


# ── 扣繳（代扣所得稅／二代健保）應繳未繳清單（旗標 `withholding`）────────────────────────────────

def _wh_flag(conn):
    if not _features.flags(conn).get("withholding"):
        raise HTTPException(409, "扣繳清單功能尚未開啟（最高管理者在「總帳作業」開啟）。")


@router.get("/withholding")
def withholding(ym: str = None, kind: str = None, authorization: str = Header(None)):
    _require_tax_read(authorization)
    if ym is not None and not (len(ym) == 7 and ym[4] == "-" and ym[:4].isdigit() and ym[5:].isdigit() and 1 <= int(ym[5:]) <= 12):
        raise HTTPException(400, "月份格式要是 YYYY-MM。")
    if kind not in (None, "income_tax", "nhi"):
        raise HTTPException(400, "種類只能是 income_tax 或 nhi。")
    conn = get_db()
    try:
        _wh_flag(conn)
        return _wh.report(conn, ym, kind)
    finally:
        conn.close()


@router.post("/withholding/remit")
def withholding_remit(body: dict = Body(...), authorization: str = Header(None)):
    """登記繳庫（出納／會計實際繳款後）。分錄由會計手工傳票處理（借 2252／貸銀行），這裡只記日期與傳票單號。"""
    user = _require_tax_write(authorization)
    b = body or {}
    conn = get_db()
    try:
        _wh_flag(conn)
        try:
            n = _wh.mark_remitted(conn, b.get("ids") or [], b.get("remitted_at"), str(b.get("voucher_no") or ""))
        except (_wh.WithholdingError, ValueError, TypeError) as exc:
            conn.rollback()
            raise HTTPException(400, str(exc))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.withholding.remit", "gl_withholding_items", ",".join(str(i) for i in (b.get("ids") or [])[:20]),
           "登記繳庫 %d 筆（%s）" % (n, b.get("remitted_at")))
    return {"updated": n}


@router.post("/withholding/unremit")
def withholding_unremit(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_tax_write(authorization)
    ids = (body or {}).get("ids") or []
    conn = get_db()
    try:
        _wh_flag(conn)
        try:
            n = _wh.unmark_remitted(conn, ids)
        except (ValueError, TypeError) as exc:
            conn.rollback()
            raise HTTPException(400, str(exc))
        conn.commit()
    finally:
        conn.close()
    _audit(_tok(authorization), "ledger.withholding.unremit", "gl_withholding_items", ",".join(str(i) for i in ids[:20]), "取消繳庫登記 %d 筆" % n)
    return {"updated": n}
