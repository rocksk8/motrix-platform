# -*- coding: utf-8 -*-
"""T40 使用者裁示：「首頁改成只給財務檢視權限者」。

儀表板財務卡片（收款項目 paymentItems、預估 vs 實際 marginComparison／settledSummary、前五高毛利 marginTop5、應收摘要
receivableSummary）＝ 原條件（superadmin／admin 或持有「財務」模組）且 can_see_financial（superadmin／admin／sales 角色，
或持有 financial_view 模組）。不符者卡片沒有資料（空值，不報錯）。仍是全公司口徑：財務人員跨案件作業，不加逐案可見。
待審核清單、保固預警、純計數不受影響。

矩陣：角色（superadmin／admin／sales／viewer／engineer）× 財務模組 × 財務檢視（見 USERS；期望值見 EXPECT_CARDS）。
"""
import json

import pytest


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _insert(quote_no, opener_id, status="已送出", tag="已成案", approval=None, settled=True):
    import db
    cr = {"payment": {"items": [{"type": "尾款", "pct": 100, "received": False}]},
          "devices": [{"name": "舊設備", "sn": "S-" + quote_no, "warrantyStart": "2020-01-01", "warrantyMonths": 12}]}
    data = {"dealTag": tag, "caseRecord": cr}
    if approval:
        data["approval"] = approval
    if settled:
        data["settlement"] = {"status": "finalized", "summary": {"netProfit": 1000, "netMarginPct": 10.0, "quotedPretax": 10000,
                                                                  "profitDiff": 1}}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, "
            "updated_at, deal_tag, quote_date, sales_person_id, sales_person, net_margin_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, status, "客戶" + quote_no, "專案", 105000, 100000, json.dumps(data, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", tag, "2026-02-03", opener_id, "開單者", 20.0))
        conn.commit()
    finally:
        conn.close()


#: 帳號 ⇒ (角色, 模組)。None＝角色預設模組。
#: 第42班（使用者裁示）：財務卡片只給 superadmin 與「財務」角色；admin／sales 與任何財務勾選（惰性）都不算。
USERS = {
    "sa":               ("superadmin", None),
    "finance":          ("finance", None),
    "admin":            ("admin", None),                                                     # 失去卡片（原本有）
    "sales":            ("sales", None),                                                     # 失去卡片（原本有）
    "sales_flags":      ("sales", ["dashboard", "quotation", "case_manage", "financial_view", "finance"]),     # 惰性勾選不算
    "fin_noview":       ("viewer", ["dashboard", "finance"]),
    "eng_fin_noview":   ("engineer", ["dashboard", "finance"]),
    "fin_view":         ("viewer", ["dashboard", "finance", "financial_view"]),
    "view_nofin":       ("viewer", ["dashboard", "financial_view"]),
    "approver":         ("viewer", ["dashboard", "quotation"]),                              # 簽核路徑上的人
}

C1, C2, CP = "T40-C1", "T40-C2", "T40-CP"          # C1、C2：已成案、已完結精算；CP：待審核（approver 在簽核名單）

#: 有財務卡片的帳號 ⇒ 看到全公司兩案（make_user 會把「一般角色＋明確勾財務鍵」換成 finance 角色 ⇒ 那幾個也算）
CARDS = {"sa", "finance", "sales_flags", "fin_noview", "eng_fin_noview", "fin_view", "view_nofin"}
#: 有「待審核」清單的帳號（can_quotation：角色 superadmin／admin／sales，或持有 quotation 模組）
PENDING = {"sa", "admin", "sales", "approver", "finance", "sales_flags"}


@pytest.fixture()
def world(client, make_user):
    import db
    creds = {n: make_user("t40_" + n, role=r, modules=m) for n, (r, m) in USERS.items()}
    conn = db.get_db()
    try:
        sid = conn.execute("SELECT id FROM users WHERE username='t40_sa'").fetchone()[0]
    finally:
        conn.close()
    _insert(C1, sid)
    _insert(C2, sid)
    appr = {"requestedBy": "x", "requestedByDisplay": "申請人", "reasons": [], "currentTier": 0,
            "tiers": [{"approvers": [{"username": "t40_approver", "status": "pending"}]}]}
    _insert(CP, sid, status="待審核", tag="", approval=appr, settled=False)
    return {n: _login(client, *c) for n, c in creds.items()}


def _who(items, key="quoteNo"):
    return {i[key] for i in items}


@pytest.mark.parametrize("name", sorted(USERS))
def test_finance_cards_need_the_finance_rule_and_stay_company_wide(client, world, name):
    j = client.get("/api/dashboard/stats", headers=world[name]).json()
    both = {C1, C2} if name in CARDS else set()
    assert _who(j["paymentItems"]) == both
    assert _who(j["marginComparison"]) == both
    assert _who(j["marginTop5"]) <= both
    assert bool(j["settledSummary"]) == bool(both)
    rv = j["receivableSummary"]
    assert (rv["total"] > 0) == bool(both)
    if not both:
        assert j["marginTop5"] == [] and rv == {"total": 0, "received": 0, "unreceived": 0, "feeTotal": 0, "netReceived": 0}


@pytest.mark.parametrize("name", sorted(USERS))
def test_finance_visible_flag_matches_the_cards(client, world, name):
    """前端用 financeVisible 隱藏應收款項面板與收款百分比：它必須是布林，且與卡片有沒有資料一致。"""
    j = client.get("/api/dashboard/stats", headers=world[name]).json()
    assert j["financeVisible"] is (name in CARDS)
    assert j["financeVisible"] == bool(j["settledSummary"])


@pytest.mark.parametrize("name", sorted(USERS))
def test_other_dashboard_parts_are_untouched(client, world, name):
    """待審核清單（can_quotation）、保固預警（全公司）、純計數都不受財務卡片收緊影響。"""
    j = client.get("/api/dashboard/stats", headers=world[name]).json()
    assert _who(j["pendingList"]) == ({CP} if name in PENDING else set())
    assert _who(j["warrantyWarnings"]) == {C1, C2, CP}      # 三案都有一台過保設備
    assert j["totalQuotes"] == 3 and j["activeCases"] == 2
    assert j["deviceSummary"]["total"] == 3


def test_admin_and_sales_lose_the_cards_even_with_the_inert_flags(client, make_user):
    """上線矩陣的另一面：admin／sales（即使 DB 裡還留著惰性的財務勾選）沒有卡片；只有 superadmin 與財務角色有。"""
    adm = make_user("t40_flagged_admin", role="admin", modules=["dashboard", "quotation", "finance", "financial_view", "cashier"],
                    legacy_finance_flag=False)
    h = _login(client, *adm)
    j = client.get("/api/dashboard/stats", headers=h).json()
    assert j["financeVisible"] is False and _who(j["paymentItems"]) == set()
