# -*- coding: utf-8 -*-
"""GET /api/platform/menu：目前使用者看得到的選單（階段 C／C3、C4，core.menu）。

L1 項目（core/menu_l1.json）＋**已載入**模組的 module.json `pages[].menu`，依使用者的模組權限過濾。
- `groups`／`denied`：宣告版（與 P9 排版器面板預覽讀的是同一份，不套版面——面板自己疊要預覽的操作）
- `layout`（C4，STAGE-C L79 更正 ②）：套上**使用者角色**版面之後的選單，再併入使用者看得到的已發布自訂模組
  （core.menu.merge_custom；過濾與 /api/custom-modules 同一份 helpers.custom_modules.visible_to）；sidebar.js 在 session 取回後讀它重排。
  每個有側欄點的已載入模組各 resolve 一次（`core.catalog.effective_layout_ops`，與 GET /api/layout/{module} 同一份）；
  hide 只是顯示、不是權限（`denied` 不因版面改變）。讀版面失敗 ⇒ 該模組用程式預設，錯誤列在 `layout.errors`。

`sidebar_js_source()`（C4，STAGE-C L79 更正 ①）：`/static/sidebar.js` 前置 `window.MOTRIX_MENU`——**與使用者無關**的宣告
（那個請求不帶 token）：`groups`（L1＋已載入模組，每項帶 perm，declaration()）、`pageModules`（頁面 ⇒ 所屬模組，含沒載入的，
給直接打網址的後備提示用）。模組狀態（停用／未授權）與自訂模組**不放**：前者是 /api/system/modules/availability、
後者是公司資料（名稱），都要登入才拿得到。每次請求現組（模組狀態會變），不快取（no_cache_static 對 .js 設 no-store）。
"""
import json
from pathlib import Path

from fastapi import APIRouter, Header

from core import catalog, registry
from core import menu as core_menu
from db import get_db
from helpers import _require_user
from helpers import custom_modules as CM

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
    customs, custom_error = [], None
    try:
        conn = get_db()
        try:
            customs = CM.visible_to(CM.published_modules(conn), user)
        finally:
            conn.close()
    except Exception as e:                                   # noqa: BLE001 自訂模組讀失敗 ⇒ 選單照常、錯誤列出
        import logging
        logging.getLogger(__name__).warning("讀自訂模組失敗 ⇒ 選單不含自訂模組：%s", e)
        custom_error = "讀自訂模組失敗，選單暫不含自訂模組"
    if custom_error:
        errors.append({"module": None, "error": custom_error})
    return {"groups": core_menu.merge_custom(new_groups, customs), "applied": applied, "skipped": skipped,
            "dropped": dropped, "errors": errors, "sources": sources, "role": role,
            "custom": [m["key"] for m in customs]}


def menu_declaration(page_map):
    """⇒ MOTRIX_MENU（dict）。page_map：core.pages 的 {頁名: (模組key, 路徑)}（main.py 啟動時組好的那一份）。"""
    mod_items = core_menu.module_items({m.key: m.manifest for m in registry.loaded()})
    names = {s["key"]: s.get("name") or s["key"] for s in registry.module_states()}
    return {"v": 1,
            "groups": core_menu.declaration(core_menu.load_l1(), mod_items),
            "pageModules": {name: {"key": key, "name": names.get(key, key)}
                            for name, (key, _path) in sorted((page_map or {}).items())}}


def _js_literal(obj):
    """JSON ⇒ 可以安全放進 JS 原始碼的字面值（</ 與 U+2028／2029 跳脫）。"""
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return s.replace("</", "<" + chr(92) + "/").replace(chr(0x2028), chr(92) + "u2028").replace(chr(0x2029), chr(92) + "u2029")


def sidebar_js_source(page_map, frontend_dir):
    """`/static/sidebar.js` 的內容：`window.MOTRIX_MENU = {...};` ＋ 檔案本體（原樣）。"""
    body = (Path(frontend_dir) / "static" / "sidebar.js").read_text(encoding="utf-8")
    return "window.MOTRIX_MENU = %s;" % _js_literal(menu_declaration(page_map)) + chr(10) + body


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
