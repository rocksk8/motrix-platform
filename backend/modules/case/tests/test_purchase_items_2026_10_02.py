# -*- coding: utf-8 -*-
"""32-S1：請購／採購單連結案件品項——挑選器清單、已用量、剩餘量、超計畫判定（純函式）與 `GET …/purchase-items`。
（設計 docs/platform/plans/PR-PO-CASE-ITEM-LINK-DESIGN.md §2.1／§2.2／§2.4；Q3：請購只提示、上限只擋採購單——擋的動作在 S2。）"""
import json

import pytest

import db
from modules.case import purchase_items as PI

NO = "MQ-PI-1"
Q = {"items": [
    {"id": "h1", "type": "header", "description": "標題"},
    {"id": "a", "description": "交換器", "brand": "X", "qty": 10, "unit": "台", "cost": 1000},
    {"id": "b", "description": "線材", "qty": 100, "unit": "米", "cost": 5},
    {"id": "", "description": "沒有 id"},
    {"id": "c", "description": "   "},
]}


def _row(i, kind, status, lines):
    return {"id": i, "kind": kind, "status": status, "lines_json": json.dumps(lines)}


def test_plan_items_skips_headers_and_incomplete_rows():
    got = PI.plan_items(Q)
    assert [p["itemId"] for p in got] == ["a", "b"]
    assert got[0] == {"itemId": "a", "description": "交換器", "brand": "X", "unit": "台", "planQty": 10.0, "planUnitCost": 1000.0}
    assert PI.plan_items(None) == [] and PI.plan_items({"items": "x"}) == []


def test_usage_counts_only_counted_statuses_and_known_kinds():
    rows = [_row(1, "purchase_order", "已核准", [{"itemId": "a", "qty": 3}]),
            _row(2, "purchase_order", "待審核", [{"itemId": "a", "qty": 2}, {"itemId": "b", "qty": 10}]),
            _row(3, "purchase_order", "草稿", [{"itemId": "a", "qty": 99}]),             # 草稿不佔量
            _row(4, "purchase_order", "已駁回", [{"itemId": "a", "qty": 99}]),            # 釋放
            _row(5, "purchase_order", "已作廢", [{"itemId": "a", "qty": 99}]),
            _row(6, "purchase_req", "已核准", [{"itemId": "a", "qty": 4}]),
            _row(7, "travel", "已核准", [{"itemId": "a", "qty": 50}]),                   # 其他類型不計
            _row(8, "purchase_order", "已核准", [{"qty": 7}, {"itemId": "", "qty": 7}])]  # 沒連品項
    u = PI.usage(rows)
    assert u == {"a": {"requestedQty": 4.0, "orderedQty": 5.0}, "b": {"requestedQty": 0.0, "orderedQty": 10.0}}
    assert PI.usage(rows, exclude_id=1)["a"]["orderedQty"] == 2.0                          # 編輯自己時不把自己算進去


def test_usage_survives_bad_json_and_bad_numbers():
    rows = [{"id": 1, "kind": "purchase_order", "status": "已核准", "lines_json": "{oops"},
            {"id": 2, "kind": "purchase_order", "status": "已核准",
             "lines_json": json.dumps([{"itemId": "a", "qty": "x"}, "bad", {"itemId": "a", "qty": 1e999}])}]
    assert PI.usage(rows) == {"a": {"requestedQty": 0.0, "orderedQty": 0.0}}


def test_picker_remaining_is_plan_minus_ordered_and_hides_cost_when_asked():
    rows = [_row(1, "purchase_order", "已核准", [{"itemId": "a", "qty": 4}]), _row(2, "purchase_req", "已核准", [{"itemId": "a", "qty": 9}])]
    p = {r["itemId"]: r for r in PI.picker(Q, rows)}
    assert p["a"]["remainingQty"] == 6.0 and p["a"]["requestedQty"] == 9.0 and p["a"]["orderedQty"] == 4.0   # 請購只提示、不扣剩餘
    assert p["a"]["planUnitCost"] == 1000.0 and p["b"]["remainingQty"] == 100.0
    assert all("planUnitCost" not in r for r in PI.picker(Q, rows, show_cost=False))
    over = PI.picker(Q, [_row(1, "purchase_order", "已核准", [{"itemId": "a", "qty": 25}])])
    assert {r["itemId"]: r["remainingQty"] for r in over}["a"] == 0.0                         # 超採不出現負數


