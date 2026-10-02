# -*- coding: utf-8 -*-
"""32-S4a：叫料與請購／採購單的連結——`material_link_status` 三態判定、叫料對已訂量的貢獻（與採購單挑選器同一口徑、連採購單者只算一次）、
上限檢查與挑選器剩餘量同一份數字。（規格 docs/platform/plans/MATERIAL-ORDER-LINK-SPEC.md §2／§3.4）"""
import json

import pytest

import db
from modules.case import purchase_items as PI
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _mk, _status, _submit  # noqa: F401


def _po(code, status="已核准", lines=None, kind="purchase_order"):
    return {"doc_code": code, "kind": kind, "status": status, "lines_json": json.dumps(lines if lines is not None else [{"itemId": "a", "qty": 2}, {"qty": 1}])}


def _o(**kw):
    base = {"itemId": "m1", "itemName": "交換器", "quantity": 3, "totalPrice": 3000}
    base.update(kw)
    return base


# ── material_link_status ──────────────────────────────────────────────────

def test_status_exempt_for_legacy_and_zero_amount_whatever_the_link():
    rows = [_po("PO-1")]
    assert PI.material_link_status(_o(), rows, legacy=True)["state"] == "exempt"                 # 舊單不標
    assert PI.material_link_status(_o(totalPrice=0), rows)["state"] == "exempt"                  # $0 不標
    assert PI.material_link_status(_o(totalPrice="0"), rows)["reason"] == "zero_amount"
    assert PI.material_link_status(_o(poDocCode="PO-1", totalPrice=0), rows)["state"] == "exempt"


def test_status_none_without_link_has_the_fixed_text_and_is_not_stale():
    st = PI.material_link_status(_o(), [_po("PO-1")])
    assert st == {"state": "none", "reason": "no_link", "stale": False, "text": "該材料申請未申請採購單"}


def test_status_linked_requires_an_active_po_of_the_case_and_valid_line():
    rows = [_po("PO-1")]
    assert PI.material_link_status(_o(poDocCode="PO-1"), rows)["state"] == "linked"
    assert PI.material_link_status(_o(poDocCode="PO-1", poLine=2), rows)["state"] == "linked"
    for status in ("待審核", "簽核中", "已核准"):
        assert PI.material_link_status(_o(poDocCode="PO-1"), [_po("PO-1", status)])["state"] == "linked", status


@pytest.mark.parametrize("po, order, reason", [
    (_po("PO-1", "草稿"), {"poDocCode": "PO-1"}, "po_inactive"),
    (_po("PO-1", "已駁回"), {"poDocCode": "PO-1"}, "po_inactive"),
    (_po("PO-1", "已作廢"), {"poDocCode": "PO-1"}, "po_inactive"),
    (_po("PO-1", kind="purchase_req"), {"poDocCode": "PO-1"}, "po_missing"),                   # 請購單不算
    (_po("PO-9"), {"poDocCode": "PO-1"}, "po_missing"),
    (_po("PO-1"), {"poDocCode": "PO-1", "poLine": 3}, "bad_line"),
    (_po("PO-1"), {"poDocCode": "PO-1", "poLine": 0}, "bad_line"),
    (_po("PO-1"), {"poDocCode": "PO-1", "poLine": "x"}, "bad_line"),
    (_po("PO-1"), {"poDocCode": "PO-1", "poLine": 1, "quoteItemId": "b"}, "item_mismatch"),     # 採購單那列連 a，叫料連 b
])
def test_status_none_and_stale_when_the_link_is_not_valid(po, order, reason):
    st = PI.material_link_status(_o(**order), [po])
    assert st["state"] == "none" and st["reason"] == reason and st["stale"] is True
    assert st["text"] == "該材料申請未申請採購單（原連結採購單已失效）"


def test_status_line_without_item_id_or_order_without_quote_item_does_not_mismatch():
    rows = [_po("PO-1")]
    assert PI.material_link_status(_o(poDocCode="PO-1", poLine=2, quoteItemId="b"), rows)["state"] == "linked"   # 採購單第 2 列沒有 itemId
    assert PI.material_link_status(_o(poDocCode="PO-1", poLine=1), rows)["state"] == "linked"                   # 叫料沒有 quoteItemId


# ── 叫料對已訂量的貢獻 ──────────────────────────────────────────────────────

