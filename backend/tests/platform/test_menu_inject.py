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


def test_unloaded_module_leaves_no_trace_in_the_public_declaration(client, make_user, monkeypatch):
    """模組沒載入 ⇒ 未登入拿得到的宣告裡**項目與頁面都不列**（稽核 X C4-O3 主持裁示：不可以從 groups 與 pageModules 的差
    推出哪些模組停用／未授權）。登入後的 /api/platform/menu pageModules 仍有完整對照（前端藏連結、後備提示用）。
    〔更正：原題名 test_unloaded_module_items_leave_but_its_pages_stay_mapped，斷言頁面**仍在**——那正是 O3 的外洩〕"""
    _r, before, _b = _served(client)
    key = next((it["module"] for g in before["groups"] for it in g["items"] if it.get("module")), None)
    if key is None:
        pytest.skip("沒有已載入、宣告選單項的模組 ⇒ 無對象")
    pages = sorted(p for p, v in before["pageModules"].items() if v["key"] == key)
    assert pages, "正對照：載入時它的頁面在 pageModules 裡"
    real = registry.loaded
    monkeypatch.setattr(registry, "loaded", lambda: [m for m in real() if m.key != key])
    _r, after, _b = _served(client)
    assert not any(it.get("module") == key for g in after["groups"] for it in g["items"])
    assert not [p for p, v in after["pageModules"].items() if v["key"] == key], "沒載入的模組頁不可以列在未登入的宣告裡"
    assert all(g["items"] for g in after["groups"]), "不可以留空群組"
    loaded_keys = {m.key for m in registry.loaded()}
    assert {v["key"] for v in after["pageModules"].values()} <= loaded_keys, "pageModules 只可以有已載入的模組"
    u, pw = make_user(username="c4_o3_sa", role="superadmin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}
    full = client.get("/api/platform/menu", headers=h).json()["pageModules"]
    assert sorted(p for p, v in full.items() if v["key"] == key) == pages, "登入後的完整對照要有它（含沒載入的）"


def test_js_literal_cannot_break_out_of_the_script():
    s = PM._js_literal({"a": "</script><b>", "b": "x" + chr(0x2028) + "y" + chr(0x2029)})
    assert "</" not in s and chr(0x2028) not in s and chr(0x2029) not in s
    assert json.loads(s) == {"a": "</script><b>", "b": "x" + chr(0x2028) + "y" + chr(0x2029)}


# ── 主持判定（2026-09-26，STAGE-C L79 附註）：MOTRIX_MENU 不含任何來自資料庫的字串 ──────────────────
# 透露「裝了哪些模組」可以接受（程式宣告、不是資料）；自訂模組名稱、公司名稱等**資料**不可以出現在不需登入的 js。

_SENTINEL_MOD = "哨兵自訂模組ZQX7"
_SENTINEL_CO = "哨兵公司名稱ZQX7"


def _plant_db_strings(client, make_user):
    u, pw = make_user(username="c4_inj_leak", role="superadmin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}
    body = {"name": _SENTINEL_MOD, "permission": "custom.c4_sentinel",
            "numbering": {"prefix": "ZQ", "date": "YYYYMMDD", "digits": 4},
            "fields": [{"key": "item", "label": "項目", "type": "text"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []}}
    r = client.put("/api/definitions/custom_module/c4_sentinel/draft", headers=h, json={"body": body})
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    assert client.post("/api/definitions/custom_module/c4_sentinel/publish", headers=h, json={}).status_code == 200
    assert client.put("/api/settings/company-profile", headers=h, json={"name": _SENTINEL_CO}).status_code == 200
    # 正對照：兩個字串確實寫進資料庫、登入後拿得到（否則下面的「不含」是空轉）
    assert any(m.get("name") == _SENTINEL_MOD for m in client.get("/api/custom-modules", headers=h).json())
    assert client.get("/api/settings/company-profile", headers=h).json().get("name") == _SENTINEL_CO
    return h


def _leaks(text):
    return [s for s in (_SENTINEL_MOD, _SENTINEL_CO, "c4_sentinel") if s in text]


def test_motrix_menu_contains_no_database_strings(client, make_user):
    _plant_db_strings(client, make_user)
    r = client.get("/static/sidebar.js")          # 不帶 token
    # 判準對「未登入就拿得到的整份回應」，不是只看第一行（稽核 X C4-S3：放在第二行的外洩原本抓不到）
    assert r.text.startswith(PREFIX) and _leaks(r.text) == [], _leaks(r.text)


def test_rc_database_string_leak_would_be_caught(client, make_user, monkeypatch):
    """反向控制：宣告若把已發布自訂模組併進去（最自然的錯法），上一題的判準要抓得到。"""
    _plant_db_strings(client, make_user)
    real = PM.menu_declaration

    def leaky(page_map):
        from db import get_db
        from helpers import custom_modules as CM
        d = real(page_map)
        conn = get_db()
        try:
            d["custom"] = CM.published_modules(conn)
        finally:
            conn.close()
        return d
    monkeypatch.setattr(PM, "menu_declaration", leaky)
    assert _SENTINEL_MOD in _leaks(client.get("/static/sidebar.js").text)


def test_rc_leak_outside_the_first_line_is_caught(client, make_user, monkeypatch):
    """反向控制（稽核 X9）：資料庫字串放在宣告以外的行（例 `window.MOTRIX_CUSTOM = …`）⇒ 判準也要抓到。"""
    _plant_db_strings(client, make_user)
    real = PM.sidebar_js_source

    def leaky(page_map, frontend_dir):
        from db import get_db
        from helpers import custom_modules as CM
        conn = get_db()
        try:
            extra = "window.MOTRIX_CUSTOM = %s;" % PM._js_literal(CM.published_modules(conn))
        finally:
            conn.close()
        head, _, body = real(page_map, frontend_dir).partition(chr(10))
        return head + chr(10) + extra + chr(10) + body
    monkeypatch.setattr(PM, "sidebar_js_source", leaky)
    assert _SENTINEL_MOD in _leaks(client.get("/static/sidebar.js").text)
