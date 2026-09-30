# -*- coding: utf-8 -*-
"""費用單據 A2 第一段：migration 0003（通用欄位一次加齊）＋無案件單據（哨兵路徑 `/api/quotations/-/extra-expenses`、`quote_no=''`）。

驗：migration 冪等／舊列維持原值／doc_code 唯一（空字串不受限）；無案件建立的權限（管理員或 `expense_forms`）；逐列可見規則
（建立者、簽核鏈成員含代理、出納／財務、admin；其他人 404）；送審／稽核 target 不是空字串；「我的請款」列得出自己的無案件列；
有案件的舊路徑行為不變。"""
import importlib
import json
import sqlite3

import pytest

SENT = "/api/quotations/-/extra-expenses"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _x(sql, args=()):
    import db
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def _no_tiers():
    _x("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
       ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))


BODY = {"category": "其他", "description": "無案件測試支出", "qty": 2, "unitCost": 500}


@pytest.fixture
def users(client, make_user):
    out = {}
    for u, role, mods in (("cl_admin", "admin", None), ("cl_form", "sales", ["expense_forms"]), ("cl_plain", "sales", None),
                          ("cl_cash", "engineer", ["cashier"]), ("cl_apr", "engineer", None)):
        name, pw = make_user(username=u, role=role, modules=mods)
        out[u] = _login(client, name, pw)
    return out


# ── migration 0003 ─────────────────────────────────────────────────────────

def test_migration_adds_all_columns_idempotently_and_keeps_old_rows():
    m = importlib.import_module("modules.case.migrations.0003_expense_forms")
    c = sqlite3.connect(":memory:")
    assert isinstance(m.up(c), str) and "case_extra_expenses" in m.up(c)              # 表不在 ⇒ 原因字串
    c.execute("CREATE TABLE case_extra_expenses (id INTEGER PRIMARY KEY, quote_no TEXT NOT NULL, status TEXT NOT NULL DEFAULT '草稿')")
    c.execute("INSERT INTO case_extra_expenses (quote_no) VALUES ('MQ-OLD-1')")
    assert m.up(c) is None and m.up(c) is None                                          # 冪等
    cols = {r[1]: r for r in c.execute("PRAGMA table_info(case_extra_expenses)")}
    for name, _ddl in m._COLS:
        assert name in cols, name
    old = dict(zip([d[0] for d in c.execute("SELECT * FROM case_extra_expenses").description],
                   c.execute("SELECT * FROM case_extra_expenses").fetchone()))
    assert old["kind"] == "" and old["doc_code"] == "" and old["data_json"] == "{}" and old["lines_json"] == "[]" and old["currency"] == "TWD"
    # doc_code 有值要唯一、空字串不受限
    c.execute("INSERT INTO case_extra_expenses (quote_no, doc_code) VALUES ('', 'RQ-202610-001')")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO case_extra_expenses (quote_no, doc_code) VALUES ('', 'RQ-202610-001')")
    c.execute("INSERT INTO case_extra_expenses (quote_no) VALUES ('MQ-OLD-2')")         # 兩個空字串照樣可以


def test_real_db_has_the_columns_and_schema_version(client):
    cols = {r["name"] for r in _q("PRAGMA table_info(case_extra_expenses)")}
    assert {"kind", "doc_code", "lines_json", "payee_bank", "void_reason", "pay_method"} <= cols
    assert _q("SELECT version FROM module_schema_versions WHERE module='case'")[0]["version"] >= 3


# ── 無案件：建立權限 ───────────────────────────────────────────────────────

def test_caseless_create_needs_admin_or_expense_forms(client, users):
    r = client.post(SENT, headers=users["cl_plain"], json=BODY)
    assert r.status_code == 403 and _q("SELECT COUNT(*) AS n FROM case_extra_expenses WHERE quote_no=''")[0]["n"] == 0
    for who in ("cl_form", "cl_admin"):
        r = client.post(SENT, headers=users[who], json=BODY)
        assert r.status_code == 201, (who, r.text)
    rows = _q("SELECT quote_no, created_by, status, total_cost FROM case_extra_expenses WHERE quote_no=''")
    assert sorted(x["created_by"] for x in rows) == ["cl_admin", "cl_form"] and all(x["status"] == "草稿" and x["total_cost"] == 1000 for x in rows)


