# -*- coding: utf-8 -*-
"""33-M1 E4／33-M2：涵蓋快照、`item_request_exists`、`change_proposal`（唯讀；規格 MATERIAL-FORCE-PO-AND-SHIPPING-SPEC §A.1／§B）。
品項 a：計畫 10×1000；b：100×5。"""
import json

import db
from modules.case import material_approval as MA
from modules.case import material_coverage as MC
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_material_link_booking_2026_10_02 import _approved_po, _order, _won_case  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _mk, _set_tiers, _submit  # noqa: F401


def _conn():
    return db.get_db()


def _row(item_id, status="已核准", snapshot=None, doc="MO-X"):
    cn = _conn()
    try:
        cn.execute("UPDATE case_material_approvals SET status=?, doc_code=?, approval_json=?, created_at=? WHERE quote_no=? AND item_id=?",
                   (status, doc, json.dumps({"snapshot": {"poSnapshot": snapshot or []}}), MA.PO_REQUIRED_FROM + "T09:00:00", NO, item_id))   # 規則上線後建立（非 grandfather）
        cn.commit()
    finally:
        cn.close()


def _line(code, n, qty, amount, unit="台"):
    return {"poDocCode": code, "line": n, "qty": qty, "unit": unit, "amount": amount}


def _call(fn, *a, **kw):
    cn = _conn()
    try:
        return fn(cn, NO, *a, **kw)
    finally:
        cn.close()


def test_coverage_counts_only_approved_po_lines_of_the_item(W):
    c, h = W
    p1 = _approved_po(c, h, [_ln("a", 3, unitCost=1000), _ln("b", 10, unitCost=5), _ln(None, 1, unitCost=77)])
    _set_tiers([{"order": 0, "approvers": [{"username": "pl_sa", "displayName": "主管"}]}])
    pending = _mk(c, h, "purchase_order", [_ln("a", 5, unitCost=1000)]).json()
    assert _submit(c, h, pending["id"]).status_code == 200                              # 待審核：不涵蓋
    _set_tiers([])
    _mk(c, h, "purchase_order", [_ln("a", 7, unitCost=1000)])                           # 草稿：不涵蓋
    snap = _call(MC.coverage_snapshot, "a")
    assert [(l["poDocCode"], l["line"], l["qty"], l["amount"]) for l in snap["poSnapshot"]] == [(p1["docCode"], 1, 3.0, 3000.0)]
    assert (snap["quantity"], snap["totalPrice"], snap["unitPrice"]) == (3.0, 3000.0, 1000.0)
    assert _call(MC.coverage_snapshot, "zzz")["poSnapshot"] == []                       # 沒有已核准行 ⇒ 空（不能建立材料申請）


def test_mixed_units_default_to_the_plan_quantity_and_extras_are_per_po(W):
    c, h = W
    po = _approved_po(c, h, [_ln("b", 4, unitCost=5, unit="個"), _ln("b", 2, unitCost=10, unit="條"), _ln(None, 3, unitCost=100), _ln(None, 1, unitCost=40)])
    s = _call(MC.coverage_snapshot, "b")
    assert (s["quantity"], s["unit"], s["totalPrice"]) == (100.0, "米", 20.0 + 20.0)    # 單位不同 ⇒ 品項報價量、報價單位；金額＝行合計
    e = _call(MC.coverage_snapshot, "", po["docCode"])                                   # 額外採購（N1）：以採購單為單位，涵蓋沒有品項的行
    assert [l["line"] for l in e["poSnapshot"]] == [3, 4] and e["totalPrice"] == 340.0


def test_item_request_exists_only_live_statuses_occupy(W):
    c, h = W
    _put_materials([_order("M1", 1, 100, quoteItemId="a")], {"M1": "已核准"})
    for st, occupies in (("草稿", True), ("待審核", True), ("簽核中", True), ("已核准", True), ("已退回", False), ("已取消", False)):
        _row("M1", st, doc="MO-1")
        got = _call(MC.item_request_exists, "a")
        assert (got is not None) == occupies, st
        if occupies:
            assert got == {"itemId": "M1", "docCode": "MO-1", "status": st}
    _row("M1", "已核准")
    assert _call(MC.item_request_exists, "a", exclude_item_id="M1") is None             # 排除自己（正在送審的那筆）
    assert _call(MC.item_request_exists, "b") is None                                    # 別的品項不受影響


