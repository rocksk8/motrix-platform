"""2026-08-28（模組逐步檢查：案件代辦事項）：PUT 編輯內容原本不管代辦事項是否已
完成兩階段簽核（status='done'，stage1_approver/stage2_approver 都已簽）都能直接
覆蓋 text，但簽核紀錄不會跟著重置，變成畫面上顯示「某主管已核准」，但實際內容
早就被改過、根本沒被審過的情況。修正：內容真的有變動、且已進入/完成簽核流程時，
一併把 status/兩階段簽核紀錄重置回 pending，需要重新走一次簽核。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_case(quote_no):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 100000, 95238, "{}",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def _make_org(conn, dept_manager_id, div_manager_id, tag):
    conn.execute(f"INSERT INTO divisions (name, sort_order, created_at, manager_user_id) "
                 f"VALUES ('測試處{tag}', 0, '2026-01-01T00:00:00', ?)", (div_manager_id,))
    division_id = conn.execute(f"SELECT id FROM divisions WHERE name='測試處{tag}'").fetchone()["id"]
    conn.execute(f"INSERT INTO departments (division_id, name, sort_order, manager_user_id, created_at) "
                 f"VALUES (?, '測試部門{tag}', 0, ?, '2026-01-01T00:00:00')",
                 (division_id, dept_manager_id))
    department_id = conn.execute(f"SELECT id FROM departments WHERE name='測試部門{tag}'").fetchone()["id"]
    return division_id, department_id


def _setup_done_item(client, make_user, tag):
    """建好組織架構＋案件＋一項已通過兩階段簽核的代辦事項，回傳
    (eng_token, biz_token, quote_no, item_id)。"""
    import db

    eng_user, eng_pw = make_user(username=f"eng_mgr_{tag}", role="engineer")
    biz_user, biz_pw = make_user(username=f"biz_mgr_{tag}", role="sales")
    sales_user, _ = make_user(username=f"sales_{tag}", role="sales")
    quote_no = f"MQ-CAI-{tag}"

    conn = db.get_db()
    try:
        eng_id = conn.execute("SELECT id FROM users WHERE username=?", (f"eng_mgr_{tag}",)).fetchone()["id"]
        biz_id = conn.execute("SELECT id FROM users WHERE username=?", (f"biz_mgr_{tag}",)).fetchone()["id"]
        sales_id = conn.execute("SELECT id FROM users WHERE username=?", (f"sales_{tag}",)).fetchone()["id"]
        _, department_id = _make_org(conn, dept_manager_id=eng_id, div_manager_id=biz_id, tag=tag)
        conn.execute("UPDATE users SET department_id=? WHERE id=?", (department_id, sales_id))
        conn.commit()
    finally:
        conn.close()

    _make_case(quote_no)
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET sales_person_id=? WHERE quote_no=?", (sales_id, quote_no))
        conn.commit()
    finally:
        conn.close()

    eng_token = _login(client, eng_user, eng_pw)
    biz_token = _login(client, biz_user, biz_pw)

    r = client.post(f"/api/quotations/{quote_no}/action-items", headers=_auth(eng_token),
                     json={"text": "原始內容"})
    assert r.status_code == 201, r.text
    item_id = r.json()["id"]

    r = client.patch(f"/api/quotations/{quote_no}/action-items/{item_id}/approve",
                      headers=_auth(eng_token), json={"stage": 1})
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/quotations/{quote_no}/action-items/{item_id}/approve",
                      headers=_auth(biz_token), json={"stage": 2})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["status"] == "done"

    return eng_token, biz_token, quote_no, item_id


def test_editing_text_after_done_resets_approval(client, make_user):
    eng_token, biz_token, quote_no, item_id = _setup_done_item(client, make_user, "a")

    r = client.put(f"/api/quotations/{quote_no}/action-items/{item_id}", headers=_auth(eng_token),
                    json={"text": "改過的內容"})
    assert r.status_code == 200, r.text

    r = client.get(f"/api/quotations/{quote_no}/action-items", headers=_auth(eng_token))
    item = r.json()["items"][0]
    assert item["text"] == "改過的內容"
    assert item["status"] == "pending"
    assert item["stage1Approver"] is None
    assert item["stage1At"] is None
    assert item["stage2Approver"] is None
    assert item["stage2At"] is None


def test_saving_same_text_does_not_reset_approval(client, make_user):
    """內容其實沒變（例如前端誤觸存檔）不該無謂地打掉已完成的簽核。"""
    eng_token, biz_token, quote_no, item_id = _setup_done_item(client, make_user, "b")

    r = client.put(f"/api/quotations/{quote_no}/action-items/{item_id}", headers=_auth(eng_token),
                    json={"text": "原始內容"})
    assert r.status_code == 200, r.text

    r = client.get(f"/api/quotations/{quote_no}/action-items", headers=_auth(eng_token))
    item = r.json()["items"][0]
    assert item["status"] == "done"
    assert item["stage1Approver"] is not None
    assert item["stage2Approver"] is not None


def test_editing_text_while_pending_does_not_touch_approval_fields(client, make_user):
    admin_user, admin_pw = make_user(username="cai_admin_c", role="admin")
    quote_no = "MQ-CAI-c"
    _make_case(quote_no)
    token = _login(client, admin_user, admin_pw)

    r = client.post(f"/api/quotations/{quote_no}/action-items", headers=_auth(token),
                     json={"text": "初版"})
    item_id = r.json()["id"]

    r = client.put(f"/api/quotations/{quote_no}/action-items/{item_id}", headers=_auth(token),
                    json={"text": "改版"})
    assert r.status_code == 200, r.text

    r = client.get(f"/api/quotations/{quote_no}/action-items", headers=_auth(token))
    item = r.json()["items"][0]
    assert item["text"] == "改版"
    assert item["status"] == "pending"
