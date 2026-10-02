# -*- coding: utf-8 -*-
"""33-M1（守門側）：強制採購單（E1／E2）——新申請必須帶採購單連結、送審必須已有「已核准」採購單；舊單與規則上線前已存在的單不受影響，
可「補對應」（只增連結鍵，不重簽，留歷程與稽核）。付款互斥（E3）見 test_material_link_api／seam（有效連結不能開匯款申請）。"""
import json

import pytest

import db
from modules.case import material_approval as MA
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _mk, _status, _submit  # noqa: F401

@pytest.fixture(autouse=True)
def _po_rule_on(monkeypatch):
    """出貨預設是關的（見 test_material_po_default_off_2026_10_03.py）；本檔驗規則本身，明確設成開。"""
    monkeypatch.setattr(MA, "PO_REQUIRED", True)


MSG_NONE = "需先申請請購單，再申請採購單；採購單通過後，才能對應這筆材料申請。"
MSG_PENDING = "採購單尚未通過，通過後才能對應這筆材料申請。"
MSG_VOID = "對應的採購單已退回（或作廢），請重新申請採購單。"


def _mo(item, **kw):
    o = {"itemId": item, "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 1000, "totalPrice": 2000, "supplierId": 1,
         "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": "", "quoteItemId": "a"}
    o.update(kw)
    return o


def _po(c, h, approve=True):
    r = _mk(c, h, "purchase_order", [_ln("a", 2)]).json()
    if approve:
        assert _submit(c, h, r["id"]).status_code == 200
    return r


def _ap(item):
    cn = db.get_db()
    try:
        r = cn.execute("SELECT status, approval_json, created_at FROM case_material_approvals WHERE quote_no=? AND item_id=?", (NO, item)).fetchone()
        return dict(r) if r else None
    finally:
        cn.close()


def _orders():
    cn = db.get_db()
    try:
        return (json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]).get("caseRecord") or {}).get("materialOrders") or []
    finally:
        cn.close()


def _patch(c, h, orders):
    r = c.patch("/api/quotations/%s/material-orders" % NO, headers=h, json={"materialOrders": orders})
    assert r.status_code == 200, r.text
    return r.json()


def _submit_mo(c, h, item):
    return c.post("/api/quotations/%s/material-orders/%s/submit" % (NO, item), headers=h)


def _age(item, when):
    cn = db.get_db()
    cn.execute("UPDATE case_material_approvals SET created_at=? WHERE quote_no=? AND item_id=?", (when, NO, item))
    cn.commit()
    cn.close()


def test_a_new_request_must_carry_a_po_link_but_a_linked_one_is_saved(W):
    c, h = W
    res = _patch(c, h, [_mo("n1")])
    assert [x["code"] for x in res["rejected"]] == ["po_required"] and MSG_NONE in res["rejected"][0]["message"]
    assert _orders() == [] and _ap("n1") is None                                         # 不留列、不建草稿
    po = _po(c, h)
    res = _patch(c, h, [_mo("n1", poDocCode=po["docCode"], poLine=1)])
    assert not res.get("rejected"), res
    assert _orders()[0]["poDocCode"] == po["docCode"] and _ap("n1")["status"] == "草稿"


def test_submit_needs_an_approved_po_with_the_three_wordings(W):
    c, h = W
    _put_materials([_mo("m1")], {"m1": "草稿"})
    _age("m1", "2026-10-05T00:00:00")                                                   # 規則上線後建立（不在 grandfather 範圍）
    r = _submit_mo(c, h, "m1")
    assert r.status_code == 400 and MSG_NONE in r.text and _ap("m1")["status"] == "草稿"
    draft_po = _po(c, h, approve=False)                                                  # 草稿採購單＝尚未通過
    _put_materials([_mo("m1", poDocCode=draft_po["docCode"], poLine=1)], {})
    r = _submit_mo(c, h, "m1")
    assert r.status_code == 400 and MSG_PENDING in r.text
    _status(draft_po["id"], "已駁回")                                                    # 退回／作廢
    r = _submit_mo(c, h, "m1")
    assert r.status_code == 400 and MSG_VOID in r.text
    good = _po(c, h)
    _put_materials([_mo("m1", poDocCode=good["docCode"], poLine=1)], {})
    r = _submit_mo(c, h, "m1")
    assert r.status_code == 200, r.text and _ap("m1")["status"] in ("待審核", "已核准")


