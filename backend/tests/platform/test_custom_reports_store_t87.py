# -*- coding: utf-8 -*-
"""T87 B2-S2：「我的報表」的儲存（表、CRUD、etag、上限、分享、刪除進暫存區）。

重點：只讀寫自己的列（非擁有者與不存在逐字相同的 404）；定義存檔前完整驗證且不存壞資料；etag 409；每人 30 份；
分享（D4）與刪除方式（D5）由設定決定、後端每次請求重讀；被分享者只能讀與複製；migration 冪等。
"""
import json
import sqlite3

import pytest

from db import get_db
from helpers import settings_registry as R
from modules.analytics.api import custom_reports as CR
import importlib

BASE = "/api/custom-reports"
_M = importlib.import_module("modules.analytics.migrations.0001_custom_reports")


def _login(client, make_user, name, role="sales", modules=None):
    kw = {"username": name, "role": role}
    if modules is not None:
        kw["modules"] = modules
    u, p = make_user(**kw)
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _set(client, **kv):
    c = get_db()
    try:
        R.publish("custom_reports", kv, reason="測試", user="sa_store", conn=c)
    finally:
        c.close()
    R.invalidate()


@pytest.fixture(autouse=True)
def _on(client):
    CR.reset_rate_limit()
    _set(client, enabled=1)
    yield
    R.invalidate()


def _defn(**kw):
    d = {"version": 1, "source": "quotation", "columns": ["quote_no", "customer_name"]}
    d.update(kw)
    return d


def _create(client, h, name="報表A", definition=None):
    return client.post(BASE, json={"name": name, "definition": definition or _defn()}, headers=h)


def _count(table="custom_reports"):
    c = get_db()
    try:
        return c.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
    finally:
        c.close()


# ── 基本 CRUD 與只讀寫自己的列 ─────────────────────────────────────────────

def test_create_list_get_roundtrip(client, make_user):
    h = _login(client, make_user, "st_a1", modules=["quotation", "case_manage"])
    r = _create(client, h)
    assert r.status_code == 201
    b = r.json()
    assert b["name"] == "報表A" and b["isOwner"] is True and b["definition"]["columns"] == ["quote_no", "customer_name"] and b["etag"]
    lst = client.get(BASE, headers=h).json()
    assert [x["name"] for x in lst["mine"]] == ["報表A"] and lst["shared"] == [] and lst["max"] == 30
    assert client.get("%s/%d" % (BASE, b["id"]), headers=h).json()["id"] == b["id"]


def test_other_users_and_missing_reports_get_the_very_same_404(client, make_user):
    a = _login(client, make_user, "st_a2", modules=["quotation", "case_manage"])
    b = _login(client, make_user, "st_b2", modules=["quotation", "case_manage"])
    rid = _create(client, a).json()["id"]
    mine_missing = client.get("%s/999999" % BASE, headers=a)
    theirs = client.get("%s/%d" % (BASE, rid), headers=b)
    assert theirs.status_code == mine_missing.status_code == 404 and theirs.json() == mine_missing.json()
    for method, url in (("put", "%s/%d" % (BASE, rid)), ("delete", "%s/%d" % (BASE, rid)), ("post", "%s/%d/copy" % (BASE, rid))):
        kw = {"json": {"name": "x"}, "headers": dict(b, **{"If-Match": "x"})} if method == "put" else {"headers": b}
        r = getattr(client, method)(url, **kw)
        assert r.status_code == 404 and r.json() == mine_missing.json(), method
    assert [x["name"] for x in client.get(BASE, headers=b).json()["mine"]] == []


def test_no_endpoint_takes_an_account_parameter_so_a_body_username_is_ignored_or_refused(client, make_user):
    a = _login(client, make_user, "st_a3", modules=["quotation", "case_manage"])
    r = client.post(BASE, json={"name": "x", "definition": _defn(), "username": "someone_else"}, headers=a)
    assert r.status_code == 422 and _count() == 0


def test_flag_off_closes_the_crud_too(client, make_user):
    h = _login(client, make_user, "st_a4", modules=["quotation", "case_manage"])
    rid = _create(client, h).json()["id"]
    _set(client, enabled=0)
    assert client.get(BASE, headers=h).status_code == 404
    assert client.get("%s/%d" % (BASE, rid), headers=h).status_code == 404
    assert _create(client, h, "報表B").status_code == 404
    _set(client, enabled=1)
    assert client.get("%s/%d" % (BASE, rid), headers=h).status_code == 200                     # 資料保留


# ── 驗證、名稱、上限、etag ─────────────────────────────────────────────────

