# -*- coding: utf-8 -*-
"""P9 拖曳排版器的後端（CUSTOMIZATION-SPEC §3.9 排版守門、§3.10 套用）。

- layout 驗證器（P5 × P3）：發布前經 `catalog.check_layout`，只能動模組登記、且經 `layout_points` 過濾後的點；
  問題的 path 以 body 為根（`ops[i].…`），給排版器標回畫面。
- `GET /api/layout/{module}`：任何登入者讀**自己角色**的版面（角色 ＞ 公司 ＞ 程式預設）；`?role=` 只給超級管理員；
  已發布但現在不合法的操作不套用、列在 dropped。

⚙️ 反向控制：未登記的點、核心欄位的隱藏、打錯的鍵、非超級管理員預覽別的角色——每一條都有一題證明它真的擋。
"""
import json

import pytest

from core import registry
from tests.platform.test_platform_catalog import _manifest, _router

#: 合成模組（MODULE-GUIDE §7：L1 的正對照不綁特定 L2 模組）
MOD = "zz_syn"
KEY = "module:" + MOD
BASE = "/api/definitions/layout/" + KEY
P = MOD + ":zz-syn.html"
COL = P + "/list:docs/column:"


@pytest.fixture(autouse=True)
def synthetic_module(client):
    snap = registry.snapshot()
    spec = registry.ModuleSpec(key=MOD, routers=[_router()])
    registry.register(registry.LoadedModule(key=MOD, manifest=_manifest(), spec=spec))
    yield
    registry.restore(snap)


def _h(client, make_user, name, role, modules=None):
    u, p = make_user(name, "Lay-Pass-123", role=role, modules=modules)[:2]
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _publish(client, h, ops, scope="company"):
    r = client.put(BASE + "/draft", headers=h, params={"scope": scope}, json={"body": {"ops": ops}})
    assert r.status_code == 200, r.text
    r = client.post(BASE + "/publish", headers=h, params={"scope": scope}, json={"note": "t"})
    return r


def _published_rows(scope="company"):
    import db
    conn = db.get_db()
    try:
        return [json.loads(r[0]) for r in conn.execute(
            "SELECT body_json FROM ui_definitions WHERE kind='layout' AND key=? AND scope=? AND status='published' "
            "ORDER BY version", (KEY, scope)).fetchall()]
    finally:
        conn.close()


def test_layout_validator_accepts_registered_points(client, make_user):
    h = _h(client, make_user, "p9_boss", "superadmin")
    ops = [{"op": "show", "target": COL + "note"}, {"op": "relabel", "target": COL + "note", "label": "說明"},
           {"op": "reorder", "target": P + "/list:docs", "order": [COL + "amount", COL + "docNo", COL + "note"]}]
    r = _publish(client, h, ops)
    assert r.status_code == 200, r.text
    assert _published_rows() == [{"ops": ops}]


@pytest.mark.parametrize("op,path_tail", [
    ({"op": "hide", "target": COL + "noSuchField"}, "target"),                  # 未登記的點
    ({"op": "hide", "target": COL + "docNo"}, "op"),                              # 核心欄位不可隱藏
    ({"op": "relabel", "target": COL + "note", "lable": "x"}, ""),          # 打錯的鍵
    ({"op": "hide", "target": "crm:customers.html/list:x/column:y"}, "target"),  # 別的模組的點
])
def test_layout_publish_refuses_unregistered_or_disallowed_ops(client, make_user, op, path_tail):
    """反向控制：打 API 企圖排入未登記的點 ⇒ 422、問題帶位置、沒有任何發布版。"""
    h = _h(client, make_user, "p9_boss2", "superadmin")
    r = _publish(client, h, [{"op": "show", "target": COL + "note"}, op])
    assert r.status_code == 422, r.text
    paths = [p["path"] for p in r.json()["problems"]]
    assert all(p.startswith("ops[1]") for p in paths), paths
    if path_tail:
        assert "ops[1].%s" % path_tail in paths, paths
    assert _published_rows() == []