def test_overplan_cumulates_within_the_document_and_over_existing_usage():
    rows = [_row(1, "purchase_order", "已核准", [{"itemId": "a", "qty": 8}])]
    lines = [{"itemId": "a", "qty": 1}, {"itemId": "a", "qty": 2, "overPlanReason": "客戶加購"}, {"itemId": "b", "qty": 5}, {"qty": 999}]
    got = PI.overplan("purchase_order", lines, Q, rows)
    assert [(g["index"], g["over"]) for g in got] == [(1, 1.0)]                              # 8+1=9 還行；再 +2＝11 ⇒ 超 1（第二列）
    assert got[0]["reason"] == "客戶加購" and got[0]["planQty"] == 10.0 and got[0]["usedQty"] == 8.0
    assert PI.overplan("purchase_order", [{"itemId": "a", "qty": 2}], Q, rows) == []         # 剛好 10 不算超
    assert PI.overplan("purchase_order", [{"itemId": "a", "qty": 3}], Q, rows, exclude_id=1) == []     # 編輯自己：不重複算
    assert PI.overplan("purchase_order", [{"itemId": "gone", "qty": 99}], Q, rows) == []     # 品項已不在報價 ⇒ 不算超（視為額外支出）


def test_overplan_for_requests_counts_requested_not_ordered():
    rows = [_row(1, "purchase_order", "已核准", [{"itemId": "a", "qty": 10}])]
    assert PI.overplan("purchase_req", [{"itemId": "a", "qty": 5}], Q, rows) == []           # 請購看已請購量（0），與已採購無關
    rows.append(_row(2, "purchase_req", "已核准", [{"itemId": "a", "qty": 8}]))
    assert len(PI.overplan("purchase_req", [{"itemId": "a", "qty": 3}], Q, rows)) == 1


# ── 端點 ──────────────────────────────────────────────────────────────────

def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def W(client, make_user):
    h = {}
    for n, role, mods in (("pi_sa", "superadmin", None), ("pi_eng", "engineer", ["case_manage"]), ("pi_out", "engineer", ["case_manage"])):
        u, p = make_user(username=n, role=role, modules=mods)
        h[n] = _login(client, u, p)
    c = db.get_db()
    try:
        uid = c.execute("SELECT id FROM users WHERE username='pi_eng'").fetchone()["id"]
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, sales_person, assigned_user_ids)"
                  " VALUES (?,?,?,?,?,?,?,?,?)", (NO, "已送出", "客", "案", json.dumps(Q), "2026-10-02T00:00:00", "2026-10-02T00:00:00", "pi_owner", json.dumps([uid])))
        c.commit()
    finally:
        c.close()
    return client, h


def _doc(client, h, kind, lines, status):
    r = client.post("/api/quotations/%s/extra-expenses" % NO, headers=h["pi_sa"],
                    json={"kind": kind, "lines": lines, "payeeName": "某人", "payeeType": "employee", "data": {"applicant": "pi_sa"}})
    assert r.status_code == 201, r.text
    c = db.get_db()
    c.execute("UPDATE case_extra_expenses SET status=? WHERE id=?", (status, r.json()["id"]))
    c.commit()
    c.close()
    return r.json()["id"]


def test_endpoint_lists_picker_with_usage_and_cost_for_finance_viewers(W):
    c, h = W
    _doc(c, h, "purchase_order", [{"category": "雜項", "summary": "交換器", "qty": 4, "unitCost": 900, "itemId": "a"}], "已核准")
    _doc(c, h, "purchase_req", [{"category": "雜項", "summary": "交換器", "qty": 7, "unitCost": 900, "itemId": "a"}], "已核准")
    r = c.get("/api/quotations/%s/purchase-items" % NO, headers=h["pi_sa"])
    assert r.status_code == 200, r.text
    a = {i["itemId"]: i for i in r.json()["items"]}["a"]
    assert (a["planQty"], a["orderedQty"], a["requestedQty"], a["remainingQty"], a["planUnitCost"]) == (10.0, 4.0, 7.0, 6.0, 1000.0)
    assert [i["itemId"] for i in r.json()["items"]] == ["a", "b"]


def test_endpoint_hides_plan_cost_without_financial_view_and_guards_case_and_caseless(W):
    c, h = W
    r = c.get("/api/quotations/%s/purchase-items" % NO, headers=h["pi_eng"])
    assert r.status_code == 200 and all("planUnitCost" not in i for i in r.json()["items"]) and r.json()["items"][0]["planQty"] == 10.0
    assert all("actualAmount" not in i for i in r.json()["items"])                                     # 實際成本金額同樣不給看不到財務金額的人
    assert c.get("/api/quotations/%s/purchase-items" % NO, headers=h["pi_out"]).status_code == 404        # 看不到的案件＝查無
    assert c.get("/api/quotations/NOPE/purchase-items", headers=h["pi_sa"]).status_code == 404
    assert c.get("/api/quotations/-/purchase-items", headers=h["pi_sa"]).status_code == 400              # 無案件沒有品項
    assert c.get("/api/quotations/%s/purchase-items" % NO).status_code in (401, 403)
