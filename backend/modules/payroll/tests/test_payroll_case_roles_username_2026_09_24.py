"""獎金自動帶入執行人員用帳號（需要本模組）。

（2026-09-26 自 tests/test_case_roles_username_2026_09_24.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
案件角色改存帳號（CM3，2026-09-24 使用者表單＋裁示）。

過去 caseRecord.roles 的 filler／sales／executor 存顯示名稱 ⇒ 改名／同名時獎金帶入、業績歸屬、
案件可見性出錯。改存 {"username", "display"}；舊資料升級時依使用者表轉換，**查不到或同名的不猜**，
保留原字串並列在「使用者管理」頁的清單（GET /api/system/case-roles-unmapped，superadmin）。
讀取端一律吃兩種形狀（物件、未轉換的舊字串）。
"""
import json

import pytest

NO = "MQ-ROLES-001"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _set_display(username, display):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET display_name=? WHERE username=?", (display, username))
        conn.commit()
    finally:
        conn.close()


def _seed(roles, quote_no=NO, sales_person_id=None):
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, sales_person_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "客", "案", 100, 95,
             json.dumps({"dealTag": "已成案", "caseRecord": {"roles": roles, "materials": []}}, ensure_ascii=False),
             now, now, "已成案", sales_person_id))
        conn.commit()
    finally:
        conn.close()


def _roles(quote_no=NO):
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()[0])
    finally:
        conn.close()
    return d["caseRecord"]["roles"]


# ── 升級轉換 ─────────────────────────────────────────────────────────────────

def _run_migration():
    import db
    conn = db.get_db()
    try:
        db._m116_case_roles_username(conn)
        conn.commit()
    finally:
        conn.close()


# ── 讀取端吃兩種形狀 ────────────────────────────────────────────────────────


def test_bonus_auto_executor_uses_username(client, make_user):
    import db
    from modules.payroll.api import bonus
    make_user(username="rl_bexec", role="engineer"); _set_display("rl_bexec", "現在的名字")
    _seed({"executor": {"username": "rl_bexec", "display": "當時的名字"}})
    conn = db.get_db()
    try:
        members, notes = bonus._auto_members(conn, NO)
    finally:
        conn.close()
    assert [m["username"] for m in members["project"]] == ["rl_bexec"], (members, notes)


def test_bonus_auto_executor_legacy_string_still_works(client, make_user):
    import db
    from modules.payroll.api import bonus
    make_user(username="rl_bold", role="engineer"); _set_display("rl_bold", "舊資料名")
    _seed({"executor": "舊資料名"})
    conn = db.get_db()
    try:
        members, _ = bonus._auto_members(conn, NO)
    finally:
        conn.close()
    assert [m["username"] for m in members["project"]] == ["rl_bold"]


# ── 未對應清單 ──────────────────────────────────────────────────────────────