def test_legacy_orders_without_an_approval_row_do_not_occupy(W):
    c, h = W
    _put_materials([_order("L", 1, 100, quoteItemId="a")], {})
    assert _call(MC.item_request_exists, "a") is None                                    # 舊單不溯及既往


def _approved_request(c, h, qty=3, amount=3000):
    po = _approved_po(c, h, [_ln("a", qty, unitCost=amount / qty, unit="台")])
    _put_materials([_order("M1", qty, amount, quoteItemId="a", poDocCode=po["docCode"], poLine=1, unit="台")], {"M1": "已核准"})
    _row("M1", "已核准", [_line(po["docCode"], 1, qty, amount)])
    return po


def test_change_proposal_picks_up_new_approved_lines_and_shows_the_diff(W):
    c, h = W
    po1 = _approved_request(c, h)
    po2 = _approved_po(c, h, [_ln("a", 2, unitCost=1000, unit="台")])                               # 下個月又買一批
    p = _call(MC.change_proposal, "M1")
    assert p["problems"] == []
    assert [(l["poDocCode"], l["line"]) for l in p["uncoveredLines"]] == [(po2["docCode"], 1)]
    assert p["before"]["quantity"] == 3 and p["after"]["quantity"] == 5 and p["after"]["totalPrice"] == 5000
    assert sorted(d["field"] for d in p["diff"]) == ["poSnapshot", "quantity", "totalPrice"]            # 單價 1000 不變
    money = {d["field"]: d["money"] for d in p["diff"]}
    assert money["totalPrice"] is True and money["quantity"] is False
    assert {(l["poDocCode"], l["line"]) for l in p["after"]["poSnapshot"]} == {(po1["docCode"], 1), (po2["docCode"], 1)}


def test_change_proposal_problems(W):
    c, h = W
    _approved_request(c, h)
    assert [x["code"] for x in _call(MC.change_proposal, "M1")["problems"]] == ["no_change"]                      # 沒有新行、沒改東西
    assert [x["code"] for x in _call(MC.change_proposal, "NOPE")["problems"]] == ["not_found"]
    _row("M1", "待審核")
    assert "not_approved" in [x["code"] for x in _call(MC.change_proposal, "M1")["problems"]]
    _row("M1", "已核准")
    assert "bad_quantity" in [x["code"] for x in _call(MC.change_proposal, "M1", {"quantity": 0})["problems"]]
    assert "unknown_field" in [x["code"] for x in _call(MC.change_proposal, "M1", {"totalPrice": 1})["problems"]]  # 金額來源在採購單，不能手改


def test_quantity_can_be_lowered_and_unit_price_follows_the_pos_amount(W):
    c, h = W
    _approved_request(c, h)
    p = _call(MC.change_proposal, "M1", {"quantity": 2, "notes": "客戶退一台"})
    assert p["problems"] == [] and p["after"]["quantity"] == 2 and p["after"]["totalPrice"] == 3000 and p["after"]["unitPrice"] == 1500
    assert {d["field"] for d in p["diff"]} == {"quantity", "unitPrice", "notes"}


def test_coverage_that_loses_an_approved_line_is_a_problem(W):
    c, h = W
    po = _approved_request(c, h)
    cn = _conn()
    cn.execute("UPDATE case_extra_expenses SET status='已作廢' WHERE doc_code=?", (po["docCode"],))
    cn.commit()
    cn.close()
    codes = [x["code"] for x in _call(MC.change_proposal, "M1")["problems"]]
    assert "coverage_shrinks" in codes and "no_coverage" in codes