def test_invalid_definitions_and_names_are_refused_and_nothing_is_stored(client, make_user):
    h = _login(client, make_user, "st_a5", role="engineer", modules=["quotation"])
    assert _create(client, h, "x", {"version": 1, "source": "quotation", "columns": ["nope"]}).status_code == 422
    r = _create(client, h, "x", _defn(filters=[{"field": "total", "op": "gte", "value": 1}]))              # 工程師看不到金額欄 ⇒ 不能存
    assert r.status_code == 422 and r.json()["detail"]["reason"] == "no_permission"
    assert _create(client, h, "   ").status_code == 422
    assert _create(client, h, "名" * 41).status_code == 422
    assert client.post(BASE, json={"name": "x"}, headers=h).status_code == 422
    assert _count() == 0


def test_duplicate_name_is_409_and_whitespace_is_normalised(client, make_user):
    h = _login(client, make_user, "st_a6", modules=["quotation", "case_manage"])
    assert _create(client, h, "月報").status_code == 201
    r = _create(client, h, "  月報 ")
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "duplicate_name"
    other = _login(client, make_user, "st_b6", modules=["quotation", "case_manage"])
    assert _create(client, other, "月報").status_code == 201                                            # 不同人可同名


def test_limit_of_30_per_user_and_message(client, make_user):
    h = _login(client, make_user, "st_a7", modules=["quotation", "case_manage"])
    for i in range(30):
        assert _create(client, h, "r%d" % i).status_code == 201
    r = _create(client, h, "r30")
    assert r.status_code == 422 and "30" in r.json()["detail"]["message"] and _count() == 30
    other = _login(client, make_user, "st_b7", modules=["quotation", "case_manage"])
    assert _create(client, other, "r0").status_code == 201                                              # 上限是每人的


def test_etag_conflict_and_successful_update(client, make_user):
    h = _login(client, make_user, "st_a8", modules=["quotation", "case_manage"])
    b = _create(client, h).json()
    url = "%s/%d" % (BASE, b["id"])
    ok = client.put(url, json={"name": "新名稱"}, headers=dict(h, **{"If-Match": b["etag"]}))
    assert ok.status_code == 200 and ok.json()["name"] == "新名稱" and ok.json()["etag"] != b["etag"]
    stale = client.put(url, json={"name": "又改"}, headers=dict(h, **{"If-Match": b["etag"]}))
    assert stale.status_code == 409 and stale.json()["detail"]["reason"] == "etag"
    assert client.put(url, json={"name": "又改"}, headers=h).status_code == 409                          # 沒帶 If-Match 也不放行
    assert client.get(url, headers=h).json()["name"] == "新名稱"
    d = client.put(url, json={"definition": _defn(columns=["quote_no"])}, headers=dict(h, **{"If-Match": ok.json()["etag"]}))
    assert d.status_code == 200 and d.json()["definition"]["columns"] == ["quote_no"]
    assert client.put(url, json={}, headers=dict(h, **{"If-Match": d.json()["etag"]})).status_code == 422
    assert client.put(url, json={"username": "x"}, headers=dict(h, **{"If-Match": d.json()["etag"]})).status_code == 422


def test_rename_to_an_existing_name_is_409(client, make_user):
    h = _login(client, make_user, "st_a9", modules=["quotation", "case_manage"])
    _create(client, h, "甲")
    b = _create(client, h, "乙").json()
    r = client.put("%s/%d" % (BASE, b["id"]), json={"name": "甲"}, headers=dict(h, **{"If-Match": b["etag"]}))
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "duplicate_name"


def test_stored_definition_is_rerun_with_the_runners_permissions_not_the_savers(client, make_user):
    """A 存、B 跑：存的只是設定；B 用 B 的權限預覽，看不到的欄位被拿掉。"""
    a = _login(client, make_user, "st_a10", role="sales", modules=["quotation", "case_manage"])
    saved = _create(client, a, "含金額", _defn(columns=["quote_no", "total"])).json()
    assert saved["definition"]["columns"] == ["quote_no", "total"]
    eng = _login(client, make_user, "st_e10", role="engineer", modules=["quotation"])
    res = client.post(BASE + "/preview", json=saved["definition"], headers=eng).json()
    assert [c["label"] for c in res["columns"]] == ["報價單號"] and res["hiddenCount"] == 1


# ── 複製 ───────────────────────────────────────────────────────────────────

def test_copy_names_and_counts_toward_the_limit(client, make_user):
    h = _login(client, make_user, "st_a11", modules=["quotation", "case_manage"])
    rid = _create(client, h, "月報").json()["id"]
    c1 = client.post("%s/%d/copy" % (BASE, rid), headers=h)
    c2 = client.post("%s/%d/copy" % (BASE, rid), headers=h)
    assert c1.status_code == c2.status_code == 201
    assert c1.json()["name"] == "月報（複本）" and c2.json()["name"] == "月報（複本2）" and c1.json()["isOwner"] is True
    long = _create(client, h, "長" * 40).json()["id"]
    assert len(client.post("%s/%d/copy" % (BASE, long), headers=h).json()["name"]) <= 40


