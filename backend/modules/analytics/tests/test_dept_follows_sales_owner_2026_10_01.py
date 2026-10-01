# -*- coding: utf-8 -*-
"""2026-10-01 使用者裁示：案件的部門跟「業務負責人」（caseRecord.roles.sales），不是開單者。

業務員績效（依 roles.sales）與部門績效、部門篩選、未收款項、收款異常、首頁統計必須同一口徑：
- roles.sales 是帳號 ⇒ 該帳號的部門；
- 只有名字／查無帳號 ⇒ 「未分類」（不悄悄退回開單者的部門）；
- roles.sales 沒填 ⇒ 開單者的部門（與過去相同）。
正向控制：把 `_case_dept` 改回開單者口徑（見最後一題）⇒ 對帳題會紅。
"""
import json

import pytest

PERIOD = ("2026-01-01", "2026-12-31")


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _setup(client, make_user):
    """部門 A（alice）、B（bob；開單者）。回 (admin 標頭, 部門 A id, 部門 B id, alice id, bob id)。"""
    import db
    admin = make_user("dso_admin", role="superadmin")
    alice = make_user("dso_alice", role="sales")
    bob = make_user("dso_bob", role="sales")
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO divisions (name, created_at) VALUES ('測試處', '2026-01-01T00:00:00')")
        div = conn.execute("SELECT id FROM divisions WHERE name='測試處'").fetchone()[0]
        for n in ("部門A", "部門B"):
            conn.execute("INSERT INTO departments (division_id, name, created_at) VALUES (?,?,'2026-01-01T00:00:00')", (div, n))
        a = conn.execute("SELECT id FROM departments WHERE name='部門A'").fetchone()[0]
        b = conn.execute("SELECT id FROM departments WHERE name='部門B'").fetchone()[0]
        ids = {}
        for u, d, disp in (("dso_alice", a, "愛麗絲"), ("dso_bob", b, "鮑伯")):
            conn.execute("UPDATE users SET department_id=?, display_name=? WHERE username=?", (d, disp, u))
            ids[u] = conn.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return _login(client, admin[0], admin[1]), a, b, ids["dso_alice"], ids["dso_bob"]


def _case(quote_no, opener_id, sales_role, total, received=False):
    import db
    cr = {"payment": {"items": [{"label": "全額", "amount": total, "received": received,
                                 "expectedReceiptDate": "2026-03-10"}]}}
    if sales_role is not None:
        cr["roles"] = {"sales": sales_role}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
            "created_at, updated_at, deal_tag, quote_date, sales_person_id, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "客戶", "專案", total, round(total / 1.05),
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "2026-01-05", opener_id, "開單者"))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def world(client, make_user):
    h, a, b, alice, bob = _setup(client, make_user)
    # 1 開單者 bob、業務負責 alice（帳號）⇒ 部門 A
    _case("DSO-1", bob, {"username": "dso_alice", "display": "愛麗絲"}, 100000)
    # 2 開單者 bob、業務負責只有名字且查無帳號 ⇒ 未分類（不退回 bob 的部門 B）
    _case("DSO-2", bob, "沒有帳號的人", 20000)
    # 3 沒填 roles.sales ⇒ 開單者 bob 的部門 B
    _case("DSO-3", bob, None, 3000)
    return client, h, a, b


def _dept_totals(data):
    return {d["deptName"]: d["totalAmount"] for d in data["deptPerf"]}


def test_dept_total_follows_sales_owner_not_opener(world):
    from modules.analytics.api import reports as R
    _client, _h, _a, _b = world
    data = R._collect(*PERIOD)
    assert _dept_totals(data) == {"部門A": 100000, "未分類": 20000, "部門B": 3000}


def test_dept_totals_reconcile_with_sales_performance_rows(world):
    """兩表並排看：部門 A 的合計＝業務員績效裡屬於部門 A 帳號的列合計；名字型歸屬的列 ⇒ 未分類。"""
    from modules.analytics.api import reports as R
    data = R._collect(*PERIOD)
    by_name = {s["salesPerson"]: s["totalAmount"] for s in data["salesPerf"]}
    dept = _dept_totals(data)
    assert dept["部門A"] == by_name["愛麗絲"]
    assert dept["未分類"] == by_name["沒有帳號的人"]
    assert sum(dept.values()) == sum(by_name.values())


