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
