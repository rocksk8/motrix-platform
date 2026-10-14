# -*- coding: utf-8 -*-
"""BP-2 R4：案件的標示規則紀錄提供者（modules/case/rule_provider.py）。
- 逐筆讀取權限：擁有者只看到自己的案件、admin 看全部、別的業務看不到（看不到＝不存在）；`ids` 只是再縮小，不會放寬
- 金額欄位只在 `quote_money_visible` 為真時才出現：讀得到案件列但沒有報價金額權限的人（工程師）拿不到金額值（縱深防禦，L1 目錄還會再裁一次）
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


def _provide(user, ids=None, limit=200, fields=None):
    conn = db.get_db()
    try:
        return RP.provide(conn, user, ids, limit, fields)
    finally:
        conn.close()


@pytest.fixture()
def world(client, make_user):
    a = _user(make_user, "t62p_sales_a", "sales")
    b = _user(make_user, "t62p_sales_b", "sales")
    adm = _user(make_user, "t62p_admin", "admin")
    # 讀得到案件列、但沒有報價金額權限的人：工程師擁有（業務欄指向他）的案件。⚠ 不能再用『只勾出納模組的一般帳號』——第42班起出納/財務能力由財務角色決定，
    # conftest 會把明確勾 cashier 的一般帳號換成 finance 角色（本來就看得到報價金額），惰性勾選也讀不到別人的案件。
    cashier = _user(make_user, "t62p_eng", "engineer")
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
    _add("Q-ENG", world["cashier"], net=7.0, updated="2026-10-14 08:00:00")                     # 只在這題加一列，不影響其他題的列數
    eng = {r["id"]: r for r in _provide(world["cashier"])}
    assert sorted(eng) == ["Q-ENG"]                                                            # 工程師只讀得到自己的案件列
    for r in eng.values():
        assert not ({"netMarginPct", "directMarginPct", "total", "projectMarginPct"} & set(r["values"]))      # 但拿不到任何金額值
        assert r["values"]["status"] == "草稿"
    assert "7.0" not in json.dumps(eng["Q-ENG"])                                               # 位元組層級也找不到毛利數字
    fin = {r["id"]: r for r in _provide(world["admin"])}["Q-ENG"]   # 對照：admin 看同一列有金額（證明上面是被遮蔽，不是欄位本來就沒有）
    assert fin["values"]["netMarginPct"] == 7.0 and fin["values"]["total"] == 1050


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


def test_it_is_read_only_and_parameterized(client, world):
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


def _add_raw(quote_no, owner, deal_tag, settle, data_json, updated="2026-10-14 13:00:00"):
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, direct_margin_pct, net_margin_pct, sales_person_id, "
                     "sales_person, data_json, updated_at, deal_tag, settle_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (quote_no, "草稿", "客戶", "專案", 100, 100, 1, 1, owner["id"], owner["username"], data_json, updated, deal_tag, settle))
        conn.commit()
    finally:
        conn.close()


def test_legacy_rows_get_deal_tag_and_settle_status_from_data_json(client, make_user):
    """舊資料（v6 之前）欄位是空的、值還在 data_json：與 SQL_DEAL_TAG／SQL_SETTLE_STATUS 同語意（直接讀欄位會把已結案的舊案件當成未結案）。"""
    a = _user(make_user, "t62p_legacy", "sales")
    _add_raw("L-OLD", a, "", "", json.dumps({"dealTag": "已結案", "settlement": {"status": "已完結"}}, ensure_ascii=False))
    _add_raw("L-NEW", a, "已成案", "進行中", json.dumps({"dealTag": "已結案", "settlement": {"status": "已完結"}}, ensure_ascii=False))     # 欄位有值 ⇒ 以欄位為準
    _add_raw("L-NONE", a, None, None, "{}")
    _add_raw("L-BAD", a, "", "", "{not json")
    got = {r["id"]: r["values"] for r in _provide(a)}
    assert (got["L-OLD"]["dealTag"], got["L-OLD"]["settleStatus"]) == ("已結案", "已完結")
    assert (got["L-NEW"]["dealTag"], got["L-NEW"]["settleStatus"]) == ("已成案", "進行中")
    assert (got["L-NONE"]["dealTag"], got["L-NONE"]["settleStatus"]) == ("", "")
    assert (got["L-BAD"]["dealTag"], got["L-BAD"]["settleStatus"]) == ("", "")                     # 壞 JSON 只影響這一列，不丟例外


def test_deeply_nested_json_does_not_break_the_request(client, make_user):
    a = _user(make_user, "t62p_deep", "sales")
    _add_raw("D-1", a, "已成案", "x", "[" * 60000 + "]" * 60000, updated="2026-10-14 14:00:00")
    _add_raw("D-2", a, "", "", "{" * 60000, updated="2026-10-14 13:30:00")
    rows = _provide(a)
    assert {r["id"] for r in rows} == {"D-1", "D-2"}                                              # 過深的 JSON（RecursionError）→ 該列照常回來
    assert all(r["values"]["status"] == "草稿" for r in rows)


def test_data_json_is_only_parsed_when_the_caller_needs_it(client, make_user, monkeypatch):
    a = _user(make_user, "t62p_lazy", "sales")
    _add_raw("P-1", a, "已成案", "進行中", "{}")
    n = []
    real = RP._parse
    monkeypatch.setattr(RP, "_parse", lambda raw: (n.append(1), real(raw))[1])
    _provide(a, fields={"status", "total"})
    assert n == []                                                                                 # 沒有人要 cf_／專案毛利，欄位也都有值 ⇒ 完全不解析
    _provide(a, fields={"cf_site"})
    assert n                                                                                       # 要自訂欄位 ⇒ 才解析
    n.clear()
    _add_raw("P-2", a, "", "進行中", "{}", updated="2026-10-14 15:00:00")
    _provide(a, fields={"status"})
    assert n                                                                                       # 舊資料要靠 data_json 補結案標籤 ⇒ 仍會解析

