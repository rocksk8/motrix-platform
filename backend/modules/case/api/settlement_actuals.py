# -*- coding: utf-8 -*-
"""完結精算實際成本的唯讀端點（33-A2；規格 docs/platform/plans/SETTLEMENT-ACTUALS-SPEC.md §2）。
`GET /api/quotations/{案件}/settlement-actuals`：每品項估計／採購單／材料申請／額外支出歸屬與規則 A 的實際、未對應清單、沖銷紀錄、合計。
權限＝與 `get_settlement` 相同（案件可見＋財務檢視）；只讀、不寫。計算全在 `modules/case/settlement_actuals.py`（與營運報表、總帳共用同一批列）。"""
import json

from fastapi import APIRouter, Header, HTTPException

from db import get_db
from helpers import _require_user, can_see_financial
from modules.case import settlement_actuals as SA
from modules.case.api.case_extra_expenses import _guard_case

router = APIRouter()


@router.get("/api/quotations/{quote_no}/settlement-actuals")
def settlement_actuals(quote_no: str, offsets: str = "", authorization: str = Header(None)):
    """`offsets`（選填，JSON 清單）＝**預覽**：用頁面上尚未存檔的沖銷對應重算；不寫入、不驗證（存檔時 PUT 才驗，見 validate_offsets）。"""
    if not quote_no or quote_no == "-":
        raise HTTPException(400, "無案件的單據沒有完結精算")
    user = _require_user(authorization)
    conn = get_db()
    try:
        _guard_case(conn, quote_no, user)                                   # 看不到＝不存在（同一個 404）
        if not can_see_financial(user):
            raise HTTPException(403, "此帳號沒有檢視財務金額的權限（需要「財務金額可視」模組）")
        preview = None
        if offsets:
            try:
                preview = json.loads(offsets)
            except ValueError:
                raise HTTPException(422, "offsets 不是合法的 JSON")
            if not isinstance(preview, list):
                raise HTTPException(422, "offsets 必須是清單")
        return SA.compute(conn, quote_no, offsets=preview)
    finally:
        conn.close()
