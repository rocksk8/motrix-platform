"""2026-08-28（模組逐步檢查：使用者管理）：DELETE /api/users/{user_id} 原本沒有任何
關聯資料檢查，但 users.id 被多張表以 FK 引用（quotations.sales_person_id／
dev_cases.created_by／divisions.manager_user_id 等）且都沒定 ON DELETE 行為，硬刪除
有關聯資料的帳號原本會拋出未接住的 sqlite3.IntegrityError，被全域 exception handler
接成一個不明不白的「伺服器發生內部錯誤」500。修正：接住後回傳清楚的 409，並提示改用
「停用」（toggle_user_active，正規離職流程）。
"""
def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_delete_user_with_no_references_succeeds(client, make_user):
    su, su_pw = make_user(username="del_su1", role="superadmin")
    target, _ = make_user(username="del_target1", role="engineer")
    token = _login(client, su, su_pw)

    import db
    conn = db.get_db()
    target_id = conn.execute("SELECT id FROM users WHERE username='del_target1'").fetchone()["id"]
    conn.close()

    r = client.delete(f"/api/users/{target_id}", headers=_auth(token))
    assert r.status_code == 200, r.text


def test_delete_user_referenced_by_quotation_returns_409(client, make_user):
    su, su_pw = make_user(username="del_su2", role="superadmin")
    target, _ = make_user(username="del_target2", role="sales")
    token = _login(client, su, su_pw)

    import db
    conn = db.get_db()
    try:
        target_id = conn.execute("SELECT id FROM users WHERE username='del_target2'").fetchone()["id"]
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person_id) "
            "VALUES ('MQ-DELU-001','已送出','客戶','專案',1000,952,'{}','2026-01-01T00:00:00',"
            "'2026-01-01T00:00:00','', ?)",
            (target_id,),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.delete(f"/api/users/{target_id}", headers=_auth(token))
    assert r.status_code == 409, r.text
    assert "停用" in r.text

    conn = db.get_db()
    still_there = conn.execute("SELECT 1 FROM users WHERE id=?", (target_id,)).fetchone()
    conn.close()
    assert still_there is not None


def test_delete_user_referenced_by_department_manager_returns_409(client, make_user):
    su, su_pw = make_user(username="del_su3", role="superadmin")
    target, _ = make_user(username="del_target3", role="admin")
    token = _login(client, su, su_pw)

    import db
    conn = db.get_db()
    try:
        target_id = conn.execute("SELECT id FROM users WHERE username='del_target3'").fetchone()["id"]
        conn.execute(
            "INSERT INTO divisions (name, sort_order, created_at, manager_user_id) "
            "VALUES ('刪除測試處', 0, '2026-01-01T00:00:00', ?)", (target_id,),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.delete(f"/api/users/{target_id}", headers=_auth(token))
    assert r.status_code == 409, r.text
