"""專案管理併入案件管理（2026-08-26）整合測試。涵蓋新增的三塊能力：
- case_action_items 代辦事項 CRUD + 工程主管/業務主管兩階段簽核
  （routers/case_action_items.py，透過案件 sales_person_id → users.department_id
  → departments/divisions.manager_user_id 查主管，見該檔 _case_approver_ids()）
- work_logs 照片上傳/刪除（routers/system.py 新增端點，沿用 projects.py 既有的
  GPS/浮水印處理管線）
- quotations.assigned_user_ids 成員分配 PATCH 端點

以及 db.py::_m062_case_project_merge() 一次性資料搬移邏輯的單元測試。
PDF 產生走 Edge headless（本機測試環境沒有，既有慣例見
test_reports_export_expenses.py），這裡只測 _project_execution_report_data()/
_build_project_execution_report_html() 純 Python 組裝部分。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_case(quote_no="MQ-PJM-001", sales_person_id=None):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 100000, 95238, "{}",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", sales_person_id),
        )
        conn.commit()
    finally:
        conn.close()


def _make_org(conn, dept_manager_id, div_manager_id):
    """建立一個處＋部門，處主管/部門主管各自指向傳入的 user id，回傳
    (division_id, department_id)。"""
    conn.execute("INSERT INTO divisions (name, sort_order, created_at, manager_user_id) "
                 "VALUES ('測試處', 0, '2026-01-01T00:00:00', ?)", (div_manager_id,))
    division_id = conn.execute("SELECT id FROM divisions WHERE name='測試處'").fetchone()["id"]
    conn.execute("INSERT INTO departments (division_id, name, sort_order, manager_user_id, created_at) "
                 "VALUES (?, '測試部門', 0, ?, '2026-01-01T00:00:00')",
                 (division_id, dept_manager_id))
    department_id = conn.execute("SELECT id FROM departments WHERE name='測試部門'").fetchone()["id"]
    return division_id, department_id


# ── 代辦事項 CRUD + 兩階段簽核 ────────────────────────────────────────────────

def test_action_item_two_stage_approval(client, make_user):
    import db

    eng_user, eng_pw = make_user(username="eng_mgr", role="engineer")
    biz_user, biz_pw = make_user(username="biz_mgr", role="sales")
    sales_user, _ = make_user(username="salesperson", role="sales")
    outsider, outsider_pw = make_user(username="outsider", role="engineer")

    conn = db.get_db()
    try:
        eng_id = conn.execute("SELECT id FROM users WHERE username='eng_mgr'").fetchone()["id"]
        biz_id = conn.execute("SELECT id FROM users WHERE username='biz_mgr'").fetchone()["id"]
        sales_id = conn.execute("SELECT id FROM users WHERE username='salesperson'").fetchone()["id"]
        _, department_id = _make_org(conn, dept_manager_id=eng_id, div_manager_id=biz_id)
        conn.execute("UPDATE users SET department_id=? WHERE id=?", (department_id, sales_id))
        conn.commit()
    finally:
        conn.close()

    _make_case("MQ-PJM-001", sales_person_id=sales_id)

    eng_token = _login(client, eng_user, eng_pw)
    biz_token = _login(client, biz_user, biz_pw)
    outsider_token = _login(client, outsider, outsider_pw)

    # 新增代辦事項（任何登入者皆可，比照原專案管理寬鬆權限）
    r = client.post("/api/quotations/MQ-PJM-001/action-items", headers=_auth(outsider_token),
                     json={"text": "確認防火牆規則"})
    assert r.status_code == 201, r.text
    item_id = r.json()["id"]

    # 業務主管不能先簽第二階段
    r = client.patch(f"/api/quotations/MQ-PJM-001/action-items/{item_id}/approve",
                      headers=_auth(biz_token), json={"stage": 2})
    assert r.status_code == 400, r.text

    # 非部門/處主管、也沒有 project_approve_eng 權限 → 403
    r = client.patch(f"/api/quotations/MQ-PJM-001/action-items/{item_id}/approve",
                      headers=_auth(outsider_token), json={"stage": 1})
    assert r.status_code == 403, r.text

    # 部門主管簽第一階段
    r = client.patch(f"/api/quotations/MQ-PJM-001/action-items/{item_id}/approve",
                      headers=_auth(eng_token), json={"stage": 1})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["status"] == "stage1_done"

    # 處主管簽第二階段
    r = client.patch(f"/api/quotations/MQ-PJM-001/action-items/{item_id}/approve",
                      headers=_auth(biz_token), json={"stage": 2})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["status"] == "done"

    # list 端點回傳的 canApproveEng/canApproveBiz 依登入者身分正確反映
    r = client.get("/api/quotations/MQ-PJM-001/action-items", headers=_auth(eng_token))
    items = r.json()["items"]
    assert items[0]["canApproveEng"] is True
    assert items[0]["canApproveBiz"] is False

    # 非 admin 不能刪除
    r = client.delete(f"/api/quotations/MQ-PJM-001/action-items/{item_id}", headers=_auth(outsider_token))
    assert r.status_code == 403, r.text


# ── 成員分配 ─────────────────────────────────────────────────────────────────

def test_assigned_users_patch(client, make_user):
    admin_user, admin_pw = make_user(username="admin1", role="admin")
    viewer_user, viewer_pw = make_user(username="viewer1", role="viewer")
    _make_case("MQ-PJM-002")

    admin_token = _login(client, admin_user, admin_pw)
    viewer_token = _login(client, viewer_user, viewer_pw)

    r = client.patch("/api/quotations/MQ-PJM-002/assigned-users", headers=_auth(viewer_token),
                      json={"user_ids": [1]})
    assert r.status_code == 403, r.text

    r = client.patch("/api/quotations/MQ-PJM-002/assigned-users", headers=_auth(admin_token),
                      json={"user_ids": [1, 2]})
    assert r.status_code == 200, r.text

    r = client.get("/api/quotations/MQ-PJM-002", headers=_auth(admin_token))
    assert r.json()["assigned_user_ids"] == [1, 2]


# ── 工作日誌照片上傳/刪除 ─────────────────────────────────────────────────────

def test_work_log_photo_upload_and_delete(client, make_user):
    username, password = make_user(username="wl_user", role="engineer")
    _make_case("MQ-PJM-003")
    token = _login(client, username, password)

    import db
    uid = None
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='wl_user'").fetchone()["id"]
    finally:
        conn.close()

    r = client.post("/api/work-logs", headers=_auth(token), json={
        "log_date": "2026-08-26", "user_id": uid, "content": "現場測試", "case_no": "MQ-PJM-003",
    })
    assert r.status_code == 200, r.text
    log_id = r.json()["id"]

    r = client.post(f"/api/work-logs/{log_id}/photos", headers=_auth(token),
                     files=[("files", ("site.jpg", b"fake-image-bytes", "image/jpeg"))])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["added"] == 1
    photo_id = body["photos"][0]["id"]

    # 動態 feed 應該看得到這筆工作日誌與其照片
    r = client.get("/api/quotations/MQ-PJM-003/updates", headers=_auth(token))
    wl_items = [it for it in r.json() if it.get("source") == "work_log"]
    assert len(wl_items) == 1
    assert len(wl_items[0]["photos"]) == 1

    r = client.delete(f"/api/work-logs/{log_id}/photos/{photo_id}", headers=_auth(token))
    assert r.status_code == 200, r.text

    r = client.get("/api/work-logs", headers=_auth(token), params={"case_no": "MQ-PJM-003"})
    assert r.json()[0]["photos"] == []


# ── 專案執行報告：資料組裝／HTML 組裝（不需要 Edge headless）──────────────────

def test_project_execution_report_data_and_html(client, make_user):
    make_user(username="rp_user", role="admin")
    _make_case("MQ-PJM-004")

    conn_import_check = __import__("db")
    conn = conn_import_check.get_db()
    try:
        now = "2026-08-26T00:00:00"
        conn.execute(
            "INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)", ("MQ-PJM-004", "現場勘查", 0, 1, now, now, now),
        )
        conn.execute(
            "INSERT INTO case_action_items (quote_no, text, status, sort_order, created_at, created_by, updated_at) "
            "VALUES (?,?,?,?,?,?,?)", ("MQ-PJM-004", "確認線材規格", "pending", 0, now, "tester", now),
        )
        conn.commit()
    finally:
        conn.close()

    from pdf_gen import _project_execution_report_data, _build_project_execution_report_html
    data = _project_execution_report_data("MQ-PJM-004")
    assert data["quoteNo"] == "MQ-PJM-004"
    assert len(data["stages"]) == 1
    assert len(data["actionItems"]) == 1

    html = _build_project_execution_report_html(data)
    assert "專案執行報告" in html
    assert "現場勘查" in html
    assert "確認線材規格" in html


# ── db.py::_m062_case_project_merge() 一次性資料搬移 ─────────────────────────

def test_m062_migrates_project_logs_and_action_items(client):
    """直接呼叫 migration 函式本身（而非透過 init_db 全套 pipeline，因為新鮮
    測試 DB 的 projects 表本來就是空的），驗證舊 projects/project_logs 資料能
    正確搬進 work_logs/case_action_items。"""
    import db

    conn = db.get_db()
    try:
        # 刻意不建立 display_name='舊記錄人' 的帳號，讓 migration 的 best-effort
        # 比對找不到人、走 fallback superadmin 分支並在內容前面註記原記錄人姓名。
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at, must_change_password) "
            "VALUES ('sa_fallback','x','測試超管','superadmin','[]',1,'2026-01-01T00:00:00',0)"
        )
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("MQ-PJM-LEGACY", "已送出", "舊客戶", "舊專案", 1000, 950, "{}",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        cur = conn.execute(
            "INSERT INTO projects (code, name, status, description, linked_cases, created_at, created_by, "
            "data_json, assigned_user_ids) VALUES ('PR-9001','舊專案','進行中','', ?, ?, ?, '{}', '[]')",
            (json.dumps(["MQ-PJM-LEGACY"]), "2026-01-01T00:00:00", "舊記錄人"),
        )
        project_id = cur.lastrowid
        conn.execute(
            "INSERT INTO project_logs (project_id, log_date, work_content, attendees, action_items, "
            "materials_used, photos, log_status, created_at, created_by, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, "2026-08-01", "完成現場配線", "[]",
             json.dumps([{"id": "abc123", "text": "待確認", "status": "pending"}]),
             "[]", "[]", "draft", "2026-08-01T09:00:00", "舊記錄人", "2026-08-01T09:00:00"),
        )
        conn.commit()

        from db import _m062_case_project_merge
        _m062_case_project_merge(conn)

        wl = conn.execute(
            "SELECT * FROM work_logs WHERE case_no='MQ-PJM-LEGACY'"
        ).fetchall()
        assert len(wl) == 1
        assert "完成現場配線" in wl[0]["content"]
        assert "舊記錄人" in wl[0]["content"]  # 找不到對應帳號時註記原記錄人姓名

        items = conn.execute(
            "SELECT * FROM case_action_items WHERE quote_no='MQ-PJM-LEGACY'"
        ).fetchall()
        assert len(items) == 1
        assert items[0]["text"] == "待確認"
        assert items[0]["status"] == "pending"
    finally:
        conn.close()
