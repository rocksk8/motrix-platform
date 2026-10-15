# -*- coding: utf-8 -*-
"""T65 F7 S1b 家族二／三的真實出口證明：打真的 GET／PUT /api/quotations/{no}（暫存庫、真實登入），
角色 × finance_via_effective（off／shadow／on）× 授予／扣項，期望值來自獨立的舊規則表（test_field_policy_t65._expected，寫死在測試裡）。
含『工程師被授予出納（旗標 on）』格：money 為真、報價單層級為假——出口保留整份不遮的短路。
另證：寫入路徑求值出錯要像今天一樣丟出（不寫入），讀取路徑則遮蔽（fail-closed）。"""
import json

import pytest

from tests._requires import requires_module
from tests.platform.test_field_policy_t65 import GRANTS, MODES, ROLES, _expected
from tests.test_case_money_mask_2026_09_24 import NO, _db_data, _login, _seed, _user_id

pytestmark = requires_module("case", "打 M01（案件）的端點")


@pytest.fixture
def fin(monkeypatch):
    from helpers import auth
    st = {"mode": "off", "grant": None}
    monkeypatch.setattr(auth, "_finance_mode", lambda: st["mode"])
    monkeypatch.setattr(auth, "_finance_grants", lambda uid, cache: (set(GRANTS[st["grant"]][0]), set(GRANTS[st["grant"]][1])))
    monkeypatch.setattr(auth, "_finance_shadow_report", lambda *a, **k: None)
    return st


def _users(make_user):
    return {r: make_user(username="fp_%s" % r, role=r) for r in ROLES}


def _expect(role, mode, grant):
    return (_expected("finance_money", role, mode, grant), _expected("quote_money", role, mode, grant), _expected("material_money", role, mode, grant))


def test_get_quotation_matches_the_old_table_for_every_role_mode_and_grant(client, make_user, fin):
    users = _users(make_user)
    _seed(assigned=[u[0] for u in users.values()])
    heads = {r: _login(client, *u) for r, u in users.items()}
    cells = {"full": 0, "quote_only": 0, "masked": 0}
    for mode in MODES:
        fin["mode"] = mode
        for role in ROLES:
            for grant in GRANTS:
                fin["grant"] = grant
                money, quote, orders = _expect(role, mode, grant)
                r = client.get("/api/quotations/" + NO, headers=heads[role])
                assert r.status_code == 200, (role, mode, grant, r.text)
                d = r.json()["data"]
                it = d["items"][0]
                pay = d["caseRecord"]["payment"]["items"][0]
                mo = d["caseRecord"]["materialOrders"][0]
                cell = (role, mode, grant)
                if money:
                    cells["full"] += 1
                    assert it["cost"] == 3000 and pay["amount"] == 3087 and d["settlement"]["summary"]["grossProfit"] == 3000 and mo["unitPrice"] == 100, cell
                else:
                    assert d["settlement"] == {"status": "未精算"} and "amount" not in pay, cell
                    assert ("cost" in it and it["cost"] == 3000) == quote, cell
                    assert ("unitPrice" in mo) == orders, cell
                    cells["quote_only" if quote else "masked"] += 1
    assert all(cells.values()), cells                       # 三種結果（整份／僅報價層級／全遮）都真的測到


def test_engineer_granted_cashier_is_the_money_true_quote_false_cell(client, make_user, fin):
    """出口的短路：旗標 on、被授予 cashier 的工程師 money=True、keep_quote=False——整份不遮（今天的行為，不可因遷移改變）。"""
    u = make_user(username="fp_eng_cash", role="engineer")
    _seed(assigned=[u[0]])
    fin["mode"], fin["grant"] = "on", 2
    d = client.get("/api/quotations/" + NO, headers=_login(client, *u)).json()["data"]
    assert d["items"][0]["cost"] == 3000 and d["caseRecord"]["payment"]["items"][0]["amount"] == 3087


def _own(uid):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET sales_person_id=? WHERE quote_no=?", (uid, NO))
        conn.commit()
    finally:
        conn.close()


def test_put_quotation_restores_masked_parts_exactly_when_the_old_table_says_so(client, make_user, fin):
    users = _users(make_user)
    _seed(status="草稿", assigned=[u[0] for u in users.values()])
    base = _db_data()
    heads = {r: _login(client, *u) for r, u in users.items()}
    seen = {200: 0, "denied": 0}
    for mode in MODES:
        fin["mode"] = mode
        for role in ROLES:
            for grant in GRANTS:
                fin["grant"] = grant
                money, quote, _ = _expect(role, mode, grant)
                _own(_user_id(users[role][0]))
                g = client.get("/api/quotations/" + NO, headers=heads[role])
                if not quote:                                   # 報價單層級閘門（含 money 為真但 quote 為假的格子）→ 403
                    r = client.put("/api/quotations/" + NO, headers=heads[role], json={"data": {"items": []}})
                    assert r.status_code in (403, 404), (role, mode, grant)
                    assert _db_data() == base, (role, mode, grant)
                    seen["denied"] += 1
                    continue
                d = g.json()
                data = d["data"]
                data["items"][0]["unitPrice"] = 5500
                data["items"][0]["amount"] = 11000
                r = client.put("/api/quotations/" + NO, headers=heads[role], json={"data": data, "status": d["status"]})
                assert r.status_code == 200, (role, mode, grant, r.text)
                now = _db_data()
                assert now["items"][0]["unitPrice"] == 5500, (role, mode, grant)
                assert now["settlement"]["summary"]["grossProfit"] == 3000, (role, mode, grant)           # 精算沒被空值蓋掉
                assert now["caseRecord"]["payment"]["items"][0]["actualAmount"] == 3087, (role, mode, grant)
                seen[200] += 1
                _seed_reset(base)
    assert seen[200] and seen["denied"]


def _seed_reset(base):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(base, ensure_ascii=False), NO))
        conn.commit()
    finally:
        conn.close()


def test_write_paths_propagate_evaluation_errors_and_reads_fail_closed(client, make_user, fin, monkeypatch):
    """今天：求值丟例外 ⇒ 寫入端點 500、什麼都沒寫；讀取端點維持遮蔽。不可把寫入也 fail-closed 成『遮』後回成功（靜默以現值覆蓋）。"""
    from helpers import financial_mask as FM
    u = make_user(username="fp_sales_err", role="sales")
    _seed(status="草稿", assigned=[u[0]])
    _own(_user_id(u[0]))
    h = _login(client, *u)
    base = _db_data()
    d = client.get("/api/quotations/" + NO, headers=h).json()
    d["data"]["items"][0]["unitPrice"] = 5500

    def boom(user):
        raise RuntimeError("flag evaluation failed")
    monkeypatch.setattr(FM, "money_visible", boom)
    try:
        r = client.put("/api/quotations/" + NO, headers=h, json={"data": d["data"], "status": d["status"]})
        status = r.status_code
    except RuntimeError:                                    # TestClient 把未處理例外直接丟出來
        status = 500
    assert status == 500
    assert _db_data() == base                               # 什麼都沒寫
    g = client.get("/api/quotations/" + NO, headers=h)      # 讀取：fail-closed（money 旗標算不出來 ⇒ 當作遮）
    assert g.status_code == 200 and g.json()["data"]["settlement"] == {"status": "未精算"}
