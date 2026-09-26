"""C4：選單套用角色版面（STAGE-C L79 更正 ②③；主持裁示 A）。

- `core.menu.apply_layout`：只認側欄點的 hide／show／move{index}（群組內、0 起算），不換群組；不改傳入值；空群組不留標題
- `GET /api/platform/menu` 的 `layout`：套**使用者角色**的版面；`groups`／`denied` 仍是宣告版（P9 面板預覽讀它）
- hide 只是顯示、不是權限：伺服器端權限不看版面
- `/api/layout/{module}` 與選單用同一個 `core.catalog.effective_layout_ops`（不複製 resolve＋check_layout）
不綁特定 L2：任取一個已載入、有選單項的模組；沒有 ⇒ skip 寫明。
"""
import json

import pytest

from core import catalog, registry
from core import menu as M


def _groups():
    return [{"key": "g", "label": "G", "items": [
        {"href": "a.html", "label": "A", "module": "ma"},
        {"href": "b.html", "label": "B", "module": "mb"},
        {"href": "l1.html", "label": "L1 項"}]},
        {"key": "h", "label": "H", "items": [{"href": "c.html", "label": "C", "module": "mc"}]}]


def _hrefs(groups):
    return [(g["key"], [it["href"] for it in g["items"]]) for g in groups]


def test_apply_layout_hide_move_show():
    src = _groups()
    out, applied, skipped = M.apply_layout(src, [
        {"op": "move", "target": "mb:b.html/sidebar", "index": 0},
        {"op": "hide", "target": "mc:c.html/sidebar"}])
    assert _hrefs(out) == [("g", ["b.html", "a.html", "l1.html"])]          # 群組 h 被 hide 到空 ⇒ 不出現
    assert len(applied) == 2 and skipped == []
    assert _hrefs(src)[0][1] == ["a.html", "b.html", "l1.html"], "不可以改到傳入的 groups"
    out2, _, _ = M.apply_layout(src, [{"op": "hide", "target": "ma:a.html/sidebar"},
                                      {"op": "show", "target": "ma:a.html/sidebar"}])
    assert _hrefs(out2) == _hrefs(src)                                        # show 抵銷 hide


def test_apply_layout_skips_what_it_does_not_understand():
    """不是側欄點、或選單上沒有那一項（模組未載入／沒權限）⇒ 略過並列出，不猜。"""
    out, applied, skipped = M.apply_layout(_groups(), [
        {"op": "hide", "target": "ma:a.html/list:tenders"},
        {"op": "hide", "target": "zz:nope.html/sidebar"},
        {"op": "relabel", "target": "ma:a.html/sidebar", "label": "x"}])
    assert applied == [] and len(skipped) == 3 and _hrefs(out) == _hrefs(_groups())


def test_apply_layout_move_index_out_of_range_goes_last():
    out, _, _ = M.apply_layout(_groups(), [{"op": "move", "target": "ma:a.html/sidebar", "index": 99}])
    assert _hrefs(out)[0][1] == ["b.html", "l1.html", "a.html"]


# ── API：任取一個已載入、有選單項的模組 ───────────────────────────────────────────

def _pick():
    for m in registry.loaded():
        for p in (m.manifest or {}).get("pages") or []:
            if isinstance(p, dict) and p.get("menu"):
                return m.key, p["path"], m.manifest
    pytest.skip("沒有已載入、宣告選單項的模組 ⇒ 無對象")


def _login(client, make_user, name, role):
    u, pw = make_user(username=name, role=role)
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def _publish_role_layout(role, key, ops):
    import db
    from core import definitions as D
    conn = db.get_db()
    try:
        D.save_draft(conn, "layout", "module:%s" % key, "role:%s" % role, {"ops": ops}, user="test")
        D.publish(conn, "layout", "module:%s" % key, "role:%s" % role, note="test", user="test")
    finally:
        conn.close()


def _flat(groups):
    return [it["href"] for g in groups for it in g["items"]]


def test_menu_layout_applies_the_users_role_only(client, make_user):
    key, href, _m = _pick()
    h_admin = _login(client, make_user, "c4_admin", "admin")
    h_sa = _login(client, make_user, "c4_sa", "superadmin")
    before = client.get("/api/platform/menu", headers=h_admin).json()
    assert href in _flat(before["groups"]) and href in _flat(before["layout"]["groups"])   # 正對照：還沒有版面
    _publish_role_layout("admin", key, [{"op": "hide", "target": "%s:%s/sidebar" % (key, href)}])
    after = client.get("/api/platform/menu", headers=h_admin).json()
    assert href not in _flat(after["layout"]["groups"]), after["layout"]
    assert href in _flat(after["groups"]), "groups 是宣告版（P9 面板預覽讀它），不套版面"
    assert after["denied"] == before["denied"], "hide 只是顯示，不改變權限（denied）"
    other = client.get("/api/platform/menu", headers=h_sa).json()
    assert href in _flat(other["layout"]["groups"]), "別的角色不受 admin 的版面影響"


def test_hide_is_display_only_not_permission(client, make_user):
    """STAGE-C L79 ③：版面把項目藏起來，伺服器端照樣准許那個模組的端點（權限不看版面）。"""
    key, href, man = _pick()
    probes = (man.get("provides") or {}).get("probes") or []
    if not probes:
        pytest.skip("任取到的模組 %s 沒有宣告 probes ⇒ 無可打的端點" % key)
    h = _login(client, make_user, "c4_sa2", "superadmin")
    assert client.get(probes[0], headers=h).status_code == 200                     # 正對照
    _publish_role_layout("superadmin", key, [{"op": "hide", "target": "%s:%s/sidebar" % (key, href)}])
    assert href not in _flat(client.get("/api/platform/menu", headers=h).json()["layout"]["groups"])
    assert client.get(probes[0], headers=h).status_code == 200, "藏起來之後伺服器端權限不可以跟著變"


