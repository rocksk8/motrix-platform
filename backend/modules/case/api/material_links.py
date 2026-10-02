# -*- coding: utf-8 -*-
"""叫料連結的唯讀端點（32-S4b；規格 docs/platform/plans/MATERIAL-ORDER-LINK-SPEC.md §3／§5）。
- `GET /api/quotations/{案件}/material-po-lines`：「從採購單帶入」清單（尚未被有效連結用掉的採購單明細列）。
- `GET /api/quotations/{案件}/material-link-status`：每一列叫料的連結判定（`{itemId: {state, reason, stale, text}}`），畫面徽章用。
權限＝案件可見（同額外支出清單）；金額（單價、小計）只給有財務檢視者（裁示 10）。只讀、不寫。"""
import json

from fastapi import APIRouter, Header, HTTPException

from db import get_db
from helpers import _require_user, can_see_financial
from modules.case import purchase_items as PI
from modules.case.api.case_extra_expenses import _guard_case

router = APIRouter()


def _case(quote_no):
    if not quote_no or quote_no == "-":
        raise HTTPException(400, "無案件的單據沒有材料申請")
    return quote_no


@router.get("/api/quotations/{quote_no}/material-po-lines")
def material_po_lines(quote_no: str, authorization: str = Header(None)):
    quote_no = _case(quote_no)
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        return {"quoteNo": quote_no, "lines": PI.available_po_lines(conn, quote_no, show_cost=can_see_financial(user))}
    finally:
        conn.close()


@router.get("/api/quotations/{quote_no}/material-link-status")
def material_link_statuses(quote_no: str, authorization: str = Header(None)):
    quote_no = _case(quote_no)
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)
        data, rows = PI._case_state(conn, quote_no)
        po_rows = [r for r in rows if (r["kind"] or "") == PI.ORD]
        return {"quoteNo": quote_no, "statuses": {
            str(o.get("itemId")): PI.material_link_status(o, po_rows, legacy=(st == ""))
            for o, st in PI.load_material_orders(conn, quote_no, data)}}
    finally:
        conn.close()
