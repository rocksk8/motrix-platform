"""C4：`/static/sidebar.js` 前置 `window.MOTRIX_MENU`（STAGE-C L79 更正 ①；主持裁示 A）。

- 內容**與使用者無關**（那個請求不帶 token）：groups（L1＋已載入模組，每項帶 perm）、pageModules
- 模組狀態與自訂模組**不在裡面**（要登入才拿得到的東西不可以放進公開的 js）
- 前端用 perm 同步過濾的結果必須等於伺服器的 build()（同一個使用者）⇒ 宣告版與 /api/platform/menu 不會各說各話
- 模組沒載入 ⇒ 它的選單項不在宣告裡，但 pageModules 仍有它的頁面（直接打網址的後備提示要知道頁面屬於誰）
"""
import json

import pytest

from core import menu as M
from core import registry
from routers import platform_menu as PM

PREFIX = "window.MOTRIX_MENU = "


def _served(client):
    r = client.get("/static/sidebar.js")
    assert r.status_code == 200
    text = r.text
    assert text.startswith(PREFIX), text[:80]
    head, _, body = text.partition("\n")
    return r, json.loads(head[len(PREFIX):].rstrip(";")), body


def _mod_items():
    return M.module_items({m.key: m.manifest for m in registry.loaded()})


def _filter(decl, modules, superadmin):
    """前端要做的同步過濾（規則同 core.menu.visible）；空群組不留。"""
    out = []
    for g in decl:
        items = [{k: v for k, v in it.items() if k != "perm"} for it in g["items"]
                 if M.visible(it["perm"], set(modules), superadmin)]
        if items:
            out.append({"key": g["key"], "label": g["label"], "items": items})
    return out


def test_sidebar_js_is_prefixed_with_the_declaration(client):
    from core import paths as _paths
    from pathlib import Path
    r, menu, body = _served(client)
    assert body == (Path(_paths.FRONTEND_DIR) / "static" / "sidebar.js").read_text(encoding="utf-8"), "檔案本體要原樣接在後面"
    assert "no-store" in r.headers.get("cache-control", ""), "模組狀態會變 ⇒ 不可以被快取"
    assert r.headers["content-type"].startswith("application/javascript")
    assert set(menu) == {"v", "groups", "pageModules"}, "只放與使用者無關的宣告（狀態、自訂模組要登入才拿得到）"
    assert all(set(v) == {"key", "name"} for v in menu["pageModules"].values())
    assert client.head("/static/sidebar.js").status_code == 200


@pytest.mark.parametrize("modules,sa", [([], False), ([], True), (["quotation", "finance"], False),
                                        (["equipment", "cashier", "work_log"], False)])
def test_declaration_filtered_equals_build(modules, sa):
    l1, mi = M.load_l1(), _mod_items()
    assert _filter(M.declaration(l1, mi), modules, sa) == M.build(l1, mi, modules, sa)


def test_declaration_matches_platform_menu_for_the_same_user(client, make_user):
    _r, menu, _b = _served(client)
    u, pw = make_user(username="c4_inj_sa", role="superadmin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}
    assert _filter(menu["groups"], [], True) == client.get("/api/platform/menu", headers=h).json()["groups"]


def test_unloaded_module_items_leave_but_its_pages_stay_mapped(client, monkeypatch):
    _r, before, _b = _served(client)
    key = next((it["module"] for g in before["groups"] for it in g["items"] if it.get("module")), None)
    if key is None:
        pytest.skip("沒有已載入、宣告選單項的模組 ⇒ 無對象")
    pages = sorted(p for p, v in before["pageModules"].items() if v["key"] == key)
    assert pages, "正對照：它的頁面在 pageModules 裡"
    real = registry.loaded
    monkeypatch.setattr(registry, "loaded", lambda: [m for m in real() if m.key != key])
    _r, after, _b = _served(client)
    assert not any(it.get("module") == key for g in after["groups"] for it in g["items"])
    assert sorted(p for p, v in after["pageModules"].items() if v["key"] == key) == pages
    assert all(g["items"] for g in after["groups"]), "不可以留空群組"


def test_js_literal_cannot_break_out_of_the_script():
    s = PM._js_literal({"a": "</script><b>", "b": "x" + chr(0x2028) + "y" + chr(0x2029)})
    assert "</" not in s and chr(0x2028) not in s and chr(0x2029) not in s
    assert json.loads(s) == {"a": "</script><b>", "b": "x" + chr(0x2028) + "y" + chr(0x2029)}
