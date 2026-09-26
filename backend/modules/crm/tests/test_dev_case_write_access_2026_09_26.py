"""業務開發案的「改不了」（稽核 D M02-S2，2026-09-26）：原本只有「看不到」的題，修改端點的列權限沒有題目守。

同模組、同角色的外人（不是建立者、不在業務人員／規劃人員名單）：
- `PUT /api/dev-cases/{id}`（改內容）、`PATCH …/status`、`PATCH …/convert`、`POST …/logs`（新增開發記錄）⇒ 403，資料不變
- 刪除申請／核准、重新連結申請／核准：只准管理員（角色）⇒ 業務 403
  〔更正（稽核 D M02-S2 觀察）：本題只打了兩個**申請**端點，核准端點沒有外人題，也沒有「管理員成功」的正對照（分不出 403 是角色還是列權限）⇒ 補在 `test_request_and_approve_are_gated_by_role_not_row_access`〕
正對照：建立者做同樣的事 ⇒ 成功。觀測點打在資料庫（`dev_cases`／`dev_logs`），不打回應文字。
"""
from datetime import date


def _login(client, make_user, username, role="sales", modules=("dev_crm",)):
    name, pw = make_user(username=username, role=role, modules=None if modules is None else list(modules))  # None＝角色樣板
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


def _flags(cid):
    import db
    conn = db.get_db()
    try:
        return dict(conn.execute("SELECT pending_delete, is_deleted, pending_relink, converted_quote_no"
                                 " FROM dev_cases WHERE id=?", (cid,)).fetchone())
    finally:
        conn.close()


def test_request_and_approve_are_gated_by_role_not_row_access(client, make_user):
    """申請＝管理員以上、核准＝最高管理者（角色）；與列權限無關（稽核 D M02-S2 觀察，2026-09-26）。

    分辨「角色」與「列權限」：建立者（業務，有列權限）申請 ⇒ 403；管理員（不是建立者、不在名單）申請 ⇒ 成功。
    核准端點：外人／建立者／管理員 ⇒ 403 且資料不變；最高管理者 ⇒ 成功（正對照）。觀測點打在 `dev_cases`。
    """
    owner = _login(client, make_user, "dca_owner")
    out = _login(client, make_user, "dca_out")
    admin = _login(client, make_user, "dca_admin", role="admin", modules=None)
    sup = _login(client, make_user, "dca_sup", role="superadmin", modules=None)
    cid = client.post("/api/dev-cases", headers=owner, json={"case_name": "案", "customer_name": "稽核客戶"}).json()["id"]
    _seed_quote("MQ-S2-A")
    _seed_quote("MQ-S2-B")
    assert client.patch(f"/api/dev-cases/{cid}/convert", headers=owner, json={"quote_no": "MQ-S2-A"}).status_code == 200

    # 重新連結
    relink = {"quote_no": "MQ-S2-B", "reason": "x"}
    assert client.post(f"/api/dev-cases/{cid}/request-relink-quote", headers=owner, json=relink).status_code == 403
    assert _flags(cid)["pending_relink"] == 0                           # 有列權限的建立者也不行 ⇒ 擋的是角色
    assert client.post(f"/api/dev-cases/{cid}/request-relink-quote", headers=admin, json=relink).status_code == 200
    assert _flags(cid)["pending_relink"] == 1                           # 管理員不在名單也可以 ⇒ 不看列權限
    for who, h in (("外人", out), ("建立者", owner), ("管理員", admin)):
        assert client.post(f"/api/dev-cases/{cid}/approve-relink-quote", headers=h,
                           json={"approve": True}).status_code == 403, who
        assert _flags(cid)["pending_relink"] == 1 and _flags(cid)["converted_quote_no"] == "MQ-S2-A", who
    assert client.post(f"/api/dev-cases/{cid}/approve-relink-quote", headers=sup, json={"approve": True}).status_code == 200
    assert _flags(cid)["pending_relink"] == 0 and _flags(cid)["converted_quote_no"] == "MQ-S2-B"

    # 刪除
    assert client.post(f"/api/dev-cases/{cid}/request-delete", headers=owner, json={"reason": "x"}).status_code == 403
    assert _flags(cid)["pending_delete"] == 0
    assert client.post(f"/api/dev-cases/{cid}/request-delete", headers=admin, json={"reason": "x"}).status_code == 200
    assert _flags(cid)["pending_delete"] == 1
    for who, h in (("外人", out), ("建立者", owner), ("管理員", admin)):
        assert client.post(f"/api/dev-cases/{cid}/approve-delete", headers=h, json={"approve": True}).status_code == 403, who
        assert _flags(cid)["is_deleted"] == 0 and _flags(cid)["pending_delete"] == 1, who
    assert client.post(f"/api/dev-cases/{cid}/approve-delete", headers=sup, json={"approve": True}).status_code == 200
    assert _flags(cid)["is_deleted"] == 1
