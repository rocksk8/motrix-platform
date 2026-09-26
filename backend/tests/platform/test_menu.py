"""選單宣告守門＋API（階段 C／C3、C4）。

〔C4：C3 的新舊對等題（逐項比對 sidebar.js 舊 `buildSidebar()`，檔名 test_menu_parity.py）隨舊選單一起退場；
  原本「模組不在 ⇒ 扣掉它的項目」是用 sidebar.js 寫死的 `MODULE_PAGES` 扣，而那份表遮住了 menu_l1.json 裡 7 項其實是
  模組頁面的缺口（主持裁示 A：搬回各模組 module.json）。改為——〕
- 宣告有效（validate）；L1 選單項不可指向任何模組頁（check_l1_pages；repo 層級用 docs/platform/modules.json 登記的頁面）
- 對**拿掉模組的樹**實際比對：modules.json 登記、這棵樹沒裝的模組，它的頁面不可出現在送出去的 `MOTRIX_MENU`
  （完整樹上對象是空的；core-only／sparse 反向控制時才有對象——那正是它要守的情況）
"""
import json

import pytest

from core import menu as M


def _manifests():
    from core import source_tree
    return {d.name: json.loads((d / "module.json").read_text(encoding="utf-8")) for d in source_tree.module_dirs()}


def _registered_pages():
    """docs/platform/modules.json 登記的**已搬成模組**的頁面 ⇒ {頁名: 模組key}（repo 層級：這棵樹裝不裝都一樣）。
    已搬＝該組的 units 有 `mod:` 單位；還沒搬的組（頁面仍是 L1 頁）不算——它們的頁面本來就由 L1 提供。
    〔更正：第一版取了所有組的 page: 單位 ⇒ 把 M01／M03／M05／M06 還沒搬的 11 頁當成「沒裝的模組」而紅〕"""
    from pathlib import Path
    p = Path(__file__).resolve().parents[3] / "docs" / "platform" / "modules.json"
    out = {}
    for g in json.loads(p.read_text(encoding="utf-8"))["modules"].values():
        if not any(u.startswith("mod:") for u in g.get("units") or []):
            continue
        for u in g.get("units") or []:
            if u.startswith("page:"):
                out[u.split("/")[-1]] = g["key"]
    assert out, "modules.json 讀不到任何 page: 單位 ⇒ 讀法壞了"
    return out


def test_declarations_are_valid():
    assert M.validate(M.load_l1(), M.module_items(_manifests())) == []


def test_l1_menu_never_points_at_a_module_page():
    """STAGE-C L63：menu_l1 只放 L1 頁面。寫在 L1 的模組頁 ⇒ 模組不在時入口照樣出現。"""
    mod_pages = {p["path"]: k for k, m in _manifests().items() for p in (m.get("pages") or [])}
    assert M.check_l1_pages(M.load_l1(), {**_registered_pages(), **mod_pages}) == []


def test_rc_l1_item_pointing_at_a_module_page_is_caught():
    l1 = _base()
    probs = M.check_l1_pages(l1, {"a.html": "m"})
    assert len(probs) == 1 and "a.html" in probs[0] and "m" in probs[0], probs
    assert M.check_l1_pages(l1, {"b.html": "m"}) == []


def test_removed_module_pages_are_not_in_the_served_menu(client):
    """拿掉模組的樹：modules.json 登記、而這棵樹沒裝的模組，它的頁面不可以出現在 MOTRIX_MENU（任何一項的 href）。"""
    from core import source_tree
    installed = {d.name for d in source_tree.module_dirs()}
    reg = _registered_pages()
    head = client.get("/static/sidebar.js").text.partition("\n")[0]
    menu = json.loads(head[len("window.MOTRIX_MENU = "):].rstrip(";"))
    hrefs = {it["href"].lstrip("/") for g in menu["groups"] for it in g["items"]}
    assert hrefs, "正對照：選單是空的 ⇒ 下面的「沒有」是空轉"
    leaked = sorted("%s（%s）" % (h, reg[h]) for h in hrefs if h in reg and reg[h] not in installed)
    assert not leaked, "沒裝的模組的入口出現在選單上：%s" % leaked


# ── 宣告守門的反向控制 ─────────────────────────────────────────────────────

def _base():
    return {"groups": [{"key": "g", "label": "G"}], "items": [
        {"group": "g", "href": "a.html", "label": "A", "order": 10, "perm": ["x"]}]}


@pytest.mark.parametrize("bad,msg", [
    ({"group": "nope"}, "不存在的群組"),
    ({"order": "10"}, "整數 order"),
    ({"perm": []}, "perm 不合法"),
    ({"perm": "admin"}, "perm 不合法"),
    ({"label": ""}, "缺 label"),
    ({"icon": "x"}, "不認得的欄位"),
])
def test_rc_bad_item_is_caught(bad, msg):
    l1 = _base()
    l1["items"][0].update(bad)
    assert any(msg in p for p in M.validate(l1)), M.validate(l1)


def test_rc_module_cannot_invent_group_or_duplicate_href():
    l1 = _base()
    probs = M.validate(l1, [{"group": "mine", "href": "b.html", "label": "B", "order": 5, "perm": "any", "module": "m"},
                            {"group": "g", "href": "a.html", "label": "A2", "order": 5, "perm": "any", "module": "m"}])
    assert any("群組只能在 L1 定義" in p for p in probs)
    assert any("重複" in p for p in probs)


def test_rc_group_hidden_when_no_visible_item():
    l1 = _base()
    assert M.build(l1, [], ["y"], False) == []
    assert M.build(l1, [], ["x"], False)[0]["items"][0]["href"] == "a.html"
    assert M.build(l1, [], [], True)[0]["items"][0]["href"] == "a.html"   # 最高管理者一律可


# ── API ──────────────────────────────────────────────────────────────────────

def _hrefs(r):
    return [it["href"] for g in r.json()["groups"] for it in g["items"]]


def test_api_menu_follows_permissions_and_module_state(client, make_user, monkeypatch):
    from core import registry
    from tests.test_mp1_map_points_link_to_records_2026_09_24 import _auth
    from core import source_tree
    h = _auth(client, make_user)                 # 最高管理者
    r = client.get("/api/platform/menu", headers=h)
    assert r.status_code == 200
    assert "users.html" in _hrefs(r)
    # 任取一個已載入、有選單項的模組（不綁特定 L2；core-only 反向控制時沒有 ⇒ 模組狀態那一半無對象）
    pick = None
    for d in source_tree.module_dirs():
        pages = json.loads((d / "module.json").read_text(encoding="utf-8")).get("pages") or []
        href = next((p["path"] for p in pages if p.get("menu")), None)
        if href and d.name in registry._LOADED:
            pick = (d.name, href)
            break
    if pick is None:
        pytest.skip("沒有已載入且宣告選單項的模組 ⇒ 「模組沒載入 ⇒ 選單項不出現」無對象")
    key, href = pick
    assert href in _hrefs(r)
    monkeypatch.delitem(registry._LOADED, key)          # 模組沒載入 ⇒ 選單項不出現
    assert href not in _hrefs(client.get("/api/platform/menu", headers=h))


def test_api_menu_requires_login(client):
    assert client.get("/api/platform/menu").status_code in (401, 403)
