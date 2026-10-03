# -*- coding: utf-8 -*-
"""34-M2 接線：`purchase_items.material_submit_check`（po_required 路徑）加上 一品項一筆（`item_request_exists`）、涵蓋快照 `poSnapshot`、調整單 `adjustOf`。
舊路徑（po_required=False）逐位不變；`po_line_taken` 保留。"""
import json

import db
from modules.case import material_coverage as MC
from modules.case import purchase_items as PI
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_material_link_booking_2026_10_02 import _approved_po, _order, _won_case  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln  # noqa: F401


def _check(order, **kw):
    cn = db.get_db()
    try:
        return PI.material_submit_check(cn, NO, order, **kw)
    finally:
        cn.close()


def _row(item_id, status="已核准", doc=None):
    cn = db.get_db()
    try:
        cn.execute("UPDATE case_material_approvals SET status=?, doc_code=? WHERE quote_no=? AND item_id=?", (status, doc or "MO-" + item_id, NO, item_id))
        cn.commit()
    finally:
        cn.close()


def _paid(item_id, amount):
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        for o in d["caseRecord"]["materialOrders"]:
            if str(o["itemId"]) == item_id:
                o["paidAmount"] = amount
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        cn.commit()
    finally:
        cn.close()


def _codes(r):
    return [p["code"] for p in r["problems"]]


def test_first_request_gets_the_coverage_snapshot_and_no_problems(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000, unit="台"), _ln("a", 2, unitCost=1000, unit="台")])
    order = _order("M1", 5, 5000, quoteItemId="a", poDocCode=po["docCode"], poLine=1, unit="台")
    r = _check(order, exclude_item_id="M1", po_required=True)
    assert r["problems"] == []
    assert [(l["poDocCode"], l["line"], l["qty"]) for l in r["snapshot"]["poSnapshot"]] == [(po["docCode"], 1, 3.0), (po["docCode"], 2, 2.0)]


def test_second_live_request_on_the_same_item_is_refused_and_released_when_returned(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000, unit="台")])
    _put_materials([_order("M1", 3, 3000, quoteItemId="a", poDocCode=po["docCode"], poLine=1)], {"M1": "已核准"})
    _row("M1")
    second = _order("M2", 1, 100, quoteItemId="a", poDocCode=po["docCode"], poLine=1)
    r = _check(second, exclude_item_id="M2", po_required=True)
    assert "item_request_exists" in _codes(r) and "MO-M1" in [p["message"] for p in r["problems"] if p["code"] == "item_request_exists"][0]
    assert "po_line_taken" in _codes(r)                                        # 舊守門保留（d7 的補對應測試依賴它）
    _row("M1", "已退回")                                                        # 已退回不占
    assert "item_request_exists" not in _codes(_check(second, exclude_item_id="M2", po_required=True))
    _row("M1", "已核准")
    assert "item_request_exists" not in _codes(_check(_order("M1", 3, 3000, quoteItemId="a", poDocCode=po["docCode"], poLine=1), exclude_item_id="M1", po_required=True))   # 自己不算


def test_adjust_of_needs_a_paid_in_full_original_and_covers_only_new_lines(W):
    c, h = W
    po1 = _approved_po(c, h, [_ln("a", 3, unitCost=1000, unit="台")])
    _put_materials([_order("M1", 3, 3000, quoteItemId="a", poDocCode=po1["docCode"], poLine=1)], {"M1": "已核准"})
    _row("M1")
    _paid("M1", 3000)
    nothing_new = _order("M3", 1, 1, quoteItemId="a", poDocCode=po1["docCode"], poLine=1, adjustOf="M1")
    assert "adjust_no_new_lines" in _codes(_check(nothing_new, exclude_item_id="M3", po_required=True))             # 全額付款了但還沒有新的採購單行
    _paid("M1", 1000)
    po2 = _approved_po(c, h, [_ln("a", 2, unitCost=1000, unit="台")])
    adj = _order("M2", 2, 2000, quoteItemId="a", poDocCode=po2["docCode"], poLine=1, adjustOf="M1")
    r = _check(adj, exclude_item_id="M2", po_required=True)
    assert "adjust_not_paid_in_full" in _codes(r) and "item_request_exists" not in _codes(r)
    _paid("M1", 3000)
    r = _check(adj, exclude_item_id="M2", po_required=True)
    assert r["problems"] == [] and r["snapshot"]["adjustOf"] == "M1"
    assert [(l["poDocCode"], l["line"]) for l in r["snapshot"]["poSnapshot"]] == [(po2["docCode"], 1)]            # 只涵蓋原申請沒有的行


