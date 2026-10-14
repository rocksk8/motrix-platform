# -*- coding: utf-8 -*-
"""狀態顯示名稱與顏色的讀取端點（S-X2；邏輯在 helpers/status_display.py）。

- GET /api/status-display：登入即可。旗標 `builder_status_display.enabled` 關（預設）⇒ `{"enabled": false}`，不帶任何內容；
  開 ⇒ `{"enabled": true, "tones": [...], "contexts": [...], "statuses": {鍵: {label, names, tone, order}}}`。
  內容只有『字與色』，沒有任何金額或權限資訊，所以所有登入者都讀得到；邏輯不讀這張表。
"""
from fastapi import APIRouter, Header

from helpers import _require_user
from helpers import status_display as SD

router = APIRouter()


@router.get("/api/status-display")
def get_status_display(authorization: str = Header(None)):
    _require_user(authorization)
    return SD.public_payload()
