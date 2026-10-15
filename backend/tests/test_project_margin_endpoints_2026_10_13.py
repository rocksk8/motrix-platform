# -*- coding: utf-8 -*-
"""報價單「專案毛利%」端點題（T57；設計 §1.1／§6）：逐面可見度（5 角色）、詳情重算不信用戶端、不回寫、設定端點。
建單會觸發自動 PDF（Edge）——需經 1c 同意才跑。"""
import json

import pytest

import db

ITEMS = [{"id": "a", "type": "item", "description": "品 a", "qty": 1, "unit": "式", "cost": 600, "margin": 0.3, "unitPrice": 1000, "amount": 1000},
         {"id": "b", "type": "item", "description": "品 b", "qty": 1, "unit": "式", "cost": 1500, "margin": 0.3, "unitPrice": 2000, "amount": 2000}]
EXPECT = 30.0            # (3000 − 2100) ÷ 3000


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _hdr(client, make_user, name, role, **kw):
    u, p = make_user(username=name, role=role, **kw)
    return _login(client, u, p)


def _make(client, h, owner):
    body = {"customerName": "毛利客", "projectName": "毛利案", "salesPerson": owner, "salesPersonUsername": owner, "quoteDate": "2026-10-13",
            "taxRate": 5, "items": json.loads(json.dumps(ITEMS)),
            # 表單送來的合計（legacy 管銷口徑下伺服器不重算 tot，SQL 欄 pretax／direct_margin_pct 也由此而來）
            "tot": {"subtotal": 3000, "pretax": 3000, "tax": 150, "total": 3150, "totalCost": 2100, "inputVat": 105,
                    "directProfit": 795, "directMarginPct": 26.5, "adminCost": 300, "charityDonation": 8, "totalIndirect": 308,
                    "netProfit": 487, "netMarginPct": 16.2}}
    r = client.post("/api/quotations", json={"status": "草稿", "data": body, "created_by": owner}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["quote_no"]


def _walk_has_key(obj, needle):
    if isinstance(obj, dict):
        return any(needle in str(k) or _walk_has_key(v, needle) for k, v in obj.items())
    if isinstance(obj, list):
        return any(_walk_has_key(v, needle) for v in obj)
    return False


@pytest.fixture
def world(client, make_user):
    owner = _hdr(client, make_user, "pm_sales", "sales")
    no = _make(client, owner, "pm_sales")
    return {"no": no, "sales": owner,
            "admin": _hdr(client, make_user, "pm_admin", "admin"),
            "finance": _hdr(client, make_user, "pm_fin", "finance"),
            "cashier": _hdr(client, make_user, "pm_cash", "viewer", modules=["cashier"]),          # 相容規則：持出納勾選者成為財務角色
            "engineer": _hdr(client, make_user, "pm_eng", "engineer"),
            "other_sales": _hdr(client, make_user, "pm_sales2", "sales")}


def test_detail_visibility_follows_direct_margin_pct(client, world):
    for who in ("sales", "admin", "finance", "cashier"):
        r = client.get("/api/quotations/%s" % world["no"], headers=world[who])
        assert r.status_code == 200, (who, r.status_code)
        d = r.json()
        has_dm = isinstance(d["data"].get("tot"), dict) and "directMarginPct" in d["data"]["tot"]
        assert has_dm, who
        assert d["project_margin_pct"] == EXPECT, who
    for who in ("engineer", "other_sales"):
        r = client.get("/api/quotations/%s" % world["no"], headers=world[who])
        assert r.status_code in (403, 404) or "project_margin_pct" not in r.json()
        assert not _walk_has_key(r.json(), "project_margin") and not _walk_has_key(r.json(), "projectMargin")


def test_detail_value_is_recomputed_from_items_not_from_client_tot(client, world):
    cn = db.get_db()
    try:
        row = cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (world["no"],)).fetchone()
        d = json.loads(row["data_json"])
        d["tot"] = dict(d.get("tot") or {}, pretax=999999, totalCost=1)             # 資料庫裡被竄改的 tot
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), world["no"]))
        cn.commit()
    finally:
        cn.close()
    r = client.get("/api/quotations/%s" % world["no"], headers=world["admin"])
    assert r.json()["project_margin_pct"] == EXPECT


def test_list_includes_the_value_only_where_direct_margin_is_unmasked(client, world):
    r = client.get("/api/quotations", headers=world["admin"])             # 預設不附（選用欄，不多讀 data_json）
    assert r.status_code == 200
    items = r.json()["items"] if isinstance(r.json(), dict) else r.json()
    assert all("project_margin_pct" not in i for i in items)
    r = client.get("/api/quotations?include_project_margin=1", headers=world["admin"])
    assert r.status_code == 200
    items = r.json()["items"] if isinstance(r.json(), dict) else r.json()
    mine = [i for i in items if i["quote_no"] == world["no"]]
    assert mine and mine[0]["project_margin_pct"] == EXPECT and mine[0]["direct_margin_pct"] is not None
    for who in ("engineer", "other_sales"):                                # 看不到報價金額者：即使要求也沒有這個鍵
        r = client.get("/api/quotations?include_project_margin=1", headers=world[who])
        assert not _walk_has_key(r.json(), "project_margin") and "_tc" not in r.text


