"""共用分類與設定說明端點（選單去工程師化 批次 9，2026-11-13）。

- GET /api/menu/categories                 有效分類（系統預設＋公司覆寫）；登入即可（只有分類名稱與一句話說明，沒有任何設定值）
- PUT /api/menu/categories/override        公司覆寫分類與項目的名稱／順序／所屬分類（最高管理者；`null`＝回預設）
- PUT /api/menu/settings-help/override     公司覆寫設定欄位的「?」說明文字（最高管理者；`null`＝回系統預設）
資料與驗證見 `helpers/menu_categories.py`、`helpers/settings_help.py`。
"""
from fastapi import APIRouter, Body, Header, HTTPException

from helpers import _require_user
from helpers import menu_categories as MC
from helpers import settings_help as SH

router = APIRouter()


@router.get("/api/menu/categories")
def get_categories(authorization: str = Header(None)):
    _require_user(authorization)
    return MC.effective()


@router.put("/api/menu/categories/override")
def put_categories_override(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    try:
        MC.set_override(body, user=user["username"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return MC.effective()


@router.put("/api/menu/settings-help/override")
def put_help_override(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    try:
        new = SH.set_override(body, user=user["username"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "customCount": len(new)}
