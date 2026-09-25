# -*- coding: utf-8 -*-
"""逐筆已讀存在伺服器：選單數字、清單未讀標記、鈴鐺。

使用者（2026-09-24）逐字：「目前很多使用者反應，我點選選進某些未讀的，
點選後紅色未讀沒有即時消失」；表單：「逐筆已讀，存在伺服器」。

## 這批題釘的是什麼

```
已讀時間       伺服器蓋，不收用戶端的時鐘（原本用戶端時間與 audit_log.at 字串比較）
本人的修改     不算未讀（原本清單標記用 updated_at，自己改的也亮）
逐筆           標一筆只清那一筆（原本以模組／清單為單位的時間戳）
基準時間       沒有任何已讀紀錄的清單，第一次查詢時以伺服器當下為基準，
               不會在上線當天整片變成未讀
可見性         未讀端點只回呼叫者看得到的那幾筆
```
"""
import json
import time
from datetime import datetime, timedelta

import pytest


def _hdr(client, make_user, username, role="admin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _audit(username, action, target_type, target_id, at=None):
    """直接寫一筆 audit_log —— 題只關心「誰、什麼時候、動了哪一筆」。"""
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,"
            "target_id,target_label,detail) VALUES (?,?,?,?,?,?,?,?,?)",
            (at or datetime.now().isoformat(), None, username, username, action,
             target_type, str(target_id), "", "{}"),
        )
        conn.commit()
    finally:
        conn.close()


def _dev_case(created_by_uid, name="案件"):
    import db
    conn = db.get_db()
    try:
        now = datetime.now().isoformat()
        cur = conn.execute(
            "INSERT INTO dev_cases (case_name, created_by, created_at, updated_at) VALUES (?,?,?,?)",
            (name, created_by_uid, now, now))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _tick():
    """audit_log.at 精度到微秒；Windows 的時鐘解析度可能比微秒粗，拉開一點。"""
    time.sleep(0.02)


def _unread(client, h, kind, keys):
    r = client.post("/api/reads/unread", json={"kind": kind, "keys": [str(k) for k in keys]}, headers=h)
    assert r.status_code == 200, r.text
    return set(r.json()["unread"])


# ── 已讀時間 ────────────────────────────────────────────────────────────────

def test_read_time_is_stamped_by_the_server_not_the_client(client, make_user):
    h = _hdr(client, make_user, "alice")
    r = client.post("/api/reads", json={"kind": "dev_case", "key": "7",
                                        "read_at": "1999-01-01T00:00:00"}, headers=h)
    assert r.status_code == 200, r.text
    got = client.get("/api/reads?kind=dev_case", headers=h).json()["items"]
    assert len(got) == 1
    stamped = datetime.fromisoformat(got[0]["read_at"])
    assert abs((datetime.now() - stamped).total_seconds()) < 60, got[0]["read_at"]


def test_reads_belong_to_the_caller_only(client, make_user):
    ha = _hdr(client, make_user, "alice")
    hb = _hdr(client, make_user, "bob")
    client.post("/api/reads", json={"kind": "dev_case", "key": "7"}, headers=ha)
    assert client.get("/api/reads?kind=dev_case", headers=hb).json()["items"] == []


def test_read_rejects_an_unknown_kind(client, make_user):
    h = _hdr(client, make_user, "alice")
    r = client.post("/api/reads", json={"kind": "whatever", "key": "1"}, headers=h)
    assert r.status_code == 400


# ── 清單未讀：逐筆、排除本人 ───────────────────────────────────────────────

def test_changes_made_before_the_first_look_are_not_unread(client, make_user):
    """基準：第一次查詢時沒有任何紀錄 ⇒ 以當下為基準，不整片亮起來。"""
    ha = _hdr(client, make_user, "alice")
    _hdr(client, make_user, "bob")
    cid = _dev_case(_uid("alice"))
    _audit("bob", "dev_case.update", "dev_case", cid)
    _tick()
    assert _unread(client, ha, "dev_case", [cid]) == set()


def test_my_own_change_is_not_unread(client, make_user):
    ha = _hdr(client, make_user, "alice")
    cid = _dev_case(_uid("alice"))
    _unread(client, ha, "dev_case", [cid])
    _tick()
    _audit("alice", "dev_case.update", "dev_case", cid)
    assert _unread(client, ha, "dev_case", [cid]) == set()


