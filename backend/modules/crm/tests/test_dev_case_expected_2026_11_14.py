# -*- coding: utf-8 -*-
"""業務開發「預估金額／預計成交日」（T86 #17，PM 裁示 B：固定兩欄；crm 模組 migration 0005＝schema v5）。

涵蓋：migration（表不在回原因、冪等、舊列為 NULL 而不是 0、已有的欄位不動、從 v4 狀態升級）；
API（建立／編輯／詳情／清單回傳；驗證 400；沒帶＝維持、帶 null／空字串＝清空）；金額可見性（沒有 can_see_financial ⇒ 金額 null、不能寫非空、帶 null 不清原值）；
漏斗合計端點（只算看得到的案件、排除已刪除、依狀態分組、沒有金額權限時不給金額）。
"""
import json
import sqlite3

import pytest


def _login(client, make_user, username, role="sales"):
    name, pw = make_user(username=username, role=role, modules=["dev_crm"])
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _boss(client, make_user, username="ex_boss"):
    return _login(client, make_user, username, role="superadmin")


def _row(cid):
    import db
    c = db.get_db()
    try:
        return dict(c.execute("SELECT * FROM dev_cases WHERE id=?", (cid,)).fetchone())
    finally:
        c.close()


def _mk(client, h, name="預估測試案", **extra):
    r = client.post("/api/dev-cases", headers=h, json={"case_name": name, "customer_name": "客戶甲", **extra})
    assert r.status_code == 201, r.text
    return r.json()


# ── migration ──────────────────────────────────────────────────────────────

def _m():
    import importlib
    return importlib.import_module("modules.crm.migrations.0005_dev_case_expected")


def test_migration_adds_two_nullable_columns_idempotently_and_reports_missing_table():
    m = _m()
    c = sqlite3.connect(":memory:")
    assert isinstance(m.up(c), str) and "dev_cases" in m.up(c)                           # 表不在 ⇒ 原因字串（未完成，不猜）
    c.execute("CREATE TABLE dev_cases (id INTEGER PRIMARY KEY, case_name TEXT)")
    c.execute("INSERT INTO dev_cases (case_name) VALUES ('舊案')")
    assert m.up(c) is None and m.up(c) is None                                           # 冪等
    cols = {r[1]: r for r in c.execute("PRAGMA table_info(dev_cases)")}
    assert cols["expected_amount"][2].upper() == "INTEGER" and cols["expected_amount"][3] == 0
    assert cols["expected_close_date"][2].upper() == "TEXT" and cols["expected_close_date"][3] == 0
    assert c.execute("SELECT expected_amount, expected_close_date FROM dev_cases").fetchone() == (None, None)   # 舊列＝沒填（不是 0）


def test_migration_keeps_existing_values_when_columns_already_there():
    m = _m()
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE dev_cases (id INTEGER PRIMARY KEY, case_name TEXT, expected_amount INTEGER, expected_close_date TEXT)")
    c.execute("INSERT INTO dev_cases VALUES (1, 'x', 123, '2026-12-01')")
    assert m.up(c) is None
    assert c.execute("SELECT expected_amount, expected_close_date FROM dev_cases").fetchone() == (123, "2026-12-01")


def test_upgrade_from_v4_shaped_table_keeps_rows():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE dev_cases (id INTEGER PRIMARY KEY, case_name TEXT, referrer TEXT NOT NULL DEFAULT '')")
    c.execute("INSERT INTO dev_cases (case_name, referrer) VALUES ('升級前的案件', '王大哥')")
    assert _m().up(c) is None
    assert c.execute("SELECT case_name, referrer, expected_amount, expected_close_date FROM dev_cases").fetchone() == ("升級前的案件", "王大哥", None, None)


def test_registered_as_crm_schema_v5_and_fresh_db_has_columns(client):
    import db
    from modules import crm
    assert [v for v, _fn in crm.MODULE.migrations] == [1, 2, 3, 4, 5]
    c = db.get_db()
    try:
        assert c.execute("SELECT version FROM module_schema_versions WHERE module='crm'").fetchone()[0] == 5
        assert {"expected_amount", "expected_close_date"} <= {r[1] for r in c.execute("PRAGMA table_info(dev_cases)")}
    finally:
        c.close()


# ── API：寫入與回傳 ─────────────────────────────────────────────────────────

