"""業務開發案的 row_access 行為題（稽核 X-3，2026-09-25）。

兩個業務都持有 dev_crm 模組；owner 建案。外人：
- 列表（`GET /api/dev-cases`，`routers/dev_crm.py` list_dev_cases）看不到
- 單筆（`/api/dev-cases/{id}`）403
- 開發記錄列表（`/api/dev-cases/{id}/logs`）403
- 接洽成效統計（`/api/dev-crm/activity-stats`）不計入
owner 四者都看得到（正對照），列入業務人員的人也看得到（規則不是「只有建立者」）。
觀測點是 API 回應，不是頁面文字。
"""
from datetime import date


def _login(client, make_user, username, role="sales", modules=("dev_crm",)):
    name, pw = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _add_log(case_id, by):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO dev_logs (case_id, log_date, log_by, channel, content, needs_approval,"
                     " created_by, created_at) VALUES (?,?,?,?,?,0,?,?)",
                     (case_id, date.today().isoformat(), by, "電話", "拜訪", by, "t"))
        conn.commit()
    finally:
        conn.close()


def _stat_total(client, h):
    r = client.get("/api/dev-crm/activity-stats", headers=h)
    assert r.status_code == 200, r.text
    return sum(d["count"] for d in r.json()["daily"])


def test_outsider_cannot_see_dev_case_anywhere(client, make_user):
    owner = _login(client, make_user, "dca_owner")
    out = _login(client, make_user, "dca_out")
    member = _login(client, make_user, "dca_member")
    r = client.post("/api/dev-cases", headers=owner,
                    json={"case_name": "稽核開發案", "customer_name": "稽核客戶",
                          "sales_persons": [_uid("dca_member")]})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    _add_log(cid, _uid("dca_owner"))

    ids = lambda h: [c["id"] for c in client.get("/api/dev-cases", headers=h).json()]  # noqa: E731
    # 正對照：owner 與列入業務的人
    for h in (owner, member):
        assert cid in ids(h)
        assert client.get(f"/api/dev-cases/{cid}", headers=h).status_code == 200
        assert client.get(f"/api/dev-cases/{cid}/logs", headers=h).status_code == 200
        assert _stat_total(client, h) == 1
    # 外人：同模組、同角色，四條路徑都看不到
    assert cid not in ids(out)
    assert client.get(f"/api/dev-cases/{cid}", headers=out).status_code == 403
    assert client.get(f"/api/dev-cases/{cid}/logs", headers=out).status_code == 403
    assert _stat_total(client, out) == 0