def test_legacy_and_pre_rule_requests_are_not_forced(W):
    c, h = W
    _put_materials([_mo("L1", quoteItemId=""), _mo("L2", quoteItemId=""), _mo("L3", quoteItemId="")], {"L2": "草稿", "L3": "草稿"})
    _age("L2", "2026-09-20T00:00:00")                                                   # 規則上線前建立的草稿
    cn = db.get_db()                                                                    # L3：舊單被編輯而建的審核列（grandfathered）
    cn.execute("UPDATE case_material_approvals SET approval_json=? WHERE quote_no=? AND item_id='L3'", (json.dumps({"grandfathered": True}), NO))
    cn.commit()
    cn.close()
    _age("L3", "2026-10-05T00:00:00")
    for item in ("L1", "L2", "L3"):                                                     # L1＝沒有審核列的舊單：送審時建 grandfathered 草稿
        r = _submit_mo(c, h, item)
        assert r.status_code == 200, (item, r.text)


def test_legacy_row_edit_turned_draft_stays_grandfathered(W):
    """舊單（沒有審核列）被實質編輯 ⇒ 建草稿，這個草稿不受強制採購單約束（舊單不受影響）。"""
    c, h = W
    _put_materials([_mo("L1", quoteItemId="")], {})
    _patch(c, h, [_mo("L1", quoteItemId="", unitPrice=1100, totalPrice=2200)])
    ap = _ap("L1")
    assert ap and ap["status"] == "草稿" and json.loads(ap["approval_json"]).get("grandfathered") is True
    assert _submit_mo(c, h, "L1").status_code == 200


def test_supplementing_a_link_on_a_grandfathered_request_keeps_status_and_leaves_history_and_audit(W):
    c, h = W
    po = _po(c, h)
    _put_materials([_mo("m1", quoteItemId="")], {"m1": "已核准"})                        # created_at 空＝規則上線前
    res = _patch(c, h, [_mo("m1", quoteItemId="a", poDocCode=po["docCode"], poLine=1)])
    assert not res.get("rejected"), res
    ap = _ap("m1")
    assert ap["status"] == "已核准"                                                      # 補對應：不重簽
    assert [x["action"] for x in json.loads(ap["approval_json"])["history"]][-1] == "link_supplement"
    assert _orders()[0]["poDocCode"] == po["docCode"]
    cn = db.get_db()
    try:
        assert cn.execute("SELECT COUNT(*) FROM audit_log WHERE action='material_orders.link_supplement'").fetchone()[0] == 1
    finally:
        cn.close()


def test_supplementing_a_legacy_row_does_not_create_an_approval_row(W):
    c, h = W
    po = _po(c, h)
    _put_materials([_mo("L1", quoteItemId="")], {})
    res = _patch(c, h, [_mo("L1", quoteItemId="a", poDocCode=po["docCode"], poLine=1)])
    assert not res.get("rejected"), res
    assert _orders()[0]["poDocCode"] == po["docCode"] and _ap("L1") is None


