# -*- coding: utf-8 -*-
"""被指派人（assigned_to）在「自己挑欄位 SELECT」的各個呼叫點也必須可見（審查補題，2026-11-03）。

## 為什麼要有這題

`DEV_CASE_ACCESS` 加了 `owner_id_col="assigned_to"` 之後，`row_access.visible()` 讀的是那一列的 `assigned_to`；
列沒有這個欄位時 `_get()` 回 None ⇒ 不相符 ⇒ 靜默「看不到」（fail closed，不報錯）。
`list/get/update/status/logs` 用 `SELECT *`，欄位在；但有幾處是**手列欄位**的 SELECT，沒列 `assigned_to`：

- `routers/item_reads.py`（未讀標記：`SELECT id, created_by, sales_persons, planners`）
- `modules/crm/api.py::dev_crm_activity_stats`（接洽成效統計）
- `modules/analytics/api/dashboard.py`（停滯案件、動態牆）

結果：被指派人在案件清單看得到那一筆，但未讀標記、成效統計、首頁停滯提醒／動態牆都沒有它——
與「被指派人與業務／企劃同等」的裁示不符。本檔用 item_reads 與 activity-stats 兩個點釘住這個行為。
"""
import time
from datetime import date, datetime

import db


def _login(client, make_user, username, role="sales", modules=("dev_crm",)):
    name, pw = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _seed_case_assigned_to(assignee_uid, creator_uid):
    """案件：建立者＝creator、業務／企劃名單空、assigned_to＝assignee；另放一筆已核准開發記錄。"""
    conn = db.get_db()
    try:
        now = datetime.now().isoformat()
        cur = conn.execute(
            "INSERT INTO dev_cases (case_name, created_by, created_at, updated_at, assigned_to) "
            "VALUES (?,?,?,?,?)", ("指派可見性案", creator_uid, now, now, assignee_uid))
        cid = cur.lastrowid
        conn.execute(
            "INSERT INTO dev_logs (case_id, log_date, log_by, channel, content, needs_approval, created_by, created_at) "
            "VALUES (?,?,?,?,?,0,?,?)", (cid, date.today().isoformat(), creator_uid, "電話", "x", creator_uid, now))
        conn.commit()
        return cid
    finally:
        conn.close()


def _audit(username, action, cid):
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO audit_log (at,user_id,username,display_name,action,target_type,target_id,target_label,detail) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(), None, username, username, action, "dev_case", str(cid), "", "{}"))
        conn.commit()
    finally:
        conn.close()


def _unread(client, h, keys):
    r = client.post("/api/reads/unread", json={"kind": "dev_case", "keys": [str(k) for k in keys]}, headers=h)
    assert r.status_code == 200, r.text
    return set(r.json()["unread"])


def test_assignee_sees_the_case_in_the_list_baseline(client, make_user):
    """正對照：被指派人在 SELECT * 的清單看得到——下面兩題的「看不到」才是缺口，不是測試本身設定錯。"""
    _login(client, make_user, "creator1")
    ha = _login(client, make_user, "assignee1")
    cid = _seed_case_assigned_to(_uid("assignee1"), _uid("creator1"))
    ids = [c["id"] for c in client.get("/api/dev-cases", headers=ha).json()]
    assert cid in ids


def test_assignee_gets_unread_marks_for_their_assigned_case(client, make_user):
    _login(client, make_user, "creator2")
    ha = _login(client, make_user, "assignee2")
    _login(client, make_user, "other2")
    cid = _seed_case_assigned_to(_uid("assignee2"), _uid("creator2"))
    _unread(client, ha, [cid])                       # 建立基準
    time.sleep(0.02)
    _audit("other2", "dev_case.update", cid)         # 別人動了它
    assert _unread(client, ha, [cid]) == {str(cid)}, "被指派人看得到這張案件，卻收不到它的未讀標記"


def test_assignee_activity_stats_counts_their_assigned_case(client, make_user):
    _login(client, make_user, "creator3")
    ha = _login(client, make_user, "assignee3")
    _seed_case_assigned_to(_uid("assignee3"), _uid("creator3"))
    r = client.get("/api/dev-crm/activity-stats", headers=ha)
    assert r.status_code == 200, r.text
    assert sum(d["count"] for d in r.json()["daily"]) == 1, "被指派人的接洽成效統計漏了自己被指派案件的記錄"
