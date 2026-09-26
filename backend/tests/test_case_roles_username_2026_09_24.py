"""案件角色改存帳號（CM3，2026-09-24 使用者表單＋裁示）。

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


def test_migration_converts_unique_names_and_keeps_the_rest(client, make_user):
    make_user(username="rl_amy", role="sales"); _set_display("rl_amy", "王小美")
    make_user(username="rl_dup1", role="engineer"); _set_display("rl_dup1", "陳大同")
    make_user(username="rl_dup2", role="engineer"); _set_display("rl_dup2", "陳大同")
    _seed({"sales": "王小美", "executor": "陳大同", "filler": "離職的人"})
    _run_migration()
    r = _roles()
    assert r["sales"] == {"username": "rl_amy", "display": "王小美"}
    assert r["executor"] == "陳大同", "同名不猜，保留原值"
    assert r["filler"] == "離職的人", "查不到不猜，保留原值"


def test_migration_is_idempotent_and_leaves_objects_and_blanks(client, make_user):
    make_user(username="rl_bob", role="sales"); _set_display("rl_bob", "林小明")
    obj = {"username": "someone", "display": "舊名字"}
    _seed({"sales": obj, "executor": "", "filler": "林小明"})
    _run_migration()
    _run_migration()
    r = _roles()
    assert r["sales"] == obj and r["executor"] == ""
    assert r["filler"] == {"username": "rl_bob", "display": "林小明"}


def test_migration_does_not_touch_updated_at(client, make_user):
    import db
    make_user(username="rl_ua", role="sales"); _set_display("rl_ua", "張三")
    _seed({"sales": "張三"})
    _run_migration()
    conn = db.get_db()
    try:
        ua = conn.execute("SELECT updated_at FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0]
    finally:
        conn.close()
    assert ua == "2026-01-01T00:00:00", "升級轉換不是使用者的修改，不可以改到樂觀鎖的時間戳"


# ── 讀取端吃兩種形狀 ────────────────────────────────────────────────────────

def test_member_check_uses_username_after_rename(client, make_user):
    u = make_user(username="rl_exec", role="engineer")
    _set_display("rl_exec", "新名字")                 # 改名之後
    _seed({"executor": {"username": "rl_exec", "display": "舊名字"}})
    r = client.patch(f"/api/quotations/{NO}/case-record", headers=_login(client, *u), json={
        "segments": {"materials": [{"id": 1, "name": "x"}]}, "base": {"materials": []}})
    assert r.status_code == 200, r.text


def test_member_check_by_username_ignores_same_display_name(client, make_user):
    """物件形狀以 username 比對：同名的另一個人不會因為顯示名稱相同被放行。"""
    make_user(username="rl_real", role="engineer"); _set_display("rl_real", "同名")
    other = make_user(username="rl_same", role="engineer"); _set_display("rl_same", "同名")
    _seed({"executor": {"username": "rl_real", "display": "同名"}})
    r = client.patch(f"/api/quotations/{NO}/case-record", headers=_login(client, *other), json={
        "segments": {"materials": [{"id": 1, "name": "x"}]}, "base": {"materials": []}})
    assert r.status_code == 403, r.text


def test_change_history_and_summary_show_display_not_dict():
    from modules.case.api import quotations as q
    assert q._fmt_change_value({"username": "a", "display": "王小美"}) == "王小美"
    flat = q._flatten_case_record({"roles": {"sales": {"username": "a", "display": "王小美"}}})
    assert "王小美" in flat.values(), flat


# ── 未對應清單 ──────────────────────────────────────────────────────────────

def test_unmapped_list_for_superadmin(client, make_user):
    sa = make_user(username="rl_sa", role="superadmin")
    make_user(username="rl_d1", role="engineer"); _set_display("rl_d1", "重名")
    make_user(username="rl_d2", role="engineer"); _set_display("rl_d2", "重名")
    _seed({"sales": "重名", "executor": "查無此人", "filler": {"username": "x", "display": "y"}})
    r = client.get("/api/system/case-roles-unmapped", headers=_login(client, *sa))
    assert r.status_code == 200, r.text
    rows = {(x["quoteNo"], x["role"]): x for x in r.json()["items"]}
    assert rows[(NO, "sales")]["value"] == "重名" and "同名" in rows[(NO, "sales")]["reason"]
    assert rows[(NO, "executor")]["value"] == "查無此人" and "查無" in rows[(NO, "executor")]["reason"]
    assert (NO, "filler") not in rows


def test_unmapped_list_is_superadmin_only(client, make_user):
    u = make_user(username="rl_adm", role="admin")
    assert client.get("/api/system/case-roles-unmapped", headers=_login(client, *u)).status_code == 403
