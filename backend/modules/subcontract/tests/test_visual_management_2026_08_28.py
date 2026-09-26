"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_visual_management_2026_08_28.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
2026-08-28 視覺化管理優化：部門篩選擴大到案件執行看板／月支出（承攬商/料件）、
庫存水位燈號。
"""
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


# ── 月支出部門篩選（承攬商派發／料件進貨） ───────────────────────────────────────

def test_expenses_monthly_filters_contractor_and_material_by_department(client, make_user):
    admin_user, admin_pw = make_user(role="admin")
    token = _login(client, admin_user, admin_pw)
    dept_a, dept_b, sales_a, sales_b = _make_dept_setup(make_user)
    _insert_case_with_stage("MQ-EXP-A01", sales_a)
    _insert_case_with_stage("MQ-EXP-B01", sales_b)

    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, total_amount, "
            "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("MQ-EXP-A01", "2026-03-10", "amount", "[]", 10000, "completed",
             "2026-03-10T00:00:00", "2026-03-10T00:00:00"),
        )
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, total_amount, "
            "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("MQ-EXP-B01", "2026-03-11", "amount", "[]", 20000, "completed",
             "2026-03-11T00:00:00", "2026-03-11T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    r_all = client.get("/api/reports/expenses-monthly?year=2026", headers=_auth(token))
    assert r_all.status_code == 200, r_all.text
    march_all = next(m for m in r_all.json()["expenses"]["monthly"] if m["month"] == "2026-03")
    # 2026-09-24 AC2：預設權責口徑＝承攬商未稅（原本含稅 ×1.05）；本題驗的是部門篩選
    assert march_all["contractor"] == 10000 + 20000

    r_a = client.get(f"/api/reports/expenses-monthly?year=2026&department_id={dept_a}", headers=_auth(token))
    assert r_a.status_code == 200, r_a.text
    march_a = next(m for m in r_a.json()["expenses"]["monthly"] if m["month"] == "2026-03")
    assert march_a["contractor"] == 10000


# ── 庫存水位燈號 ────────────────────────────────────────────────────────────────

def _create_part(client, token, part_no, safety_stock):
    r = client.post("/api/parts", headers=_auth(token), json={
        "partNo": part_no, "name": "測試料件", "category": "其他", "safetyStock": safety_stock,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]
