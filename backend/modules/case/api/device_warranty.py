# -*- coding: utf-8 -*-
"""一條龍 P3：案件設備頁的出貨預填與序號歷史（唯讀；旗標 `onepipe.ship_device_warranty` 關 ⇒ 404，與端點不存在相同）。

`GET /api/quotations/{quote_no}/device-prefill`          這個案件已出貨、尚未登載成設備的序號＋建議的保固起始日（只預填，由人確認後儲存）
`GET /api/quotations/{quote_no}/device-history?sn=…`     設備序號的來去歷史（其他案件的異動只標「其他案件」）
權限＝案件成員（看不到＝查無，同一個 404）；回應沒有任何金額欄位。邏輯在 `modules/case/device_warranty.py`。
"""
from fastapi import APIRouter, Header, HTTPException

from db import get_db
from helpers import _require_user, onepipe_flags
from helpers.case_access import require_case
from modules.case import device_warranty as DW

router = APIRouter()


def _case(conn, user, quote_no):
    q = conn.execute("SELECT data_json, sales_person_id, sales_person, assigned_user_ids FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    require_case(user, q, quote_no)
    return q


@router.get("/api/quotations/{quote_no}/device-prefill")
def get_device_prefill(quote_no: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        if not onepipe_flags.flag_on("ship_device_warranty", conn):
            raise HTTPException(404, "Not Found")
        return DW.prefill(conn, quote_no, _case(conn, user, quote_no))
    finally:
        conn.close()


@router.get("/api/quotations/{quote_no}/device-history")
def get_device_history(quote_no: str, sn: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    conn = get_db()
    try:
        if not onepipe_flags.flag_on("ship_device_warranty", conn):
            raise HTTPException(404, "Not Found")
        return DW.history(conn, quote_no, _case(conn, user, quote_no), sn)
    finally:
        conn.close()
