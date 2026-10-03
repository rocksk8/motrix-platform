# -*- coding: utf-8 -*-
"""34-M1 UI：`GET /api/quotations/{no}/material-coverage`（「從採購單帶入」的涵蓋分組）。
一個報價品項一組（內容＝全部已核准採購單行的涵蓋快照）；額外採購以採購單為單位各一組（N1）；審核中的採購單行不併入、只計 pendingLines；
已有活的材料申請 ⇒ `existing`；內容必然通過送審的「涵蓋」檢查；看不到財務的人不給單價／小計。唯讀。"""
import json

import db
from modules.case import material_approval as MA
from modules.case import purchase_items as PI
from modules.case.tests.test_material_link_2026_10_02 import _put_materials
from modules.case.tests.test_material_link_booking_2026_10_02 import _approved_po, _order, _won_case  # noqa: F401
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W, _ln, _mk, _set_tiers, _submit  # noqa: F401

URL = "/api/quotations/%s/material-coverage" % NO


def _groups(c, h):
    r = c.get(URL, headers=h)
    assert r.status_code == 200, r.text
    return {g["key"]: g for g in r.json()["groups"]}


def test_groups_one_per_item_sum_all_approved_lines_and_extra_purchase_per_po(W):
    c, h = W
    p1 = _approved_po(c, h, [_ln("a", 3, unitCost=1000, summary="交換器甲"), _ln(None, 1, unitCost=500, summary="雜項線材")])
    p2 = _approved_po(c, h, [_ln("a", 2, unitCost=1100, summary="交換器乙")])
    g = _groups(c, h)
    a = g["item:a"]
    assert (a["quantity"], a["totalPrice"], a["lineCount"], a["quoteItemId"]) == (5.0, 3000 + 2200, 2, "a"), a
    assert a["docCodes"] == sorted([p1["docCode"], p2["docCode"]]) and a["poDocCode"] and a["poLine"] >= 1
    assert abs(a["unitPrice"] * a["quantity"] - a["totalPrice"]) < 1e-6
    ex = g["po:" + p1["docCode"]]
    assert (ex["quoteItemId"], ex["quantity"], ex["totalPrice"], ex["lineCount"], ex["name"]) == ("", 1.0, 500.0, 1, "雜項線材"), ex
    assert "item:b" not in g and len(g) == 2


def test_pending_po_lines_are_not_merged_but_counted(W):
    c, h = W
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    _set_tiers([{"order": 0, "approvers": [{"username": "pl_sa", "displayName": "主管"}]}])          # 之後送審的採購單停在待審核
    pend = _mk(c, h, "purchase_order", [_ln("a", 2, unitCost=1000), _ln("b", 10, unitCost=5)]).json()
    assert _submit(c, h, pend["id"]).status_code == 200
    g = _groups(c, h)
    assert (g["item:a"]["quantity"], g["item:a"]["totalPrice"], g["item:a"]["pendingLines"]) == (3.0, 3000.0, 1), g["item:a"]
    assert "item:b" not in g                                                                             # 只有審核中的採購單行 ⇒ 沒有可涵蓋的行


def test_group_content_passes_the_submit_coverage_check_and_existing_request_is_marked(W, monkeypatch):
    c, h = W
    monkeypatch.setattr(MA, "PO_REQUIRED", True)
    _approved_po(c, h, [_ln("a", 3, unitCost=1000), _ln("a", 2, unitCost=1000)])
    a = _groups(c, h)["item:a"]
    assert a["existing"] is None
    order = {"itemId": "n1", "itemName": a["name"], "quantity": a["quantity"], "unit": a["unit"], "unitPrice": a["unitPrice"], "totalPrice": a["totalPrice"],
             "quoteItemId": "a", "poDocCode": a["poDocCode"], "poLine": a["poLine"], "supplierId": 1}
    cn = db.get_db()
    try:
        res = PI.material_submit_check(cn, NO, order, exclude_item_id="n1", po_required=True)
    finally:
        cn.close()
    assert [p for p in res["problems"] if p["code"] in ("content_not_cover_snapshot", "item_request_exists", "no_coverage")] == [], res["problems"]
    lowered = dict(order, quantity=a["quantity"] - 1)                                                       # 數量可往下調、金額不變
    cn = db.get_db()
    try:
        assert not [p for p in PI.material_submit_check(cn, NO, lowered, exclude_item_id="n1", po_required=True)["problems"] if p["code"] == "content_not_cover_snapshot"]
    finally:
        cn.close()
    _put_materials([dict(order, paidStatus="pending", paidAmount=0, paidDate="", notes="", invoiceDate="")], {"n1": "草稿"})
    cn = db.get_db()
    cn.execute("UPDATE case_material_approvals SET created_at=? WHERE quote_no=? AND item_id='n1'", (MA.PO_REQUIRED_FROM + "T09:00:00", NO))
    cn.commit()
    cn.close()
    ex = _groups(c, h)["item:a"]["existing"]
    assert ex and ex["itemId"] == "n1" and ex["status"] == "草稿", ex


def test_prices_hidden_without_financial_view_and_access_is_checked(W, client, make_user):
    c, h = W
    _approved_po(c, h, [_ln("a", 3, unitCost=1000)])
    u, p = make_user(username="pl_nofin", role="sales", modules=["quotation"])
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    r = client.get(URL, headers={"Authorization": "Bearer " + tok})
    assert r.status_code in (403, 404), r.text                                                          # 不是這案的人看不到
    assert client.get(URL).status_code in (401, 403)
