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


def _seed(assigned=(), status="已送出"):
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
                 "actualAmount": 3087, "feeAmount": 15, "feeNote": "匯費", "note": "", "invoiceNo": "",
                 "invoicePretax": 2940, "invoiceTax": 147},
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
            (NO, status, "客", "案", 10290, 9800, 38.0, 20.0, json.dumps(data, ensure_ascii=False),
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


# ── ② 單筆內容 ───────────────────────────────────────────────────────────────

def _db_data():
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])
    finally:
        conn.close()


@pytest.mark.parametrize("role", ["engineer", "viewer"])
def test_detail_hides_money_from_non_financial(client, make_user, role):
    u = make_user(username=f"mk_d_{role}", role=role)
    _seed(assigned=[u[0]])
    r = client.get(f"/api/quotations/{NO}", headers=_login(client, *u))
    assert r.status_code == 200, r.text
    body = r.json()
    for k in MONEY_COLS:
        assert body[k] is None, k
    d = body["data"]
    assert d["moneyMasked"] is True
    it = d["items"][0]
    assert it["desc"] == "攝影機" and it["qty"] == 2
    for k in ("cost", "margin", "unitPrice", "amount"):
        assert k not in it, k
    for k in ("discount", "freight", "tot"):
        assert k not in d, k
    assert d["settlement"] == {"status": "未精算"}
    assert all("毛利" not in x and "NT$" not in x for x in d["approval"]["reasons"])
    for p in d["caseRecord"]["payment"]["items"]:
        for k in ("amount", "pct", "actualAmount", "feeAmount", "feeNote", "invoicePretax", "invoiceTax"):
            assert k not in p, k
    assert d["caseRecord"]["payment"]["items"][0]["received"] is True   # 非金額欄位照舊
    mo = d["caseRecord"]["materialOrders"][0]
    assert mo["itemName"] == "線材" and "unitPrice" not in mo and "totalPrice" not in mo


@pytest.mark.parametrize("role,modules", [("sales", None), ("admin", None), ("engineer", ["case_manage", "financial_view"])])
def test_detail_keeps_money_for_financial(client, make_user, role, modules):
    u = make_user(username=f"mk_df_{role}", role=role, modules=modules)
    _seed(assigned=[u[0]])
    d = client.get(f"/api/quotations/{NO}", headers=_login(client, *u)).json()["data"]
    assert d["items"][0]["unitPrice"] == 5000 and d["tot"]["total"] == 10290
    assert d["caseRecord"]["payment"]["items"][0]["amount"] == 3087
    assert not d.get("moneyMasked")


def test_cashier_module_without_financial_view_is_not_masked(client, make_user):
    """使用者裁示 A：遮蔽條件＝無 can_see_financial 且無 cashier 模組（出納頁本來就看得到金額）。"""
    u = make_user(username="mk_cashier", role="engineer", modules=["case_manage", "cashier"])
    _seed(assigned=[u[0]])
    h = _login(client, *u)
    assert _row(client.get("/api/quotations?deal_tag=已成案", headers=h).json())["total"] == 10290
    d = client.get(f"/api/quotations/{NO}", headers=h).json()["data"]
    assert d["caseRecord"]["payment"]["items"][0]["amount"] == 3087 and not d.get("moneyMasked")


# ── ③ 回寫：被遮蔽的欄位不可被空值蓋掉 ─────────────────────────────────────

def test_engineer_segment_save_keeps_amounts(client, make_user):
    u = make_user(username="mk_w_seg", role="engineer")
    _seed(assigned=[u[0]])
    h = _login(client, *u)
    seen = client.get(f"/api/quotations/{NO}", headers=h).json()["data"]["caseRecord"]
    base = json.loads(json.dumps(seen["payment"]))
    new = json.loads(json.dumps(seen["payment"]))
    new["items"][1]["note"] = "工程師備註"
    r = client.patch(f"/api/quotations/{NO}/case-record", headers=h,
                     json={"segments": {"payment": new}, "base": {"payment": base}})
    assert r.status_code == 200, r.text
    items = _db_data()["caseRecord"]["payment"]["items"]
    assert items[1]["note"] == "工程師備註"
    assert [i["amount"] for i in items] == [3087, 7203]
    assert [i["pct"] for i in items] == [30, 70]
    assert items[0]["actualAmount"] == 3087 and items[0]["feeAmount"] == 15 and items[0]["feeNote"] == "匯費"
    assert items[0]["invoicePretax"] == 2940 and items[0]["invoiceTax"] == 147


def test_engineer_legacy_whole_record_save_keeps_amounts(client, make_user):
    u = make_user(username="mk_w_old", role="engineer")
    _seed(assigned=[u[0]])
    h = _login(client, *u)
    seen = client.get(f"/api/quotations/{NO}", headers=h).json()["data"]["caseRecord"]
    seen["materials"][0]["name"] = "改料"
    r = client.patch(f"/api/quotations/{NO}/case-record", headers=h, json={"case_record": seen})
    assert r.status_code == 200, r.text
    cr = _db_data()["caseRecord"]
    assert cr["materials"][0]["name"] == "改料"
    assert [i["amount"] for i in cr["payment"]["items"]] == [3087, 7203]
    assert cr["materialOrders"][0]["unitPrice"] == 100


