# -*- coding: utf-8 -*-
"""GET /api/platform/menu：目前使用者看得到的選單（階段 C／C3，core.menu）。

L1 項目（core/menu_l1.json）＋**已載入**模組的 module.json `pages[].menu`，依使用者的模組權限過濾。
C3 期間與 sidebar.js 的舊選單並行（前端還沒切換，C4 才切）；對等守門：tests/platform/test_menu_parity.py。
"""
import json

from fastapi import APIRouter, Header

from core import menu as core_menu
from core import registry
from helpers import _require_user

router = APIRouter()


@router.get("/api/platform/menu")
def platform_menu(authorization: str = Header(None)):
    user = _require_user(authorization)
    try:
        modules = json.loads(user.get("modules") or "[]")
    except (TypeError, ValueError):
        modules = []
    mod_items = core_menu.module_items({m.key: m.manifest for m in registry.loaded()})
    l1, sa = core_menu.load_l1(), user.get("role") == "superadmin"
    return {"groups": core_menu.build(l1, mod_items, modules, sa),
            "denied": core_menu.denied(l1, mod_items, modules, sa)}
