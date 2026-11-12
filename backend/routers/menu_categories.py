"""共用分類與設定說明端點（選單去工程師化 批次 9，2026-11-13）。

- GET /api/menu/categories                 有效分類（系統預設＋公司覆寫）；登入即可，但設定中心群組（`settings_group:`）只回給最高管理者（只有名稱與一句話說明，沒有任何設定值）
- PUT /api/menu/categories/override        公司覆寫分類與項目的名稱／順序／所屬分類（最高管理者；`null`＝回預設）
- PUT /api/menu/settings-help/override     公司覆寫設定欄位的「?」說明文字（最高管理者；`null`＝回系統預設）
資料與驗證見 `helpers/menu_categories.py`、`helpers/settings_help.py`。

[回應鍵基準的說明] `tests/platform/response_keys_baseline.json` 對 `/api/menu/categories` 記了約 440 行「`items.settings_group:<群組>.*`」：
那是**資料長出來的鍵**（每個設定群組一組），不是結構變動。日後新增設定群組、基準會跟著多一組，重錄時只應多出 `settings_group:<新群組>` 的那幾行；
結構本身（每個項目有哪些欄位）由 `tests/test_settings_center_b9_2026_11_13.py` 的分類檔驗證守門。（PM 2026-11-13 裁示：不改記錄器、以註解說明。）
"""
from fastapi import APIRouter, Body, Header, HTTPException

from helpers import _require_user, _tok
from helpers import menu_categories as MC
from helpers import settings_help as SH

router = APIRouter()


@router.get("/api/menu/categories")
def get_categories(authorization: str = Header(None)):
    user = _require_user(authorization)
    e = MC.effective()
    if user.get("role") == "superadmin":
        return e
    # 設定中心的群組（`settings_group:`）只有最高管理者看得到：其他人不回這些名稱與說明；沒有項目的分類也不回
    items = {k: v for k, v in e["items"].items() if not k.startswith("settings_group:")}
    used = {v["category"] for v in items.values()}
    return {"version": e["version"], "categories": [c for c in e["categories"] if c["key"] in used], "items": items}


@router.put("/api/menu/categories/override")
def put_categories_override(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    try:
        MC.set_override(body, user=user["username"], token=_tok(authorization))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return MC.effective()


@router.put("/api/menu/settings-help/override")
def put_help_override(body: dict = Body(...), authorization: str = Header(None)):
    user = _require_user(authorization, require_superadmin=True)
    try:
        new = SH.set_override(body, user=user["username"], token=_tok(authorization))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "customCount": len(new)}
