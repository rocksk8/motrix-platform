# -*- coding: utf-8 -*-
"""擇一方案內部比較端點（M3 T4；T57）。只有具報價單成本權限者（`quote_money_visible`）能呼叫；沒有權限 ⇒ 403，回應不含任何成本／毛利／管銷欄位。
唯讀：不寫庫、不寫稽核、不改 data_json。案件頁的方案比較（`money_visible`）是另一個介面，T10 另做，兩個判定函式不得互換。"""
import json

from fastapi import APIRouter, Header, HTTPException, Query

from db import get_db
from helpers import _require_user
from helpers.case_access import case_page_readable, deny_case
from helpers.financial_mask import money_visible, quote_money_visible
from modules.case import alt_options, alt_policy
from modules.case import profit_guard as PG

router = APIRouter()


def _plan_row(conn, quote_no, user):
    """(報價單列, 這位使用者能不能讀這張案件)。讀取規則與 `GET /api/quotations/{no}` 同一支 `case_page_readable`。"""
    try:
        row = conn.execute("SELECT * FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        return row, (row is not None and case_page_readable(conn, quote_no, user))
    except Exception:
        conn.close()
        raise


def _plan_response(row, picks, combos, user, gate):
    """兩個介面共用的回應；差別只在『成本權限』的判定函式（兩者語意不同，不得互換）。逐案可見性已由各路由先過 `deny_case`（被拒＝查無）。"""
    if not gate(user):
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


@router.get("/api/quotations/{quote_no}/plan-view")
def get_plan_view(quote_no: str, picks: str = Query("", description="假設的選擇 JSON：{組名: 品項id}"),
                  combos: bool = Query(False), authorization: str = Header(None)):
    """報價單頁的內部成本面板：判定函式＝`quote_money_visible`（業務／管理員／財務角色）。"""
    user = _require_user(authorization)
    conn = get_db()
    row, readable = _plan_row(conn, quote_no, user)
    if not readable:
        deny_case(conn, quote_no, user, "not_found" if row is None else "denied")      # 看不到＝不存在（同一個 404）
    conn.close()
    return _plan_response(row, picks, combos, user, lambda u: quote_money_visible(u))


@router.get("/api/quotations/{quote_no}/case-plan-view")
def get_case_plan_view(quote_no: str, picks: str = Query("", description="假設的選擇 JSON：{組名: 品項id}"),
                       combos: bool = Query(False), authorization: str = Header(None)):
    """案件頁的方案比較（唯讀、標示未採用）：判定函式＝`money_visible`（只有財務角色與最高管理者；與報價單頁不同，不得互換）。"""
    user = _require_user(authorization)
    conn = get_db()
    row, readable = _plan_row(conn, quote_no, user)
    if not readable:
        deny_case(conn, quote_no, user, "not_found" if row is None else "denied")      # 看不到＝不存在（同一個 404）
    conn.close()
    return _plan_response(row, picks, combos, user, lambda u: money_visible(u))


@router.get("/api/alt-quote/config")
def get_alt_config(authorization: str = Header(None)):
    """報價單表單用的擇一方案設定（登入者可讀；只有設定中心的文字與數量，沒有任何金額／成本）。"""
    _require_user(authorization)
    return {"enabled": bool(alt_policy.setting("alt_enabled")), "totalText": str(alt_policy.setting("total_text")),
            "noteTemplate": str(alt_policy.setting("note_template")), "groupsMax": int(alt_policy.setting("alt_groups_max")),
            "comboViewMax": int(alt_policy.setting("combo_view_max")), "comboViewDefaultOpen": bool(alt_policy.setting("combo_view_default_open"))}