def test_create_edit_detail_list_roundtrip_for_financial_user(client, make_user):
    h = _boss(client, make_user)
    c = _mk(client, h, expectedAmount=1200000, expectedCloseDate="2026-12-31")
    assert c["expectedAmount"] == 1200000 and c["expectedCloseDate"] == "2026-12-31" and c["expectedAmountVisible"] is True
    r = _row(c["id"])
    assert r["expected_amount"] == 1200000 and r["expected_close_date"] == "2026-12-31"
    assert client.get("/api/dev-cases/%d" % c["id"], headers=h).json()["expectedAmount"] == 1200000
    listed = [x for x in client.get("/api/dev-cases", headers=h).json() if x["id"] == c["id"]][0]
    assert listed["expectedAmount"] == 1200000 and listed["expectedCloseDate"] == "2026-12-31"
    up = client.put("/api/dev-cases/%d" % c["id"], headers=h, json={"case_name": "預估測試案", "expectedAmount": "2,500,000", "expectedCloseDate": "2027-01-15"})
    assert up.status_code == 200 and up.json()["expectedAmount"] == 2500000 and up.json()["expectedCloseDate"] == "2027-01-15"


def test_missing_key_keeps_values_and_null_or_empty_clears(client, make_user):
    h = _boss(client, make_user)
    c = _mk(client, h, expectedAmount=500, expectedCloseDate="2026-12-01")
    url = "/api/dev-cases/%d" % c["id"]
    keep = client.put(url, headers=h, json={"case_name": "改名", "customer_name": "客戶甲"})                 # 舊用戶端：沒帶這兩個鍵
    assert keep.status_code == 200 and keep.json()["expectedAmount"] == 500 and keep.json()["expectedCloseDate"] == "2026-12-01"
    clear = client.put(url, headers=h, json={"case_name": "改名", "expectedAmount": None, "expectedCloseDate": ""})
    assert clear.status_code == 200 and clear.json()["expectedAmount"] is None and clear.json()["expectedCloseDate"] is None
    assert _row(c["id"])["expected_amount"] is None and _row(c["id"])["expected_close_date"] is None
    zero = client.put(url, headers=h, json={"case_name": "改名", "expectedAmount": 0})                      # 0 是有效值（和「沒填」不同）
    assert zero.json()["expectedAmount"] == 0 and _row(c["id"])["expected_amount"] == 0


@pytest.mark.parametrize("body", [
    {"expectedAmount": -1}, {"expectedAmount": 1.5}, {"expectedAmount": "abc"}, {"expectedAmount": True},
    {"expectedAmount": [1]}, {"expectedAmount": 10_000_000_000},
    {"expectedCloseDate": "2026/12/31"}, {"expectedCloseDate": "2026-13-40"}, {"expectedCloseDate": "20261231"}, {"expectedCloseDate": 20261231},
])
def test_invalid_values_are_400_not_422_and_nothing_saved(client, make_user, body):
    h = _boss(client, make_user)
    r = client.post("/api/dev-cases", headers=h, json={"case_name": "壞值", **body})
    assert r.status_code == 400, (body, r.status_code, r.text)
    c = _mk(client, h, expectedAmount=100)
    r2 = client.put("/api/dev-cases/%d" % c["id"], headers=h, json={"case_name": "壞值", **body})
    assert r2.status_code == 400 and _row(c["id"])["expected_amount"] == 100


def test_past_close_date_is_allowed(client, make_user):
    h = _boss(client, make_user)
    assert _mk(client, h, expectedCloseDate="2020-01-01")["expectedCloseDate"] == "2020-01-01"


def test_update_audit_records_changes_without_amount_value(client, make_user):
    import db
    h = _boss(client, make_user)
    c = _mk(client, h, expectedAmount=777777, expectedCloseDate="2026-12-01")
    client.put("/api/dev-cases/%d" % c["id"], headers=h, json={"case_name": "預估測試案", "expectedAmount": 888888, "expectedCloseDate": "2026-12-05"})
    conn = db.get_db()
    try:
        rows = conn.execute("SELECT detail FROM audit_log WHERE action IN ('dev_case.create','dev_case.update') ORDER BY id").fetchall()
    finally:
        conn.close()
    blob = " ".join(str(r[0]) for r in rows)
    assert "2026-12-05" in blob and "777777" not in blob and "888888" not in blob


# ── 金額可見性 ───────────────────────────────────────────────────────────────