def test_grandfathered_rows_use_direct_edit_not_a_change_request(W):
    c, h = W
    _approved_request(c, h)
    cn = _conn()
    cn.execute("UPDATE case_material_approvals SET approval_json=? WHERE quote_no=? AND item_id='M1'", (json.dumps({"grandfathered": True, "snapshot": {"poSnapshot": []}}), NO))
    cn.commit()
    cn.close()
    assert "use_direct_edit" in [x["code"] for x in _call(MC.change_proposal, "M1")["problems"]]


def test_unit_price_after_a_quantity_change_is_rounded_to_four_places(W):
    c, h = W
    _approved_request(c, h, qty=3, amount=1000)
    p = _call(MC.change_proposal, "M1", {"quantity": 3})
    assert p["after"]["unitPrice"] == round(1000 / 3, 4) == 333.3333


def _paid(item_id, amount):
    """付款明細的投影欄位（material_payment.sync_order_paid 寫的）。"""
    cn = _conn()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        for o in d["caseRecord"]["materialOrders"]:
            if str(o["itemId"]) == item_id:
                o["paidAmount"] = amount
                o["paidStatus"] = "paid" if amount >= o["totalPrice"] else "partial"
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        cn.commit()
    finally:
        cn.close()


def test_paid_in_full_blocks_a_change_and_points_to_an_adjustment(W):
    c, h = W
    _approved_request(c, h)
    _approved_po(c, h, [_ln("a", 2, unitCost=1000, unit="台")])                          # 有新採購單行，變更會改金額
    _paid("M1", 3000)
    codes = [x["code"] for x in _call(MC.change_proposal, "M1")["problems"]]
    assert "paid_in_full" in codes
    _paid("M1", 1000)                                                                    # 部分已付：可以變更，只要新小計不低於已付
    assert "paid_in_full" not in [x["code"] for x in _call(MC.change_proposal, "M1")["problems"]]
    _paid("M1", 2500)                                                                    # 部分已付 2500；涵蓋的採購單被作廢 ⇒ 新小計 0 低於已付
    cn = _conn()
    cn.execute("UPDATE case_extra_expenses SET status='已作廢' WHERE kind='purchase_order'")
    cn.commit()
    cn.close()
    assert "below_paid" in [x["code"] for x in _call(MC.change_proposal, "M1")["problems"]]


def test_adjust_of_is_exempt_from_one_item_one_request_only_when_the_original_is_paid_in_full(W):
    c, h = W
    _approved_request(c, h)
    assert _call(MC.item_request_exists, "a", adjust_of="M1") is not None                # 沒全額付款：原申請照常占用
    _paid("M1", 3000)
    assert _call(MC.item_request_exists, "a", adjust_of="M1") is None                    # 全額付款：調整單可另開
    assert _call(MC.item_request_exists, "a") is not None                                # 沒帶 adjustOf：仍占用（正對照）
    assert _call(MC.item_request_exists, "a", adjust_of="OTHER") is not None


def test_adjust_check_and_untaken_coverage(W):
    c, h = W
    po1 = _approved_request(c, h)
    codes = lambda: [x["code"] for x in _call(MC.adjust_check, "a", "M1")]   # noqa: E731
    assert set(codes()) == {"adjust_not_paid_in_full", "adjust_no_new_lines"}
    _paid("M1", 3000)
    assert codes() == ["adjust_no_new_lines"]                                            # 全額付款了，但沒有新的採購單行
    po2 = _approved_po(c, h, [_ln("a", 2, unitCost=1000, unit="台")])
    assert codes() == []
    snap = _call(MC.coverage_snapshot, "a", only_untaken=True)
    assert [(l["poDocCode"], l["line"]) for l in snap["poSnapshot"]] == [(po2["docCode"], 1)] and snap["totalPrice"] == 2000   # 只涵蓋原申請沒有的行
    assert {(l["poDocCode"], l["line"]) for l in _call(MC.coverage_snapshot, "a")["poSnapshot"]} == {(po1["docCode"], 1), (po2["docCode"], 1)}
    assert [x["code"] for x in _call(MC.adjust_check, "a", "NOPE")] == ["adjust_target_missing"]
    assert "adjust_item_mismatch" in [x["code"] for x in _call(MC.adjust_check, "b", "M1")]
