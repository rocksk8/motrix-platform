# -*- coding: utf-8 -*-
"""GET /api/platform/menu：目前使用者看得到的選單（階段 C／C3、C4，core.menu）。

L1 項目（core/menu_l1.json）＋**已載入**模組的 module.json `pages[].menu`，依使用者的模組權限過濾。
- `groups`／`denied`：宣告版（與 P9 排版器面板預覽讀的是同一份，不套版面——面板自己疊要預覽的操作）
- `layout`（C4，STAGE-C L79 更正 ②）：套上**使用者角色**版面之後的選單；sidebar.js 在 session 取回後讀它重排。
  每個有側欄點的已載入模組各 resolve 一次（`core.catalog.effective_layout_ops`，與 GET /api/layout/{module} 同一份）；
  hide 只是顯示、不是權限（`denied` 不因版面改變）。讀版面失敗 ⇒ 該模組用程式預設，錯誤列在 `layout.errors`。
"""
import json

from fastapi import APIRouter, Header

from core import catalog, registry
from core import menu as core_menu
from db import get_db
from helpers import _require_user

router = APIRouter()


def _layout_for(user, groups, mod_items):
    """角色版面套到選單上 ⇒ {"groups", "applied", "skipped", "dropped", "errors", "sources", "role"}。"""
    role = user.get("role")
    keys = sorted({it["module"] for it in mod_items if it.get("module")})
    ops, dropped, errors, sources = [], [], [], {}
    if keys:
        conn = get_db()
        try:
            for key in keys:
                eff = catalog.effective_layout_ops(conn, key, role)
                ops += [op for op in eff["ops"] if str((op or {}).get("target", "")).endswith("/sidebar")]
                dropped += [dict(d, module=key) for d in eff["dropped"]]
                sources[key] = eff["source"]
                if eff["error"]:
                    errors.append({"module": key, "error": eff["error"]})
        finally:
            conn.close()
    new_groups, applied, skipped = core_menu.apply_layout(groups, ops)
    return {"groups": new_groups, "applied": applied, "skipped": skipped, "dropped": dropped,
            "errors": errors, "sources": sources, "role": role}


@router.get("/api/platform/menu")
def platform_menu(authorization: str = Header(None)):
    user = _require_user(authorization)
    try:
        modules = json.loads(user.get("modules") or "[]")
    except (TypeError, ValueError):
        modules = []
    mod_items = core_menu.module_items({m.key: m.manifest for m in registry.loaded()})
    l1, sa = core_menu.load_l1(), user.get("role") == "superadmin"
    groups = core_menu.build(l1, mod_items, modules, sa)
    return {"groups": groups,
            "denied": core_menu.denied(l1, mod_items, modules, sa),
            "layout": _layout_for(user, groups, mod_items)}
