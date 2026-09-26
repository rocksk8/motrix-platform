"""選單由登錄表產生（階段 C／C3）：新舊對等＋宣告守門＋API。

C3 期間 sidebar.js 的舊選單（buildSidebar）與 core.menu 並行；本檔確保兩邊**逐項一致**：
群組、順序、標題、權限、active、徽章。C4 切換、刪掉舊選單時，對等題一起移除（改成只驗宣告）。
"""
import json
from itertools import chain

import pytest

from core import menu as M
from tests.platform import _menu_legacy as L


def _declared():
    """宣告式選單：L1 ＋ 安裝目錄每一個模組（不論載入與否——對等比的是「全部都裝、都開」的情況）。"""
    from core import source_tree
    manifests = {d.name: json.loads((d / "module.json").read_text(encoding="utf-8")) for d in source_tree.module_dirs()}
    return M.load_l1(), M.module_items(manifests)


def _legacy_installed():
    """舊選單扣掉「所屬模組不在這棵樹」的項目（sidebar.js `MODULE_PAGES` 的頁面 ⇒ 模組 key）。

    舊選單在執行期由 `_moduleLoaded()` 藏起未載入模組的入口；宣告式選單則根本沒有那個模組的 module.json。
    兩邊比的是「這棵樹裝了的」——M08 反向控制：拿掉模組之後對等題不可以因為舊選單寫死了它的項目而紅。
    ⚠ 依賴 `MODULE_PAGES` 的 key 寫對：key 打錯時，對等兩題會把那一項從兩邊一起濾掉而轉綠——
    由 `test_module_selection::test_every_module_page_is_declared_in_sidebar`（key 必須對得上 module.json）補住（稽核 ⑰ O-1 實測）。"""
    import re
    from core import source_tree
    src = L.SIDEBAR.read_text(encoding="utf-8")
    block = src[src.index("var MODULE_PAGES = {"):]
    block = block[:block.index("window.MOTRIX_MODULE_PAGES")]
    page_key = dict(re.findall(r"'([\w.-]+\.html)':\s*\{\s*key:\s*'(\w+)'", block))
    assert page_key, "sidebar.js 的 MODULE_PAGES 讀不到任何頁面 ⇒ 改本檔的解析"
    installed = {d.name for d in source_tree.module_dirs()}
    legacy = L.legacy_menu()
    for g in legacy["groups"]:
        g["items"] = [it for it in g["items"] if page_key.get(it["href"]) in (None, *installed)]
    return legacy, page_key


def test_legacy_filter_drops_only_pages_of_modules_not_installed(monkeypatch):
    """反向控制：假裝一個模組都沒裝 ⇒ 被扣掉的恰好是 MODULE_PAGES 裡的頁面、其餘一項不少；
    全部都裝（每個 MODULE_PAGES 的 key 都在）⇒ 一項不扣。"""
    from core import source_tree
    full = [it["href"] for g in L.legacy_menu()["groups"] for it in g["items"]]
    monkeypatch.setattr(source_tree, "module_dirs", lambda: [])
    none_installed, page_key = _legacy_installed()
    kept = [it["href"] for g in none_installed["groups"] for it in g["items"]]
    assert kept == [h for h in full if h not in page_key]
    assert set(full) - set(kept) == set(page_key) & set(full)
    fake = [type("D", (), {"name": k})() for k in set(page_key.values())]
    monkeypatch.setattr(source_tree, "module_dirs", lambda: fake)
    all_installed, _ = _legacy_installed()
    assert [it["href"] for g in all_installed["groups"] for it in g["items"]] == full


def _norm(it):
    return {"href": it["href"], "label": it["label"], "perm": it["perm"],
            "active": list(it.get("active") or [it["href"]]), "badge": it.get("badge"),
            "extra_badge": it.get("extra_badge")}


def _all_keys(legacy):
    ks = set()
    for g in legacy["groups"]:
        for it in g["items"]:
            if isinstance(it["perm"], list):
                ks |= set(it["perm"])
    return sorted(ks)


def test_declarations_are_valid():
    l1, mods = _declared()
    assert M.validate(l1, mods) == []


def test_every_legacy_item_is_declared_identically():
    """逐項：同一群組、同一順序、同一權限／active／徽章。"""
    legacy, _ = _legacy_installed()
    l1, mods = _declared()
    labels = {g["key"]: g["label"] for g in l1["groups"]}
    assert [g["label"] for g in legacy["groups"]] == [g["label"] for g in l1["groups"]]
    for lg in legacy["groups"]:
        key = next(k for k, v in labels.items() if v == lg["label"])
        mine = sorted((it for it in chain(l1["items"], mods) if it["group"] == key), key=lambda it: (it["order"], it["href"]))
        assert [_norm(it) for it in mine] == [_norm(it) for it in lg["items"]], lg["label"]


def test_group_condition_equals_union_of_items():
    """舊碼的 sec() 條件＝底下各項條件的聯集 ⇒ 新選單以「至少一項可見」推導群組是等價的。"""
    for g in L.legacy_menu()["groups"]:
        perms = [it["perm"] for it in g["items"]]
        if "any" in perms:
            assert g["perm"] == "any", g["label"]
            continue
        union = set()
        for p in perms:
            union |= {"superadmin"} if p == "superadmin" else set(p)
        assert sorted(union) == g["perm"], g["label"]


def _legacy_visible(legacy, modules, superadmin):
    out = []
    for g in legacy["groups"]:
        items = [it["href"] for it in g["items"] if M.visible(it["perm"], set(modules), superadmin)]
        if items:
            out.append((g["label"], items))
    return out


def test_rendered_menu_matches_for_every_single_permission():
    """最高管理者、沒有任何權限、以及每一個單一模組權限：新舊渲染出的群組與項目（含順序）完全相同。"""
    legacy, _ = _legacy_installed()
    l1, mods = _declared()
    cases = [([], True), ([], False)] + [([k], False) for k in _all_keys(legacy)]
    for modules, sa in cases:
        new = [(g["label"], [it["href"] for it in g["items"]]) for g in M.build(l1, mods, modules, sa)]
        assert new == _legacy_visible(legacy, modules, sa), (modules, sa)
        assert M.denied(l1, mods, modules, sa) == _legacy_denied(legacy, modules, sa), (modules, sa)


def _legacy_denied(legacy, modules, superadmin):
    """舊碼 ni(show=false) 把 activeNames 併進 `_deniedPages`。"""
    out = set()
    for g in legacy["groups"]:
        for it in g["items"]:
            if not M.visible(it["perm"], set(modules), superadmin):
                out |= set(it["active"])
    return sorted(out)


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
    h = _auth(client, make_user)                 # 最高管理者
    r = client.get("/api/platform/menu", headers=h)
    assert r.status_code == 200
    assert "tender-radar.html" in _hrefs(r) and "users.html" in _hrefs(r)

    monkeypatch.delitem(registry._LOADED, "tender_radar")      # 模組沒載入 ⇒ 選單項不出現
    assert "tender-radar.html" not in _hrefs(client.get("/api/platform/menu", headers=h))


def test_api_menu_requires_login(client):
    assert client.get("/api/platform/menu").status_code in (401, 403)
