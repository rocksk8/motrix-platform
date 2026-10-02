# -*- coding: utf-8 -*-
"""業務開發「介紹人」（dev_cases.referrer；使用者 2026-09-30）：migration、API（建立／編輯／列表搜尋／詳情）、驗證、稽核、匯出。

migration：只新增一欄、冪等、表不在回原因字串。API：自由文字、去頭尾空白、最多 60 字（超過 400、不是 422、不截斷）、型別不對 400；
列表搜尋框（`q`）也搜介紹人（LIKE 萬用字元當字面值）；編輯時稽核 detail 記 old→new；備份匯出（archive 的 `SELECT *`）含此欄。"""
import json
import sqlite3

import pytest

NAME = "rf_user"


def _login(client, make_user, username=NAME, role="sales"):
    name, pw = make_user(username=username, role=role, modules=["dev_crm"])
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _create(client, h, **extra):
    body = {"case_name": "介紹人測試案", "customer_name": "客戶甲", **extra}
    return client.post("/api/dev-cases", headers=h, json=body)


def _row(cid):
    import db
    c = db.get_db()
    try:
        return dict(c.execute("SELECT * FROM dev_cases WHERE id=?", (cid,)).fetchone())
    finally:
        c.close()


# ── migration ──────────────────────────────────────────────────────────────

def test_migration_adds_one_column_idempotently_and_reports_missing_table():
    import importlib
    m = importlib.import_module("modules.crm.migrations.0001_dev_cases_referrer")
    c = sqlite3.connect(":memory:")
    assert isinstance(m.up(c), str) and "dev_cases" in m.up(c)                       # 表不在 ⇒ 原因字串（未完成，不猜）
    c.execute("CREATE TABLE dev_cases (id INTEGER PRIMARY KEY, case_name TEXT)")
    c.execute("INSERT INTO dev_cases (case_name) VALUES ('舊案')")
    assert m.up(c) is None and m.up(c) is None                                        # 冪等
    cols = {r[1]: r for r in c.execute("PRAGMA table_info(dev_cases)")}
    assert "referrer" in cols and cols["referrer"][4] == "''" and cols["referrer"][3] == 1
    assert c.execute("SELECT referrer FROM dev_cases").fetchone()[0] == ""            # 舊列補空字串


def test_real_db_has_the_column_after_init(client):
    import db
    c = db.get_db()
    try:
        assert "referrer" in {r[1] for r in c.execute("PRAGMA table_info(dev_cases)")}
        assert c.execute("SELECT version FROM module_schema_versions WHERE module='crm'").fetchone()[0] >= 1
    finally:
        c.close()


# ── API ────────────────────────────────────────────────────────────────────

def test_create_edit_list_search_detail_roundtrip(client, make_user):
    h = _login(client, make_user)
    r = _create(client, h, referrer="  王大哥（同業介紹）  ")
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["referrer"] == "王大哥（同業介紹）" and _row(cid)["referrer"] == "王大哥（同業介紹）"      # 去頭尾空白
    assert client.get("/api/dev-cases/%d" % cid, headers=h).json()["referrer"] == "王大哥（同業介紹）"
    listed = client.get("/api/dev-cases", headers=h).json()
    assert [c["referrer"] for c in listed if c["id"] == cid] == ["王大哥（同業介紹）"]
    assert [c["id"] for c in client.get("/api/dev-cases", headers=h, params={"q": "同業"}).json()] == [cid]       # 搜尋框也搜介紹人
    assert client.get("/api/dev-cases", headers=h, params={"q": "不存在的人"}).json() == []
    up = client.put("/api/dev-cases/%d" % cid, headers=h, json={"case_name": "介紹人測試案", "referrer": "李經理"})
    assert up.status_code == 200 and up.json()["referrer"] == "李經理" and _row(cid)["referrer"] == "李經理"
    clear = client.put("/api/dev-cases/%d" % cid, headers=h, json={"case_name": "介紹人測試案", "referrer": ""})
    assert clear.json()["referrer"] == ""                                                                          # 可清空
    omitted = _create(client, h)
    assert omitted.status_code == 201 and omitted.json()["referrer"] == ""                                          # 不帶＝空