def test_non_financial_user_cannot_see_or_set_amount_but_sees_close_date(client, make_user):
    import db
    boss = _boss(client, make_user)
    c = _mk(client, boss, expectedAmount=900000, expectedCloseDate="2026-12-20")
    sales = _login(client, make_user, "ex_sales")
    conn = db.get_db()
    try:                                                                                                # 把業務加進這件的業務名單，他才看得到
        uid = conn.execute("SELECT id FROM users WHERE username='ex_sales'").fetchone()["id"]
        conn.execute("UPDATE dev_cases SET sales_persons=? WHERE id=?", (json.dumps([uid]), c["id"]))
        conn.commit()
    finally:
        conn.close()
    got = client.get("/api/dev-cases/%d" % c["id"], headers=sales).json()
    assert got["expectedAmount"] is None and got["expectedAmountVisible"] is False and got["expectedCloseDate"] == "2026-12-20"
    listed = [x for x in client.get("/api/dev-cases", headers=sales).json() if x["id"] == c["id"]][0]
    assert listed["expectedAmount"] is None
    url = "/api/dev-cases/%d" % c["id"]
    assert client.put(url, headers=sales, json={"case_name": "預估測試案", "expectedAmount": 1}).status_code == 403
    keep = client.put(url, headers=sales, json={"case_name": "預估測試案", "expectedAmount": None, "expectedCloseDate": "2027-02-01"})
    assert keep.status_code == 200 and keep.json()["expectedAmount"] is None and keep.json()["expectedCloseDate"] == "2027-02-01"
    assert _row(c["id"])["expected_amount"] == 900000                                                   # 他看不到 ⇒ 帶 null 也清不掉
    assert client.post("/api/dev-cases", headers=sales, json={"case_name": "業務自己開的", "expectedAmount": 5}).status_code == 403
    ok = client.post("/api/dev-cases", headers=sales, json={"case_name": "業務自己開的", "expectedCloseDate": "2026-11-30"})
    assert ok.status_code == 201 and ok.json()["expectedAmount"] is None


# ── 漏斗合計 ─────────────────────────────────────────────────────────────────

def test_expected_summary_totals_by_status_and_excludes_deleted(client, make_user):
    import db
    h = _boss(client, make_user)
    _mk(client, h, "A", expectedAmount=1000)
    b = _mk(client, h, "B", expectedAmount=2500)
    _mk(client, h, "C（沒填）")
    d = _mk(client, h, "D", expectedAmount=40000)
    assert client.patch("/api/dev-cases/%d/status" % b["id"], headers=h, json={"status": "成案"}).status_code == 200
    conn = db.get_db()
    try:
        conn.execute("UPDATE dev_cases SET is_deleted=1 WHERE id=?", (d["id"],))
        conn.commit()
    finally:
        conn.close()
    s = client.get("/api/dev-cases/expected-summary", headers=h)
    assert s.status_code == 200, s.text
    j = s.json()
    assert j["visible"] is True and j["total"] == 3500 and j["count"] == 2 and j["missing"] == 1
    assert j["byStatus"]["洽談中"] == {"count": 1, "total": 1000, "missing": 1}
    assert j["byStatus"]["成案"] == {"count": 1, "total": 2500, "missing": 0}
    assert j["byStatus"]["未成案"] == {"count": 0, "total": 0, "missing": 0}


def test_expected_summary_respects_row_access_and_hides_amount_without_permission(client, make_user):
    boss = _boss(client, make_user)
    _mk(client, boss, "老闆的案", expectedAmount=70000)
    sales = _login(client, make_user, "ex_sales2")
    _mk(client, sales, "業務自己的案")                                                                  # 業務是建立者 ⇒ 看得到
    j = client.get("/api/dev-cases/expected-summary", headers=sales).json()
    assert j["visible"] is False and j["total"] is None and all(v["total"] is None for v in j["byStatus"].values())
    assert j["count"] + j["missing"] == 1                                                              # 只算他看得到的那一件，看不到老闆的案
    assert client.get("/api/dev-cases/expected-summary").status_code in (401, 403)


def test_summary_route_is_not_shadowed_by_case_id_route(client, make_user):
    h = _boss(client, make_user)
    r = client.get("/api/dev-cases/expected-summary", headers=h)
    assert r.status_code == 200 and "byStatus" in r.json()