def test_owner_with_no_account_is_unclassified_and_not_in_openers_dept(world):
    from modules.analytics.api import reports as R
    _client, _h, a, b = world
    in_b = {c["quoteNo"] for c in R._collect(*PERIOD, department_id=b)["cases"]} if "cases" in R._collect(*PERIOD) else None
    items_b = {i["quoteNo"] for i in R._collect_unreceived_items("2026-03-01", "2026-03-31", b)}
    assert items_b == {"DSO-3"}                                         # 只有「沒填業務負責」的案件仍跟開單者
    assert {i["quoteNo"] for i in R._collect_unreceived_items("2026-03-01", "2026-03-31", a)} == {"DSO-1"}
    assert in_b is None or "DSO-2" not in in_b


def test_dashboard_department_filter_uses_sales_owner(world):
    client, h, a, b = world
    r = client.get("/api/dashboard/stats", headers=h, params={"department_id": a})
    assert r.status_code == 200, r.text
    assert r.json()["activeCases"] == 1                                 # 只有 DSO-1（業務負責 alice）
    r = client.get("/api/dashboard/stats", headers=h, params={"department_id": b})
    assert r.json()["activeCases"] == 1                                 # 只有 DSO-3；DSO-2 是未分類、DSO-1 不再算 B


def test_payment_anomalies_department_filter_uses_sales_owner(world):
    from modules.analytics.api import reports as R
    _client, _h, a, b = world
    import db
    conn = db.get_db()
    try:                                                                 # 製造異常：已有收款日期但沒勾已收款
        for no in ("DSO-1", "DSO-2", "DSO-3"):
            d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
            d["caseRecord"]["payment"]["items"][0]["receivedDate"] = "2026-03-11"
            conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), no))
        conn.commit()
    finally:
        conn.close()
    assert {i["quoteNo"] for i in R._collect_payment_anomalies(a)} <= {"DSO-1"}
    assert "DSO-1" not in {i["quoteNo"] for i in R._collect_payment_anomalies(b)}
    assert "DSO-2" not in {i["quoteNo"] for i in R._collect_payment_anomalies(b)}


def test_positive_control_opener_rule_would_break_reconciliation(world, monkeypatch):
    """正向控制：把部門改回「開單者」口徑，對帳題的前提（部門 A 有 100000）就不成立 ⇒ 上面的題會紅。"""
    from modules.analytics.api import reports as R

    def opener_rule(cr, row, name_index, user_by_id):
        info = user_by_id.get(row["sales_person_id"])
        return (info["deptId"], info["deptName"]) if info else (None, "未分類")

    monkeypatch.setattr(R, "_case_dept", opener_rule)
    assert _dept_totals(R._collect(*PERIOD)) != {"部門A": 100000, "未分類": 20000, "部門B": 3000}


def test_department_filter_survives_opener_without_account_or_name(client, make_user):
    """回歸：開單者沒有帳號（sales_person_id 為空）且沒填業務負責 ⇒ `_case_sales_owner` 會讀 sales_person；各彙總查詢都得選出這欄（缺欄＝IndexError）。"""
    import db
    from modules.analytics.api import reports as R
    h, a, b, _alice, _bob = _setup(client, make_user)
    _case("DSO-9", None, None, 5000)
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET sales_person='' WHERE quote_no='DSO-9'")
        conn.commit()
    finally:
        conn.close()
    assert R._collect_expenses(2026, a)["monthly"] is not None
    assert client.get("/api/dashboard/monthly", headers=h, params={"department_id": a}).status_code == 200
    assert client.get("/api/dashboard/stats", headers=h, params={"department_id": a}).status_code == 200


def test_activity_feed_department_filter_uses_sales_owner(world):
    """首頁最新動態的部門篩選（案件留言）也跟業務負責人：DSO-1 的留言屬部門 A、不屬開單者的部門 B。"""
    import db
    client, h, a, b = world
    conn = db.get_db()
    try:
        for no in ("DSO-1", "DSO-2", "DSO-3"):
            conn.execute("INSERT INTO case_updates (quote_no, author, content, created_at) VALUES (?,?,?,?)",
                         (no, "dso_admin", "留言 " + no, "2026-03-01T09:00:00"))
        conn.commit()
    finally:
        conn.close()

    def comments(dept):
        r = client.get("/api/dashboard/activity-feed", headers=h, params={"department_id": dept})
        assert r.status_code == 200, r.text
        return {i["id"] for i in r.json().get("items", []) if i.get("source") == "comment"}

    assert len(comments(a)) == 1 and len(comments(b)) == 1 and comments(a) != comments(b)
