# -*- coding: utf-8 -*-
"""第 31 包 PR/PO 連品項的獨立探針（2e 稽核；與作者測試不同的攻擊角度）。隔離庫、唯讀（只對測試庫動作）。"""
import json
import threading
from datetime import date

import pytest

import db
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, BASE, Q, _body, _ln, _login, _mk, _set_tiers, _status, _submit  # noqa: F401


@pytest.fixture
def P(client, make_user):
    out = {}
    for n, role, mods in (("pb_sa", "superadmin", None), ("pb_eng", "engineer", ["case_manage", "expense_forms"]),
                          ("pb_out", "engineer", ["case_manage"])):
        u, p = make_user(username=n, role=role, modules=mods)
        out[n] = _login(client, u, p)
    cn = db.get_db()
    try:
        uid = cn.execute("SELECT id FROM users WHERE username='pb_eng'").fetchone()["id"]
        for no, assigned in ((NO, [uid]), ("MQ-PB-OTHER", [])):
            cn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, sales_person, assigned_user_ids)"
                       " VALUES (?,?,?,?,?,?,?,?,?)", (no, "已送出", "客", "案", json.dumps(Q), "2026-10-02T00:00:00", "2026-10-02T00:00:00", "pb_sa", json.dumps(assigned)))
        cn.commit()
    finally:
        cn.close()
    _set_tiers([])
    return client, out


def _po(c, h, lines, no=NO):
    return c.post("/api/quotations/%s/extra-expenses" % no, headers=h, json=_body("purchase_order", lines))


# ── (1) 可見性與越權 ────────────────────────────────────────────────────────────

def test_non_finance_viewer_never_sees_plan_cost_or_actual_money_anywhere(P):
    c, h = P
    eid = _po(c, h["pb_sa"], [_ln("a", 3, unitCost=1000)]).json()["id"]
    assert _submit(c, h["pb_sa"], eid).status_code == 200
    for who in ("pb_eng",):
        r = c.get("/api/quotations/%s/purchase-items" % NO, headers=h[who])
        assert r.status_code == 200
        txt = r.text
        assert "planUnitCost" not in txt and "actualAmount" not in txt and "3000" not in txt
        lst = c.get(BASE, headers=h[who]).json()
        # 單據金額對非申請人／簽核人／財務者遮蔽；合計與連結金額不可洩漏被遮蔽列
        assert lst["itemLinkedAmount"] == 0 and lst["extraOnlyAmount"] == 0 and lst["totalAmount"] == 0
        assert "3000" not in json.dumps(lst)


def test_other_cases_and_unrelated_users_get_404_and_cross_case_item_ids_are_rejected(P):
    c, h = P
    assert c.get("/api/quotations/%s/purchase-items" % NO, headers=h["pb_out"]).status_code == 404
    assert c.get("/api/quotations/MQ-PB-OTHER/purchase-items", headers=h["pb_eng"]).status_code == 404       # eng 沒被指派到別案
    # 別案件的品項 id：在這案不存在 ⇒ 400（兩案的 id 都叫 a，所以改用只存在於別案的 id）
    cn = db.get_db()
    d = dict(Q, items=Q["items"] + [{"id": "only_other", "description": "別案專屬", "qty": 5, "unit": "台", "cost": 1}])
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no='MQ-PB-OTHER'", (json.dumps(d),))
    cn.commit()
    cn.close()
    assert _po(c, h["pb_sa"], [_ln("only_other", 1)]).status_code == 400


# ── 上限、超計畫原因、竄改 ──────────────────────────────────────────────────────

def test_client_cannot_forge_snapshots_amounts_or_reasons(P):
    c, h = P
    r = _po(c, h["pb_sa"], [dict(_ln("a", 3, unitCost=1000), amount=1, itemQtyPlan=999, itemCostPlan=1, overPlanQty=0, overPlanReason="偽")])
    assert r.status_code == 201
    cn = db.get_db()
    row = cn.execute("SELECT total_cost, lines_json FROM case_extra_expenses WHERE id=?", (r.json()["id"],)).fetchone()
    cn.close()
    line = json.loads(row["lines_json"])[0]
    assert row["total_cost"] == 3000 and line["amount"] == 3000                                 # 金額以 qty×unitCost 重算
    assert (line["itemQtyPlan"], line["itemCostPlan"]) == (10.0, 1000.0)                          # 快照是伺服器的
    assert "overPlanReason" not in line and "overPlanQty" not in line                             # 沒超 ⇒ 偽造的原因不留