def test_validation_length_and_type_are_400_and_nothing_is_written(client, make_user):
    """**反向控制**：拿掉 `_clean_referrer` 的長度／型別檢查 ⇒ 這題紅。"""
    h = _login(client, make_user)
    ok60 = _create(client, h, referrer="字" * 60)
    assert ok60.status_code == 201 and len(ok60.json()["referrer"]) == 60                                          # 60 字剛好可以
    before = len(client.get("/api/dev-cases", headers=h).json())
    for bad, why in (("字" * 61, "太長"), (123, "數字"), (["a"], "陣列"), ({"a": 1}, "物件"), (True, "布林")):
        r = _create(client, h, referrer=bad)
        assert r.status_code == 400, (why, r.status_code, r.text[:120])
    assert len(client.get("/api/dev-cases", headers=h).json()) == before                                           # 被拒的沒寫進去
    cid = ok60.json()["id"]
    r = client.put("/api/dev-cases/%d" % cid, headers=h, json={"case_name": "x", "referrer": "字" * 61})
    assert r.status_code == 400 and _row(cid)["referrer"] == "字" * 60                                              # 編輯被拒＝原值不變
    r = client.put("/api/dev-cases/%d" % cid, headers=h, json={"case_name": "x", "referrer": 5})
    assert r.status_code == 400
    assert len(_create(client, h, referrer="  " + "字" * 60 + "  ").json()["referrer"]) == 60                      # 空白不算字數


def test_search_treats_like_wildcards_literally(client, make_user):
    h = _login(client, make_user)
    a = _create(client, h, case_name="案A", customer_name="甲", referrer="100%推薦").json()["id"]
    b = _create(client, h, case_name="案B", customer_name="乙", referrer="1000推薦").json()["id"]
    c = _create(client, h, case_name="案C", customer_name="丙", referrer="a_b").json()["id"]
    d = _create(client, h, case_name="案D", customer_name="丁", referrer="axb").json()["id"]
    ids = lambda q: sorted(x["id"] for x in client.get("/api/dev-cases", headers=h, params={"q": q}).json())
    assert ids("100%") == [a] and ids("a_b") == [c]
    assert ids("%") == [a]                                                                                          # 單獨 % 只匹配含 % 的


def test_update_audit_records_old_to_new_only_when_changed(client, make_user):
    h = _login(client, make_user)
    cid = _create(client, h, referrer="甲").json()["id"]
    body = {"case_name": "介紹人測試案", "referrer": "甲"}
    client.put("/api/dev-cases/%d" % cid, headers=h, json=body)                                                     # 沒變
    client.put("/api/dev-cases/%d" % cid, headers=h, json=dict(body, referrer="乙"))                                # 甲 → 乙
    import db
    c = db.get_db()
    try:
        rows = [json.loads(r["detail"] or "{}") for r in c.execute(
            "SELECT detail FROM audit_log WHERE action='dev_case.update' AND target_id=? ORDER BY id", (str(cid),))]
        created = [json.loads(r["detail"] or "{}") for r in c.execute(
            "SELECT detail FROM audit_log WHERE action='dev_case.create' AND target_id=?", (str(cid),))]
    finally:
        c.close()
    assert created == [{"referrer": "甲"}]
    assert rows[0] == {} and rows[1] == {"referrer": {"from": "甲", "to": "乙"}}


def test_backup_export_includes_the_column(client, make_user):
    """備份匯出（archive 的 `SELECT * FROM dev_cases`）自動含新欄位——不是顯式欄位清單。"""
    h = _login(client, make_user)
    _create(client, h, referrer="匯出測試")
    import archive
    import inspect
    src = inspect.getsource(archive)
    assert '"SELECT * FROM dev_cases ORDER BY id"' in src
    import db
    c = db.get_db()
    try:
        cols = [r[0] for r in c.execute("SELECT * FROM dev_cases").description]
    finally:
        c.close()
    assert "referrer" in cols
