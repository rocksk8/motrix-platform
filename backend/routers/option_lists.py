# -*- coding: utf-8 -*-
"""選項清單的端點（census #4）。旗標 `builder_option_lists.enabled`（且 `builder_governance.enabled`）關閉 ⇒ status 回未開放、預覽 404。

- `GET  /api/option-lists/{id}/status`  登入即可 ⇒ `{enabled, canEdit, ...}`；只有最高管理者（且開啟）拿到清單目錄、預設與用途（給編輯器）。不是已登記的清單 ⇒ 404。
- `POST /api/option-lists/{id}/preview` 僅最高管理者、唯讀 ⇒ `{id, label, usedBy, values, added, disabled, warnings}`；不寫任何資料；草稿不合法 ⇒ 422。
發布走既有的 `/api/definitions/option_list/{id}/*`（版本／差異／還原／帳本／發布前預覽雜湊全部沿用）。頁面讀清單不需要額外請求：`/api/platform/menu` 對所有人帶 `optionLists`（只在開啟且有發布版本時）。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from helpers import _require_user
from helpers import option_lists as OL

router = APIRouter()


@router.get("/api/option-lists/{list_id}/status")
def option_list_status(list_id: str, authorization: str = Header(None)):
    u = _require_user(authorization)
    reg = OL.registered()
    if list_id not in reg:
        raise HTTPException(404, "沒有這份清單")
    if not OL.enabled():
        return {"enabled": False, "canEdit": False}
    out = {"enabled": True, "canEdit": u.get("role") == "superadmin"}
    if out["canEdit"]:
        out.update(reg[list_id], listId=list_id, current=OL.effective(list_id))
    return out


@router.post("/api/option-lists/{list_id}/preview")
def option_list_preview(list_id: str, body: dict = Body(default={}), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)
    if list_id not in OL.registered():
        raise HTTPException(404, "沒有這份清單")
    if not OL.enabled():
        raise HTTPException(404, "未開放")
    try:
        return OL.preview(list_id, (body or {}).get("template") if isinstance(body, dict) else None)
    except ValueError as e:
        raise HTTPException(422, {"problems": e.args[0]})
    except LookupError as e:
        raise HTTPException(404, str(e))
