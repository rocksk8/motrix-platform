# -*- coding: utf-8 -*-
"""32-S2：請購／採購單明細連案件品項——`itemId` 驗證、伺服器快照、累計上限（採購單擋、請購單只警示）、超計畫原因必填（Q2）、
`fromPr` 驗證、變更申請不能繞過；沒有 `itemId` 的明細與今天完全相同。"""
import json

import pytest

import db

NO = "MQ-PL-1"
Q = {"items": [
    {"id": "a", "description": "交換器", "qty": 10, "unit": "台", "cost": 1000},
    {"id": "b", "description": "線材", "qty": 100, "unit": "米", "cost": 5},
]}
BASE = "/api/quotations/%s/extra-expenses" % NO


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _set_tiers(tiers):
    c = db.get_db()
    c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
              ("unified_approval_flow", json.dumps({"tiers": tiers, "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
    c.commit()
    c.close()


@pytest.fixture
def W(client, make_user):
    u, p = make_user(username="pl_sa", role="superadmin")
    h = _login(client, u, p)
    c = db.get_db()
    for no in (NO, "MQ-PL-2"):
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, sales_person)"
                  " VALUES (?,?,?,?,?,?,?,?)", (no, "已送出", "客", "案", json.dumps(Q), "2026-10-02T00:00:00", "2026-10-02T00:00:00", "pl_sa"))
    c.commit()
    c.close()
    _set_tiers([])                                       # 沒設簽核層 ⇒ 送審即核准
    return client, h


def _body(kind, lines, data=None):
    return {"kind": kind, "lines": lines, "payeeName": "某人", "payeeType": "employee", "data": dict({"applicant": "pl_sa"}, **(data or {}))}


def _ln(item, qty, **kw):
    d = {"category": "雜項", "summary": "x", "qty": qty, "unitCost": 100}
    if item:
        d["itemId"] = item
    d.update(kw)
    return d


def _mk(c, h, kind, lines, data=None, no=NO):
    r = c.post("/api/quotations/%s/extra-expenses" % no, headers=h, json=_body(kind, lines, data))
    return r


def _status(eid, status):
    cn = db.get_db()
    cn.execute("UPDATE case_extra_expenses SET status=? WHERE id=?", (status, eid))
    cn.commit()
    cn.close()


def _stored(eid):
    cn = db.get_db()
    try:
        return json.loads(cn.execute("SELECT lines_json FROM case_extra_expenses WHERE id=?", (eid,)).fetchone()["lines_json"])
    finally:
        cn.close()


def _submit(c, h, eid, no=NO):
    return c.post("/api/quotations/%s/extra-expenses/%d/submit" % (no, eid), headers=h)


# ── 基本驗證與伺服器快照 ────────────────────────────────────────────────────

def test_linked_line_gets_server_plan_snapshot_and_ignores_client_snapshot(W):
    c, h = W
    r = _mk(c, h, "purchase_order", [_ln("a", 3, itemQtyPlan=999, itemCostPlan=1, overPlanQty=77)])
    assert r.status_code == 201 and "overPlan" not in r.json(), r.text
    l = _stored(r.json()["id"])[0]
    assert (l["itemId"], l["itemQtyPlan"], l["itemCostPlan"]) == ("a", 10.0, 1000.0) and "overPlanQty" not in l


def test_unlinked_lines_are_unchanged_and_lose_reserved_link_keys(W):
    c, h = W
    r = _mk(c, h, "purchase_order", [_ln(None, 2, itemQtyPlan=5, overPlanReason="偷塞", custom="保留")])
    assert r.status_code == 201
    l = _stored(r.json()["id"])[0]
    assert "itemId" not in l and "itemQtyPlan" not in l and "overPlanReason" not in l and l["custom"] == "保留"     # 未知鍵照舊保留，保留鍵拿掉


@pytest.mark.parametrize("lines, why", [
    ([_ln("zzz", 1)], "品項不在報價"),
    ([_ln("a", 0)], "數量 0"),
    ([_ln("a", "x")], "數量不是數字"),
    ([_ln("a", -1)], "數量負數"),
])
def test_bad_linked_lines_are_rejected(W, lines, why):
    c, h = W
    assert _mk(c, h, "purchase_order", lines).status_code == 400, why


def test_links_only_on_case_bound_pr_and_po(W):
    c, h = W
    assert c.post("/api/quotations/-/extra-expenses", headers=h, json=_body("purchase_order", [_ln("a", 1)])).status_code == 400    # 無案件
    assert _mk(c, h, "travel", [_ln("a", 1)]).status_code == 400                                                                      # 其他類型
    assert _mk(c, h, "petty_cash", [_ln("a", 1)]).status_code == 400
    assert _mk(c, h, "purchase_req", [_ln("a", 1)]).status_code == 201                                                                # 請購單可以


# ── 累計上限與超計畫原因 ─────────────────────────────────────────────────────

def test_po_over_plan_warns_on_draft_but_submit_needs_a_reason(W):
    c, h = W
    first = _mk(c, h, "purchase_order", [_ln("a", 8)]).json()["id"]
    assert _submit(c, h, first).status_code == 200                          # 8/10 核准（沒設層⇒核准）
    r = _mk(c, h, "purchase_order", [_ln("a", 5)])
    assert r.status_code == 201 and r.json()["overPlan"][0]["over"] == 3.0 and r.json()["overPlan"][0]["usedQty"] == 8.0
    eid = r.json()["id"]
    s = _submit(c, h, eid)
    assert s.status_code == 400 and "超出報價計畫量" in s.text
    assert c.get("%s" % BASE, headers=h).json()["items"][-1]["status"] == "草稿"            # 狀態沒動
    u = c.patch("%s/%d" % (BASE, eid), headers=h, json=_body("purchase_order", [_ln("a", 5, overPlanReason="客戶加購")]))
    assert u.status_code == 200 and u.json()["overPlan"][0]["reason"] == "客戶加購"
    assert _submit(c, h, eid).status_code == 200
    l = _stored(eid)[0]
    assert l["overPlanQty"] == 3.0 and l["overPlanReason"] == "客戶加購"


def test_pr_over_plan_only_warns(W):
    c, h = W
    r = _mk(c, h, "purchase_req", [_ln("a", 15)])
    assert r.status_code == 201 and r.json()["overPlan"][0]["over"] == 5.0
    assert _submit(c, h, r.json()["id"]).status_code == 200                 # 請購單：不需要原因（Q3）


def test_cumulates_within_one_document_and_is_released_by_rejection_and_void(W):
    c, h = W
    r = _mk(c, h, "purchase_order", [_ln("a", 6), _ln("a", 6)])
    assert [w["line"] for w in r.json()["overPlan"]] == [2] and r.json()["overPlan"][0]["over"] == 2.0
    eid = _mk(c, h, "purchase_order", [_ln("b", 90)]).json()["id"]
    assert _submit(c, h, eid).status_code == 200
    again = _mk(c, h, "purchase_order", [_ln("b", 20)])
    assert again.json()["overPlan"][0]["over"] == 10.0
    for st in ("已駁回", "已作廢"):
        _status(eid, st)
        assert "overPlan" not in _mk(c, h, "purchase_order", [_ln("b", 20)]).json()      # 駁回／作廢釋放用量


def test_editing_my_own_document_does_not_count_it_twice_and_two_submits_cannot_both_slip_through(W):
    c, h = W
    a = _mk(c, h, "purchase_order", [_ln("a", 6)]).json()["id"]
    assert _submit(c, h, a).status_code == 200
    # 兩張各 6／10：第二張送審時第一張已佔量 ⇒ 要原因
    b = _mk(c, h, "purchase_order", [_ln("a", 6)]).json()["id"]
    assert _submit(c, h, b).status_code == 400
    assert c.patch("%s/%d" % (BASE, b), headers=h, json=_body("purchase_order", [_ln("a", 4)])).status_code == 200      # 6+4＝10 剛好
    assert _submit(c, h, b).status_code == 200


# ── fromPr ────────────────────────────────────────────────────────────────

def test_from_pr_must_be_an_approved_pr_of_the_same_case(W):
    c, h = W
    pr = _mk(c, h, "purchase_req", [_ln("a", 2)]).json()
    other = _mk(c, h, "purchase_req", [_ln("a", 2)], no="MQ-PL-2").json()
    assert _mk(c, h, "purchase_order", [_ln("a", 1)], {"fromPr": pr["docCode"]}).status_code == 400          # 請購單還沒核准
    assert _submit(c, h, pr["id"]).status_code == 200
    assert _submit(c, h, other["id"], no="MQ-PL-2").status_code == 200
    ok = _mk(c, h, "purchase_order", [_ln("a", 1)], {"fromPr": pr["docCode"]})
    assert ok.status_code == 201
    assert _mk(c, h, "purchase_order", [_ln("a", 1)], {"fromPr": other["docCode"]}).status_code == 400      # 別案件的請購單
    assert _mk(c, h, "purchase_order", [_ln("a", 1)], {"fromPr": "PR-NOPE"}).status_code == 400
    assert _mk(c, h, "purchase_req", [_ln("a", 1)], {"fromPr": pr["docCode"]}).status_code == 400            # 請購單不能有來源
    po_code = c.get(BASE, headers=h).json()["items"][-1]["docCode"]
    assert _mk(c, h, "purchase_order", [_ln("a", 1)], {"fromPr": po_code}).status_code == 400                # 來源不是請購單


# ── 變更申請不能繞過 ──────────────────────────────────────────────────────

def test_change_request_cannot_bypass_the_cap(W):
    c, h = W
    po = _mk(c, h, "purchase_order", [_ln("a", 4)]).json()["id"]
    assert _submit(c, h, po).status_code == 200
    r = c.put("%s/%d/change-request" % (BASE, po), headers=h, json=_body("purchase_order", [_ln("a", 12)]))
    assert r.status_code == 200, r.text
    s = c.post("%s/%d/change-request/submit" % (BASE, po), headers=h)
    assert s.status_code == 400 and "超出報價計畫量" in s.text                    # 自己原本的 4 不重複算，仍超 2
    r = c.put("%s/%d/change-request" % (BASE, po), headers=h, json=_body("purchase_order", [_ln("a", 12, overPlanReason="追加")]))
    assert r.status_code == 200
    assert c.post("%s/%d/change-request/submit" % (BASE, po), headers=h).status_code == 200
