# -*- coding: utf-8 -*-
"""被指派人（assigned_to）在「自己挑欄位 SELECT」的各個呼叫點也必須可見（審查補題，2026-11-03；
2026-11-04 列車整合後獨立稽核補第 5 處＋前兩處的 HTTP 端點題，見 docs/platform/audit/AUDIT-pm-sub-t73.md A-1／A-2）。

## 為什麼要有這題

`DEV_CASE_ACCESS` 加了 `owner_id_col="assigned_to"` 之後，`row_access.visible()` 讀的是那一列的 `assigned_to`；
列沒有這個欄位時 `_get()` 回 None ⇒ 不相符 ⇒ 靜默「看不到」（fail closed，不報錯）。
`list/get/update/status/logs` 用 `SELECT *`，欄位在；但有幾處是**手列欄位**的 SELECT，沒列 `assigned_to`：

- `routers/item_reads.py`（未讀標記：`SELECT id, created_by, sales_persons, planners`）
- `modules/crm/api.py::dev_crm_activity_stats`（接洽成效統計）
- `modules/analytics/api/dashboard.py`（停滯案件 `/api/dashboard/ops-alerts`、動態牆 `/api/dashboard/activity-feed`）
- `modules/crm/api.py::_check_dev_case_stale`（每日排程通知；獨立稽核補發現，本檔原先漏這一處）

結果：被指派人在案件清單看得到那一筆，但未讀標記、成效統計、首頁停滯提醒／動態牆、每日停滯排程通知都沒有它——
與「被指派人與業務／企劃同等」的裁示不符。本檔用 item_reads、activity-stats、ops-alerts、activity-feed、
每日停滯排程通知五個點釘住這個行為。
"""
import time
from datetime import date, datetime, timedelta

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


def _make_stale(cid, days_ago):
    """把案件的 updated_at 往回調，模擬「洽談中已停滯 N 天」（不碰 status，維持種子資料的『洽談中』）。"""
    conn = db.get_db()
    try:
        then = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE dev_cases SET updated_at=? WHERE id=?", (then, cid))
        conn.commit()
    finally:
        conn.close()


def test_assignee_sees_their_stale_case_in_dashboard_ops_alerts(client, make_user):
    """`/api/dashboard/ops-alerts` 的 `devStale` 手列欄位 SELECT 補了 `assigned_to`（CHANGELOG analytics 1.0.45）——
    這裡用真正的端點呼叫釘住，不只是讀碼推論。"""
    _login(client, make_user, "creator4")
    ha = _login(client, make_user, "assignee4")
    cid = _seed_case_assigned_to(_uid("assignee4"), _uid("creator4"))
    _make_stale(cid, 31)
    r = client.get("/api/dashboard/ops-alerts", headers=ha)
    assert r.status_code == 200, r.text
    ids = [d["id"] for d in r.json()["devStale"]]
    assert cid in ids, "被指派人在首頁停滯提醒（ops-alerts）看不到自己被指派的停滯案件"


def test_assignee_sees_their_dev_log_in_dashboard_activity_feed(client, make_user):
    """`/api/dashboard/activity-feed` 業務開發區塊的 `dc_map` SELECT 補了 `assigned_to`（CHANGELOG analytics 1.0.45）——
    這裡用真正的端點呼叫釘住，不只是讀碼推論。"""
    _login(client, make_user, "creator5")
    ha = _login(client, make_user, "assignee5")
    cid = _seed_case_assigned_to(_uid("assignee5"), _uid("creator5"))
    r = client.get("/api/dashboard/activity-feed", headers=ha)
    assert r.status_code == 200, r.text
    found = [it for it in r.json()["items"] if it.get("source") == "dev_log" and it.get("itemLabel") == "指派可見性案"]
    assert found, "被指派人在首頁動態牆（activity-feed）看不到自己被指派案件的開發記錄"


def test_assignee_gets_the_daily_stale_reminder_notification(client, make_user):
    """每日排程 `_check_dev_case_stale`（審查發現本檔原先漏掉的第 5 處）：手列欄位 SELECT 現在補了
    `assigned_to`，且被指派人與業務／企劃同等一律收提醒（不只是 sales_persons/planners/created_by 都沒人時的備援）。"""
    from modules.crm import api as crm

    _login(client, make_user, "creator6")
    _login(client, make_user, "assignee6")
    cid = _seed_case_assigned_to(_uid("assignee6"), _uid("creator6"))
    _make_stale(cid, 31)

    crm._check_dev_case_stale()

    conn = db.get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE username=? AND type='dev_case_stale' AND ref_id=?",
            ("assignee6", str(cid))).fetchall()
    finally:
        conn.close()
    assert rows, "被指派人沒有收到每日停滯排程的站內通知（_check_dev_case_stale 漏列 assigned_to）"