def test_client_supplied_values_are_not_stored(client, world):
    h = world["admin"]
    d = json.loads(client.get("/api/quotations/%s" % world["no"], headers=h).text)["data"]
    d["project_margin_pct"] = 99
    d["projectMargin"] = 98
    d["tot"]["project_margin_pct"] = 97
    r = client.put("/api/quotations/%s" % world["no"], json={"status": "草稿", "data": d}, headers=h)
    assert r.status_code == 200, r.text
    cn = db.get_db()
    try:
        raw = cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (world["no"],)).fetchone()["data_json"]
    finally:
        cn.close()
    assert "project_margin" not in raw and "projectMargin" not in raw


def test_plan_view_options_carry_the_same_function_result(client, world):
    items = json.loads(json.dumps(ITEMS))
    items[0]["altGroup"] = items[1]["altGroup"] = "G"
    h = world["admin"]
    d = json.loads(client.get("/api/quotations/%s" % world["no"], headers=h).text)["data"]
    d["items"], d["totalsByAlt"] = items, True
    assert client.put("/api/quotations/%s" % world["no"], json={"status": "草稿", "data": d}, headers=h).status_code == 200
    r = client.get("/api/quotations/%s/plan-view" % world["no"], headers=h)
    assert r.status_code == 200
    opts = {o["id"]: o for g in r.json()["groups"] for o in g["options"]}
    assert opts["a"]["projectMarginPct"] == round((1000 - 600) / 1000 * 100, 1) and opts["b"]["projectMarginPct"] == round((2000 - 1500) / 2000 * 100, 1)
    assert client.get("/api/quotations/%s/plan-view" % world["no"], headers=world["engineer"]).status_code in (403, 404)


def test_config_endpoint_requires_cost_visibility(client, world):
    r = client.get("/api/project-margin/config", headers=world["sales"])
    # approval-thresholds r1/r2 起這支端點在 warnPct 之外也回三個報價送審門檻（另有新報價單預設有效天數 defaultValidDays，T64 A，預設 30；預設＝今天寫死的 30%／30 天／0 元；同一個金額權限閘門）
    assert r.status_code == 200 and r.json() == {"warnPct": 0.0, "minItemMarginPct": 30.0, "maxValidDays": 30, "discountReviewAbove": 0, "defaultValidDays": 30}
    assert client.get("/api/project-margin/config", headers=world["admin"]).status_code == 200
    r = client.get("/api/project-margin/config", headers=world["engineer"])
    assert r.status_code == 403 and "warnPct" not in r.text                      # 最小揭露
    assert client.get("/api/project-margin/config").status_code in (401, 403)


def test_malformed_or_failing_recompute_never_turns_detail_into_500(client, world, monkeypatch):
    cn = db.get_db()
    try:
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?",
                   (json.dumps({"customerName": "壞單", "items": "oops", "tot": {"pretax": "x", "totalCost": None}, "taxRate": "abc"}), world["no"]))
        cn.commit()
    finally:
        cn.close()
    for who in ("admin", "sales", "finance", "engineer"):
        r = client.get("/api/quotations/%s" % world["no"], headers=world[who])
        assert r.status_code in (200, 403, 404), (who, r.status_code, r.text[:200])
        if r.status_code == 200 and "project_margin_pct" in r.json():
            assert r.json()["project_margin_pct"] is None
    from modules.case import profit_guard as PG

    def boom(q):
        raise ValueError("boom")
    monkeypatch.setattr(PG, "quote_project_margin", boom)
    r = client.get("/api/quotations/%s" % world["no"], headers=world["admin"])
    assert r.status_code == 200 and r.json().get("project_margin_pct") is None
    called = []
    monkeypatch.setattr(PG, "quote_project_margin", lambda q: called.append(1) or {"pct": 1})
    client.get("/api/quotations/%s" % world["no"], headers=world["engineer"])
    assert not called                                                           # 看不到報價金額的角色根本不算


def test_list_survives_pathological_stored_json_for_the_optin_column(client, world, monkeypatch):
    """過深的 JSON 會讓 json.loads 丟 RecursionError（SQLite 自己的 JSON 深度上限是 1000，真的做出來的文件會先讓基本欄位的 SQL 失敗，
    所以用標記字串讓 Python 端的解析丟 RecursionError，驗證選用欄只影響該列、不讓整個清單 500）。"""
    import json as _json
    real = _json.loads

    def flaky(s, *a, **kw):
        if isinstance(s, str) and "__RECURSE__" in s:
            raise RecursionError("maximum recursion depth exceeded")
        return real(s, *a, **kw)
    cn = db.get_db()
    try:
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", ('{"tot": {"totalCost": 1}, "x": "__RECURSE__"}', world["no"]))
        cn.commit()
    finally:
        cn.close()
    monkeypatch.setattr(_json, "loads", flaky)
    r = client.get("/api/quotations?include_project_margin=1", headers=world["admin"])
    assert r.status_code == 200, r.text[:200]
    items = r.json()["items"] if isinstance(r.json(), dict) else r.json()
    mine = [i for i in items if i["quote_no"] == world["no"]]
    assert mine and mine[0].get("project_margin_pct") is None
