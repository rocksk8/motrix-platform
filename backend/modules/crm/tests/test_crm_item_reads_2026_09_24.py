# -*- coding: utf-8 -*-
"""未讀標記（L1 item_reads）以業務開發案件為對象的題。

（2026-09-26 自 tests/test_item_reads_server_side_2026_09_24.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
逐筆已讀存在伺服器：選單數字、清單未讀標記、鈴鐺。

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


# ── 清單未讀：逐筆、排除本人 ───────────────────────────────────────────────


def test_someone_elses_change_after_the_baseline_is_unread(client, make_user):
    ha = _hdr(client, make_user, "alice")
    _hdr(client, make_user, "bob")
    cid = _dev_case(_uid("alice"))
    _unread(client, ha, "dev_case", [cid])          # 建立基準
    _tick()
    _audit("bob", "dev_case.update", "dev_case", cid)
    assert _unread(client, ha, "dev_case", [cid]) == {str(cid)}


def test_marking_one_item_read_clears_only_that_item(client, make_user):
    ha = _hdr(client, make_user, "alice")
    _hdr(client, make_user, "bob")
    c1, c2 = _dev_case(_uid("alice"), "一"), _dev_case(_uid("alice"), "二")
    _unread(client, ha, "dev_case", [c1, c2])
    _tick()
    _audit("bob", "dev_case.update", "dev_case", c1)
    _audit("bob", "dev_case.update", "dev_case", c2)
    assert _unread(client, ha, "dev_case", [c1, c2]) == {str(c1), str(c2)}
    _tick()
    client.post("/api/reads", json={"kind": "dev_case", "key": str(c1)}, headers=ha)
    assert _unread(client, ha, "dev_case", [c1, c2]) == {str(c2)}


def test_a_new_change_after_reading_makes_it_unread_again(client, make_user):
    ha = _hdr(client, make_user, "alice")
    _hdr(client, make_user, "bob")
    cid = _dev_case(_uid("alice"))
    _unread(client, ha, "dev_case", [cid])
    _tick()
    _audit("bob", "dev_case.update", "dev_case", cid)
    _tick()
    client.post("/api/reads", json={"kind": "dev_case", "key": str(cid)}, headers=ha)
    assert _unread(client, ha, "dev_case", [cid]) == set()
    _tick()
    _audit("bob", "dev_case.update", "dev_case", cid)
    assert _unread(client, ha, "dev_case", [cid]) == {str(cid)}


def test_a_dev_log_by_someone_else_marks_its_case_unread(client, make_user):
    """dev_log 的 audit target 是**日誌 id** 不是案件 id —— 要從 dev_logs 表對回案件。"""
    import db
    ha = _hdr(client, make_user, "alice")
    _hdr(client, make_user, "bob")
    cid = _dev_case(_uid("alice"))
    _unread(client, ha, "dev_case", [cid])
    _tick()
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO dev_logs (case_id, log_date, log_by, created_by, created_at) VALUES (?,?,?,?,?)",
            (cid, "2026-09-24", _uid("bob"), _uid("bob"), datetime.now().isoformat()))
        conn.commit()
    finally:
        conn.close()
    assert _unread(client, ha, "dev_case", [cid]) == {str(cid)}


# ── 選單數字 ────────────────────────────────────────────────────────────────


# ── 舊 localStorage 一次性遷移 ─────────────────────────────────────────────