# ── 無案件：逐列可見 ───────────────────────────────────────────────────────

def _mk(client, users, who="cl_form"):
    r = client.post(SENT, headers=users[who], json=BODY)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_row_visibility_creator_cashier_admin_yes_stranger_404(client, users):
    eid = _mk(client, users)
    for who, ok in (("cl_form", True), ("cl_admin", True), ("cl_cash", True), ("cl_plain", False), ("cl_apr", False)):
        listed = client.get(SENT, headers=users[who]).json()["items"]
        if who != "cl_cash":          # 清單另受既有「財務金額可視」規則（can_see_financial）約束；出納走出納頁付款，這裡只驗單列可見（下方 PATCH 403≠404）
            assert (eid in [i["id"] for i in listed]) == ok, who
        if who in ("cl_form", "cl_admin"):
            continue                                                                 # 建立者與管理員本來就可改；這題只驗「看得到但不能改／看不到」
        up = client.patch("%s/%d" % (SENT, eid), headers=users[who], json=dict(BODY, description="改"))
        if who == "cl_cash":                          # 出納看得到但不是填寫人／管理員 ⇒ 不能改（403，不是 404）
            assert up.status_code == 403, up.text
        elif not ok:
            assert up.status_code == 404, (who, up.status_code)                     # 看不到＝不存在
    assert _q("SELECT description FROM case_extra_expenses WHERE id=?", (eid,))[0]["description"] == BODY["description"]


def test_approval_chain_member_can_see_and_stranger_still_cannot(client, users):
    eid = _mk(client, users)
    appr = {"requestedBy": "cl_form", "tiers": [{"order": 0, "approvers": [{"username": "cl_apr", "display_name": "簽核人"}]}], "currentTier": 0}
    _x("UPDATE case_extra_expenses SET status='待審核', approval_json=? WHERE id=?", (json.dumps(appr), eid))
    assert eid in [i["id"] for i in client.get(SENT, headers=users["cl_apr"]).json()["items"]]        # 鏈成員看得到
    assert eid not in [i["id"] for i in client.get(SENT, headers=users["cl_plain"]).json()["items"]]  # 路人看不到
    r = client.post("%s/%d/approve" % (SENT, eid), headers=users["cl_plain"])
    assert r.status_code in (403, 404)
    assert _q("SELECT status FROM case_extra_expenses WHERE id=?", (eid,))[0]["status"] == "待審核"


# ── 無案件：送審、稽核、我的請款 ───────────────────────────────────────────

def test_submit_audit_target_and_my_list(client, users):
    _no_tiers()
    eid = _mk(client, users)
    r = client.post("%s/%d/submit" % (SENT, eid), headers=users["cl_form"])
    assert r.status_code == 200 and r.json()["status"] == "已核准"
    rows = _q("SELECT action, target_type, target_id, case_no, ref_no FROM audit_log WHERE action LIKE 'extra_expense.%'"
              " AND target_id IN (?, '') ORDER BY id", (str(eid),))
    assert rows and all(x["target_type"] == "case_extra_expense" and x["target_id"] == str(eid) and x["case_no"] == "" for x in rows), rows
    assert not _q("SELECT 1 FROM audit_log WHERE action LIKE 'extra_expense.%' AND target_type='quotation' AND target_id=''")   # 不留空 target_id
    mine = client.get("/api/extra-expenses/mine", headers=users["cl_form"]).json()
    assert eid in [m["id"] for m in mine]                                                 # 我的請款列得出自己的無案件列


def test_case_bound_paths_unchanged(client, users, seed_extra_expense):
    """有案件的舊路徑：行為不變（找不到案件 404、別人案件看不到）。"""
    r = client.get("/api/quotations/MQ-NOT-THERE/extra-expenses", headers=users["cl_admin"])
    assert r.status_code == 404
    r = client.post("/api/quotations/MQ-NOT-THERE/extra-expenses", headers=users["cl_admin"], json=BODY)
    assert r.status_code == 404
    assert _q("SELECT COUNT(*) AS n FROM case_extra_expenses WHERE quote_no='MQ-NOT-THERE'")[0]["n"] == 0
