# -*- coding: utf-8 -*-
"""一條龍 P1'：案件物料流程時間軸 `GET /api/quotations/{quote_no}/material-flow`（唯讀；旗標 `onepipe.timeline` 關 ⇒ 404，與端點不存在相同）。

權限＝案件成員（同叫料／額外支出的案件可見性：看不到＝查無，同一個 404）；回應沒有任何金額欄位。組裝邏輯在 `modules/case/material_flow.py`。
"""
from fastapi import APIRouter, Header, HTTPException

from db import get_db
from helpers import _require_user
from helpers.case_access import require_case
from helpers import onepipe_flags
from modules.case import material_flow as MF

router = APIRouter()


@router.get("/api/quotations/{quote_no}/material-flow")
def get_material_flow(quote_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    if not onepipe_flags.flag_on("timeline"):
        raise HTTPException(404, "Not Found")
    conn = get_db()
    try:
        q = conn.execute("SELECT data_json, sales_person_id, sales_person, assigned_user_ids FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        require_case(user, q, quote_no)
        return MF.build(conn, user, quote_no, q, authorization)
    finally:
        conn.close()
