# -*- coding: utf-8 -*-
"""V1：首頁 pendingList 的金額層遮蔽。沒有報價金額可視權限、又不是送審人／簽核鏈上的人 ⇒ total=None、帶金額的審核原因換成 MASKED_REASON；
簽核人與送審人照舊看得到金額（設計）；哪些列會出現（逐案可見）不變——T40 釘住，是否收緊另案由使用者裁示。"""
import json

import pytest

from helpers.financial_mask import MASKED_REASON

REASONS = ["整體毛利 8% 低於 30%", "折讓 NT$5,000 超過限額", "客戶為新客戶"]
QN = "V1-Q1"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _insert_pending(quote_no, owner_id, chain=(), requested_by="v1_requester"):
    import db
    appr = {"requestedBy": requested_by, "requestedByDisplay": "申請人", "reasons": list(REASONS), "currentTier": 0,
            "tiers": [{"approvers": [{"username": u, "status": "pending"} for u in chain]}]}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, "
            "updated_at, deal_tag, quote_date, sales_person_id, sales_person, net_margin_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "待審核", "客戶" + quote_no, "專案", 105000, 100000, json.dumps({"approval": appr}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "", "2026-02-03", owner_id, "開單者", 20.0))
        conn.commit()
    finally:
        conn.close()


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


@pytest.fixture()
def world(client, make_user):
    owner = make_user("v1_owner", role="admin", modules=None)
    users = {
        "owner": owner,
        "outsider": make_user("v1_outsider", role="viewer", modules=["dashboard", "quotation"]),      # 有 quotation 模組、無報價金額可視、不在鏈上
        "chain": make_user("v1_chain", role="viewer", modules=["dashboard", "quotation"]),            # 同上但在簽核鏈上
        "requester": make_user("v1_requester", role="viewer", modules=["dashboard", "quotation"]),    # 送審人
        "sales": make_user("v1_sales", role="sales", modules=None),
    }
    _insert_pending(QN, _uid("v1_owner"), chain=["v1_chain"])
    return {n: _login(client, *c) for n, c in users.items()}


def _row(client, h):
    rows = [i for i in client.get("/api/dashboard/stats", headers=h).json()["pendingList"] if i["quoteNo"] == QN]
    assert len(rows) == 1
    return rows[0]


def test_viewer_outside_the_chain_gets_the_row_without_money(client, world):
    i = _row(client, world["outsider"])
    assert i["total"] is None
    assert i["reasons"] == [MASKED_REASON, MASKED_REASON, "客戶為新客戶"]
    assert i["customer"] == "客戶" + QN and i["salesPerson"] == "開單者"            # 列本身（逐案可見）不變


@pytest.mark.parametrize("name", ["chain", "requester", "sales", "owner"])
def test_chain_requester_and_money_roles_still_see_the_amounts(client, world, name):
    i = _row(client, world[name])
    assert i["total"] == 105000 and i["reasons"] == REASONS


def test_masking_does_not_change_counts_or_row_set(client, world):
    j = client.get("/api/dashboard/stats", headers=world["outsider"]).json()
    assert j["pendingQuotes"] >= 1 and QN in {i["quoteNo"] for i in j["pendingList"]}