def test_material_ordered_counts_unlinked_non_excluded_rows_once():
    po = [_po("PO-1")]
    owl = [
        (_o(itemId="1", quoteItemId="a", quantity=2), ""),                                       # 舊單：計
        (_o(itemId="2", quoteItemId="a", quantity=3), "已核准"),                                 # 計
        (_o(itemId="3", quoteItemId="a", quantity=4), "待審核"),                                 # 審核中也計（佔量）
        (_o(itemId="4", quoteItemId="a", quantity=50), "草稿"),                                  # 不計
        (_o(itemId="5", quoteItemId="a", quantity=50), "已退回"),
        (_o(itemId="6", quoteItemId="a", quantity=50), "已取消"),
        (_o(itemId="7", quoteItemId="a", quantity=9, poDocCode="PO-1"), "已核准"),               # 連到有效採購單：與採購單同一筆，不重複算
        (_o(itemId="8", quoteItemId="a", quantity=6, poDocCode="PO-DEAD"), "已核准"),            # 連結失效：算（叫料自己）
        (_o(itemId="9", quantity=7), "已核准"),                                                  # 沒有 quoteItemId（手動新增）：不影響報價品項
        (_o(itemId="10", quoteItemId="b", quantity=1.5, totalPrice=0), "已核准"),                # $0 也佔量
    ]
    assert PI.material_ordered(owl, po) == {"a": 2 + 3 + 4 + 6, "b": 1.5}


def test_usage_and_picker_and_overplan_share_the_same_ordered_number():
    q = {"items": [{"id": "a", "description": "交換器", "qty": 10, "unit": "台", "cost": 1000}]}
    rows = [{"id": 1, "kind": "purchase_order", "status": "已核准", "lines_json": json.dumps([{"itemId": "a", "qty": 3}]), "doc_code": "PO-1"}]
    extra = {"a": 4.0}
    assert PI.usage(rows, extra_ordered=extra)["a"]["orderedQty"] == 7.0
    p = PI.picker(q, rows, extra_ordered=extra)[0]
    assert p["orderedQty"] == 7.0 and p["remainingQty"] == 3.0
    got = PI.overplan("purchase_order", [{"itemId": "a", "qty": 4}], q, rows, extra_ordered=extra)
    assert len(got) == 1 and got[0]["usedQty"] == 7.0 and got[0]["over"] == 1.0
    assert PI.overplan("purchase_order", [{"itemId": "a", "qty": 3}], q, rows, extra_ordered=extra) == []


# ── 端點：採購單挑選器與上限檢查的剩餘量把叫料算進去 ─────────────────────────────

def _put_materials(orders, approvals):
    cn = db.get_db()
    try:
        d = json.loads(cn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["caseRecord"] = {"materialOrders": orders}
        cn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d), NO))
        for item_id, status in approvals.items():
            cn.execute("INSERT INTO case_material_approvals (quote_no, item_id, status) VALUES (?,?,?)", (NO, item_id, status))
        cn.commit()
    finally:
        cn.close()


def test_purchase_items_remaining_and_submit_cap_include_unlinked_material_orders(W):
    c, h = W
    po = _mk(c, h, "purchase_order", [_ln("a", 3, unitCost=1000)]).json()
    assert _submit(c, h, po["id"]).status_code == 200                                         # 採購單 3/10
    _put_materials([
        {"itemId": "m1", "itemName": "交換器", "quantity": 4, "unit": "台", "unitPrice": 900, "totalPrice": 3600, "quoteItemId": "a"},
        {"itemId": "m2", "itemName": "交換器", "quantity": 99, "unit": "台", "unitPrice": 900, "totalPrice": 89100, "quoteItemId": "a"},       # 草稿：不計
        {"itemId": "m3", "itemName": "交換器", "quantity": 2, "unit": "台", "unitPrice": 900, "totalPrice": 1800, "quoteItemId": "a",
         "poDocCode": po["docCode"], "poLine": 1},                                             # 連到有效採購單：只算一次
    ], {"m1": "已核准", "m2": "草稿", "m3": "已核准"})
    r = c.get("/api/quotations/%s/purchase-items" % NO, headers=h)
    a = {i["itemId"]: i for i in r.json()["items"]}["a"]
    assert (a["orderedQty"], a["remainingQty"]) == (3 + 4, 3)
    # 同一口徑：再開一張採購單 5 台 ⇒ 7+5＞10 ⇒ 超出 2，送審要原因
    new = _mk(c, h, "purchase_order", [_ln("a", 5, unitCost=1000)])
    assert new.status_code == 201 and new.json()["overPlan"][0]["over"] == 2.0 and new.json()["overPlan"][0]["usedQty"] == 7.0
    assert _submit(c, h, new.json()["id"]).status_code == 400