# ── D4 分享 ────────────────────────────────────────────────────────────────

def _pair(client, make_user, tag):
    a = _login(client, make_user, "sh_a_" + tag, modules=["quotation", "case_manage"])
    b = _login(client, make_user, "sh_b_" + tag, modules=["quotation", "case_manage"])
    return a, b, "sh_b_" + tag


def test_sharing_off_by_default_nothing_visible_and_shares_refused(client, make_user):
    a, b, bname = _pair(client, make_user, "off")
    rep = _create(client, a).json()
    r = client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": [bname]}, headers=dict(a, **{"If-Match": rep["etag"]}))
    assert r.status_code == 403 and r.json()["detail"]["reason"] == "sharing_off" and _count("custom_report_shares") == 0
    ok = client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": []}, headers=dict(a, **{"If-Match": rep["etag"]}))
    assert ok.status_code == 200                                                                          # 清空分享在關閉時也允許（不是新的分享）
    assert client.get("%s/%d" % (BASE, rep["id"]), headers=b).status_code == 404


def test_sharing_on_recipient_can_read_and_copy_but_not_change(client, make_user):
    _set(client, sharing=1)
    a, b, bname = _pair(client, make_user, "on")
    rep = _create(client, a, "共用報表").json()
    put = client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": [bname]}, headers=dict(a, **{"If-Match": rep["etag"]}))
    assert put.status_code == 200 and put.json()["sharedWith"] == [bname]
    lst = client.get(BASE, headers=b).json()
    assert [x["name"] for x in lst["shared"]] == ["共用報表"] and lst["shared"][0]["ownerName"] and lst["mine"] == [] and lst["sharingEnabled"] is True
    got = client.get("%s/%d" % (BASE, rep["id"]), headers=b).json()
    assert got["isOwner"] is False and got["definition"] == rep["definition"] and "sharedWith" not in got
    url = "%s/%d" % (BASE, rep["id"])
    assert client.put(url, json={"name": "偷改"}, headers=dict(b, **{"If-Match": got["etag"]})).status_code == 404
    assert client.delete(url, headers=b).status_code == 404
    assert client.put(url, json={"sharedWith": [bname]}, headers=dict(b, **{"If-Match": got["etag"]})).status_code == 404           # 不能再分享
    cp = client.post(url + "/copy", headers=b)
    assert cp.status_code == 201 and cp.json()["isOwner"] is True and cp.json()["name"] == "共用報表（複本）"
    assert [x["name"] for x in client.get(BASE, headers=b).json()["mine"]] == ["共用報表（複本）"]
    third = _login(client, make_user, "sh_c_on", modules=["quotation", "case_manage"])
    assert client.get(url, headers=third).status_code == 404                                              # 沒被分享的人


def test_turning_sharing_off_hides_but_keeps_the_rows(client, make_user):
    _set(client, sharing=1)
    a, b, bname = _pair(client, make_user, "tog")
    rep = _create(client, a).json()
    client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": [bname]}, headers=dict(a, **{"If-Match": rep["etag"]}))
    _set(client, sharing=0)
    assert client.get("%s/%d" % (BASE, rep["id"]), headers=b).status_code == 404 and client.get(BASE, headers=b).json()["shared"] == []
    assert _count("custom_report_shares") == 1
    _set(client, sharing=1)
    assert client.get("%s/%d" % (BASE, rep["id"]), headers=b).status_code == 200


def test_share_target_validation(client, make_user):
    _set(client, sharing=1)
    a, b, bname = _pair(client, make_user, "val")
    rep = _create(client, a).json()
    url, hh = "%s/%d" % (BASE, rep["id"]), dict(a)
    def put(v):
        cur = client.get(url, headers=a).json()["etag"]
        return client.put(url, json={"sharedWith": v}, headers=dict(hh, **{"If-Match": cur}))
    assert put(["sh_a_val"]).status_code == 422                                  # 自己
    r = put(["no_such_user"])
    assert r.status_code == 422 and "no_such_user" not in r.text                  # 不回顯輸入
    assert put("x").status_code == 422 and put([1]).status_code == 422
    assert put(["u%d" % i for i in range(21)]).status_code == 422
    assert put([bname, bname]).json()["sharedWith"] == [bname]                   # 去重
    assert put([]).json()["sharedWith"] == []


# ── D5 刪除 ────────────────────────────────────────────────────────────────

def test_default_delete_removes_the_row_and_its_shares(client, make_user):
    _set(client, sharing=1)
    a, b, bname = _pair(client, make_user, "del")
    rep = _create(client, a).json()
    client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": [bname]}, headers=dict(a, **{"If-Match": rep["etag"]}))
    r = client.delete("%s/%d" % (BASE, rep["id"]), headers=a)
    assert r.status_code == 200 and r.json() == {"deleted": True, "recycled": False}
    assert _count() == 0 and _count("custom_report_shares") == 0
    assert client.delete("%s/%d" % (BASE, rep["id"]), headers=a).status_code == 404


