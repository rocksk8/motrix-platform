"""第42班（使用者裁示 2026-10-05）：款項期別（收款排程）的新增／刪除／調整＝財務角色／superadmin。
業務、管理員在後端被擋（PATCH /api/quotations/{no}/case-record 回 403「此帳號沒有財務檢視權限，不可新增、刪除或調整款項期別」），結構不變；財務角色可以。
"""
import json

import pytest

NO = "MQ-PPF-1"
MSG = "財務檢視權限"


def _login(client, cred):
    r = client.post("/api/auth/login", json={"username": cred[0], "password": cred[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _items():
    import db
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        return [i["id"] for i in d["caseRecord"]["payment"]["items"]]
    finally:
        c.close()


def _seed(owner, member=None):
    import db
    items = [{"id": 1, "type": "訂金", "pct": 30, "amount": 30000, "received": False},
             {"id": 2, "type": "尾款", "pct": 70, "amount": 70000, "received": False}]
    c = db.get_db()
    try:
        uid = c.execute("SELECT id FROM users WHERE username=?", (owner,)).fetchone()["id"]
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
                  " deal_tag, sales_person, sales_person_id, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (NO, "已送出", "客", "案", 100000, 95238, json.dumps({"dealTag": "已成案", "caseRecord": {"payment": {"items": items}}}, ensure_ascii=False),
                   "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", owner, uid, json.dumps([uid] + ([c.execute("SELECT id FROM users WHERE username=?", (member,)).fetchone()["id"]] if member else []))))
        c.commit()
    finally:
        c.close()


def _patch(client, h, items):
    return client.patch("/api/quotations/%s/case-record" % NO, headers=h, json={"case_record": {"payment": {"items": items}}})


@pytest.mark.parametrize("role", ["sales", "admin"])
def test_sales_and_admin_cannot_delete_add_or_reorder_payment_periods(client, make_user, role):
    u = make_user(username="ppf_" + role, role=role)
    _seed(u[0])
    h = _login(client, u)
    two = [{"id": 1, "type": "訂金", "pct": 30, "amount": 30000, "received": False}, {"id": 2, "type": "尾款", "pct": 70, "amount": 70000, "received": False}]
    for name, items in (("delete", two[:1]), ("add", two + [{"id": 3, "type": "驗收", "pct": 0, "amount": 0, "received": False}]), ("reorder", two[::-1])):
        r = _patch(client, h, items)
        assert r.status_code == 403 and MSG in r.text, (role, name, r.status_code, r.text[:200])
        assert _items() == [1, 2], "%s %s：被拒絕的修改不可改到結構" % (role, name)


def test_finance_role_can_delete_add_and_reorder_payment_periods_on_a_foreign_case(client, make_user):
    owner = make_user(username="ppf_owner", role="sales")
    fin = make_user(username="ppf_fin", role="finance")
    _seed(owner[0])      # 財務角色不是這個案件的成員（業務是別人）：使用者裁示財務角色可編輯任何案件的款項（case-record 款項部分不受成員限制，a5ac9b5e）
    h = _login(client, fin)
    two = [{"id": 1, "type": "訂金", "pct": 30, "amount": 30000, "received": False}, {"id": 2, "type": "尾款", "pct": 70, "amount": 70000, "received": False}]
    r = _patch(client, h, two[::-1])
    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert _items() == [2, 1]
    r = _patch(client, h, two[:1])
    assert r.status_code == 200, (r.status_code, r.text[:200])
    assert _items() == [1]
