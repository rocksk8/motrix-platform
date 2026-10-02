# -*- coding: utf-8 -*-
"""32-S4b：叫料連結的送審檢查（`material_submit_check`，接縫函式）、核准詳情欄位、「從採購單帶入」清單與連結判定端點。
31-C 的守門（`MG.LINK_VALIDATOR`、送審路徑）由 d7 接線；這裡直接呼叫接縫函式（stub 注入形態）。"""
import json

import pytest

import db
from modules.case import purchase_items as PI
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _login, _ln, _mk, _status, _submit  # noqa: F401


def _approved_po(c, h, lines):
    r = _mk(c, h, "purchase_order", lines).json()
    assert _submit(c, h, r["id"]).status_code == 200
    return r


def _check(order, exclude=None):
    cn = db.get_db()
    try:
        return PI.material_submit_check(cn, NO, order, exclude_item_id=exclude)
    finally:
        cn.close()


def _codes(res):
    return sorted(p["code"] for p in res["problems"])


# ── 送審檢查 ──────────────────────────────────────────────────────────────

def test_submit_check_clean_for_in_plan_unlinked_order(W):
    res = _check({"itemId": "m1", "quoteItemId": "a", "quantity": 4, "totalPrice": 4000})
    assert res["problems"] == [] and res["snapshot"] == {"linkState": "none", "linkReason": "no_link", "overPlanQty": 0, "overPlanReason": ""}


def test_submit_check_rejects_unknown_quote_item_and_bad_link(W):
    c, h = W
    assert _codes(_check({"itemId": "m1", "quoteItemId": "zzz", "quantity": 1, "totalPrice": 10})) == ["bad_quote_item"]
    res = _check({"itemId": "m1", "quoteItemId": "a", "quantity": 1, "totalPrice": 10, "poDocCode": "PO-NOPE"})
    assert _codes(res) == ["bad_link"] and "po_missing" in res["problems"][0]["message"]
    draft = _mk(c, h, "purchase_order", [_ln("a", 1)]).json()                                   # 草稿採購單不算有效連結
    assert _codes(_check({"itemId": "m1", "quantity": 1, "totalPrice": 10, "poDocCode": draft["docCode"]})) == ["bad_link"]


def test_submit_check_over_plan_needs_a_reason_and_counts_po_and_other_orders(W):
    c, h = W
    _approved_po(c, h, [_ln("a", 6)])                                                         # 採購單 6/10
    _put_materials([{"itemId": "m9", "itemName": "x", "quantity": 2, "unit": "台", "unitPrice": 1, "totalPrice": 2, "quoteItemId": "a"}], {"m9": "已核准"})   # 另一張叫料 2
    res = _check({"itemId": "m1", "quoteItemId": "a", "quantity": 5, "totalPrice": 5000})      # 6+2+5=13 ＞ 10 ⇒ 超 3
    assert _codes(res) == ["over_plan_reason_required"] and res["snapshot"]["overPlanQty"] == 3
    ok = _check({"itemId": "m1", "quoteItemId": "a", "quantity": 5, "totalPrice": 5000, "overPlanReason": "客戶加購"})
    assert ok["problems"] == [] and ok["snapshot"]["overPlanQty"] == 3 and ok["snapshot"]["overPlanReason"] == "客戶加購"
    assert _check({"itemId": "m1", "quoteItemId": "a", "quantity": 2, "totalPrice": 2000})["problems"] == []      # 剛好 10


def test_submit_check_does_not_count_the_order_itself_and_skips_cap_when_linked_to_a_po(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 9)])
    _put_materials([{"itemId": "m1", "itemName": "x", "quantity": 3, "unit": "台", "unitPrice": 1, "totalPrice": 3, "quoteItemId": "a"}], {"m1": "草稿"})
    # 自己（草稿）送審：本來就不佔量；3 ＋ 採購單 9 ＞ 10 ⇒ 超 2
    res = _check({"itemId": "m1", "quoteItemId": "a", "quantity": 3, "totalPrice": 3}, exclude="m1")
    assert _codes(res) == ["over_plan_reason_required"] and res["snapshot"]["overPlanQty"] == 2
    # 連到有效採購單：與採購單同一筆採購，採購單那邊已驗 ⇒ 這裡不重複超量
    linked = _check({"itemId": "m1", "quoteItemId": "a", "quantity": 9, "totalPrice": 9, "poDocCode": po["docCode"], "poLine": 1})
    assert linked["problems"] == [] and linked["snapshot"]["linkState"] == "linked" and linked["snapshot"]["overPlanQty"] == 0


def test_detail_fields_show_link_and_over_plan():
    po = [{"doc_code": "PO-1", "kind": "purchase_order", "status": "已核准", "lines_json": "[]"}]
    f = {x["label"]: x["value"] for x in PI.material_detail_fields({"totalPrice": 5, "poDocCode": "PO-1"}, po)}
    assert f == {"採購單連結": "已連採購單 PO-1", "超出計畫": "—"}
    g = {x["label"]: x["value"] for x in PI.material_detail_fields({"totalPrice": 5}, po, snapshot={"overPlanQty": 2, "overPlanReason": "加購"})}
    assert g["採購單連結"] == "該叫料未申請採購單" and g["超出計畫"] == "超出 2（加購）"
    legacy = {x["label"]: x["value"] for x in PI.material_detail_fields({"totalPrice": 5}, po, legacy=True)}
    assert legacy["採購單連結"] == "不適用"


