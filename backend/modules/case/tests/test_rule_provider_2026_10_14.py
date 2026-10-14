# -*- coding: utf-8 -*-
"""BP-2 R4：案件的標示規則紀錄提供者（modules/case/rule_provider.py）。
- 逐筆讀取權限：擁有者只看到自己的案件、admin 看全部、別的業務看不到（看不到＝不存在）；`ids` 只是再縮小，不會放寬
- 金額欄位只在 `quote_money_visible` 為真時才出現：持 cashier 模組的工程師看得到案件列、但拿不到金額值（縱深防禦，L1 目錄還會再裁一次）
- 自訂欄位只讀已存 JSON、純量、鍵合法、以 cf_ 開頭；壞 JSON 不丟例外
- 唯讀（資料列數與內容不變；原始碼沒有寫入語句）、參數化（含引號的 id 不會變成 SQL）
- 旗標關：規則路由 404，提供者完全不被呼叫；已登記在 ModuleSpec（("rules.entity","case")）"""
import json
import re
from pathlib import Path

import pytest

import db
from core import registry
from modules.case import rule_provider as RP


def _user(make_user, name, role, modules=None):
    u, p = make_user(username=name, role=role, **({"modules": modules} if modules is not None else {}))[:2]
    conn = db.get_db()
    try:
        return dict(conn.execute("SELECT * FROM users WHERE username=?", (u,)).fetchone())
    finally:
        conn.close()


def _add(quote_no, owner, *, net=12.5, direct=20.0, total=1050, status="草稿", cf=None, raw=None, updated="2026-10-14 10:00:00"):
    data = raw if raw is not None else json.dumps({"caseRecord": {"customFields": cf or {}}}, ensure_ascii=False)
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, direct_margin_pct, net_margin_pct, "
                     "sales_person_id, sales_person, data_json, updated_at, deal_tag, settle_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (quote_no, status, "客戶甲", "專案" + quote_no, total, direct, net, owner["id"], owner["display_name"] or owner["username"], data, updated, "", ""))
        conn.commit()
    finally:
        conn.close()


def _provide(user, ids=None, limit=200):
    conn = db.get_db()
    try:
        return RP.provide(conn, user, ids, limit)
    finally:
        conn.close()


@pytest.fixture()
def world(client, make_user):
    a = _user(make_user, "t62p_sales_a", "sales")
    b = _user(make_user, "t62p_sales_b", "sales")
    adm = _user(make_user, "t62p_admin", "admin")
    cashier = _user(make_user, "t62p_cashier", "engineer", modules=["cashier"])
    _add("Q-001", a, net=5.0, updated="2026-10-14 09:00:00", cf={"site": "北廠", "ok": True, "lvl": "A"})
    _add("Q-002", a, net=40.0, updated="2026-10-14 11:00:00")
    _add("Q-003", b, net=8.0, updated="2026-10-14 10:00:00")
    return {"a": a, "b": b, "admin": adm, "cashier": cashier}


def test_row_level_read_permission(world):
    w = world
    assert [r["id"] for r in _provide(w["a"])] == ["Q-002", "Q-001"]                          # 擁有者只看到自己的，最近更新的在前
    assert [r["id"] for r in _provide(w["b"])] == ["Q-003"]
    assert sorted(r["id"] for r in _provide(w["admin"])) == ["Q-001", "Q-002", "Q-003"]       # admin 直通
    assert _provide(w["a"], ids=["Q-003"]) == []                                              # 指名別人的案件也拿不到
    assert [r["id"] for r in _provide(w["admin"], ids=["Q-003", "nope"])] == ["Q-003"]
    assert [r["id"] for r in _provide(w["admin"], limit=1)] == ["Q-002"]


def test_money_values_only_for_quote_money_viewers(world):
    sales = {r["id"]: r for r in _provide(world["a"])}
    assert sales["Q-001"]["values"]["netMarginPct"] == 5.0 and sales["Q-001"]["values"]["total"] == 1050
    cash = {r["id"]: r for r in _provide(world["cashier"])}
    assert sorted(cash) == ["Q-001", "Q-002", "Q-003"]                                         # 持 cashier 讀得到案件列
    for r in cash.values():
        assert not ({"netMarginPct", "directMarginPct", "total"} & set(r["values"]))           # 但拿不到任何金額值
        assert r["values"]["status"] == "草稿"
    assert "5.0" not in json.dumps(cash["Q-001"])                                              # 位元組層級也找不到毛利數字


def test_custom_fields_are_scalar_cf_keys_only(client, make_user):
    a = _user(make_user, "t62p_cf", "sales")
    _add("Q-CF", a, cf={"site": "北廠", "ok": True, "n": 3, "bad key": "x", "nested": {"a": 1}, "list": [1], "9x": "y", "none": None})
    v = _provide(a)[0]["values"]
    assert v["cf_site"] == "北廠" and v["cf_ok"] is True and v["cf_n"] == 3 and v["cf_none"] is None
    assert not [k for k in v if k in ("cf_bad key", "cf_nested", "cf_list", "cf_9x")]
    _add("Q-BAD", a, raw="{not json", updated="2026-10-14 12:00:00")
    _add("Q-NOCR", a, raw=json.dumps({"caseRecord": "x"}), updated="2026-10-14 12:30:00")
    got = {r["id"]: r["values"] for r in _provide(a)}
    assert not [k for k in got["Q-BAD"] if k.startswith("cf_")] and not [k for k in got["Q-NOCR"] if k.startswith("cf_")]


def test_label_and_ids_are_plain_strings(world):
    r = _provide(world["a"])[0]
    assert r["id"] == "Q-002" and "專案Q-002" in r["label"] and isinstance(r["values"], dict)


def test_it_is_read_only_and_parameterized(world):
    conn = db.get_db()
    try:
        before = [tuple(x) for x in conn.execute("SELECT * FROM quotations ORDER BY id").fetchall()]
    finally:
        conn.close()
    _provide(world["admin"])
    assert _provide(world["admin"], ids=["Q-001' OR '1'='1", "x\"; DROP TABLE quotations; --"]) == []
    conn = db.get_db()
    try:
        assert [tuple(x) for x in conn.execute("SELECT * FROM quotations ORDER BY id").fetchall()] == before
    finally:
        conn.close()
    src = Path(RP.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|REPLACE)\b", re.sub(r'"""[\s\S]*?"""', "", src))      # 去掉說明文字後沒有任何寫入語句
    assert "commit" not in src


def test_it_is_declared_in_the_module_spec():
    from modules.case import MODULE
    assert MODULE.providers[("rules.entity", "case")] is RP.provide


def test_flag_off_routes_never_call_the_provider(client, make_user, monkeypatch):
    called = []

    def boom(*a, **k):
        called.append(1)
        raise AssertionError("旗標關時提供者不該被呼叫")
    real = registry.providers
    monkeypatch.setattr(registry, "providers", lambda cap: dict(real(cap), case=boom) if cap == "rules.entity" else real(cap))
    u, p = make_user(username="t62p_sa", role="superadmin")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    for method, url, kw in (("get", "/api/rules/config", {}), ("get", "/api/rules/summary?entity=case", {}),
                            ("get", "/api/rules/marks?entity=case&ids=Q-001", {}),
                            ("post", "/api/rules/preview", {"json": {"entity": "case", "body": {"rules": []}}})):
        assert getattr(client, method)(url, headers=h, **kw).status_code == 404
    assert called == []
