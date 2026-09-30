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
