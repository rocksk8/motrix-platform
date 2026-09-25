"""業務開發案的「改不了」（稽核 D M02-S2，2026-09-26）：原本只有「看不到」的題，修改端點的列權限沒有題目守。

同模組、同角色的外人（不是建立者、不在業務人員／規劃人員名單）：
- `PUT /api/dev-cases/{id}`（改內容）、`PATCH …/status`、`PATCH …/convert`、`POST …/logs`（新增開發記錄）⇒ 403，資料不變
- 刪除申請／核准、重新連結申請／核准：只准管理員（角色）⇒ 業務 403
正對照：建立者做同樣的事 ⇒ 成功。觀測點打在資料庫（`dev_cases`／`dev_logs`），不打回應文字。
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


def _case(cid):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT case_name, status, converted_quote_no FROM dev_cases WHERE id=?", (cid,)).fetchone()
        logs = conn.execute("SELECT COUNT(*) FROM dev_logs WHERE case_id=?", (cid,)).fetchone()[0]
        return dict(row), logs
    finally:
        conn.close()


def _seed_quote(no):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                     " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (no, "草稿", "客", "案", 0, 0, "{}", "t", "t"))
        conn.commit()
    finally:
        conn.close()


def _writes(client, h, cid, uid):
    """四種修改，回 {動作: status_code}。"""
    got = {}
    got["put"] = client.put(f"/api/dev-cases/{cid}", headers=h, json={"case_name": "改名", "customer_name": "稽核客戶"}).status_code
    got["status"] = client.patch(f"/api/dev-cases/{cid}/status", headers=h, json={"status": "暫擱置"}).status_code
    got["convert"] = client.patch(f"/api/dev-cases/{cid}/convert", headers=h, json={"quote_no": "MQ-S2-0926"}).status_code
    got["log"] = client.post(f"/api/dev-cases/{cid}/logs", headers=h,
                             data={"log_date": date.today().isoformat(), "log_by": str(uid), "content": "拜訪"}).status_code
    return got


def test_outsider_cannot_change_a_dev_case(client, make_user):
    owner = _login(client, make_user, "dcw_owner")
    out = _login(client, make_user, "dcw_out")
    r = client.post("/api/dev-cases", headers=owner, json={"case_name": "原名", "customer_name": "稽核客戶"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    _seed_quote("MQ-S2-0926")
    before = _case(cid)

    got = _writes(client, out, cid, _uid("dcw_out"))
    assert got == {"put": 403, "status": 403, "convert": 403, "log": 403}, got
    assert _case(cid) == before                                          # 資料不變

    for path, body in (("request-delete", {"reason": "x"}), ("request-relink-quote", {"quote_no": "", "reason": "x"})):
        assert client.post(f"/api/dev-cases/{cid}/{path}", headers=out, json=body).status_code == 403, path

    # 正對照：建立者做同樣的事都成功
    got = _writes(client, owner, cid, _uid("dcw_owner"))
    assert all(200 <= c < 300 for c in got.values()), got
    after, logs = _case(cid)
    assert after["case_name"] == "改名" and after["converted_quote_no"] == "MQ-S2-0926" and logs == before[1] + 1
