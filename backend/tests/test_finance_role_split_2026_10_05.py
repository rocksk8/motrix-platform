"""第42班（使用者裁示「拆開」＋財務角色不受擁有者限制）：

1. 報價單層級（編輯報價單、報價總額、品項成本／毛利）維持業務／管理員；精算與款項期別（收款／付款）才是財務專屬。
   業務／管理員編輯報價單時，被遮蔽的精算／款項期別以資料庫現值補回，不被空值蓋掉。
2. 財務角色（與 superadmin）不受案件擁有者限制：額外支出、材料申請（發票日／讀取）、材料申請匯款申請、精算。
   admin 維持既有直通；沒有案件關係的業務／工程師仍然 404／403。
"""
import json

import pytest

from tests._requires import requires_module  # noqa: E402

pytestmark = requires_module("case", "本檔的題打 M01（案件）的端點")

NO = "MQ-SPLIT-001"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _seed(owner_username):
    import db
    data = {
        "dealTag": "", "status": "草稿",
        "items": [{"desc": "攝影機", "qty": 2, "cost": 3000, "margin": 40, "unitPrice": 5000, "amount": 10000}],
        "discount": 500, "freight": 300,
        "tot": {"subtotal": 10000, "pretax": 9800, "total": 10290, "totalCost": 6000, "directProfit": 3800},
        "settlement": {"status": "未精算", "summary": {"grossProfit": 3000}},
        "caseRecord": {
            "payment": {"items": [
                {"id": 1, "type": "訂金款", "pct": 30, "amount": 3087, "received": True, "receivedAt": "2026-09-01",
                 "actualAmount": 3087, "feeAmount": 15, "note": "", "invoiceNo": ""}]},
            "materialOrders": [],
        },
    }
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, direct_margin_pct,"
            " net_margin_pct, data_json, created_at, updated_at, deal_tag, sales_person_id, sales_person, assigned_user_ids)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "草稿", "客", "案", 10290, 9800, 38.0, 20.0, json.dumps(data, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "", _uid(owner_username), owner_username, "[]"))
        conn.commit()
    finally:
        conn.close()
    return data


def _db_data():
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])
    finally:
        conn.close()


@pytest.fixture
def world(client, make_user):
    out = {}
    out["sales"] = make_user("sp_sales", role="sales")
    out["admin"] = make_user("sp_admin", role="admin")
    out["finance"] = make_user("sp_fin", role="finance")
    out["super"] = make_user("sp_root", role="superadmin", modules=[])
    out["eng"] = make_user("sp_eng", role="engineer")
    out["other_sales"] = make_user("sp_sales2", role="sales")
    _seed("sp_sales")
    return {k: _login(client, *v) for k, v in out.items()}


# ── 1. 拆開 ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("who", ["sales", "admin"])
def test_sales_and_admin_keep_quotation_level_data_but_not_settlement_or_payments(client, world, who):
    r = client.get("/api/quotations/" + NO, headers=world[who])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total"] == 10290 and d["direct_margin_pct"] == 38.0           # 報價總額、毛利率（報價單層級）維持
    assert d["data"]["items"][0]["unitPrice"] == 5000 and d["data"]["items"][0]["cost"] == 3000
    assert d["data"]["tot"]["total"] == 10290
    assert d["data"]["settlement"] == {"status": "未精算"}                    # 精算＝財務專屬
    pay = d["data"]["caseRecord"]["payment"]["items"][0]
    assert "amount" not in pay and "actualAmount" not in pay and "feeAmount" not in pay   # 款項期別金額＝財務專屬


@pytest.mark.parametrize("who", ["finance", "super"])
def test_finance_and_superadmin_see_everything(client, world, who):
    d = client.get("/api/quotations/" + NO, headers=world[who]).json()
    assert d["data"]["settlement"]["summary"]["grossProfit"] == 3000
    assert d["data"]["caseRecord"]["payment"]["items"][0]["actualAmount"] == 3087


def test_engineer_stays_fully_masked(client, world):
    # 工程師不是案件成員 ⇒ 404；若成為成員也看不到金額（既有 CM13 規則不變）
    r = client.get("/api/quotations/" + NO, headers=world["eng"])
    assert r.status_code in (403, 404)


@pytest.mark.parametrize("who", ["sales", "admin"])
def test_sales_and_admin_can_put_the_quotation_and_masked_parts_survive(client, world, who):
    d = client.get("/api/quotations/" + NO, headers=world[who]).json()
    data = d["data"]
    data["items"][0]["unitPrice"] = 5500                                      # 業務改單價（報價單層級編輯）
    data["items"][0]["amount"] = 11000
    r = client.put("/api/quotations/" + NO, headers=world[who], json={"data": data, "status": d["status"]})
    assert r.status_code == 200, r.text
    now = _db_data()
    assert now["items"][0]["unitPrice"] == 5500
    assert now["settlement"]["summary"]["grossProfit"] == 3000                  # 精算沒被空值蓋掉
    assert now["caseRecord"]["payment"]["items"][0]["actualAmount"] == 3087     # 款項期別金額沒被蓋掉


def test_engineer_cannot_put_the_quotation(client, world):
    d = client.get("/api/quotations/" + NO, headers=world["super"]).json()
    r = client.put("/api/quotations/" + NO, headers=world["eng"], json={"data": d["data"], "status": d["status"]})
    assert r.status_code in (403, 404)


def test_quote_money_visible_matrix():
    from helpers.financial_mask import quote_money_visible, money_visible
    for role, quote_ok, fin_ok in (("superadmin", True, True), ("finance", True, True), ("admin", True, False),
                                   ("sales", True, False), ("engineer", False, False), ("viewer", False, False)):
        u = {"role": role, "modules": "[]"}
        assert quote_money_visible(u) is quote_ok and money_visible(u) is fin_ok, role


# ── 2. 財務角色不受案件擁有者限制 ────────────────────────────────────────────────
def test_finance_reaches_money_endpoints_of_a_case_owned_by_another_salesperson(client, world):
    f, s2, adm = world["finance"], world["other_sales"], world["admin"]
    # 額外支出清單：財務角色／admin 通過；與案件無關的業務 404／403
    url = "/api/quotations/%s/extra-expenses" % NO
    assert client.get(url, headers=f).status_code == 200
    assert client.get(url, headers=adm).status_code == 200
    assert client.get(url, headers=s2).status_code in (403, 404)
    # 材料申請：讀取與發票日
    assert client.get("/api/quotations/%s/material-orders" % NO, headers=f).status_code == 200
    assert client.get("/api/quotations/%s/material-orders" % NO, headers=s2).status_code in (403, 404)
    r = client.patch("/api/quotations/%s/material-orders/NOPE/invoice-date" % NO, headers=f, json={"invoiceDate": ""})
    assert r.status_code not in (403,) and r.status_code != 404 or "找不到" in r.text      # 通過擁有者關卡（後面才是找不到這筆叫料）
    # 精算
    assert client.get("/api/quotations/%s/settlement" % NO, headers=f).status_code == 200
    assert client.get("/api/quotations/%s/settlement" % NO, headers=s2).status_code in (403, 404)
