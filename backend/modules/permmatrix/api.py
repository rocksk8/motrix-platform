# -*- coding: utf-8 -*-
"""權限矩陣的唯讀狀態探針（D7 final_drill 要求每個模組宣告 provides.probes）。

回應固定為 `{"ok": true}`：不含字串值（probe 規則：回應值不得出現在 log；字串會與路徑／啟動訊息重複），
不讀 perm_* 表、不碰任何權限判斷。矩陣的寫入端點與頁面仍未接線（SPEC PMX14）。
"""
from fastapi import APIRouter, Header

from helpers import _require_user

router = APIRouter()


@router.get("/api/permmatrix/status")
def permmatrix_status(authorization: str = Header(None)):
    _require_user(authorization)
    return {"ok": True}
