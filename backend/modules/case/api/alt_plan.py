# -*- coding: utf-8 -*-
"""擇一方案內部比較端點（M3 T4；T57）。只有具報價單成本權限者（`quote_money_visible`）能呼叫；沒有權限 ⇒ 403，回應不含任何成本／毛利／管銷欄位。
唯讀：不寫庫、不寫稽核、不改 data_json。案件頁的方案比較（`money_visible`）是另一個介面，T10 另做，兩個判定函式不得互換。"""
import json

from fastapi import APIRouter, Header, HTTPException, Query

from db import get_db
from helpers import _require_user
from helpers.case_access import case_page_readable, deny_case
from helpers.financial_mask import quote_money_visible
from modules.case import alt_options, alt_policy
from modules.case import profit_guard as PG

router = APIRouter()


@router.get("/api/quotations/{quote_no}/plan-view")
def get_plan_view(quote_no: str, picks: str = Query("", description="假設的選擇 JSON：{組名: 品項id}"),
                  combos: bool = Query(False), authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        readable = row is not None and case_page_readable(conn, quote_no, user)
    except Exception:
        conn.close()
        raise
    if not readable:
        deny_case(conn, quote_no, user, "not_found" if row is None else "denied")
    conn.close()
    if not quote_money_visible(user):
        raise HTTPException(403, "你沒有查看報價成本與毛利的權限")
    try:
        q = json.loads(row["data_json"] or "{}") or {}
    except (TypeError, ValueError):
        q = {}
    selection = None
    if picks:
        try:
            selection = json.loads(picks)
        except ValueError:
            raise HTTPException(422, "假設的選擇格式不正確")
        if not isinstance(selection, dict):
            raise HTTPException(422, "假設的選擇格式不正確")
    return alt_options.plan_view(q, selection, settled=PG.is_settled(row), combos=combos,
                                 combo_max=alt_policy.setting("combo_view_max"))
