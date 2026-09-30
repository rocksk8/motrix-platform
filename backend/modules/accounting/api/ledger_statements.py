# -*- coding: utf-8 -*-
"""總帳：財務報表 API（B2：資產負債表、綜合損益表）。設計：proposal-gl/04-reports.md。

只讀＝cashier／finance。日期一律 YYYY-MM-DD；損益表期間不可跨會計年度（損益科目每年度歸零）。
`compare_*` 帶了就一併回比較期。任何 `checks.balanced=False` 都是資料問題，畫面必須明說，不可當成正常。
"""
import datetime as _dt

from fastapi import APIRouter, Header, HTTPException

from db import get_db
from helpers import _require_user, require_any_module
from modules.accounting.ledger import statements as _st

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


def _require_stmt_read(authorization):
    user = _require_user(authorization)
    require_any_module(user, ("cashier", "finance"), "總帳")
    return user


def _d(v, name):
    try:
        return _dt.date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise HTTPException(400, "%s 格式要是 YYYY-MM-DD。" % name)


@router.get("/balance-sheet")
def balance_sheet(as_of: str, compare_as_of: str = None, include_drafts: bool = False, show_zero: bool = False,
                  authorization: str = Header(None)):
    _require_stmt_read(authorization)
    a = _d(as_of, "截至日")
    c = _d(compare_as_of, "比較截至日") if compare_as_of else None
    conn = get_db()
    try:
        out = _st.balance_sheet(conn, a, include_drafts, show_zero)
        if c:
            out["compare"] = _st.balance_sheet(conn, c, include_drafts, show_zero)
        return out
    finally:
        conn.commit()               # ensure_meta 可能補了缺的設定列（冪等種子）
        conn.close()


@router.get("/income-statement")
def income_statement(start: str, end: str, compare_start: str = None, compare_end: str = None,
                     include_drafts: bool = False, show_zero: bool = False, authorization: str = Header(None)):
    _require_stmt_read(authorization)
    s, e = _d(start, "起日"), _d(end, "迄日")
    if s > e:
        raise HTTPException(400, "起日不可晚於迄日。")
    conn = get_db()
    try:
        try:
            out = _st.income_statement(conn, s, e, include_drafts, show_zero)
            if compare_start and compare_end:
                cs, ce = _d(compare_start, "比較起日"), _d(compare_end, "比較迄日")
                out["compare"] = _st.income_statement(conn, cs, ce, include_drafts, show_zero)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return out
    finally:
        conn.commit()
        conn.close()


@router.get("/statements/check")
def statements_check(as_of: str, include_drafts: bool = False, authorization: str = Header(None)):
    """資產負債表、損益表、試算表的互相對帳（同一日期、該日所在會計年度）。"""
    _require_stmt_read(authorization)
    a = _d(as_of, "截至日")
    conn = get_db()
    try:
        return _st.check_consistency(conn, a, include_drafts)
    finally:
        conn.commit()
        conn.close()