def test_cap_cannot_be_bypassed_by_update_after_draft_or_by_change_request(P):
    c, h = P
    first = _po(c, h["pb_sa"], [_ln("a", 8)]).json()["id"]
    assert _submit(c, h["pb_sa"], first).status_code == 200
    second = _po(c, h["pb_sa"], [_ln("a", 1)]).json()["id"]                                      # 草稿時在上限內
    up = c.patch("%s/%d" % (BASE, second), headers=h["pb_sa"], json=_body("purchase_order", [_ln("a", 5)]))
    assert up.status_code == 200 and up.json()["overPlan"]                                       # 改大後仍是警示（草稿）
    assert _submit(c, h["pb_sa"], second).status_code == 400                                     # 送審擋下
    # 核准後用變更申請把量改大
    ok = _po(c, h["pb_sa"], [_ln("b", 10)]).json()["id"]
    assert _submit(c, h["pb_sa"], ok).status_code == 200
    assert c.put("%s/%d/change-request" % (BASE, ok), headers=h["pb_sa"], json=_body("purchase_order", [_ln("b", 500)])).status_code == 200
    assert c.post("%s/%d/change-request/submit" % (BASE, ok), headers=h["pb_sa"]).status_code == 400


def test_concurrent_submits_cannot_both_exceed_the_plan_without_a_reason(P):
    """兩個人同時送審各 6/10：寫鎖內驗 ⇒ 至多一張在沒有原因下通過。"""
    c, h = P
    ids = [_po(c, h["pb_sa"], [_ln("a", 6)]).json()["id"] for _ in range(2)]
    res = {}

    def go(i):
        res[i] = _submit(c, h["pb_sa"], ids[i]).status_code
    ts = [threading.Thread(target=go, args=(i,)) for i in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(res.values()) in ([200, 400], [400, 400]), res                                  # 絕不會 [200, 200]


# ── (1)(2) 金額只算一次、品項被刪、新口徑 ────────────────────────────────────────

def test_each_amount_is_counted_once_across_list_report_and_gl_and_new_totals_rule(P):
    from modules.case import gl_events as GE
    from modules.case import recognition as R
    c, h = P
    sa = h["pb_sa"]
    po = _po(c, sa, [_ln("a", 3, unitCost=1000), _ln(None, 1, unitCost=500)]).json()["id"]
    assert _submit(c, sa, po).status_code == 200
    pr = c.post("/api/quotations/%s/extra-expenses" % NO, headers=sa, json=_body("purchase_req", [_ln("a", 4, unitCost=900)])).json()["id"]
    assert _submit(c, sa, pr).status_code == 200
    draft = _po(c, sa, [_ln("b", 10, unitCost=5)]).json()["id"]
    rej = _po(c, sa, [_ln("b", 20, unitCost=5)]).json()["id"]
    _status(rej, "已駁回")
    lst = c.get(BASE, headers=sa).json()
    assert lst["totalAmount"] == 3500 and lst["itemLinkedAmount"] == 3000 and lst["extraOnlyAmount"] == 500          # PR／草稿／駁回不計
    assert lst["uncountedAmount"] == 3600 + 50 + 100
    cn = db.get_db()
    try:
        ent = [e for e in R.extra_entries(cn, "accrual") if e["quoteNo"] == NO]
    finally:
        cn.close()
    assert sum(e["amount"] for e in ent) == 3500 and sum(e["amount"] for e in ent if e.get("linkedItem")) == 3000
    ev = [e for e in GE.gl_events("2000-01-01", "2099-12-31")["events"] if e["event_code"] == "E11" and e["source_key"] == str(po)]
    assert len(ev) == 1 and sum(l["amount"] for l in ev[0]["lines"] if l["side"] == "D") == 3500
    assert not [e for e in GE.gl_events("2000-01-01", "2099-12-31")["events"] if e["source_key"] in (str(pr), str(draft), str(rej))]


def test_removed_item_goes_back_to_extra_and_total_is_conserved(P):
    c, h = P
    sa = h["pb_sa"]
    po = _po(c, sa, [_ln("a", 3, unitCost=1000)]).json()["id"]
    assert _submit(c, sa, po).status_code == 200
    cn = db.get_db()
    d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    d["items"] = [i for i in d["items"] if i["id"] != "a"]
    cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
    cn.commit()
    cn.close()
    lst = c.get(BASE, headers=sa).json()
    pk = c.get("/api/quotations/%s/purchase-items" % NO, headers=sa).json()["items"]
    assert lst["totalAmount"] == 3000 and lst["itemLinkedAmount"] == 0 and lst["extraOnlyAmount"] == 3000
    assert lst["extraOnlyAmount"] + sum(i["actualAmount"] for i in pk) == lst["totalAmount"]
