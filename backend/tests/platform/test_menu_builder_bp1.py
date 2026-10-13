# -*- coding: utf-8 -*-
"""BP-1 選單建構器（側欄改名、換到另一個既有群組、整份選單預覽；設定 builder_menu.enabled 預設關）。

- 純函式：`core.menu.apply_layout(builder=...)`；關著 ⇒ 與 BP-1 之前逐字相同（舊版面不變）
- 驗證：側欄名稱長度上限、標記字元一律拒絕；move.to 只能是既有群組鍵
- 遮蔽優先：改名／換群組不改 href／perm／denied；沒有權限的項目不出現在預覽；目的群組看不到 ⇒ 略過並列出
- API：POST /api/platform/menu/preview——關著 404、非最高管理者 403、開啟後回 current／preview／opsHash
不綁特定 L2：任取一個已載入、有選單項的模組。
"""
import json

import pytest

from core import customization as C
from core import menu as M
from core import registry
from helpers import menu_builder as MB


def _groups():
    return [{"key": "g", "label": "G", "items": [
        {"href": "a.html", "label": "A", "module": "ma", "perm": ["pa"]},
        {"href": "b.html", "label": "B", "module": "mb"},
        {"href": "l1.html", "label": "L1 項"}]},
        {"key": "h", "label": "H", "items": [{"href": "c.html", "label": "C", "module": "mc"}]}]


def _hrefs(groups):
    return [(g["key"], [it["href"] for it in g["items"]]) for g in groups]


def _labels(groups):
    return [(g["key"], [it["label"] for it in g["items"]]) for g in groups]


# ── 純函式 ───────────────────────────────────────────────────────────────────────────
def test_relabel_changes_label_only():
    src = _groups()
    out, applied, skipped = M.apply_layout_ex(src, [{"op": "relabel", "target": "ma:a.html/sidebar", "label": "新名稱"}], builder=True)
    assert _labels(out)[0][1][0] == "新名稱" and skipped == [] and len(applied) == 1
    it = out[0]["items"][0]
    assert it["href"] == "a.html" and it["module"] == "ma" and it["perm"] == ["pa"], "改名不改 href／module／perm"
    assert src == _groups(), "不可以改到傳入值"


def test_move_to_other_visible_group_and_index():
    out, applied, skipped = M.apply_layout_ex(_groups(), [{"op": "move", "target": "ma:a.html/sidebar", "to": "group:h", "index": 0}], builder=True)
    assert _hrefs(out) == [("g", ["b.html", "l1.html"]), ("h", ["a.html", "c.html"])] and skipped == []
    out2, _, _ = M.apply_layout_ex(_groups(), [{"op": "move", "target": "ma:a.html/sidebar", "to": "group:h"}], builder=True)
    assert _hrefs(out2)[1] == ("h", ["c.html", "a.html"]), "沒給 index ⇒ 放目的群組最後"


def test_move_to_group_the_user_cannot_see_is_skipped_and_reported():
    """(c) 目的群組不在這位使用者看得到的群組裡（build 已把沒有可見項目的群組拿掉）⇒ 略過並列出，項目留在原處。"""
    src = _groups()[:1]                                   # 使用者看不到群組 h
    op = {"op": "move", "target": "ma:a.html/sidebar", "to": "group:h"}
    out, applied, skipped = M.apply_layout_ex(src, [op], builder=True)
    assert _hrefs(out) == _hrefs(src) and applied == [] and len(skipped) == 1 and skipped[0]["op"] == op
    assert "群組" in skipped[0]["reason"]
    out, _, skipped = M.apply_layout_ex(_groups(), [dict(op, to="group:nope")], builder=True)
    assert len(skipped) == 1 and _hrefs(out) == _hrefs(_groups())


def test_ops_on_items_the_user_cannot_see_are_skipped():
    """遮蔽優先：選單上沒有的項目（沒權限／模組未載入）不論改名或換群組，都不會被帶出來。"""
    groups = [{"key": "g", "label": "G", "items": [{"href": "b.html", "label": "B", "module": "mb"}]}]
    ops = [{"op": "relabel", "target": "ma:a.html/sidebar", "label": "偷看"},
           {"op": "move", "target": "ma:a.html/sidebar", "to": "group:g"}]
    out, applied, skipped = M.apply_layout_ex(groups, ops, builder=True)
    assert applied == [] and len(skipped) == 2 and _hrefs(out) == _hrefs(groups) and _labels(out) == _labels(groups)