def test_case_activity_by_others_is_unread_and_mine_is_not(client, make_user):
    """案件管理：三個來源（案件動態／工作日誌／每日工作完成）依作者排除本人。

    ⚠️ `case_updates.created_at` 的預設值是 `datetime('now','localtime')`
       ——**空白**分隔，而 `read_at` 是 `T` 分隔。字串直接比，`' ' < 'T'`，
       同一天之內的動態永遠比已讀時間「早」⇒ 永遠不會亮。
    """
    import db
    ha = _hdr(client, make_user, "alice")
    _hdr(client, make_user, "bob")
    _unread(client, ha, "case", ["MQ-1", "MQ-2"])
    time.sleep(1.1)   # 空白分隔格式只到秒
    conn = db.get_db()
    try:
        now_space = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO case_updates (quote_no, author, content, created_at) VALUES (?,?,?,?)",
                     ("MQ-1", "bob", "x", now_space))
        conn.execute("INSERT INTO case_updates (quote_no, author, content, created_at) VALUES (?,?,?,?)",
                     ("MQ-2", "alice", "x", now_space))
        conn.commit()
    finally:
        conn.close()
    assert _unread(client, ha, "case", ["MQ-1", "MQ-2"]) == {"MQ-1"}


def test_unread_only_answers_for_cases_the_caller_can_see(client, make_user):
    """非 admin 看不到別人的報價案件 ⇒ 未讀端點不可以回它（否則等於洩漏它有動態）。"""
    import db
    hs = _hdr(client, make_user, "sam", role="user")
    _hdr(client, make_user, "bob")
    conn = db.get_db()
    try:
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO quotations (quote_no, status, sales_person, sales_person_id, data_json, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            ("MQ-9", "草稿", "bob", _uid("bob"), "{}", now, now))
        conn.commit()
    finally:
        conn.close()
    _unread(client, hs, "case", ["MQ-9"])
    time.sleep(1.1)
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO case_updates (quote_no, author, content, created_at) VALUES (?,?,?,?)",
                     ("MQ-9", "bob", "x", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    finally:
        conn.close()
    assert _unread(client, hs, "case", ["MQ-9"]) == set()


def test_non_admin_cannot_probe_dev_cases_they_cannot_access(client, make_user):
    hs = _hdr(client, make_user, "sam", role="user", modules=["dev_crm"])
    _hdr(client, make_user, "bob")
    cid = _dev_case(_uid("bob"))
    _unread(client, hs, "dev_case", [cid])
    _tick()
    _audit("bob", "dev_case.update", "dev_case", cid)
    assert _unread(client, hs, "dev_case", [cid]) == set()


# ── 選單數字 ────────────────────────────────────────────────────────────────

def test_module_counts_use_the_seen_time_stored_on_the_server(client, make_user):
    ha = _hdr(client, make_user, "alice")
    _hdr(client, make_user, "bob")
    client.post("/api/reads", json={"kind": "module", "key": "customer"}, headers=ha)
    _tick()
    _audit("bob", "customer.update", "customer", 1)
    _audit("alice", "customer.update", "customer", 2)      # 本人的不算
    d = client.get("/api/reads/module-counts", headers=ha).json()
    assert d["customer"] == 1
    _tick()
    client.post("/api/reads", json={"kind": "module", "key": "customer"}, headers=ha)
    assert client.get("/api/reads/module-counts", headers=ha).json()["customer"] == 0


def test_tender_radar_has_a_module_count(client, make_user):
    """`tender_radar` 在側欄有徽章（sidebar.js `_MOD_BADGES`），後端對照卻沒有它 ⇒ 永遠不亮。"""
    ha = _hdr(client, make_user, "alice")
    _hdr(client, make_user, "bob")
    client.post("/api/reads", json={"kind": "module", "key": "tender_radar"}, headers=ha)
    _tick()
    _audit("bob", "tender_watch.create", "tender_watch", 1)
    assert client.get("/api/reads/module-counts", headers=ha).json().get("tender_radar") == 1


# ── 舊 localStorage 一次性遷移 ─────────────────────────────────────────────

def test_legacy_migration_keeps_the_newer_of_server_and_legacy(client, make_user):
    ha = _hdr(client, make_user, "alice")
    client.post("/api/reads", json={"kind": "module", "key": "customer"}, headers=ha)
    server_at = client.get("/api/reads?kind=module", headers=ha).json()["items"][0]["read_at"]
    old = (datetime.now() - timedelta(days=3)).isoformat()
    r = client.post("/api/reads/batch", json={"items": [
        {"kind": "module", "key": "customer", "read_at": old},
        {"kind": "module", "key": "quotation", "read_at": old},
    ]}, headers=ha)
    assert r.status_code == 200, r.text
    got = {i["item_key"]: i["read_at"] for i in client.get("/api/reads?kind=module", headers=ha).json()["items"]}
    assert got["customer"] == server_at
    assert got["quotation"][:19] == old[:19]


def test_legacy_migration_cannot_set_a_time_in_the_future(client, make_user):
    """遷移是唯一收用戶端時間的路 ⇒ 未來時間會讓之後的變動永遠被當成已讀。"""
    ha = _hdr(client, make_user, "alice")
    future = (datetime.now() + timedelta(days=30)).isoformat()
    client.post("/api/reads/batch", json={"items": [
        {"kind": "module", "key": "customer", "read_at": future}]}, headers=ha)
    got = client.get("/api/reads?kind=module", headers=ha).json()["items"][0]["read_at"]
    assert datetime.fromisoformat(got) <= datetime.now()