def test_layout_endpoint_and_menu_share_one_resolver(client, make_user, monkeypatch):
    """/api/layout/{module} 與 /api/platform/menu 都經 core.catalog.effective_layout_ops（換掉它 ⇒ 兩邊一起變）。"""
    key, href, _m = _pick()
    calls = []

    def fake(conn, module_key, role):
        calls.append(module_key)
        return {"ops": [{"op": "hide", "target": "%s:%s/sidebar" % (key, href)}] if module_key == key else [],
                "dropped": [], "source": "fake", "error": None}
    monkeypatch.setattr(catalog, "effective_layout_ops", fake)
    h = _login(client, make_user, "c4_sa3", "superadmin")
    lay = client.get("/api/layout/%s" % key, headers=h).json()
    assert lay["source"] == "fake" and lay["ops"]
    menu = client.get("/api/platform/menu", headers=h).json()
    assert menu["layout"]["sources"].get(key) == "fake" and href not in _flat(menu["layout"]["groups"])
    assert key in calls


def test_menu_layout_error_is_reported_not_silent(client, make_user, monkeypatch):
    """讀版面失敗 ⇒ 用程式預設（選單照常），錯誤列在 layout.errors——不可以靜默。"""
    key, href, _m = _pick()
    from core import definitions as D

    def boom(*a, **k):
        raise RuntimeError("讀不到")
    monkeypatch.setattr(D, "resolve", boom)
    h = _login(client, make_user, "c4_sa4", "superadmin")
    menu = client.get("/api/platform/menu", headers=h).json()
    assert href in _flat(menu["layout"]["groups"])
    assert any(e["module"] == key for e in menu["layout"]["errors"]), menu["layout"]


# ── 自訂模組併進 layout（C4 步驟 ③；STAGE-C L79 更正 ①：自訂模組是資料，只在登入後出現）────────────────

def test_merge_custom_groups_order_and_no_mutation():
    src = _groups()
    customs = [{"key": "k_b", "name": "乙", "menu": {"group": "G", "order": 20}},
               {"key": "k_a", "name": "甲", "menu": {"group": "G", "order": 10}},
               {"key": "k c", "name": "丙", "menu": {}},
               {"key": "k_d", "name": "丁", "menu": {"group": "新組", "order": 2000}}]
    out = M.merge_custom(src, customs)
    assert _hrefs(src) == _hrefs(_groups()), "不可以改到傳入的 groups"
    g = {x["label"]: x for x in out}
    assert [it["label"] for it in g["G"]["items"]][-2:] == ["甲", "乙"], "同名群組 ⇒ 併進去、排在最後、依 order"
    assert [it["label"] for it in g[M.CUSTOM_DEFAULT_GROUP]["items"]] == ["丙"]
    assert g[M.CUSTOM_DEFAULT_GROUP]["items"][0]["href"] == "custom-records.html?key=k%20c"
    assert [x["label"] for x in out][-2:] == [M.CUSTOM_DEFAULT_GROUP, "新組"], "新開的組依第一次出現的順序排在最後"
    assert all(it["custom"] and it["module"] is None for gg in out for it in gg["items"] if "custom" in it)


def _publish_custom(client, h, key, name):
    body = {"name": name, "permission": "custom.%s" % key,
            "numbering": {"prefix": "ZQ", "date": "YYYYMMDD", "digits": 4},
            "fields": [{"key": "item", "label": "項目", "type": "text"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []}}
    r = client.put("/api/definitions/custom_module/%s/draft" % key, headers=h, json={"body": body})
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
    assert client.post("/api/definitions/custom_module/%s/publish" % key, headers=h, json={}).status_code == 200


def _custom_labels(menu):
    return [it["label"] for g in menu["layout"]["groups"] for it in g["items"] if it.get("custom")]


def test_platform_menu_layout_carries_only_the_custom_modules_the_user_may_see(client, make_user):
    h_sa = _login(client, make_user, "c4_cm_sa", "superadmin")
    _publish_custom(client, h_sa, "c4_cm", "C4自訂甲")
    assert "C4自訂甲" in _custom_labels(client.get("/api/platform/menu", headers=h_sa).json())
    u, pw = make_user(username="c4_cm_no", role="engineer", modules=["dashboard"])
    h_no = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}
    assert "C4自訂甲" not in _custom_labels(client.get("/api/platform/menu", headers=h_no).json())
    u, pw = make_user(username="c4_cm_yes", role="engineer", modules=["dashboard", "custom.c4_cm"])
    h_yes = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}
    menu = client.get("/api/platform/menu", headers=h_yes).json()
    assert "C4自訂甲" in _custom_labels(menu)
    # 與 /api/custom-modules 同一份過濾（helpers.custom_modules.visible_to）
    for h in (h_sa, h_no, h_yes):
        want = sorted(m["key"] for m in client.get("/api/custom-modules", headers=h).json())
        assert sorted(client.get("/api/platform/menu", headers=h).json()["layout"]["custom"]) == want


def test_custom_module_read_failure_is_reported_not_silent(client, make_user, monkeypatch):
    from helpers import custom_modules as CM

    def boom(conn):
        raise RuntimeError("讀不到")
    monkeypatch.setattr(CM, "published_modules", boom)
    h = _login(client, make_user, "c4_cm_err", "superadmin")
    menu = client.get("/api/platform/menu", headers=h).json()
    assert menu["layout"]["groups"], "選單照常"
    assert any(e["module"] is None and "自訂模組" in e["error"] for e in menu["layout"]["errors"]), menu["layout"]["errors"]