def test_supplement_is_refused_with_paid_history_or_a_bad_link_and_only_applies_to_added_links(W):
    c, h = W
    po = _po(c, h)
    _put_materials([_mo("m1", quoteItemId="", paidStatus="paid", paidAmount=2000, paidDate="2026-08-01")], {"m1": "已核准"})
    r = c.patch("/api/quotations/%s/case-record" % NO, headers=h, json={"case_record": {"materialOrders": [
        _mo("m1", quoteItemId="a", poDocCode=po["docCode"], poLine=1, paidStatus="paid", paidAmount=2000, paidDate="2026-08-01")]}})   # 後門路徑（專屬端點自己就 400）
    assert r.status_code == 200 and r.json().get("rejected") and not _orders()[0].get("poDocCode")                                 # 已有付款紀錄不可對應
    _put_materials([_mo("m2", quoteItemId="")], {"m2": "已核准"})
    res = _patch(c, h, [_mo("m2", quoteItemId="a", poDocCode="PO-NOPE")])
    assert [x["code"] for x in res["rejected"]] == ["bad_link"]
    # 補對應時同時改了金額（不是只增連結鍵）⇒ 不算補對應：走一般實質變更（已核准 ⇒ 回草稿）
    res = _patch(c, h, [_mo("m2", quoteItemId="a", poDocCode=po["docCode"], poLine=1, unitPrice=1200, totalPrice=2400)])
    assert _ap("m2")["status"] == "草稿"


def test_supplement_cannot_double_cover_one_po_line(W):
    """da S1：補對應不經送審，兩筆已核准舊單不可連到同一採購單同一行（與送審檢查同一判斷 po_line_taken）。"""
    c, h = W
    po = _po(c, h)
    _put_materials([_mo("m1", quoteItemId=""), _mo("m2", quoteItemId="")], {"m1": "已核准", "m2": "已核准"})
    res = _patch(c, h, [_mo("m1", quoteItemId="a", poDocCode=po["docCode"], poLine=1), _mo("m2", quoteItemId="")])
    assert not res.get("rejected"), res
    res = _patch(c, h, [_mo("m1", quoteItemId="a", poDocCode=po["docCode"], poLine=1), _mo("m2", quoteItemId="a", poDocCode=po["docCode"], poLine=1)])
    assert [(x["itemId"], x["code"]) for x in res["rejected"]] == [("m2", "bad_link")] and "已對應另一筆材料申請" in res["rejected"][0]["message"]
    assert not [o for o in _orders() if o["itemId"] == "m2"][0].get("poDocCode")


def test_grandfathered_flag_survives_a_tiered_submit_and_a_reject(W):
    """舊單送審（grandfathered 草稿）→ 有簽核層送審 → 退回 → 重送：標記不可在重建 approval_json 時掉掉（掉了＝舊單被當成上線後的新單，重送被擋「需先申請請購單」）。"""
    boss = {"username": "gf_boss", "role": "sales", "display_name": "主管"}
    eng = {"username": "gf_eng", "role": "sales", "display_name": "工程師"}
    cn = db.get_db()
    try:
        cn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                   ("unified_approval_flow", json.dumps({"tiers": [{"order": 0, "approvers": [{"username": boss["username"], "displayName": "主管"}]}], "includeSubmitterManagerTier": False}),
                    "2026-01-01T00:00:00"))
        cn.commit()                                                                                   # 簽核設定由另一條連線讀，要先提交
        MA.create_draft(cn, NO, "gf1", eng, "舊單", grandfathered=True)
        order = _mo("gf1", quoteItemId="")
        assert MA.submit(cn, NO, order, eng)["status"] == MA.S_PENDING
        assert json.loads(MA.get(cn, NO, "gf1")["approval_json"]).get("grandfathered") is True        # 有簽核層的送審重建 approval_json 之後標記還在
        MA.reject(cn, NO, "gf1", boss, "退回")
        assert MA.po_required_for(MA.get(cn, NO, "gf1")) is False                                      # 退回後仍是舊單：重送不必有採購單
        assert MA.submit(cn, NO, order, eng)["status"] == MA.S_PENDING
        assert json.loads(MA.get(cn, NO, "gf1")["approval_json"]).get("grandfathered") is True
        cn.rollback()
    finally:
        cn.close()
