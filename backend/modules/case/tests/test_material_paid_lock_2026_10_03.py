# -*- coding: utf-8 -*-
"""D7（使用者裁示 A＋B）：已全額付款的材料申請不能改金額（paid_in_full）；部分已付的新小計不得低於已付（B：既有 `_valid_order` 的「已付金額必須 0 ~ 小計」，400）；其餘欄位照舊。"""
import json

import db
from modules.case import material_approval as MA
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_material_po_required_2026_10_03 import _ap, _mo, _orders, _patch
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401

PAID = dict(paidStatus="paid", paidAmount=2000, paidDate="2026-08-01")
PART = dict(paidStatus="partial", paidAmount=800, paidDate="2026-08-01")


def _row(item="p1"):
    return next(o for o in _orders() if o["itemId"] == item)


def test_paid_in_full_legacy_request_cannot_change_amounts_but_other_fields_save(W):
    c, h = W
    _put_materials([_mo("p1", quoteItemId="", **PAID)], {})
    for patch in ({"unitPrice": 1200, "totalPrice": 2400}, {"quantity": 3, "totalPrice": 3000}):
        res = _patch(c, h, [_mo("p1", quoteItemId="", **PAID, **patch)])
        assert [x["code"] for x in res["rejected"]] == ["paid_in_full"], (patch, res)
        r = _row()
        assert (r["quantity"], r["unitPrice"], r["totalPrice"]) == (2, 1000, 2000) and _ap("p1") is None       # 資料不變、沒有被打成草稿
    res = _patch(c, h, [_mo("p1", quoteItemId="", notes="備註", **PAID)])
    assert not res.get("rejected") and _row()["notes"] == "備註"


def test_paid_in_full_is_judged_by_history_plus_live_payment_lines(W):
    c, h = W
    _put_materials([_mo("p1", quoteItemId="", **PAID)], {"p1": "已核准"})                    # 已核准的單（有審核列）也一樣
    res = _patch(c, h, [_mo("p1", quoteItemId="", unitPrice=1100, totalPrice=2200, **PAID)])
    assert [x["code"] for x in res["rejected"]] == ["paid_in_full"] and _ap("p1")["status"] == "已核准"


def test_partly_paid_cannot_go_below_paid_but_can_go_up_into_draft(W):
    c, h = W
    _put_materials([_mo("p2", quoteItemId="", **PART)], {})
    r = c.patch("/api/quotations/%s/material-orders" % NO, headers=h, json={"materialOrders": [_mo("p2", quoteItemId="", unitPrice=300, totalPrice=600, **PART)]})
    assert r.status_code == 400 and _row("p2")["totalPrice"] == 2000                                    # B：新小計 600 < 已付 800
    res = _patch(c, h, [_mo("p2", quoteItemId="", unitPrice=1500, totalPrice=3000, **PART)])            # 改高允許（進草稿，重新送審）
    assert not res.get("rejected") and _row("p2")["totalPrice"] == 3000 and _ap("p2")["status"] == "草稿"
    res = _patch(c, h, [_mo("p2", quoteItemId="", unitPrice=400, totalPrice=800, **PART)])              # 剛好等於已付：不低於 ⇒ 允許
    assert not res.get("rejected")


def test_unpaid_request_amounts_are_not_locked(W):
    c, h = W
    _put_materials([_mo("u1", quoteItemId="")], {})
    res = _patch(c, h, [_mo("u1", quoteItemId="", unitPrice=500, totalPrice=1000)])
    assert not res.get("rejected") and _row("u1")["totalPrice"] == 1000
