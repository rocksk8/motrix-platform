# -*- coding: utf-8 -*-
"""32-S4 接縫（d7）：材料申請的連結鍵進實質欄位、儲存時 `LINK_VALIDATOR`、送審時 `material_submit_check`、核准詳情欄位、
有採購單連結者不能開匯款申請、有匯款申請時不能改連結。走真實 HTTP／真實守門。"""
import json

import pytest

import db
from modules.case import material_approval as MA
from modules.case import material_guard as MG
from modules.case import material_payment as MP
from modules.case import purchase_items as PI
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _mk, _submit  # noqa: F401



@pytest.fixture(autouse=True)
def _po_rule_off(monkeypatch):
    """本檔測的是別的規則；33-M1「新申請必須帶採購單／送審必須有已核准採購單」另有 test_material_po_required_2026_10_03.py。"""
    from modules.case import material_approval as _MA
    monkeypatch.setattr(_MA, "PO_REQUIRED", False)

def _mo(item, **kw):
    o = {"itemId": item, "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 1000, "totalPrice": 2000, "supplierId": 1,
         "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": ""}
    o.update(kw)
    return o


def _orders():
    cn = db.get_db()
    try:
        return (json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"]).get("caseRecord") or {}).get("materialOrders") or []
    finally:
        cn.close()


def _ap(item):
    cn = db.get_db()
    try:
        r = cn.execute("SELECT status, approval_json FROM case_material_approvals WHERE quote_no=? AND item_id=?", (NO, item)).fetchone()
        return dict(r) if r else None
    finally:
        cn.close()


def _patch(c, h, orders):
    r = c.patch("/api/quotations/%s/material-orders" % NO, headers=h, json={"materialOrders": orders})
    assert r.status_code == 200, r.text
    return r.json()


def _po(c, h, qty=2):
    r = _mk(c, h, "purchase_order", [_ln("a", qty)]).json()
    assert _submit(c, h, r["id"]).status_code == 200
    return r["docCode"]


def test_link_keys_are_substantive_and_the_over_plan_note_is_not():
    for k in ("quoteItemId", "poDocCode", "poLine"):
        assert k in MA.SUBSTANTIVE_KEYS
    assert "overPlanReason" not in MA.SUBSTANTIVE_KEYS
    base = _mo("m1", quoteItemId="a", poDocCode="PO-1", poLine=1)
    assert MA.substantive_changed(base, dict(base, poDocCode="PO-2"))
    assert MA.substantive_changed(base, dict(base, poLine=2)) and MA.substantive_changed(base, dict(base, quoteItemId="b"))
    assert not MA.substantive_changed(base, dict(base, overPlanReason="客戶加購"))
    assert not MA.substantive_changed(base, dict(base, poLine="1"))                              # "1"／1 同值


def test_the_validator_is_wired_in_by_the_api_module():
    import modules.case.api.material_approvals  # noqa: F401
    assert MG.LINK_VALIDATOR is PI.link_validator


def test_new_row_with_a_bad_link_is_rejected_and_leaves_no_row_or_draft(W):
    c, h = W
    res = _patch(c, h, [_mo("n1", quoteItemId="zzz")])
    assert [x["code"] for x in res["rejected"]] == ["bad_link"] and _orders() == [] and _ap("n1") is None
    res = _patch(c, h, [_mo("n2", poDocCode="PO-NOPE")])
    assert [x["code"] for x in res["rejected"]] == ["bad_link"] and _orders() == [] and _ap("n2") is None
    res = _patch(c, h, [_mo("n3", poLine=2)])                                                       # 有列序沒採購單
    assert [x["code"] for x in res["rejected"]] == ["bad_link"] and _ap("n3") is None


def test_new_row_with_a_valid_link_is_saved_and_the_po_line_is_an_int(W):
    c, h = W
    code = _po(c, h)
    res = _patch(c, h, [_mo("n1", quoteItemId="a", poDocCode=code, poLine="1")])
    assert not res.get("rejected"), res
    o = _orders()[0]
    assert o["poDocCode"] == code and o["poLine"] == 1 and isinstance(o["poLine"], int) and o["quoteItemId"] == "a"
    assert _ap("n1")["status"] == "草稿"


def test_changing_the_link_of_an_approved_request_goes_back_to_draft_and_a_bad_change_is_refused(W, monkeypatch):
    """強制規則上線後建立的單（不在 grandfather 範圍）：核准後連結變動＝實質變動 ⇒ 回草稿重送審。"""
    from modules.case import material_approval as _MA
    monkeypatch.setattr(_MA, "PO_REQUIRED", True)
    c, h = W
    code = _po(c, h)
    _put_materials([_mo("m1", quoteItemId="a")], {"m1": "已核准"})
    cn = db.get_db()
    cn.execute("UPDATE case_material_approvals SET created_at='2026-10-05T00:00:00' WHERE quote_no=? AND item_id='m1'", (NO,))
    cn.commit()
    cn.close()
    bad = _patch(c, h, [_mo("m1", quoteItemId="a", poDocCode="PO-NOPE")])
    assert [x["code"] for x in bad["rejected"]] == ["bad_link"]
    assert _orders()[0].get("poDocCode") in (None, "") and _ap("m1")["status"] == "已核准"          # 被拒：值與狀態都沒變
    ok = _patch(c, h, [_mo("m1", quoteItemId="a", poDocCode=code, poLine=1)])
    assert not ok.get("rejected"), ok
    assert _orders()[0]["poDocCode"] == code and _ap("m1")["status"] == "草稿"                       # 實質欄位變動 ⇒ 回草稿重送審


def test_the_link_cannot_change_while_there_are_live_remittances(W, monkeypatch):
    c, h = W
    code = _po(c, h)
    _put_materials([_mo("m1", quoteItemId="a")], {"m1": "已核准"})
    monkeypatch.setattr(MP, "has_live_payments", lambda conn, q, i: True)
    res = _patch(c, h, [_mo("m1", quoteItemId="a", poDocCode=code, poLine=1)])
    assert [x["code"] for x in res["rejected"]] == ["has_payments"]
    assert _orders()[0].get("poDocCode") in (None, "") and _ap("m1")["status"] == "已核准"


def test_a_request_linked_to_a_po_cannot_open_a_remittance(W, monkeypatch):
    c, h = W
    code = _po(c, h)                                                                # 有效連結（已核准採購單）才擋；失效連結不擋（2e 65837b0c）
    monkeypatch.setattr(MP, "_check_order_for_payment", lambda conn, q, o: None)
    cn = db.get_db()
    try:
        with pytest.raises(MP.MaterialPaymentError) as e:
            MP.create(cn, NO, _mo("m1", quoteItemId="a", poDocCode=code, poLine=1), {"username": "u", "role": "superadmin"}, {})
        assert e.value.status == 409 and code in e.value.message
    finally:
        cn.close()


def test_submit_runs_the_check_stores_the_snapshot_and_the_detail_shows_it(W):
    c, h = W
    # 超出計畫量（計畫 10）沒填原因 ⇒ 400，不送審
    _put_materials([_mo("m1", quoteItemId="a", quantity=11, unitPrice=10, totalPrice=110)], {"m1": "草稿"})
    r = c.post("/api/quotations/%s/material-orders/m1/submit" % NO, headers=h)
    assert r.status_code == 400 and "超出報價計畫量" in r.text and _ap("m1")["status"] == "草稿"
    # 填了原因 ⇒ 送審成功（沒設簽核層＝直接核准），快照寫進 approval_json，詳情有兩欄
    _put_materials_reason = _orders()
    _put_materials_reason[0]["overPlanReason"] = "客戶加購"
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["caseRecord"]["materialOrders"] = _put_materials_reason
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        cn.commit()
    finally:
        cn.close()
    r = c.post("/api/quotations/%s/material-orders/m1/submit" % NO, headers=h)
    assert r.status_code == 200, r.text
    snap = json.loads(_ap("m1")["approval_json"])["linkSnapshot"]
    assert snap["overPlanQty"] == 1 and snap["overPlanReason"] == "客戶加購" and snap["linkState"] == "none"
    code = r.json()["docCode"]
    d = c.get("/api/approval-queue/detail", params={"type": "material_order", "id": code}, headers=h)
    assert d.status_code == 200, d.text
    labels = {f["label"]: f["value"] for f in d.json()["fields"]}
    assert labels["採購單連結"] == "該材料申請未申請採購單" and labels["超出計畫"].startswith("超出 1")


def test_case_record_back_door_normalizes_the_po_line_too(W):
    """專屬端點的 pydantic 會把列序轉整數；整包存檔（case-record）沒有，守門自己要轉。"""
    c, h = W
    code = _po(c, h)
    cr = {"materialOrders": [_mo("n1", quoteItemId="a", poDocCode=code, poLine="1")]}
    r = c.patch("/api/quotations/%s/case-record" % NO, headers=h, json={"case_record": cr})
    assert r.status_code == 200 and not r.json().get("rejected"), r.text
    o = _orders()[0]
    assert o["poLine"] == 1 and isinstance(o["poLine"], int)


def test_case_record_back_door_cannot_add_a_po_link_to_a_paid_order(W):
    """33：link_validator 對「已有付款紀錄」放行（讓既有連結存回）⇒ 新增／改連結的擋要在守門自己做（專屬端點另有同規則）。"""
    c, h = W
    code = _po(c, h)
    _put_materials([_mo("m1", quoteItemId="a", paidStatus="paid", paidAmount=2000, paidDate="2026-08-01")], {})
    cr = {"materialOrders": [_mo("m1", quoteItemId="a", poDocCode=code, poLine=1, paidStatus="paid", paidAmount=2000, paidDate="2026-08-01")]}
    r = c.patch("/api/quotations/%s/case-record" % NO, headers=h, json={"case_record": cr})
    assert r.status_code == 200 and [x["code"] for x in r.json().get("rejected", [])] == ["bad_link"], r.text
    assert _orders()[0].get("poDocCode") in (None, "")