def test_flag_off_apply_layout_is_byte_identical_to_before():
    """(d) builder=False ⇒ relabel 略過、move 的 to 被忽略（只做群組內 index），輸出與沒有這些欄位時逐字相同。"""
    ops_old = [{"op": "move", "target": "mb:b.html/sidebar", "index": 0}, {"op": "hide", "target": "mc:c.html/sidebar"}]
    base = M.apply_layout(_groups(), ops_old)
    assert M.apply_layout_ex(_groups(), ops_old, builder=False) == base
    mixed = ops_old + [{"op": "relabel", "target": "ma:a.html/sidebar", "label": "x"}]
    out, applied, skipped = M.apply_layout(_groups(), mixed)
    assert out == base[0] and applied == base[1] and len(skipped) == 1 and skipped[0]["reason"] == "不是側欄點的操作"
    with_to = [{"op": "move", "target": "ma:a.html/sidebar", "to": "group:h", "index": 1}]
    assert M.apply_layout(_groups(), with_to)[0] == M.apply_layout_ex(_groups(), [{"op": "move", "target": "ma:a.html/sidebar", "index": 1}])[0]


# ── 驗證 ─────────────────────────────────────────────────────────────────────────────
def test_label_markup_and_length_rejected():
    """(a) 含標記字元一律拒絕、最長 20 字；正對照：合法名稱通過。"""
    assert C.SIDEBAR_LABEL_MAX == 20
    assert C.sidebar_label_problem("我的工作") is None and C.sidebar_label_problem("x" * 20) is None
    for bad in ("<b>x</b>", "a&b", 'a"b', "a'b", "a`b", "a\\b", "x" * 21, "   ", "a\nb", 5):
        assert C.sidebar_label_problem(bad), repr(bad)


def _sidebar_point(mod="ma"):
    return {"id": "%s:a.html/sidebar" % mod, "kind": "sidebar", "ops": list(C.OPS_BY_KIND["sidebar"])}


def test_check_ops_sidebar_relabel_and_group_move():
    pts = [_sidebar_point()]
    first = [g["key"] for g in M.load_l1()["groups"]][0]
    ok = [{"op": "relabel", "target": "ma:a.html/sidebar", "label": "好名字"},
          {"op": "move", "target": "ma:a.html/sidebar", "to": "group:" + first, "index": 0}]
    assert C._check_ops(pts, ok) == []
    assert C._check_ops(pts, [{"op": "relabel", "target": "ma:a.html/sidebar", "label": "<i>x"}])
    assert C._check_ops(pts, [{"op": "move", "target": "ma:a.html/sidebar", "to": "group:not_a_group"}])
    assert C._check_ops(pts, [{"op": "move", "target": "ma:a.html/sidebar", "to": "mb:b.html/sidebar"}]), "to 只能是群組鍵"
    assert C._check_ops(pts, [{"op": "move", "target": "ma:a.html/sidebar", "index": 1}]) == [], "群組內 move 照舊"


# ── API ──────────────────────────────────────────────────────────────────────────────
def _pick():
    for m in registry.loaded():
        for p in (m.manifest or {}).get("pages") or []:
            perm = (p.get("menu") or {}).get("perm") if isinstance(p, dict) else None
            if isinstance(p, dict) and p.get("menu") and not ({"cashier", "finance", "financial_view"} & set(perm if isinstance(perm, list) else [])):
                return m.key, p["path"], m.manifest
    pytest.skip("沒有已載入、宣告選單項的模組 ⇒ 無對象")