def test_engineer_cannot_add_delete_or_reorder_payment_items(client, make_user):
    u = make_user(username="mk_w_d2", role="engineer")
    _seed(assigned=[u[0]])
    h = _login(client, *u)
    seen = client.get(f"/api/quotations/{NO}", headers=h).json()["data"]["caseRecord"]
    base = seen["payment"]
    variants = {
        "add": {"items": base["items"] + [{"id": 3, "type": "新期"}]},
        "delete": {"items": base["items"][:1]},
        "reorder": {"items": list(reversed(base["items"]))},
    }
    for name, pay in variants.items():
        r = client.patch(f"/api/quotations/{NO}/case-record", headers=h,
                         json={"segments": {"payment": pay}, "base": {"payment": base}})
        assert r.status_code == 403, (name, r.text)
    assert [i["id"] for i in _db_data()["caseRecord"]["payment"]["items"]] == [1, 2]


def test_engineer_default_payment_on_case_without_payment_is_not_written(client, make_user):
    import db
    u = make_user(username="mk_w_def", role="engineer")
    _seed(assigned=[u[0]])
    conn = db.get_db()
    try:
        d = _db_data()
        d["caseRecord"].pop("payment")
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO))
        conn.commit()
    finally:
        conn.close()
    h = _login(client, *u)
    default_pay = {"items": [{"id": 1, "type": "訂金款", "pct": 30}, {"id": 2, "type": "交貨款", "pct": 70}]}
    r = client.patch(f"/api/quotations/{NO}/case-record", headers=h,
                     json={"segments": {"materials": [{"id": 11, "name": "料2", "qty": 1}]},
                           "base": {"materials": [{"id": 11, "name": "料", "qty": 1}]},
                           "defaults": {"payment": default_pay}})
    assert r.status_code == 200, r.text
    cr = _db_data()["caseRecord"]
    assert cr["materials"][0]["name"] == "料2"
    assert "payment" not in cr, "看不到金額的人不可以替案件建立款項期別"


def test_financial_user_still_edits_amounts(client, make_user):
    u = make_user(username="mk_w_sales", role="sales")
    _seed(assigned=[u[0]])
    h = _login(client, *u)
    seen = client.get(f"/api/quotations/{NO}", headers=h).json()["data"]["caseRecord"]
    new = json.loads(json.dumps(seen["payment"]))
    new["items"][1]["amount"] = 7000
    r = client.patch(f"/api/quotations/{NO}/case-record", headers=h,
                     json={"segments": {"payment": new}, "base": {"payment": seen["payment"]}})
    assert r.status_code == 200, r.text
    assert _db_data()["caseRecord"]["payment"]["items"][1]["amount"] == 7000


def test_non_financial_put_quotation_is_403(client, make_user):
    u = make_user(username="mk_put", role="engineer")
    _seed(status="草稿")   # 草稿才過得了既有的狀態檢查——要打到的是權限檢查
    # PUT 的擁有者檢查只看 sales_person_id（它讀的欄位裡沒有 assigned_user_ids）⇒ 讓他當業務
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET sales_person_id=? WHERE quote_no=?", (_user_id(u[0]), NO))
        conn.commit()
    finally:
        conn.close()
    before = _db_data()
    r = client.put(f"/api/quotations/{NO}", headers=_login(client, *u), json={"data": {"items": []}})
    assert r.status_code == 403, r.text
    assert _db_data() == before


# ── ⑤ 叫料 ───────────────────────────────────────────────────────────────────

def test_material_orders_get_masked_for_engineer(client, make_user):
    u = make_user(username="mk_mo_eng", role="engineer")
    _seed(assigned=[u[0]])
    r = client.get(f"/api/quotations/{NO}/material-orders", headers=_login(client, *u))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["totalAmount"] is None and b["paidAmount"] is None and b["moneyMasked"] is True
    mo = b["materialOrders"][0]
    assert mo["itemName"] == "線材" and "unitPrice" not in mo and "paidAmount" not in mo


def test_material_orders_get_full_for_sales(client, make_user):
    u = make_user(username="mk_mo_sales", role="sales")
    _seed(assigned=[u[0]])
    b = client.get(f"/api/quotations/{NO}/material-orders", headers=_login(client, *u)).json()
    assert b["totalAmount"] == 1000 and b["materialOrders"][0]["unitPrice"] == 100


def test_material_orders_patch_403_for_non_financial_project_manager(client, make_user):
    u = make_user(username="mk_mo_pm", role="engineer", modules=["case_manage", "project_manage"])
    _seed(assigned=[u[0]])
    before = _db_data()
    r = client.patch(f"/api/quotations/{NO}/material-orders", headers=_login(client, *u), json={"materialOrders": []})
    assert r.status_code == 403, r.text
    assert _db_data() == before
