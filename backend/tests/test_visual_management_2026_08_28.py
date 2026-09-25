"""2026-08-28 視覺化管理優化：部門篩選擴大到案件執行看板／月支出（承攬商/料件）、
庫存水位燈號。"""
import json
from datetime import datetime


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_dept_setup(make_user):
    """建立兩個部門，各自一位業務員使用者，回傳 (dept_a_id, dept_b_id, sales_a_username, sales_b_username)。"""
    import db
    conn = db.get_db()
    try:
        now = datetime.now().isoformat()
        conn.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES (?,?,?)", ("測試處", 0, now))
        div_id = conn.execute("SELECT id FROM divisions WHERE name='測試處'").fetchone()["id"]
        conn.execute("INSERT INTO departments (division_id, name, sort_order, created_at) VALUES (?,?,?,?)",
                     (div_id, "A組", 0, now))
        conn.execute("INSERT INTO departments (division_id, name, sort_order, created_at) VALUES (?,?,?,?)",
                     (div_id, "B組", 1, now))
        dept_a = conn.execute("SELECT id FROM departments WHERE name='A組'").fetchone()["id"]
        dept_b = conn.execute("SELECT id FROM departments WHERE name='B組'").fetchone()["id"]
        conn.commit()
    finally:
        conn.close()

    sales_a, _ = make_user(username="salesA", role="sales")
    sales_b, _ = make_user(username="salesB", role="sales")
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET department_id=? WHERE username=?", (dept_a, sales_a))
        conn.execute("UPDATE users SET department_id=? WHERE username=?", (dept_b, sales_b))
        conn.commit()
    finally:
        conn.close()
    return dept_a, dept_b, sales_a, sales_b


def _insert_case_with_stage(quote_no, sales_username, total=100000):
    import db
    conn = db.get_db()
    try:
        sales_id = conn.execute("SELECT id FROM users WHERE username=?", (sales_username,)).fetchone()["id"]
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date, sales_person_id, sales_person) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", total, round(total / 1.05), "{}",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-01-05", sales_id, sales_username),
        )
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (quote_no, "測試階段", 0, 0, now, now),
        )
        conn.commit()
    finally:
        conn.close()


# ── 案件執行看板部門篩選 ────────────────────────────────────────────────────────

def test_stage_board_filters_by_department(client, make_user):
    admin_user, admin_pw = make_user(role="admin")
    token = _login(client, admin_user, admin_pw)
    dept_a, dept_b, sales_a, sales_b = _make_dept_setup(make_user)
    _insert_case_with_stage("MQ-BOARD-A01", sales_a)
    _insert_case_with_stage("MQ-BOARD-B01", sales_b)

    r = client.get(f"/api/quotations/stage-board?department_id={dept_a}", headers=_auth(token))
    assert r.status_code == 200, r.text
    quote_nos = {it["quoteNo"] for it in r.json()["items"]}
    assert "MQ-BOARD-A01" in quote_nos
    assert "MQ-BOARD-B01" not in quote_nos


def test_stage_board_without_department_shows_all(client, make_user):
    admin_user, admin_pw = make_user(role="admin")
    token = _login(client, admin_user, admin_pw)
    dept_a, dept_b, sales_a, sales_b = _make_dept_setup(make_user)
    _insert_case_with_stage("MQ-BOARD-A02", sales_a)
    _insert_case_with_stage("MQ-BOARD-B02", sales_b)

    r = client.get("/api/quotations/stage-board", headers=_auth(token))
    assert r.status_code == 200, r.text
    quote_nos = {it["quoteNo"] for it in r.json()["items"]}
    assert "MQ-BOARD-A02" in quote_nos
    assert "MQ-BOARD-B02" in quote_nos


# ── 月支出部門篩選（承攬商派發／料件進貨） ───────────────────────────────────────


# ── 庫存水位燈號 ────────────────────────────────────────────────────────────────

def _create_part(client, token, part_no, safety_stock):
    r = client.post("/api/parts", headers=_auth(token), json={
        "partNo": part_no, "name": "測試料件", "category": "其他", "safetyStock": safety_stock,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_update_part_preserves_safety_stock_when_omitted(client, make_user):
    """比照 brand 批次改名／Excel 匯入這類不知道 safetyStock 欄位的既有呼叫路徑——
    PUT 沒帶這個鍵時必須保留原值，不能被悄悄清零（見 update_part() docstring）。"""
    admin_user, admin_pw = make_user(role="admin")
    token = _login(client, admin_user, admin_pw)
    part_id = _create_part(client, token, "TESTPART-PRESERVE", safety_stock=25)

    r = client.put(f"/api/parts/{part_id}", headers=_auth(token), json={
        "name": "改名測試", "brand": "X", "unit": "台", "cost": 100, "category": "其他", "note": "",
    })
    assert r.status_code == 200, r.text

    r2 = client.get("/api/parts", headers=_auth(token))
    part = next(p for p in r2.json()["items"] if p["part_no"] == "TESTPART-PRESERVE")
    assert part["safety_stock"] == 25

    r3 = client.put(f"/api/parts/{part_id}", headers=_auth(token), json={
        "name": "改名測試2", "brand": "X", "unit": "台", "cost": 100, "category": "其他", "note": "",
        "safetyStock": 5,
    })
    assert r3.status_code == 200, r3.text
    r4 = client.get("/api/parts", headers=_auth(token))
    part2 = next(p for p in r4.json()["items"] if p["part_no"] == "TESTPART-PRESERVE")
    assert part2["safety_stock"] == 5
