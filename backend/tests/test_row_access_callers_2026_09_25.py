"""row_access 接到呼叫端之後的守門。

① 正式登錄的規則＝test_row_access_2026_09_25 驗過等價的那兩份（否則等價測試驗的是別的東西）
② 行為變更（2026-09-25 主持裁示，使用者裁示「對齊列表」）：全域搜尋與首頁動態牆的案件可見性
   改成與案件列表同一套——被指派者（assigned_user_ids）與 cashier 現在也看得到；外人仍看不到。
"""
import dataclasses
import json

from tests.test_row_access_2026_09_25 import CASE, DEV

QNO = "MQ-RA-0925"


def test_registered_rules_are_the_verified_ones():
    from helpers.quotations import CASE_ACCESS
    from modules.crm.api import DEV_CASE_ACCESS
    from helpers import row_access as ra
    assert dataclasses.replace(CASE_ACCESS, deny_message="") == dataclasses.replace(CASE, deny_message="")
    assert dataclasses.replace(DEV_CASE_ACCESS, deny_message="") == dataclasses.replace(DEV, deny_message="")
    assert ra._REGISTRY["case"] is CASE_ACCESS and ra._REGISTRY["dev_case"] is DEV_CASE_ACCESS


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _setup(client, make_user):
    """業務 owner 的案件，指派給 asg；cashier 持出納模組；outsider 什麼都不是。"""
    import db
    users = {name: make_user(username=f"ra_{name}", role="sales", modules=mods)
             for name, mods in (("owner", None), ("asg", None), ("outsider", None),
                                ("cash", ["dashboard", "quotation", "cashier"]))}
    owner_id, asg_id = _uid("ra_owner"), _uid("ra_asg")
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, sales_person_id, sales_person, assigned_user_ids)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (QNO, "已送出", "對齊測試客戶", "案", 100, 95, json.dumps({}), "2026-09-25T00:00:00",
             "2026-09-25T00:00:00", owner_id, "ra_owner", json.dumps([asg_id])))
        conn.execute("INSERT INTO case_updates (quote_no, author, content) VALUES (?,?,?)",
                     (QNO, "ra_owner", "對齊測試留言"))
        conn.commit()
    finally:
        conn.close()
    return {k: _login(client, *v) for k, v in users.items()}


def test_global_search_matches_case_list_rule(client, make_user):
    h = _setup(client, make_user)
    got = {}
    for who, hdr in h.items():
        r = client.get("/api/search", params={"q": "對齊測試客戶"}, headers=hdr)
        assert r.status_code == 200, r.text
        got[who] = any(x["quoteNo"] == QNO for x in r.json()["quotations"])
    assert got == {"owner": True, "asg": True, "cash": True, "outsider": False}


def test_activity_feed_matches_case_list_rule(client, make_user):
    h = _setup(client, make_user)
    got = {}
    for who, hdr in h.items():
        r = client.get("/api/dashboard/activity-feed", headers=hdr)
        assert r.status_code == 200, r.text
        got[who] = any(x.get("source") == "comment" and QNO in (x.get("link") or "")
                       for x in r.json()["items"])
    assert got == {"owner": True, "asg": True, "cash": True, "outsider": False}


def test_same_rule_as_case_list(client, make_user):
    """對照組：案件列表本身就是這個結果——搜尋與動態牆現在與它一致。"""
    h = _setup(client, make_user)
    got = {}
    for who, hdr in h.items():
        r = client.get("/api/quotations", headers=hdr)
        assert r.status_code == 200, r.text
        body = r.json()
        rows = body if isinstance(body, list) else (body.get("items") or body.get("quotations") or [])
        got[who] = any((x.get("quote_no") or x.get("quoteNo")) == QNO for x in rows)
    assert got == {"owner": True, "asg": True, "cash": True, "outsider": False}