def test_recycle_setting_sends_the_report_to_the_bin_and_restore_brings_it_back(client, make_user):
    _set(client, recycle_deleted=1, sharing=1)
    a, b, bname = _pair(client, make_user, "rb")
    sa = _login(client, make_user, "st_sa_rb", role="superadmin")
    rep = _create(client, a, "要還原").json()
    client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": [bname]}, headers=dict(a, **{"If-Match": rep["etag"]}))
    r = client.delete("%s/%d" % (BASE, rep["id"]), headers=a)
    assert r.status_code == 200 and r.json()["recycled"] is True and _count() == 0 and _count("custom_report_shares") == 0
    items = client.get("/api/recycle-bin", headers=sa).json()["items"]
    mine = [x for x in items if x["entityType"] == "custom_report"]
    assert len(mine) == 1 and "要還原" in mine[0]["label"]
    assert client.post("/api/recycle-bin/%d/restore" % mine[0]["id"], headers=sa).status_code == 200
    assert _count() == 1 and _count("custom_report_shares") == 1
    assert [x["name"] for x in client.get(BASE, headers=a).json()["mine"]] == ["要還原"]
    assert client.get("%s/%d" % (BASE, rep["id"]), headers=b).status_code == 200


def test_restore_with_a_name_clash_renames_instead_of_overwriting(client, make_user):
    _set(client, recycle_deleted=1)
    a = _login(client, make_user, "st_a12", modules=["quotation", "case_manage"])
    sa = _login(client, make_user, "st_sa_12", role="superadmin")
    rid = _create(client, a, "月報").json()["id"]
    client.delete("%s/%d" % (BASE, rid), headers=a)
    _create(client, a, "月報")                                                                           # 同名新報表
    mine = [x for x in client.get("/api/recycle-bin", headers=sa).json()["items"] if x["entityType"] == "custom_report"]
    res = client.post("/api/recycle-bin/%d/restore" % mine[0]["id"], headers=sa)
    assert res.status_code == 200
    assert sorted(x["name"] for x in client.get(BASE, headers=a).json()["mine"]) == ["月報", "月報（已還原）"]


def test_the_policy_is_read_at_every_delete_not_cached(client, make_user):
    a = _login(client, make_user, "st_a13", modules=["quotation", "case_manage"])
    r1 = _create(client, a, "一").json()["id"]
    r2 = _create(client, a, "二").json()["id"]
    assert client.delete("%s/%d" % (BASE, r1), headers=a).json()["recycled"] is False
    _set(client, recycle_deleted=1)
    assert client.delete("%s/%d" % (BASE, r2), headers=a).json()["recycled"] is True


# ── 稽核與 migration ───────────────────────────────────────────────────────

def test_write_endpoints_leave_audit_rows_without_names_or_values(client, make_user):
    h = _login(client, make_user, "st_a14", modules=["quotation", "case_manage"])
    secret = "機密客戶名稱-8842"
    b = _create(client, h, "稽核測", _defn(filters=[{"field": "customer_name", "op": "eq", "value": secret}])).json()
    client.delete("%s/%d" % (BASE, b["id"]), headers=h)
    c = get_db()
    try:
        rows = c.execute("SELECT action, target_label, detail FROM audit_log WHERE action LIKE 'custom_reports.%' ORDER BY id").fetchall()
    finally:
        c.close()
    assert [r["action"] for r in rows] == ["custom_reports.create", "custom_reports.delete"]
    assert secret not in json.dumps([dict(r) for r in rows], ensure_ascii=False) and all("稽核測" not in r["target_label"] for r in rows)


def test_migration_is_idempotent_and_only_adds():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE keep (a INTEGER)")
    c.execute("INSERT INTO keep VALUES (1)")
    assert _M.up(c) is None
    c.execute("INSERT INTO custom_reports (username,name,source_id,definition_json,created_at,updated_at) VALUES ('u','n','quotation','{}','t','t')")
    assert _M.up(c) is None                                                       # 重跑什麼都不改
    assert c.execute("SELECT COUNT(*) FROM custom_reports").fetchone()[0] == 1 and c.execute("SELECT a FROM keep").fetchone()[0] == 1
    cols = {r[1]: r for r in c.execute("PRAGMA table_info(custom_reports)")}
    assert cols["owner_unit_id"][4] == "1" and cols["owner_unit_id"][3] == 1
    assert {r[1] for r in c.execute("PRAGMA table_info(custom_report_shares)")} >= {"report_id", "shared_with", "owner_unit_id"}
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO custom_reports (username,name,source_id,definition_json,created_at,updated_at) VALUES ('u','n','quotation','{}','t','t')")
