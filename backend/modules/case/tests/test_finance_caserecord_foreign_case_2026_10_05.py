# -*- coding: utf-8 -*-
"""使用者裁示（第42班）：財務人員要能在**任何案件**登錄／修改收款——`PATCH /api/quotations/{no}/case-record` 的款項部分
對財務角色（與 superadmin）不受案件成員限制；非款項欄位維持「成員／管理員」。業務（非成員）仍然 403。"""
import json

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔的題打 M01（案件）的端點")

NO = "MQ-FCR-001"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed(owner):
    import db
    c = db.get_db()
    try:
        uid = c.execute("SELECT id FROM users WHERE username=?", (owner,)).fetchone()["id"]
        data = {"caseRecord": {
            "payment": {"items": [{"id": "p1", "type": "訂金款", "pct": 30, "amount": 30000, "received": False, "note": ""}]},
            "materials": [{"id": 11, "name": "原料", "qty": 1}], "contract": {"note": "原合約"}}}
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, deal_tag,"
                  " sales_person_id, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (NO, "已送出", "客", "案", json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00",
                   "已成案", uid, owner, "[]"))
        c.commit()
    finally:
        c.close()


def _cr():
    import db
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["caseRecord"]
    finally:
        c.close()


@pytest.fixture
def world(client, make_user):
    make_user("fcr_owner", role="sales")
    fin = make_user("fcr_fin", role="finance")
    other = make_user("fcr_other", role="sales")
    _seed("fcr_owner")
    return {"fin": _login(client, *fin), "other": _login(client, *other)}


def _patch(client, h, **body):
    return client.patch("/api/quotations/%s/case-record" % NO, headers=h, json=body)


def test_finance_on_a_foreign_case_legacy_format_saves_the_payment_part(client, world):
    cr = _cr()                                                  # 前端整包送出：非款項欄位與資料庫相同
    cr["payment"]["items"][0]["pct"] = 40
    cr["payment"]["items"][0]["amount"] = 40000
    r = _patch(client, world["fin"], case_record=cr)
    assert r.status_code == 200, r.text
    now = _cr()
    assert now["payment"]["items"][0]["amount"] == 40000 and now["payment"]["items"][0]["pct"] == 40
    assert now["materials"][0]["name"] == "原料" and now["contract"]["note"] == "原合約"


def test_finance_on_a_foreign_case_changed_non_payment_segment_is_403_not_silently_dropped(client, world):
    cr = _cr()
    cr["payment"]["items"][0]["pct"] = 40
    cr["materials"][0]["name"] = "被改的原料"                     # 非款項欄位不同 ⇒ 整筆 403（舊契約），款項也不寫
    r = _patch(client, world["fin"], case_record=cr)
    assert r.status_code == 403, r.text
    assert _cr()["payment"]["items"][0]["pct"] == 30 and _cr()["materials"][0]["name"] == "原料"


def test_finance_on_a_foreign_case_can_add_a_payment_period_and_receive(client, world):
    cr = _cr()
    cr["payment"]["items"].append({"id": "p2", "type": "尾款", "pct": 70, "amount": 70000, "received": False, "note": ""})
    assert _patch(client, world["fin"], case_record=cr).status_code == 200
    assert [i["id"] for i in _cr()["payment"]["items"]] == ["p1", "p2"]           # 款項結構可改（財務專屬）
    r = client.patch("/api/quotations/%s/payment/0" % NO, headers=world["fin"],
                     json={"received": True, "receivedAt": "2026-10-05", "actualAmount": 30000, "feeAmount": 0})
    assert r.status_code == 200, r.text                                            # 標記收款（mark_payment）本來就沒有擁有者限制


def test_finance_segment_format_only_payment_other_segments_still_403(client, world):
    cr = _cr()
    new_pay = json.loads(json.dumps(cr["payment"]))
    new_pay["items"][0]["note"] = "財務備註"
    ok = _patch(client, world["fin"], segments={"payment": new_pay}, base={"payment": cr["payment"]})
    assert ok.status_code == 200, ok.text
    bad = _patch(client, world["fin"], segments={"materials": [{"id": 11, "name": "x", "qty": 1}]},
                 base={"materials": cr["materials"]})
    assert bad.status_code == 403


def test_a_non_member_salesperson_is_still_refused(client, world):
    cr = _cr()
    cr["payment"]["items"][0]["note"] = "想改"
    r = _patch(client, world["other"], case_record=cr)
    assert r.status_code == 403
    assert _cr()["payment"]["items"][0]["note"] == ""