def _login(client, make_user, name, role, modules=None):
    u, pw = make_user(username=name, role=role, **({"modules": modules} if modules is not None else {}))[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def _on(monkeypatch, value=True):
    monkeypatch.setattr(MB, "enabled", lambda conn=None: value)


def _find(groups, key, href):
    return [it for g in groups for it in g["items"] if it["href"] == href and it.get("module") == key]


def test_setting_default_is_off_and_registered():
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as SR
    f = {x["key"]: x for x in SR.groups()["builder_menu"]["fields"]}["enabled"]
    assert f["default"] == 0 and (f["min"], f["max"]) == (0, 1)
    assert MB.enabled() is False, "預設關"


def test_preview_is_404_when_off_and_403_for_non_superadmin(client, make_user, monkeypatch):
    h_sa = _login(client, make_user, "bp1_sa", "superadmin")
    h_ad = _login(client, make_user, "bp1_ad", "admin")
    _on(monkeypatch, False)
    assert client.post("/api/platform/menu/preview", json={"ops": []}, headers=h_sa).status_code == 404
    _on(monkeypatch, True)
    assert client.post("/api/platform/menu/preview", json={"ops": []}, headers=h_ad).status_code == 403
    assert client.post("/api/platform/menu/preview", json={"ops": []}).status_code in (401, 403)
    assert client.post("/api/platform/menu/preview", json={"ops": []}, headers=h_sa).status_code == 200


def test_preview_applies_draft_without_writing_and_masks_by_user(client, make_user, monkeypatch):
    import db
    key, href, man = _pick()
    h_sa = _login(client, make_user, "bp1_sa2", "superadmin")
    _login(client, make_user, "bp1_none", "admin", modules=[])
    _on(monkeypatch, True)
    tgt = "%s:%s/sidebar" % (key, href)
    op = {"op": "relabel", "target": tgt, "label": "改名後"}

    def count():
        c = db.get_db()
        try:
            return c.execute("SELECT COUNT(*) FROM ui_definitions").fetchone()[0]
        finally:
            c.close()
    n0 = count()
    r = client.post("/api/platform/menu/preview", json={"ops": [op]}, headers=h_sa)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["opsHash"] == MB.ops_hash([op])
    assert _find(d["current"], key, href) and _find(d["preview"], key, href)[0]["label"] == "改名後"
    assert _find(d["current"], key, href)[0]["label"] != "改名後"
    assert _find(d["preview"], key, href)[0]["href"] == href
    assert count() == n0, "預覽不寫任何資料"
    # 遮蔽：以沒有任何模組權限的 admin 預覽 ⇒ 兩份都不含需要權限的項目，對這項的操作被略過
    perm = next(p for p in man["pages"] if p.get("path") == href)["menu"].get("perm")
    if isinstance(perm, list) and perm:
        r2 = client.post("/api/platform/menu/preview",
                         json={"user": "bp1_none", "ops": [dict(op, label="偷看")]}, headers=h_sa)
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert not _find(d2["current"], key, href) and not _find(d2["preview"], key, href) and len(d2["skipped"]) == 1
        assert "偷看" not in json.dumps(d2["current"] + d2["preview"], ensure_ascii=False)


def test_preview_rejects_bad_ops(client, make_user, monkeypatch):
    key, href, _man = _pick()
    h_sa = _login(client, make_user, "bp1_sa3", "superadmin")
    _on(monkeypatch, True)
    tgt = "%s:%s/sidebar" % (key, href)
    for bad in ([{"op": "relabel", "target": tgt, "label": "<script>"}],
                [{"op": "move", "target": tgt, "to": "group:nope"}],
                [{"op": "hide", "target": "zz:none.html/sidebar"}],
                [{"op": "hide", "target": tgt + "x"}],
                "not-a-list"):
        r = client.post("/api/platform/menu/preview", json={"ops": bad}, headers=h_sa)
        assert r.status_code == 422, (bad, r.status_code, r.text)


def test_menu_runtime_flag_off_ignores_relabel_and_on_applies_it(client, make_user, monkeypatch):
    """(b) 已發布的改名：開 ⇒ 套用且 href／denied 不變；關 ⇒ 不套用（資料保留）、回應不多鍵。"""
    import db
    from core import definitions as D
    key, href, _man = _pick()
    h_sa = _login(client, make_user, "bp1_sa4", "superadmin")
    _on(monkeypatch, True)
    tgt = "%s:%s/sidebar" % (key, href)
    conn = db.get_db()
    try:
        D.save_draft(conn, "layout", "module:%s" % key, "role:superadmin", {"ops": [{"op": "relabel", "target": tgt, "label": "新名"}]}, user="t")
        D.publish(conn, "layout", "module:%s" % key, "role:superadmin", note="t", user="t")
    finally:
        conn.close()
    on = client.get("/api/platform/menu", headers=h_sa).json()
    item = _find(on["layout"]["groups"], key, href)
    assert item and item[0]["label"] == "新名" and item[0]["href"] == href and on.get("builderMenu") is True
    _on(monkeypatch, False)
    off = client.get("/api/platform/menu", headers=h_sa).json()
    item = _find(off["layout"]["groups"], key, href)
    assert item and item[0]["label"] != "新名" and "builderMenu" not in off
    assert off["denied"] == on["denied"] and off["groups"] == on["groups"]


def test_publish_validation_rejects_builder_ops_when_off(client, make_user, monkeypatch):
    key, href, _man = _pick()
    h_sa = _login(client, make_user, "bp1_sa5", "superadmin")
    body = {"body": {"ops": [{"op": "relabel", "target": "%s:%s/sidebar" % (key, href), "label": "新名"}]}}
    url = "/api/definitions/layout/module:%s/draft?scope=company" % key
    _on(monkeypatch, False)
    r = client.put(url, json=body, headers=h_sa)
    assert MB.OFF_REASON in json.dumps(r.json(), ensure_ascii=False), r.text
    _on(monkeypatch, True)
    r = client.put(url, json=body, headers=h_sa)
    assert r.status_code == 200 and r.json()["problems"] == [], r.text
