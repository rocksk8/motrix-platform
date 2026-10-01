# -*- coding: utf-8 -*-
"""A29 稽核探針 R3：額外支出作廢／付款日覆寫的角色矩陣（第 29 班包 47db5613；不進倉庫）。"""
import json

import pytest


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def world(client, make_user):
    import db
    sa = make_user(username="p3_sa", role="superadmin")
    ad = make_user(username="p3_admin", role="admin", modules=["quotation", "case_manage", "cashier", "finance"])
    ca = make_user(username="p3_cashier", role="user", modules=["cashier", "quotation"])
    ap = make_user(username="p3_applicant", role="user", modules=["quotation", "case_manage"])
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='p3_applicant'").fetchone()[0]
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, deal_tag, sales_person, sales_person_id)"
                     " VALUES ('MQ-P3-1','已送出','客','案','{}','2026-09-01','2026-09-01','已成案','p3_applicant',?)", (uid,))
        for i, st in enumerate(["已核准", "已核准", "已核准", "草稿"], start=1):
            conn.execute(
                "INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no,"
                " files_json, created_by, created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name,"
                " status, approval_json, change_status, change_json) VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,?,'{}','','{}')",
                ("MQ-P3-1", "材料", "探針%d" % i, 1, "式", 1000, 1000, "", "2026-09-01", "", "p3_applicant", "申請人", "p3_applicant", "申請人",
                 "2026-09-01T00:00:00", "2026-09-01T00:00:00", "申請人", st))
        conn.commit()
        ids = [r[0] for r in conn.execute("SELECT id FROM case_extra_expenses ORDER BY id").fetchall()]
    finally:
        conn.close()
    h = {k: _login(client, v[0], v[1]) for k, v in (("sa", sa), ("ad", ad), ("ca", ca), ("ap", ap))}
    return client, h, ids


def _void(client, h, who, eid, reason="探針"):
    return client.post("/api/quotations/MQ-P3-1/extra-expenses/%d/void" % eid, headers=h[who], json={"reason": reason})


def _dates(client, h, who, eid, **body):
    return client.patch("/api/quotations/MQ-P3-1/extra-expenses/%d/dates" % eid, headers=h[who], json=body)


def test_void_only_superadmin(world):
    client, h, ids = world
    r = {}
    for who in ("ap", "ca", "ad"):
        r[who] = _void(client, h, who, ids[0]).status_code
    assert r == {"ap": 403, "ca": 403, "ad": 403}, r                      # 申請人／出納／admin 都不行
    assert _void(client, h, "sa", ids[0], reason="").status_code == 400       # 理由必填
    assert _void(client, h, "sa", ids[3]).status_code == 409                  # 草稿不可作廢
    ok = _void(client, h, "sa", ids[0])
    assert ok.status_code == 200, ok.text
    assert _void(client, h, "sa", ids[0]).status_code == 409                  # 重複作廢
    import db
    conn = db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='extra_expense.void'").fetchone()[0] == 1
    finally:
        conn.close()


def test_paid_date_rules(world):
    client, h, ids = world
    e = ids[1]
    assert _dates(client, h, "ap", e, paidDate="2026-09-10").status_code == 403           # 申請人不能自登付款日
    assert _dates(client, h, "ad", ids[3], paidDate="2026-09-10").status_code == 409     # 未核准不可登付款日
    first = _dates(client, h, "ad", e, paidDate="2026-09-10")
    assert first.status_code == 200, first.text                                          # 出納可首次登
    for who in ("ca", "ad", "ap"):                                                        # 已付款：改／清 只有 superadmin（ca 看不到本案＝404，同樣不是 200）
        assert _dates(client, h, who, e, paidDate="2026-09-11").status_code in (403, 404), who
        assert _dates(client, h, who, e, paidDate="").status_code in (403, 404), who
    assert _dates(client, h, "ad", e, paidDate="2026-09-11").status_code == 403              # admin 明確是 403（有權看、無權覆寫）
    ov = _dates(client, h, "sa", e, paidDate="2026-09-12")
    assert ov.status_code == 200, ov.text
    import db
    conn = db.get_db()
    try:
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='extra_expense.paid_date_override'").fetchone()[0] == 1
    finally:
        conn.close()
    assert _void(client, h, "sa", e).status_code == 409                                   # 已付款不可作廢
