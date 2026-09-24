"""案件金額欄位後端遮蔽（CM13，2026-09-24 使用者裁示「要，後端移除金額欄位」）。

沒有 `can_see_financial()` 的帳號（engineer／viewer，未持 financial_view），後端不回金額、毛利、
單價、成本；畫面顯示「—」。持有者（superadmin／admin／sales 或 financial_view 模組）照舊。
最大風險在回寫：被遮蔽的欄位不可以被空值蓋掉（伺服器以資料庫現值補回）。
"""
import json

import pytest

NO = "MQ-MASK-001"
MONEY_COLS = ("total", "pretax", "direct_margin_pct", "net_margin_pct")


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _user_id(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _seed(assigned=()):
    """一張已成案案件，指派給 assigned 裡的帳號（讓非擁有者也看得到這張案件）。"""
    import db
    data = {
        "dealTag": "已成案",
        "items": [{"desc": "攝影機", "qty": 2, "cost": 3000, "margin": 40, "unitPrice": 5000, "amount": 10000}],
        "discount": 500, "freight": 300,
        "tot": {"subtotal": 10000, "pretax": 9800, "total": 10290, "totalCost": 6000, "directProfit": 3800},
        "settlement": {"status": "未精算", "summary": {"grossProfit": 3000}},
        "approval": {"reasons": ["第 1 項毛利率 20% 低於 30%", "含折讓（NT$500）"]},
        "caseRecord": {
            "payment": {"items": [
                {"id": 1, "type": "訂金款", "pct": 30, "amount": 3087, "received": True, "receivedAt": "2026-09-01",
                 "actualAmount": 3087, "feeAmount": 15, "feeNote": "匯費", "note": "", "invoiceNo": ""},
                {"id": 2, "type": "尾款", "pct": 70, "amount": 7203, "received": False, "note": "",
                 "actualAmount": None, "feeAmount": 0, "invoiceNo": ""}]},
            "materials": [{"id": 11, "name": "料", "qty": 1}],
            "materialOrders": [{"id": 5, "itemName": "線材", "unitPrice": 100, "totalPrice": 1000, "paidAmount": 0}],
        },
    }
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax,"
            " direct_margin_pct, net_margin_pct, data_json, created_at, updated_at, deal_tag,"
            " assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", 10290, 9800, 38.0, 20.0, json.dumps(data, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案",
             json.dumps([_user_id(u) for u in assigned])))
        conn.commit()
    finally:
        conn.close()


def _row(body):
    return next(it for it in body["items"] if (it.get("quote_no") or it.get("quoteNo")) == NO)


# ── ① 清單與結案檢核 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["engineer", "viewer"])
def test_list_hides_money_from_non_financial(client, make_user, role):
    u = make_user(username=f"mk_l_{role}", role=role)
    _seed(assigned=[u[0]])
    r = client.get("/api/quotations?deal_tag=已成案", headers=_login(client, *u))
    assert r.status_code == 200, r.text
    row = _row(r.json())
    for k in MONEY_COLS:
        assert row[k] is None, (k, row[k])
    assert row["moneyMasked"] is True


@pytest.mark.parametrize("role,modules", [("sales", None), ("admin", None), ("engineer", ["case_manage", "financial_view"])])
def test_list_keeps_money_for_financial(client, make_user, role, modules):
    u = make_user(username=f"mk_lf_{role}", role=role, modules=modules)
    _seed(assigned=[u[0]])
    row = _row(client.get("/api/quotations?deal_tag=已成案", headers=_login(client, *u)).json())
    assert row["total"] == 10290 and row["pretax"] == 9800
    assert row["direct_margin_pct"] == 38.0 and row["net_margin_pct"] == 20.0
    assert not row.get("moneyMasked")


def test_gate_matrix_hides_total_from_non_financial(client, make_user):
    u = make_user(username="mk_g_eng", role="engineer")
    _seed(assigned=[u[0]])
    r = client.get("/api/quotations/gate-matrix", headers=_login(client, *u))
    assert r.status_code == 200, r.text
    row = _row(r.json())
    assert row["total"] is None and row["moneyMasked"] is True


def test_gate_matrix_keeps_total_for_financial(client, make_user):
    u = make_user(username="mk_g_sales", role="sales")
    _seed(assigned=[u[0]])
    row = _row(client.get("/api/quotations/gate-matrix", headers=_login(client, *u)).json())
    assert row["total"] == 10290
