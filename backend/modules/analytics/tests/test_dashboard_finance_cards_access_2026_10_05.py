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
USERS = {
    "sa":               ("superadmin", None),
    "admin":            ("admin", None),
    "sales_fin":        ("sales", ["dashboard", "quotation", "case_manage", "financial_view", "finance"]),
    "sales_fin_noview": ("sales", ["dashboard", "quotation", "case_manage", "finance"]),      # sales 角色本身就過 can_see_financial
    "sales_nofin":      ("sales", None),                                                     # 沒有財務模組 ⇒ 原本就沒有卡片
    "fin_noview":       ("viewer", ["dashboard", "finance"]),                                # 財務模組、沒有財務檢視 ⇒ 失去卡片
    "eng_fin_noview":   ("engineer", ["dashboard", "finance"]),                              # 同上（非 viewer 角色）
    "fin_view":         ("viewer", ["dashboard", "finance", "financial_view"]),              # 兩者都有 ⇒ 全公司卡片，不要求是案件業務
    "view_nofin":       ("viewer", ["dashboard", "financial_view"]),                         # 只有財務檢視、沒有財務模組 ⇒ 原本就沒有
    "approver":         ("viewer", ["dashboard", "quotation"]),                              # 簽核路徑上的人
}

C1, C2, CP = "T40-C1", "T40-C2", "T40-CP"          # C1、C2：已成案、已完結精算；CP：待審核（approver 在簽核名單）

#: 有財務卡片的帳號 ⇒ 看到全公司兩案
CARDS = {"sa", "admin", "sales_fin", "sales_fin_noview", "fin_view"}
#: 有「待審核」清單的帳號（can_quotation）
PENDING = {"sa", "admin", "sales_fin", "sales_fin_noview", "sales_nofin", "approver"}


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


def test_the_accounts_that_lose_the_cards_are_exactly_finance_module_without_financial_view(client, world):
    """矩陣的另一面：失去卡片的只有「有財務模組、但沒有財務檢視（角色也不是 sales／admin）」；其餘要嘛維持、要嘛原本就沒有。"""
    lost = set()
    for name, (role, mods) in USERS.items():
        had = role in ("superadmin", "admin") or "finance" in (mods or [])     # 舊條件
        if name == "sales_nofin":
            had = False                                                        # sales 預設模組沒有 finance
        now = name in CARDS
        if had and not now:
            lost.add(name)
    assert lost == {"fin_noview", "eng_fin_noview"}
