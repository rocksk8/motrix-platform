# -*- coding: utf-8 -*-
"""G1：費用類別 → 科目對應（apply_category_map）、費用類別清單、遷移 0003、API 權限（規則 B：只有最高管理者寫）。"""
import copy

import pytest

import db
from modules.accounting.ledger import category_map as CM
from modules.accounting.ledger import roles as ROLES


@pytest.fixture
def conn(client):
    c = db.get_db()
    ROLES.ensure_meta(c)
    ROLES.ensure_default_roles(c)
    c.commit()
    yield c
    c.close()


def _ev(lines, case_no="", **kw):
    e = {"event_code": "E11", "case_no": case_no, "lines": lines, "meta": {}}
    e.update(kw)
    return e


def _d(amount, **kw):
    ln = {"role": "COST_PROJECT", "side": "D", "amount": amount, "memo": "x"}
    ln.update(kw)
    return ln


def _c(amount):
    return {"role": "AP", "side": "C", "amount": amount, "memo": "x"}


def test_migration_0003_idempotent_and_additive(conn):
    import importlib
    m = importlib.import_module("modules.accounting.migrations.0003_dims_and_categories")
    m.up(conn)
    m.up(conn)                                                                     # 再跑一次不報錯
    cols = [r[1] for r in conn.execute("PRAGMA table_info(voucher_lines)")]
    assert cols.count("dim_json") == 1
    assert conn.execute("SELECT COUNT(*) FROM gl_dimensions").fetchone()[0] >= 0
    assert conn.execute("SELECT COUNT(*) FROM expense_categories").fetchone()[0] >= 0


def test_unmapped_caseless_goes_to_exp_other_never_cost_project(conn):
    e = CM.apply_category_map(conn, _ev([_d(1000, category="nomap"), _c(1000)]))
    assert e["lines"][0]["role"] == "EXP_OTHER"
    assert e["meta"]["category_unmapped"] == ["nomap"]


def test_unmapped_with_case_goes_to_cost_project(conn):
    e = CM.apply_category_map(conn, _ev([_d(1000, category="nomap", role="EXP_OTHER"), _c(1000)], case_no="C-1"))
    assert e["lines"][0]["role"] == "COST_PROJECT"


def test_map_priority_over_default(conn):
    CM.upsert_map(conn, "travel", account_code="6134")
    e = CM.apply_category_map(conn, _ev([_d(500, category="travel"), _c(500)], case_no="C-1"))
    assert e["lines"][0]["account_code"] == "6134"
    assert "category_unmapped" not in e["meta"]


def test_invoice_tax_split_and_total_balanced(conn):
    CM.upsert_map(conn, "travel", account_code="6134")
    e = CM.apply_category_map(conn, _ev([_d(1050, category="travel", tax=50, doc_type="invoice"), _c(1050)]))
    assert [(l["role"], l["amount"]) for l in e["lines"] if l["side"] == "D"] == [("COST_PROJECT", 1000), ("INPUT_TAX", 50)] or         [l["amount"] for l in e["lines"] if l["side"] == "D"] == [1000, 50]
    assert sum(l["amount"] for l in e["lines"] if l["side"] == "D") == 1050
    assert e["tax_code"] == "IN-5"
    assert [l for l in e["lines"] if l["role"] == "INPUT_TAX"][0]["tax_code"] == "IN-5"


@pytest.mark.parametrize("doc_type,nondeductible", [("receipt", False), ("foreign", False), ("invoice", True)])
def test_tax_folded_into_cost(conn, doc_type, nondeductible):
    CM.upsert_map(conn, "gift", account_code="6134", nondeductible=nondeductible)
    e = CM.apply_category_map(conn, _ev([_d(1050, category="gift", tax=50, doc_type=doc_type), _c(1050)]))
    assert not [l for l in e["lines"] if l["role"] == "INPUT_TAX"]
    assert [l["amount"] for l in e["lines"] if l["side"] == "D"] == [1050]
    assert "tax_code" not in e
    assert e["meta"]["tax_folded_into_cost"] == ["gift"]


def test_no_tax_field_full_amount(conn):
    e = CM.apply_category_map(conn, _ev([_d(1050, category="x"), _c(1050)]))
    assert [l["amount"] for l in e["lines"] if l["side"] == "D"] == [1050]


def test_legacy_event_unchanged(conn):
    ev = _ev([_d(1000), _c(1000)], case_no="C-1")
    before = copy.deepcopy(ev)
    assert CM.apply_category_map(conn, ev) == before


def test_upsert_map_refuses_bad_account_and_role(conn):
    with pytest.raises(CM.CategoryError):
        CM.upsert_map(conn, "a", account_code="9999999")
    with pytest.raises(CM.CategoryError):
        CM.upsert_map(conn, "a", role="NOPE")
    with pytest.raises(CM.CategoryError):
        CM.upsert_map(conn, "a")
    unpost = conn.execute("SELECT code FROM gl_account_meta WHERE postable=0 LIMIT 1").fetchone()
    if unpost:
        with pytest.raises(CM.CategoryError):
            CM.upsert_map(conn, "a", account_code=unpost[0])


def test_category_code_validation_and_coverage(conn):
    with pytest.raises(CM.CategoryError):
        CM.upsert_category(conn, "有中文", "x")
    with pytest.raises(CM.CategoryError):
        CM.upsert_category(conn, "ok", "")
    CM.upsert_category(conn, "meal", "餐費", "taxable", 1)
    CM.upsert_category(conn, "old", "停用", "", 2, active=False)
    CM.upsert_map(conn, "meal", account_code="6134")
    cov = {c["code"]: c for c in CM.coverage(conn)}
    assert cov["meal"]["mapped"] is True and "old" not in cov
    CM.upsert_category(conn, "fare", "交通", "", 3)
    assert {c["code"]: c for c in CM.coverage(conn)}["fare"]["mapped"] is False


def _login(client, make_user, name, role):
    u, p = make_user(username="%s%d" % (name, id(client)), role=role)
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def test_api_rule_b_only_superadmin_writes(client, make_user, conn):
    sa = _login(client, make_user, "g1sa", "superadmin")
    fin = _login(client, make_user, "g1fin", "admin")
    body = {"category": "travel", "account_code": "6134"}
    assert client.put("/api/ledger/category-map", json=body, headers=fin).status_code == 403
    assert client.put("/api/ledger/expense-categories", json={"code": "travel", "name": "差旅"}, headers=fin).status_code == 403
    assert client.delete("/api/ledger/category-map/travel", headers=fin).status_code == 403
    assert client.put("/api/ledger/expense-categories", json={"code": "travel", "name": "差旅"}, headers=sa).status_code == 200
    assert client.put("/api/ledger/category-map", json=body, headers=sa).status_code == 200
    assert client.put("/api/ledger/category-map", json={"category": "travel", "account_code": "0000"}, headers=sa).status_code == 400
    got = client.get("/api/ledger/category-map", headers=sa).json()
    assert got["map"][0]["account_code"] == "6134" and got["coverage"][0]["mapped"] is True
    assert client.delete("/api/ledger/category-map/travel", headers=sa).status_code == 200
    assert client.delete("/api/ledger/category-map/travel", headers=sa).status_code == 404


def test_provider_lists_active_categories_only(conn):
    from modules.accounting.api.ledger_category_map import provide_categories
    CM.upsert_category(conn, "a1", "甲", "taxable", 1)
    CM.upsert_category(conn, "a2", "乙", "", 2, active=False)
    conn.commit()
    assert [c["code"] for c in provide_categories(conn)] == ["a1"]