def test_layout_validator_refuses_bad_key_and_unknown_body_keys(client, make_user):
    h = _h(client, make_user, "p9_boss3", "superadmin")
    r = client.post("/api/definitions/layout/tender_radar/validate", headers=h, json={"body": {"ops": []}})
    assert r.json()["problems"] and r.json()["problems"][0]["path"] == ""
    r = client.post(BASE + "/validate", headers=h, json={"body": {"ops": [], "columns": []}})
    assert [p["path"] for p in r.json()["problems"]] == ["columns"]
    r = client.post("/api/definitions/layout/module:no_such_mod/validate", headers=h, json={"body": {"ops": []}})
    assert "未載入" in r.json()["problems"][0]["message"]


def test_effective_layout_role_then_company_then_default(client, make_user):
    boss = _h(client, make_user, "p9_boss4", "superadmin")
    admin = _h(client, make_user, "p9_admin", "admin")
    sales = _h(client, make_user, "p9_sales", "sales")
    got = client.get("/api/layout/" + MOD, headers=sales).json()
    assert got["source"] == "default" and got["ops"] == [] and got["role"] == "sales"
    ids = {p["id"] for p in got["points"]}
    assert COL + "note" in ids and P + "/form:doc/section:a" in ids

    company = [{"op": "hide", "target": COL + "note"}]
    assert _publish(client, boss, company).status_code == 200
    role_ops = [{"op": "move", "target": COL + "docNo", "index": 1}]
    assert _publish(client, boss, role_ops, scope="role:admin").status_code == 200

    a = client.get("/api/layout/" + MOD, headers=admin).json()
    s = client.get("/api/layout/" + MOD, headers=sales).json()
    assert (a["source"], a["ops"]) == ("role:admin v1", role_ops)
    assert (s["source"], s["ops"]) == ("company v1", company)          # 另一個角色看到的是公司預設


def test_effective_layout_role_preview_is_superadmin_only(client, make_user):
    boss = _h(client, make_user, "p9_boss5", "superadmin")
    sales = _h(client, make_user, "p9_sales2", "sales")
    assert _publish(client, boss, [{"op": "move", "target": COL + "docNo", "index": 1}], scope="role:admin").status_code == 200
    assert client.get("/api/layout/" + MOD, headers=boss, params={"role": "admin"}).json()["source"] == "role:admin v1"
    assert client.get("/api/layout/" + MOD, headers=sales, params={"role": "admin"}).status_code == 403
    assert client.get("/api/layout/" + MOD).status_code == 401
    assert client.get("/api/layout/no_such_mod", headers=sales).status_code == 404


def test_effective_layout_drops_ops_that_are_no_longer_valid(client, make_user):
    """已發布之後點不見了（例：模組拿掉那一欄）⇒ 那一筆不套用、列在 dropped，其他照套。"""
    import db
    sales = _h(client, make_user, "p9_sales3", "sales")
    good = {"op": "hide", "target": COL + "note"}
    gone = {"op": "hide", "target": COL + "removedLater"}
    conn = db.get_db()
    conn.execute("INSERT INTO ui_definitions (kind, key, scope, version, status, body_json, created_by, created_at) "
                 "VALUES ('layout', ?, 'company', 1, 'published', ?, 't', '2026-09-26T00:00:00')",
                 (KEY, json.dumps({"ops": [gone, good]})))
    conn.commit()
    conn.close()
    got = client.get("/api/layout/" + MOD, headers=sales).json()
    assert got["ops"] == [good]
    assert [d["index"] for d in got["dropped"]] == [0]


def test_non_superadmin_cannot_write_layout_definitions(client, make_user):
    """個人層不經定義庫：非超級管理員寫 layout 草稿／發布 ⇒ 403。"""
    admin = _h(client, make_user, "p9_admin2", "admin")
    assert client.put(BASE + "/draft", headers=admin, json={"body": {"ops": []}}).status_code == 403
    assert client.post(BASE + "/publish", headers=admin, json={}).status_code == 403
