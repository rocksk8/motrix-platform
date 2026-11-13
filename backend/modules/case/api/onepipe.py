# -*- coding: utf-8 -*-
"""一條龍（onepipe）：前端要用的開關狀態（P0a 入口與連結、P1' 物料流程）。登入者皆可讀；只回布林，不含任何資料。"""
from fastapi import APIRouter, Header

from helpers import _require_user
from helpers.onepipe_flags import flag_on

router = APIRouter()


@router.get("/api/onepipe/flags")
def get_onepipe_flags(authorization: str = Header(None)):
    """各批次旗標的開關狀態（預設全關；讀不到一律當關）。畫面據此決定要不要顯示新入口，旗標關＝畫面與今天相同。"""
    _require_user(authorization)
    return {"links": flag_on("links"), "timeline": flag_on("timeline")}
