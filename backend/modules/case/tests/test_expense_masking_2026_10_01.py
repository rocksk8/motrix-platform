# -*- coding: utf-8 -*-
"""費用單據金額遮蔽（使用者 2026-10-01 最終裁示）：金額只給申請人、本單簽核人、出納／財務、管理員；其他人只看得到狀態。

驗：案件清單（含 sales／financial_view 這種原本看得到案件財務的人，對費用單據一樣遮蔽）、案件財務總覽、簽核佇列、出納待付款、無案件單據；
遮蔽列的回應本文**不含**金額數字與銀行帳號；舊版列（kind=''）的既有規則不變。"""
import json

import pytest

NO = "MQ-202610-771"
AMOUNT = 12345
ACCOUNT = "9876501234567"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _x(sql, args=()):
    import db
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


@pytest.fixture
def world(client, make_user):
    H, ids = {}, {}
    for u, role, mods in (("mk_app", "sales", ["expense_forms"]), ("mk_col", "sales", None), ("mk_fv", "engineer", ["financial_view"]),
                          ("mk_fin", "engineer", ["finance", "financial_view"]), ("mk_cash", "engineer", ["cashier"]), ("mk_apr", "engineer", ["financial_view"])):
        name, pw = make_user(username=u, role=role, modules=mods)
        H[u] = _login(client, name, pw)
        ids[u] = _q("SELECT id FROM users WHERE username=?", (u,))[0]["id"]
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids)"
       " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "客", "專案", 100000, 95238, json.dumps({"dealTag": "已成案"}), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "",
        json.dumps([ids[k] for k in ("mk_app", "mk_col", "mk_fv", "mk_fin", "mk_cash", "mk_apr")])))
    r = client.post("/api/quotations/%s/extra-expenses" % NO, headers=H["mk_app"],
                    json={"kind": "travel", "lines": [{"category": "其他", "summary": "高鐵", "amount": AMOUNT}], "data": {"applicant": "mk_app"},
                          "payeeType": "employee", "payeeName": "申請人", "payeeBank": "玉山", "payeeAccount": ACCOUNT})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    appr = {"requestedBy": "mk_app", "requestedByDisplay": "申請人", "requestedAt": "2026-10-01T10:00:00",
            "tiers": [{"order": 0, "approvers": [{"username": "mk_apr", "display_name": "簽核人"}]}], "currentTier": 0}
    _x("UPDATE case_extra_expenses SET status='待審核', approval_json=? WHERE id=?", (json.dumps(appr), eid))
    return H, eid


def _list(client, h):
    r = client.get("/api/quotations/%s/extra-expenses" % NO, headers=h)
    assert r.status_code == 200, r.text
    return r


def test_case_list_masks_amounts_for_everyone_but_the_four_groups(client, world):
    H, eid = world
    for who in ("mk_app", "mk_apr", "mk_fin", "mk_cash"):                       # 申請人、簽核人、財務、出納 ⇒ 看得到
        d = _list(client, H[who]).json()
        (it,) = [i for i in d["items"] if i["id"] == eid]
        assert it["totalCost"] == AMOUNT and it["lines"][0]["amount"] == AMOUNT and not it.get("masked"), who
    for who in ("mk_col", "mk_fv"):                                              # 同案的 sales／財務檢視偏好者 ⇒ 只看狀態
        resp = _list(client, H[who])
        d = resp.json()
        (it,) = [i for i in d["items"] if i["id"] == eid]
        assert it["masked"] is True and it["totalCost"] is None and it["lines"] == [] and it["data"] == {} and it["status"] == "待審核", who
        assert d["totalAmount"] == 0 and d["pendingCount"] >= 1
        body = resp.text
        assert str(AMOUNT) not in body and ACCOUNT not in body and "玉山" not in body and "高鐵" not in body, who


def test_finance_overview_masks_kind_rows_for_non_viewers(client, world):
    H, eid = world
    r = client.get("/api/quotations/%s/finance-summary" % NO, headers=H["mk_fv"])
    assert r.status_code == 200, r.text
    assert str(AMOUNT) not in r.text
    items = [i for i in r.json()["settlementExtras"]["items"] if i["id"] == eid]
    assert items and items[0]["masked"] is True and items[0]["totalCost"] is None
    r = client.get("/api/quotations/%s/finance-summary" % NO, headers=H["mk_fin"])
    (it,) = [i for i in r.json()["settlementExtras"]["items"] if i["id"] == eid]
    assert it["totalCost"] == AMOUNT


def test_queue_and_payables_do_not_leak(client, world):
    H, eid = world
    def flat(resp):
        return [i for g in resp.json()["queue"] for i in g["items"]]
    mine = [i for i in flat(client.get("/api/approval-queue", headers=H["mk_apr"])) if i.get("extraExpenseId") == eid]
    assert mine and mine[0]["total"] == AMOUNT                                   # 簽核人看得到
    qc = client.get("/api/approval-queue", headers=H["mk_col"])
    assert not [i for i in flat(qc) if i.get("extraExpenseId") == eid]
    assert str(AMOUNT) not in qc.text                                            # 不是簽核人 ⇒ 佇列裡沒有這筆，金額也不在本文
    _x("UPDATE case_extra_expenses SET status='已核准' WHERE id=?", (eid,))
    for who in ("mk_col", "mk_fv", "mk_app"):
        r = client.get("/api/cashier/pending-payables", headers=H[who])
        assert r.status_code in (403, 404) or str(AMOUNT) not in r.text, (who, r.status_code)
    r = client.get("/api/cashier/pending-payables", headers=H["mk_cash"])
    assert r.status_code == 200 and any(i["key"] == str(eid) and i["amount"] == AMOUNT for i in r.json()["items"])


def test_legacy_rows_keep_the_old_rule_and_caseless_rows_stay_hidden(client, world, seed_extra_expense):
    H, _ = world
    lid = seed_extra_expense(NO, total_cost=777, category="運費", description="舊列", expense_date="2026-09-10")
    d = _list(client, H["mk_col"]).json()                      # sales 本來就看得到案件財務：舊列照舊看得到金額（行為不變）
    (old,) = [i for i in d["items"] if i["id"] == lid]
    assert old["totalCost"] == 777 and not old.get("masked")
    cl = client.post("/api/quotations/-/extra-expenses", headers=H["mk_app"], json={"kind": "petty_cash", "lines": [{"amount": 500}]})
    assert cl.status_code == 201
    assert cl.json()["id"] not in [i["id"] for i in client.get("/api/quotations/-/extra-expenses", headers=H["mk_col"]).json()["items"]]


def test_list_reports_masked_count_so_settlement_can_refuse_an_incomplete_total(client, world):
    """精算頁用 `maskedCount` 擋存檔／完結：對本人遮蔽的列數 > 0 ⇒ totalAmount 不是完整成本。看得到金額的人是 0。"""
    H, eid = world
    for who in ("mk_col", "mk_fv"):
        d = _list(client, H[who]).json()
        assert d["maskedCount"] == 1 and d["totalAmount"] == 0, who
    for who in ("mk_app", "mk_apr", "mk_fin", "mk_cash"):
        assert _list(client, H[who]).json()["maskedCount"] == 0, who
    _x("UPDATE case_extra_expenses SET status='已作廢', void_reason='x' WHERE id=?", (eid,))      # 作廢列不算「殘缺」
    assert _list(client, H["mk_fv"]).json()["maskedCount"] == 0