# ── 端點：從採購單帶入、連結判定 ───────────────────────────────────────────────

def test_po_lines_lists_only_untaken_counted_po_lines(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3, unitCost=1000, summary="交換器"), _ln(None, 2, unitCost=50, summary="雜項")])
    _mk(c, h, "purchase_order", [_ln("b", 5)])                                                  # 草稿：不列
    _mk(c, h, "purchase_req", [_ln("b", 5)])                                                    # 請購單：不列
    _put_materials([{"itemId": "m1", "itemName": "交換器", "quantity": 3, "unit": "台", "unitPrice": 1000, "totalPrice": 3000, "quoteItemId": "a",
                     "poDocCode": po["docCode"], "poLine": 1}], {"m1": "已核准"})
    r = c.get("/api/quotations/%s/material-po-lines" % NO, headers=h)
    assert r.status_code == 200, r.text
    lines = r.json()["lines"]
    assert [(l["poDocCode"], l["poLine"]) for l in lines] == [(po["docCode"], 2)]                # 第 1 列已被叫料用掉
    assert lines[0]["summary"] == "雜項" and lines[0]["amount"] == 100 and lines[0]["status"] == "已核准"


def test_po_lines_visibility_and_guards(W):
    c, h = W
    tok = h
    assert c.get("/api/quotations/-/material-po-lines", headers=tok).status_code == 400
    assert c.get("/api/quotations/NOPE/material-po-lines", headers=tok).status_code == 404
    assert c.get("/api/quotations/%s/material-po-lines" % NO).status_code in (401, 403)


def test_link_status_endpoint_marks_legacy_zero_none_linked_and_stale(W):
    c, h = W
    po = _approved_po(c, h, [_ln("a", 3)])
    _put_materials([
        {"itemId": "L", "itemName": "舊單", "quantity": 1, "unit": "式", "unitPrice": 10, "totalPrice": 10},                    # 舊單（沒有疊加列）
        {"itemId": "Z", "itemName": "客供", "quantity": 1, "unit": "式", "unitPrice": 0, "totalPrice": 0},                      # $0
        {"itemId": "N", "itemName": "無連結", "quantity": 1, "unit": "式", "unitPrice": 10, "totalPrice": 10},
        {"itemId": "K", "itemName": "已連", "quantity": 3, "unit": "式", "unitPrice": 10, "totalPrice": 30, "poDocCode": po["docCode"], "poLine": 1},
        {"itemId": "S", "itemName": "失效", "quantity": 1, "unit": "式", "unitPrice": 10, "totalPrice": 10, "poDocCode": "PO-GONE"},
    ], {"Z": "已核准", "N": "已核准", "K": "已核准", "S": "已核准"})
    r = c.get("/api/quotations/%s/material-orders/link-status" % NO, headers=h)
    assert r.status_code == 200, r.text
    st = r.json()["statuses"]
    assert st["L"]["state"] == "exempt" and st["L"]["reason"] == "legacy" and st["L"]["text"] == ""
    assert st["Z"]["state"] == "exempt" and st["Z"]["reason"] == "zero_amount"
    assert st["N"] == {"state": "none", "reason": "no_link", "stale": False, "text": "該叫料未申請採購單"}
    assert st["K"]["state"] == "linked"
    assert st["S"]["state"] == "none" and st["S"]["stale"] is True and st["S"]["text"].endswith("（原連結採購單已失效）")
    # 採購單被作廢 ⇒ 已連的變失效
    _status(po["id"], "已作廢")
    st2 = c.get("/api/quotations/%s/material-orders/link-status" % NO, headers=h).json()["statuses"]
    assert st2["K"]["state"] == "none" and st2["K"]["reason"] == "po_inactive"


def test_available_po_lines_hides_cost_without_finance_view(W):
    c, h = W
    _approved_po(c, h, [_ln(None, 2, unitCost=50, summary="雜項")])
    cn = db.get_db()
    try:
        full = PI.available_po_lines(cn, NO, show_cost=True)
        masked = PI.available_po_lines(cn, NO, show_cost=False)
    finally:
        cn.close()
    assert full[0]["amount"] == 100 and full[0]["unitCost"] == 50
    assert "amount" not in masked[0] and "unitCost" not in masked[0] and masked[0]["qty"] == 2


def test_submit_check_never_counts_the_order_being_checked_even_if_it_already_counts(W):
    """防線：被檢查的叫料單本身若已在計量狀態（例如已核准後重新檢查），不可把自己算進已用量。"""
    _put_materials([{"itemId": "m1", "itemName": "x", "quantity": 6, "unit": "台", "unitPrice": 1, "totalPrice": 6, "quoteItemId": "a"}], {"m1": "已核准"})
    res = _check({"itemId": "m1", "quoteItemId": "a", "quantity": 6, "totalPrice": 6}, exclude="m1")
    assert res["problems"] == [] and res["snapshot"]["overPlanQty"] == 0                  # 6/10，自己不重複算