def test_legacy_path_is_unchanged_and_no_coverage_is_not_double_reported(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000, unit="台")])
    order = _order("M1", 3, 3000, quoteItemId="a", poDocCode=po["docCode"], poLine=1)
    legacy = _check(order, exclude_item_id="M1")                                  # po_required=False：不加快照、不查一品項一筆
    assert "poSnapshot" not in legacy["snapshot"] and "item_request_exists" not in _codes(legacy)
    none = _check(_order("M9", 1, 100, quoteItemId="b"), exclude_item_id="M9", po_required=True)   # 品項 b 沒有已核准採購單行
    assert _codes(none).count("po_required") == 1 and "no_coverage" not in _codes(none)


def test_snapshot_lines_prefers_the_applied_snapshot_over_the_submit_time_one():
    both = {"linkSnapshot": {"poSnapshot": [{"poDocCode": "A", "line": 1}]}, "snapshot": {"poSnapshot": [{"poDocCode": "B", "line": 2}]}}
    assert MC.snapshot_lines(both) == [{"poDocCode": "B", "line": 2}] and MC.snapshot_lines(json.dumps(both)) == [{"poDocCode": "B", "line": 2}]
    assert MC.snapshot_lines({"linkSnapshot": {"poSnapshot": [{"poDocCode": "A", "line": 1}]}}) == [{"poDocCode": "A", "line": 1}]
    assert MC.snapshot_lines("not json") == [] and MC.snapshot_lines(None) == [] and MC.snapshot_lines({"snapshot": "x"}) == []


def test_item_without_approved_po_lines_but_a_valid_po_code_reports_no_coverage(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000, unit="台")])
    r = _check(_order("M5", 1, 100, quoteItemId="b", poDocCode=po["docCode"]), exclude_item_id="M5", po_required=True)    # 品項 b 在這張採購單沒有行
    assert "no_coverage" in _codes(r)


def test_request_content_must_cover_all_approved_lines_only_quantity_may_be_lowered(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000, unit="台"), _ln("a", 2, unitCost=1000, unit="台")])
    # 只帶第 1 行（3 台／3000），但涵蓋快照有兩行（5 台／5000）⇒ 擋（N2：自動涵蓋該品項所有已核准行）
    one_line = _order("M1", 3, 3000, quoteItemId="a", poDocCode=po["docCode"], poLine=1, unit="台")
    r = _check(one_line, exclude_item_id="M1", po_required=True)
    assert "content_not_cover_snapshot" in _codes(r) and "5000" in [p["message"] for p in r["problems"] if p["code"] == "content_not_cover_snapshot"][0]
    full = _order("M1", 5, 5000, quoteItemId="a", poDocCode=po["docCode"], poLine=1, unit="台")
    assert _check(full, exclude_item_id="M1", po_required=True)["problems"] == []
    lowered = _order("M1", 4, 5000, quoteItemId="a", poDocCode=po["docCode"], poLine=1, unit="台")           # 數量可往下調、金額不可改
    assert _check(lowered, exclude_item_id="M1", po_required=True)["problems"] == []
    raised = _order("M1", 9, 5000, quoteItemId="a", poDocCode=po["docCode"], poLine=1, unit="台")
    assert "content_not_cover_snapshot" in _codes(_check(raised, exclude_item_id="M1", po_required=True))
    cheaper = _order("M1", 5, 4000, quoteItemId="a", poDocCode=po["docCode"], poLine=1, unit="台")
    assert "content_not_cover_snapshot" in _codes(_check(cheaper, exclude_item_id="M1", po_required=True))
