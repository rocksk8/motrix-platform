# -*- coding: utf-8 -*-
"""內建畫面的自訂欄位——頁面讀取端點（T61 S5；設計：docs/platform/plans/T61-S5-FIELD-CATALOG-DESIGN.md）。

- `GET /api/custom-fields/{record_type}`（登入即可）：⇒ `{recordType, enabled, fields:[{key,label,type,options?,maxLength?,help?}]}`。
  旗標 `builder_custom_fields.enabled` 關閉 ⇒ `enabled:false, fields:[]`（頁面什麼都不畫）。內容只有已發布且未停用欄位的
  名稱與型別（不含任何單據的值；值跟著單據走，由單據自己的讀取權限保護）。
- 欄位定義的編輯、預覽、發布、還原走既有的 `/api/definitions/custom_fields/{record_type}/…`（僅超級管理員）。
"""
from fastapi import APIRouter, Header, HTTPException

from helpers import _require_user
from helpers import builtin_fields as BF

router = APIRouter()


@router.get("/api/custom-fields/{record_type}")
def get_custom_fields(record_type: str, authorization: str = Header(None)):
    _require_user(authorization)
    if record_type not in BF.RECORD_TYPES:
        raise HTTPException(404, "沒有這種單據類型")
    on = BF.enabled()
    return {"recordType": record_type, "enabled": on, "fields": BF.public_fields(record_type) if on else []}
